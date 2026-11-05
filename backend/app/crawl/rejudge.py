from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.crawl.judge import judge_crawl_candidate
from app.crawl.score import score_url_relevance
from app.crawl.service import OPEN_WEB_SOURCE_NAME, ensure_open_web_source
from app.models import Listing

logger = logging.getLogger(__name__)


def rejudge_open_web_listings(db: Session) -> dict[str, int]:
    """Mark obvious unusable Open Web Crawl listings as discarded."""
    source = ensure_open_web_source(db)
    rows = list(
        db.scalars(
            select(Listing).where(
                Listing.source_id == source.id,
                Listing.status.in_(("new", "candidate", "needs_review")),
            )
        ).all()
    )
    discarded = 0
    kept = 0
    for listing in rows:
        relevance = score_url_relevance(
            listing.url,
            title=listing.title,
            snippet=listing.raw_snippet,
            page_kind="detail",
        )
        judgement = judge_crawl_candidate(
            listing.url,
            title=listing.title,
            snippet=listing.raw_snippet,
            relevance=relevance,
        )
        # Refresh stored score from current heuristic
        listing.relevance_score = relevance.score
        if judgement.usable:
            kept += 1
            continue
        listing.status = "discarded"
        listing.last_seen_at = datetime.utcnow()
        reason = "judge: " + "; ".join(judgement.reasons[:4])
        snippet = listing.raw_snippet or ""
        if not snippet.startswith("judge:"):
            listing.raw_snippet = f"{reason}\n{snippet}".strip()
        discarded += 1

    db.flush()
    logger.info(
        "Rejudged %s open-web listings for %s: kept=%s discarded=%s",
        len(rows),
        OPEN_WEB_SOURCE_NAME,
        kept,
        discarded,
    )
    return {"reviewed": len(rows), "kept": kept, "discarded": discarded}
