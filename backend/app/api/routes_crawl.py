from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.crawl.rejudge import rejudge_open_web_listings
from app.crawl.runner import run_web_crawl
from app.crawl.service import OPEN_WEB_SOURCE_NAME, clear_crawl_results, ensure_open_web_source
from app.db import get_db
from app.models import ScanRun, Source
from app.schemas import (
    CrawlClearResult,
    CrawlRejudgeResult,
    CrawlRunRequest,
    CrawlRunResult,
    ScanRunOut,
)

router = APIRouter(prefix="/api/crawl", tags=["crawl"])


def _run_to_out(db: Session, run: ScanRun) -> ScanRunOut:
    source = db.get(Source, run.source_id) if run.source_id else None
    return ScanRunOut(
        id=run.id,
        source_id=run.source_id,
        started_at=run.started_at,
        finished_at=run.finished_at,
        status=run.status,
        discovered=run.discovered,
        upserted=run.upserted,
        classified=run.classified,
        candidates=run.candidates,
        errors=run.errors,
        source_name=source.name if source else None,
    )


@router.post("/run", response_model=CrawlRunResult)
def crawl_run(payload: CrawlRunRequest, db: Session = Depends(get_db)) -> CrawlRunResult:
    if payload.max_pages is not None and (payload.max_pages < 1 or payload.max_pages > 200):
        raise HTTPException(400, "max_pages must be between 1 and 200")
    if payload.max_new_urls is not None and (
        payload.max_new_urls < 1 or payload.max_new_urls > 500
    ):
        raise HTTPException(400, "max_new_urls must be between 1 and 500")
    if payload.min_relevance is not None and (
        payload.min_relevance < 0 or payload.min_relevance > 1
    ):
        raise HTTPException(400, "min_relevance must be between 0 and 1")
    if payload.queries is not None and len(payload.queries) > 30:
        raise HTTPException(400, "Max 30 queries per crawl")
    if payload.seed_urls is not None and len(payload.seed_urls) > 50:
        raise HTTPException(400, "Max 50 seed_urls per crawl")

    result = run_web_crawl(
        db,
        max_pages=payload.max_pages,
        max_new_urls=payload.max_new_urls,
        min_relevance=payload.min_relevance,
        queries=payload.queries,
        seed_urls=payload.seed_urls,
    )
    run = result["run"]
    return CrawlRunResult(
        run=_run_to_out(db, run),
        source_id=result["source_id"],
        pages_fetched=result["pages_fetched"],
        discovered=result["discovered"],
        upserted=result["upserted"],
        skipped_broker=result["skipped_broker"],
        skipped_low_score=result["skipped_low_score"],
        skipped_dup=result["skipped_dup"],
        skipped_domain=int(result.get("skipped_domain") or 0),
        skipped_unusable=int(result.get("skipped_unusable") or 0),
        skipped_recent=int(result.get("skipped_recent") or 0),
        rejudged_discarded=int(result.get("rejudged_discarded") or 0),
        proposals_created=result["proposals_created"],
        avg_relevance=result["avg_relevance"],
        errors=result.get("errors") or [],
    )


@router.post("/rejudge", response_model=CrawlRejudgeResult)
def crawl_rejudge(db: Session = Depends(get_db)) -> CrawlRejudgeResult:
    """Re-score Open Web Crawl listings and discard obvious unusables."""
    result = rejudge_open_web_listings(db)
    db.commit()
    return CrawlRejudgeResult(
        reviewed=result["reviewed"],
        kept=result["kept"],
        discarded=result["discarded"],
    )


@router.post("/clear", response_model=CrawlClearResult)
def crawl_clear(db: Session = Depends(get_db)) -> CrawlClearResult:
    """Wipe Open Web Crawl listings, crawl runs, and crawl-origin proposals."""
    result = clear_crawl_results(db)
    db.commit()
    return CrawlClearResult(**result)


@router.get("/runs", response_model=list[ScanRunOut])
def list_crawl_runs(db: Session = Depends(get_db)) -> list[ScanRunOut]:
    source = ensure_open_web_source(db)
    db.commit()
    rows = db.scalars(
        select(ScanRun)
        .where(ScanRun.source_id == source.id)
        .order_by(ScanRun.id.desc())
        .limit(50)
    ).all()
    return [_run_to_out(db, row) for row in rows]


@router.get("/source", response_model=dict)
def crawl_source_info(db: Session = Depends(get_db)) -> dict:
    source = ensure_open_web_source(db)
    db.commit()
    return {
        "id": source.id,
        "name": OPEN_WEB_SOURCE_NAME,
        "enabled": source.enabled,
        "adapter_key": source.adapter_key,
    }
