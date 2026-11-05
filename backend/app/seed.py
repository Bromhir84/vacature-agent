from __future__ import annotations

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.models import Classification, Listing, Review, ScanRun, Source, SourceProposal
from app.pipeline.settings_store import ensure_default_settings

DEFAULT_FOCUS_KEYWORDS = [
    "inhuur",
    "detachering",
    "extern",
    "inlener",
    "interim",
    "zzp",
    "ICT",
]

ANWB_CONFIG = {
    "list_url": "https://www.werkenbijanwb.nl/api/vacancy/",
    "query": {
        "sort": "created",
        "sortDir": "DESC",
        "filters[Dienstverband][]": "Inhuur",
    },
    "pagination": {
        "page_param": "pageNumber",
        "items_path": "vacancies",
        "total_pages_path": "meta.totalPageCount",
        "max_pages": 20,
    },
    "item_map": {
        "external_id": "id",
        "title": "title",
        "url_template": "https://www.werkenbijanwb.nl/vacature/{id}/{slug}",
        "location": "city",
        "description": "intro",
    },
    "default_employment_type": "Inhuur",
}

NS_CONFIG = {
    "list_url": "https://www.werkenbijns.nl/vacatures",
    "query": {"keywords": "Inhuur"},
    "list_item_selector": "a.vacancy-item",
    "fields": {
        "url": {"attr": "href"},
        "title": {"selector": ".vacancy-item-titles", "attr": "text"},
        "location": {"selector": "li.location .metadata-text, li.location", "attr": "text"},
        "description": {"selector": ".vacancy-item-body > .text, .text.text-align-left", "attr": "text"},
        "tags": {"selector": ".vacancy-tag", "attr": "text", "many": True},
    },
    "employment_from_tags": True,
    "detail": {
        "enabled": True,
        # Prefer vacancy accordion bodies; html adapter also special-cases .vacancy-accordion.
        "description_selector": ".vacancy-accordion .accordion-content, .banner-vacancy, main",
    },
    "pagination": {
        "next_selector": "a[rel='next'], .pagination a.next",
        "max_pages": 10,
    },
}


SEED_SOURCES = [
    {
        "name": "Werken bij ANWB",
        "base_url": "https://www.werkenbijanwb.nl",
        "adapter_key": "json",
        "enabled": True,
        "config": ANWB_CONFIG,
    },
    {
        "name": "Werken bij NS",
        "base_url": "https://www.werkenbijns.nl",
        "adapter_key": "html",
        "enabled": True,
        "config": NS_CONFIG,
    },
]

# Explicit removals (also anything not in SEED_SOURCES except system sources is dropped).
REMOVED_SOURCE_NAMES = {
    "Freep.nl",
    "Alliander Inhuur",
    "WerkenvoorNederland ICT",
    "WerkenbijdeOverheid",
    "Werken bij Belastingdienst",
    "Werken bij Amsterdam",
    "Werken bij Defensie",
    "Werken bij Achmea",
    "Werken bij Enexis",
    "Werken bij Radboudumc",
    "Port of Rotterdam",
    "Rijkswaterstaat ICT",
    "Kadaster ICT",
    "DICTU ICT",
}

SYSTEM_SOURCE_NAMES = {"Open Web Crawl"}


def _delete_source_cascade(db: Session, source: Source) -> None:
    listing_ids = list(
        db.scalars(select(Listing.id).where(Listing.source_id == source.id)).all()
    )
    if listing_ids:
        db.execute(delete(Classification).where(Classification.listing_id.in_(listing_ids)))
        db.execute(delete(Review).where(Review.listing_id.in_(listing_ids)))
        db.execute(delete(Listing).where(Listing.id.in_(listing_ids)))
    db.execute(delete(ScanRun).where(ScanRun.source_id == source.id))
    db.delete(source)


def wipe_all_results(db: Session) -> dict[str, int]:
    """Delete all listings, classifications, reviews, scan runs, and proposals."""
    classifications = db.execute(delete(Classification)).rowcount or 0
    reviews = db.execute(delete(Review)).rowcount or 0
    listings = db.execute(delete(Listing)).rowcount or 0
    runs = db.execute(delete(ScanRun)).rowcount or 0
    proposals = db.execute(delete(SourceProposal)).rowcount or 0
    visits = 0
    try:
        from app.crawl.visits import clear_crawl_visits

        visits = clear_crawl_visits(db)
    except Exception:  # noqa: BLE001
        visits = 0
    db.execute(update(Source).values(last_scan_at=None))
    db.flush()
    return {
        "listings": int(listings),
        "classifications": int(classifications),
        "reviews": int(reviews),
        "runs": int(runs),
        "proposals": int(proposals),
        "visits": int(visits),
    }


def cleanup_removed_sources(db: Session) -> None:
    from app.discovery.broker_gate import is_blocked_name, is_blocked_url

    keep = {s["name"] for s in SEED_SOURCES} | SYSTEM_SOURCE_NAMES

    for name in REMOVED_SOURCE_NAMES:
        existing = db.scalar(select(Source).where(Source.name == name))
        if existing:
            _delete_source_cascade(db, existing)

    # Drop any sources whose host/name hit the hard broker denylist,
    # or that are no longer in the curated pack (except system sources).
    for source in list(db.scalars(select(Source)).all()):
        if source.name in keep:
            list_url = ""
            if isinstance(source.config, dict):
                list_url = str(source.config.get("list_url") or "")
            blocked = (
                is_blocked_name(source.name).blocked
                or is_blocked_url(source.base_url).blocked
                or is_blocked_url(list_url).blocked
            )
            if blocked:
                _delete_source_cascade(db, source)
            continue

        list_url = ""
        if isinstance(source.config, dict):
            list_url = str(source.config.get("list_url") or "")
        blocked = (
            is_blocked_name(source.name).blocked
            or is_blocked_url(source.base_url).blocked
            or is_blocked_url(list_url).blocked
        )
        if blocked or source.name not in keep:
            _delete_source_cascade(db, source)


def seed_database(db: Session) -> None:
    from app.crawl.service import ensure_open_web_source

    ensure_default_settings(db)
    cleanup_removed_sources(db)
    for seed in SEED_SOURCES:
        existing = db.scalar(select(Source).where(Source.name == seed["name"]))
        if existing:
            # Keep curated pack URLs/adapters in sync after seed updates.
            existing.base_url = seed["base_url"]
            existing.adapter_key = seed["adapter_key"]
            existing.config = seed["config"]
            existing.enabled = seed["enabled"]
            continue
        db.add(Source(**seed))
    ensure_open_web_source(db)
    db.commit()
