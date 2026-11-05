from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.crawl.service import domain_key
from app.discovery.resolve import normalize_url
from app.models import CrawlVisit


def load_recent_visits(
    db: Session, *, revisit_days: float
) -> tuple[set[str], set[str]]:
    """Return (recent_urls, recent_hosts) fetched within revisit_days."""
    cutoff = datetime.utcnow() - timedelta(days=max(revisit_days, 0.0))
    rows = db.scalars(select(CrawlVisit).where(CrawlVisit.fetched_at >= cutoff)).all()
    urls: set[str] = set()
    hosts: set[str] = set()
    for row in rows:
        if row.url:
            urls.add(row.url)
        host = (row.host or domain_key(row.url) or "").lower()
        if host:
            hosts.add(host)
    return urls, hosts


def record_visit(
    db: Session,
    url: str,
    *,
    outcome: str = "fetched",
) -> None:
    normalized = normalize_url(url) or url
    if not normalized:
        return
    host = domain_key(normalized)
    existing = db.scalar(select(CrawlVisit).where(CrawlVisit.url == normalized))
    now = datetime.utcnow()
    if existing:
        existing.host = host
        existing.outcome = outcome
        existing.fetched_at = now
    else:
        db.add(
            CrawlVisit(
                url=normalized,
                host=host,
                outcome=outcome,
                fetched_at=now,
            )
        )
    db.flush()


def clear_crawl_visits(db: Session) -> int:
    result = db.execute(delete(CrawlVisit))
    db.flush()
    return int(result.rowcount or 0)
