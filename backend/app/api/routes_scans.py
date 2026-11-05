from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import SessionLocal, get_db
from app.models import ScanRun, Source
from app.pipeline.runner import scan_all_enabled, scan_source
from app.schemas import ScanRunOut

router = APIRouter(prefix="/api/scans", tags=["scans"])


def _to_out(db: Session, run: ScanRun) -> ScanRunOut:
    source_name = None
    if run.source_id:
        source = db.get(Source, run.source_id)
        source_name = source.name if source else None
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
        source_name=source_name,
    )


def _bg_scan_all() -> None:
    db = SessionLocal()
    try:
        scan_all_enabled(db, classify=True)
    finally:
        db.close()


def _bg_scan_one(source_id: int) -> None:
    db = SessionLocal()
    try:
        source = db.get(Source, source_id)
        if source:
            scan_source(db, source, classify=True)
    finally:
        db.close()


@router.get("", response_model=list[ScanRunOut])
def list_scans(db: Session = Depends(get_db)) -> list[ScanRunOut]:
    runs = db.scalars(select(ScanRun).order_by(ScanRun.id.desc()).limit(100)).all()
    return [_to_out(db, run) for run in runs]


@router.post("/run")
def run_all_scans(background: BackgroundTasks, db: Session = Depends(get_db)) -> dict:
    background.add_task(_bg_scan_all)
    return {"ok": True, "message": "Scan started for all enabled sources"}


@router.post("/run/{source_id}")
def run_source_scan(
    source_id: int,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
) -> dict:
    source = db.get(Source, source_id)
    if not source:
        raise HTTPException(404, "Source not found")
    background.add_task(_bg_scan_one, source_id)
    return {"ok": True, "message": f"Scan started for source {source_id}"}


@router.post("/run-sync/{source_id}", response_model=ScanRunOut)
def run_source_scan_sync(source_id: int, db: Session = Depends(get_db)) -> ScanRunOut:
    """Synchronous scan — useful for testing / small sources."""
    source = db.get(Source, source_id)
    if not source:
        raise HTTPException(404, "Source not found")
    run = scan_source(db, source, classify=True)
    return _to_out(db, run)
