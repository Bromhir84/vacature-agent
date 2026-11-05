from __future__ import annotations

import hashlib
from urllib.parse import urlparse

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.crawl.extract import registrable_hint
from app.discovery.resolve import normalize_url
from app.models import Classification, Listing, Review, ScanRun, Source, SourceProposal


def _clear_visits(db: Session) -> int:
    from app.crawl.visits import clear_crawl_visits

    return clear_crawl_visits(db)

OPEN_WEB_SOURCE_NAME = "Open Web Crawl"
OPEN_WEB_BASE_URL = "https://localhost/open-web-crawl"


def domain_key(url: str) -> str:
    """Hostname key for one-vacature-per-site policy (www-stripped).

    Example: https://jobs.ict.eu/a and https://jobs.ict.eu/b → jobs.ict.eu
    """
    host = (urlparse(url).hostname or "").lower().removeprefix("www.")
    return host


def clear_crawl_results(db: Session) -> dict[str, int]:
    """Delete Open Web Crawl listings, their reviews/classifications, crawl runs, and crawl proposals."""
    source = ensure_open_web_source(db)
    listing_ids = list(
        db.scalars(select(Listing.id).where(Listing.source_id == source.id)).all()
    )
    listings = len(listing_ids)
    classifications = 0
    reviews = 0
    if listing_ids:
        classifications = db.execute(
            delete(Classification).where(Classification.listing_id.in_(listing_ids))
        ).rowcount or 0
        reviews = db.execute(
            delete(Review).where(Review.listing_id.in_(listing_ids))
        ).rowcount or 0
        db.execute(delete(Listing).where(Listing.id.in_(listing_ids)))
    runs = db.execute(delete(ScanRun).where(ScanRun.source_id == source.id)).rowcount or 0
    proposals = (
        db.execute(delete(SourceProposal).where(SourceProposal.origin == "crawl")).rowcount or 0
    )
    visits = _clear_visits(db)
    db.flush()
    return {
        "listings": listings,
        "classifications": int(classifications),
        "reviews": int(reviews),
        "runs": int(runs),
        "proposals": int(proposals),
        "visits": int(visits),
    }


def ensure_open_web_source(db: Session) -> Source:
    existing = db.scalar(select(Source).where(Source.name == OPEN_WEB_SOURCE_NAME))
    if existing:
        # Keep system source disabled so scheduled scans never invoke adapter_key=crawl.
        existing.enabled = False
        existing.adapter_key = "crawl"
        if not isinstance(existing.config, dict):
            existing.config = {}
        return existing
    source = Source(
        name=OPEN_WEB_SOURCE_NAME,
        base_url=OPEN_WEB_BASE_URL,
        adapter_key="crawl",
        enabled=False,
        config={"system": True, "list_url": OPEN_WEB_BASE_URL},
    )
    db.add(source)
    db.flush()
    return source


def domains_claimed_by_source(db: Session, source_id: int) -> set[str]:
    """Hosts that already have a kept listing under the open-web crawl source."""
    urls = db.scalars(
        select(Listing.url).where(
            Listing.source_id == source_id,
            Listing.status != "discarded",
        )
    ).all()
    return {key for url in urls if (key := domain_key(url))}


def collapse_listings_to_one_per_domain(db: Session, source_id: int) -> int:
    """Keep the highest-relevance listing per host; delete the rest. Returns removed count."""
    rows = list(
        db.scalars(
            select(Listing).where(
                Listing.source_id == source_id,
                Listing.status != "discarded",
            )
        ).all()
    )
    best: dict[str, Listing] = {}
    removed = 0
    for listing in rows:
        key = domain_key(listing.url)
        if not key:
            continue
        current = best.get(key)
        if current is None:
            best[key] = listing
            continue
        cur_score = current.relevance_score if current.relevance_score is not None else -1.0
        new_score = listing.relevance_score if listing.relevance_score is not None else -1.0
        if new_score > cur_score:
            db.delete(current)
            best[key] = listing
            removed += 1
        else:
            db.delete(listing)
            removed += 1
    if removed:
        db.flush()
    return removed


def listing_url_exists(db: Session, url: str) -> bool:
    normalized = normalize_url(url) or url
    if not normalized:
        return False
    hit = db.scalar(select(Listing.id).where(Listing.url == normalized).limit(1))
    if hit:
        return True
    alt = normalized.rstrip("/")
    if alt != normalized:
        hit = db.scalar(select(Listing.id).where(Listing.url == alt).limit(1))
        if hit:
            return True
    with_slash = alt + "/"
    if with_slash != normalized:
        hit = db.scalar(select(Listing.id).where(Listing.url == with_slash).limit(1))
        if hit:
            return True
    return False


def external_id_for_url(url: str) -> str:
    normalized = normalize_url(url) or url
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:24]


def page_title_from_html(html: str) -> str | None:
    lower = html[:4000].lower()
    start = lower.find("<title")
    if start < 0:
        return None
    gt = html.find(">", start)
    end = lower.find("</title>", gt)
    if gt < 0 or end < 0:
        return None
    raw = html[gt + 1 : end].strip()
    return " ".join(raw.split())[:200] or None
