from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlparse

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.discovery.broker_gate import assert_source_allowed, is_blocked_url
from app.discovery.coverage import url_covered_by_sources
from app.discovery.harvest import harvest_portal_candidates
from app.discovery.resolve import ResolvedCareer, normalize_url, resolve_query
from app.models import Source, SourceProposal
from app.seed import DEFAULT_FOCUS_KEYWORDS

logger = logging.getLogger(__name__)

HIGH_BROKER_RISK = 0.7


def _reject_covered_pending_proposals(db: Session) -> int:
    """Drop pending/blocked proposals that sit under an already-added source."""
    removed = 0
    rows = list(
        db.scalars(
            select(SourceProposal).where(SourceProposal.status.in_(("pending", "blocked")))
        ).all()
    )
    for proposal in rows:
        hit = url_covered_by_sources(db, proposal.career_url)
        if hit:
            logger.info(
                "removing covered proposal %s (%s) — %s",
                proposal.id,
                proposal.career_url,
                hit.reason,
            )
            db.delete(proposal)
            removed += 1
    return removed


def _upsert_proposal(
    db: Session,
    *,
    name: str,
    career_url: str,
    base_url: str,
    origin: str,
    kind: str,
    broker_risk: float,
    reasons: list[str],
    status: str,
    raw_snippet: str | None,
    query: str | None,
) -> SourceProposal | None:
    career_url = normalize_url(career_url) or career_url
    if not career_url:
        return None

    hit = url_covered_by_sources(db, career_url)
    if hit:
        logger.info(
            "skip proposal; covered by source %s (%s): %s",
            hit.source_name,
            hit.source_id,
            hit.reason,
        )
        # If an old pending proposal exists for this URL, remove it.
        existing = db.scalar(select(SourceProposal).where(SourceProposal.career_url == career_url))
        if existing and existing.status in {"pending", "blocked"}:
            db.delete(existing)
        return None

    existing = db.scalar(select(SourceProposal).where(SourceProposal.career_url == career_url))
    if existing:
        # Refresh scoring / status for pending or blocked rows; leave approved/rejected alone.
        if existing.status in {"pending", "blocked"}:
            existing.name = name[:255]
            existing.base_url = base_url
            existing.origin = origin
            existing.kind = kind
            existing.broker_risk = broker_risk
            existing.reasons = reasons
            existing.status = status
            existing.raw_snippet = raw_snippet
            existing.query = query
        return existing

    proposal = SourceProposal(
        name=name[:255],
        career_url=career_url,
        base_url=base_url,
        origin=origin,
        kind=kind,
        broker_risk=broker_risk,
        reasons=reasons,
        status=status,
        raw_snippet=raw_snippet,
        query=query,
    )
    db.add(proposal)
    return proposal


def propose_from_queries(db: Session, queries: list[str], *, use_llm: bool = True) -> dict[str, Any]:
    created: list[SourceProposal] = []
    updated: list[SourceProposal] = []
    skipped: list[dict[str, str]] = []
    _reject_covered_pending_proposals(db)

    for raw in queries:
        q = (raw or "").strip()
        if not q:
            continue
        resolved: ResolvedCareer = resolve_query(q, use_llm=use_llm)
        if resolved.error and not resolved.career_url:
            skipped.append({"query": q, "reason": resolved.error})
            continue

        covered = url_covered_by_sources(db, resolved.career_url)
        if covered:
            skipped.append(
                {
                    "query": q,
                    "reason": (
                        f"covered by existing source “{covered.source_name}” "
                        f"({covered.reason})"
                    ),
                }
            )
            continue

        status = "blocked" if resolved.blocked else "pending"
        before = db.scalar(
            select(SourceProposal).where(
                SourceProposal.career_url
                == (normalize_url(resolved.career_url) or resolved.career_url)
            )
        )
        proposal = _upsert_proposal(
            db,
            name=resolved.name or q,
            career_url=resolved.career_url,
            base_url=resolved.base_url,
            origin="paste",
            kind=resolved.kind_score.kind,
            broker_risk=resolved.kind_score.broker_risk,
            reasons=list(resolved.kind_score.reasons),
            status=status,
            raw_snippet=resolved.raw_snippet,
            query=q,
        )
        if proposal is None:
            skipped.append({"query": q, "reason": "already a source or invalid URL"})
            continue
        if before is None:
            created.append(proposal)
        else:
            updated.append(proposal)

    db.commit()
    for row in created + updated:
        db.refresh(row)
    return {
        "created": created,
        "updated": updated,
        "skipped": skipped,
    }


def run_portal_harvest(db: Session) -> dict[str, Any]:
    created: list[SourceProposal] = []
    updated: list[SourceProposal] = []
    blocked = 0
    _reject_covered_pending_proposals(db)

    for candidate in harvest_portal_candidates(db):
        if url_covered_by_sources(db, candidate.career_url):
            continue
        status = "blocked" if candidate.blocked else "pending"
        if candidate.blocked:
            blocked += 1
        before = db.scalar(
            select(SourceProposal).where(SourceProposal.career_url == candidate.career_url)
        )
        proposal = _upsert_proposal(
            db,
            name=candidate.name,
            career_url=candidate.career_url,
            base_url=candidate.base_url,
            origin="portal",
            kind=candidate.kind_score.kind,
            broker_risk=candidate.kind_score.broker_risk,
            reasons=list(candidate.kind_score.reasons),
            status=status,
            raw_snippet=candidate.raw_snippet,
            query=None,
        )
        if proposal is None:
            continue
        if before is None:
            created.append(proposal)
        else:
            updated.append(proposal)

    db.commit()
    for row in created + updated:
        db.refresh(row)
    return {
        "created": created,
        "updated": updated,
        "blocked": blocked,
    }


def agent_config_for_url(url: str) -> dict[str, Any]:
    return {
        "list_url": url,
        "max_listings": 25,
        "max_pages": 5,
        "focus_keywords": list(DEFAULT_FOCUS_KEYWORDS),
    }


def approve_proposal(
    db: Session,
    proposal: SourceProposal,
    *,
    force: bool = False,
) -> Source:
    # Hard denylist always wins (blocked status or domain/name match).
    assert_source_allowed(
        name=proposal.name,
        base_url=proposal.base_url,
        list_url=proposal.career_url,
    )
    if proposal.status == "blocked" or is_blocked_url(proposal.career_url).blocked:
        raise HTTPException(400, "Proposal is blocked by broker denylist")

    needs_force = proposal.kind == "broker" or float(proposal.broker_risk or 0) >= HIGH_BROKER_RISK
    if needs_force and not force:
        raise HTTPException(
            status_code=400,
            detail=(
                f"High broker risk ({proposal.broker_risk}). "
                "Pass force=true to approve anyway."
            ),
        )

    covered = url_covered_by_sources(db, proposal.career_url)
    if covered:
        raise HTTPException(
            400,
            f"URL already covered by source “{covered.source_name}” ({covered.reason})",
        )

    # Avoid duplicate source names: append host if name taken.
    name = proposal.name
    existing_name = db.scalar(select(Source).where(Source.name == name))
    if existing_name:
        host = urlparse(proposal.career_url).hostname or "source"
        name = f"{proposal.name} ({host})"[:255]

    source = Source(
        name=name,
        base_url=proposal.base_url,
        adapter_key="agent",
        enabled=False,
        config=agent_config_for_url(proposal.career_url),
    )
    db.add(source)
    proposal.status = "approved"
    db.commit()
    db.refresh(source)
    db.refresh(proposal)
    return source
