from __future__ import annotations

import traceback
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters import get_adapter
from app.models import Classification, Listing, ScanRun, Source
from app.pipeline.classifier import classify_listing
from app.pipeline.rules import evaluate_listing
from app.pipeline.settings_store import get_runtime_settings, resolve_llm_config
from app.pipeline.snippet import summarize_with_fallback
from app.schemas import ListingDraft


INBOX_STATUSES = {"new", "open", "removed"}
LEGACY_INBOX_STATUSES = {"candidate", "needs_review", "approved"}


def _inbox_status_after_seen(listing: Listing) -> str:
    """Return new/open when a listing is (re)seen on the site."""
    if listing.viewed_at is not None or listing.status == "open":
        return "open"
    return "new"


def _upsert_listing(db: Session, source: Source, draft: ListingDraft) -> tuple[Listing, bool]:
    existing = db.scalar(
        select(Listing).where(
            Listing.source_id == source.id,
            Listing.external_id == draft.external_id,
        )
    )
    now = datetime.utcnow()
    if existing:
        existing.title = draft.title
        existing.url = draft.url
        existing.employment_type = draft.employment_type or existing.employment_type
        existing.location = draft.location or existing.location
        if draft.description:
            existing.description = draft.description
        if draft.raw_snippet:
            existing.raw_snippet = draft.raw_snippet
        existing.summary = summarize_with_fallback(
            title=existing.title,
            description=existing.description,
            raw_snippet=existing.raw_snippet,
            llm_summary=existing.summary,
        )
        existing.last_seen_at = now
        existing.disappeared = False
        # Reappeared after removal → back into inbox.
        if existing.status == "removed":
            existing.status = _inbox_status_after_seen(existing)
        return existing, False

    summary = summarize_with_fallback(
        title=draft.title,
        description=draft.description,
        raw_snippet=draft.raw_snippet,
    )
    listing = Listing(
        source_id=source.id,
        external_id=draft.external_id,
        title=draft.title,
        url=draft.url,
        employment_type=draft.employment_type,
        location=draft.location,
        description=draft.description,
        raw_snippet=draft.raw_snippet,
        summary=summary,
        status="new",
        first_seen_at=now,
        last_seen_at=now,
    )
    db.add(listing)
    db.flush()
    return listing, True


def _should_classify(listing: Listing) -> bool:
    if listing.status in {"approved", "rejected", "ignored", "removed"}:
        return False
    return listing.status in {
        "new",
        "open",
        "candidate",
        "needs_review",
        "discarded",
    }


def _apply_classification_status(listing: Listing, passed_staffing: bool) -> str:
    """Map staffing result onto inbox statuses without clobbering Open."""
    if not passed_staffing:
        # Don't yank listings the user already opened.
        if listing.status in {"open", "removed"} or listing.viewed_at is not None:
            return listing.status if listing.status in INBOX_STATUSES else "open"
        return "discarded"

    if listing.status == "open" or listing.viewed_at is not None:
        return "open"
    if listing.status in {"new", "discarded", *LEGACY_INBOX_STATUSES}:
        return "new"
    return listing.status if listing.status in INBOX_STATUSES else "new"


def scan_source(db: Session, source: Source, *, classify: bool = True) -> ScanRun:
    run = ScanRun(source_id=source.id, status="running", started_at=datetime.utcnow())
    db.add(run)
    db.commit()
    db.refresh(run)

    runtime = get_runtime_settings(db)
    llm = resolve_llm_config(db)
    discovered = 0
    upserted = 0
    classified = 0
    candidates = 0
    errors: list[str] = []

    try:
        adapter = get_adapter(source.adapter_key)
        drafts = adapter.discover(source)
        discovered = len(drafts)
        seen_ids: set[str] = set()

        for draft in drafts:
            seen_ids.add(draft.external_id)
            listing, created = _upsert_listing(db, source, draft)
            if created:
                upserted += 1

            if not classify or not _should_classify(listing):
                continue

            rule = evaluate_listing(
                draft,
                staffing_keywords=runtime["staffing_keywords"],
                employment_allowlist=runtime["employment_allowlist"],
                employment_blocklist=runtime["employment_blocklist"],
            )

            llm_json = None
            confidence = None
            passed_staffing = False

            if rule.passed:
                if llm["llm_api_key"]:
                    try:
                        llm_json = classify_listing(draft, model=llm["llm_model"])
                        confidence = float(llm_json.get("confidence") or 0)
                        if llm_json.get("is_external_staffing") and confidence >= runtime["confidence_review"]:
                            passed_staffing = True
                            if confidence >= runtime["confidence_candidate"]:
                                candidates += 1
                        elif not llm_json.get("is_external_staffing") and confidence >= runtime["confidence_candidate"]:
                            passed_staffing = False
                        else:
                            # Ambiguous LLM result: keep in inbox for human review.
                            passed_staffing = True
                    except Exception as exc:  # noqa: BLE001
                        errors.append(f"classify {draft.external_id}: {exc}")
                        passed_staffing = True
                        llm_json = {"error": str(exc)}
                else:
                    # No LLM configured: trust deterministic gate
                    passed_staffing = True
                    candidates += 1
                    confidence = 1.0
                    llm_json = {
                        "is_external_staffing": True,
                        "category": "unclear",
                        "confidence": 1.0,
                        "evidence": rule.reasons,
                        "reason": "Accepted by deterministic gate; LLM not configured",
                    }

            listing.status = _apply_classification_status(listing, passed_staffing)
            listing.summary = summarize_with_fallback(
                title=listing.title,
                description=listing.description,
                raw_snippet=listing.raw_snippet,
                llm_summary=(llm_json or {}).get("summary") if isinstance(llm_json, dict) else None,
            )
            db.add(
                Classification(
                    listing_id=listing.id,
                    rule_hit=rule.passed,
                    rule_reasons=rule.reasons,
                    llm_json=llm_json,
                    confidence=confidence,
                )
            )
            classified += 1

        # Gone from the site → Removed from website (keep history, do not delete).
        existing_listings = db.scalars(select(Listing).where(Listing.source_id == source.id)).all()
        for listing in existing_listings:
            if listing.external_id not in seen_ids:
                listing.disappeared = True
                if listing.status != "discarded":
                    listing.status = "removed"

        source.last_scan_at = datetime.utcnow()
        run.status = "success" if not errors else "success"
        run.discovered = discovered
        run.upserted = upserted
        run.classified = classified
        run.candidates = candidates
        run.errors = "\n".join(errors) if errors else None
        run.finished_at = datetime.utcnow()
        db.commit()
        db.refresh(run)
        return run
    except Exception as exc:  # noqa: BLE001
        run.status = "error"
        run.discovered = discovered
        run.upserted = upserted
        run.classified = classified
        run.candidates = candidates
        run.errors = f"{exc}\n{traceback.format_exc()}"
        run.finished_at = datetime.utcnow()
        db.commit()
        db.refresh(run)
        return run


def scan_all_enabled(db: Session, *, classify: bool = True) -> list[ScanRun]:
    sources = db.scalars(select(Source).where(Source.enabled.is_(True))).all()
    return [scan_source(db, source, classify=classify) for source in sources]
