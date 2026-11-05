from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from sqlalchemy import delete

from app.crawl.service import OPEN_WEB_SOURCE_NAME
from app.db import get_db
from app.discovery.broker_gate import assert_source_allowed
from app.discovery.coverage import url_covered_by_sources
from app.models import Classification, Listing, Review, ScanRun, Source
from app.schemas import SourceCreate, SourceOut, SourceUpdate

router = APIRouter(prefix="/api/sources", tags=["sources"])


def _is_system_crawl_source(source: Source) -> bool:
    return source.name == OPEN_WEB_SOURCE_NAME or source.adapter_key == "crawl"


def _list_url_from_config(config: dict | None) -> str | None:
    if not config:
        return None
    value = config.get("list_url")
    return str(value) if value else None


@router.get("", response_model=list[SourceOut])
def list_sources(db: Session = Depends(get_db)) -> list[Source]:
    return list(db.scalars(select(Source).order_by(Source.id)).all())


@router.post("", response_model=SourceOut)
def create_source(payload: SourceCreate, db: Session = Depends(get_db)) -> Source:
    if payload.adapter_key == "crawl" or payload.name == OPEN_WEB_SOURCE_NAME:
        raise HTTPException(400, "Open Web Crawl is a system source; use /api/crawl/run")
    assert_source_allowed(
        name=payload.name,
        base_url=payload.base_url,
        list_url=_list_url_from_config(payload.config),
    )
    list_url = _list_url_from_config(payload.config) or payload.base_url
    covered = url_covered_by_sources(db, list_url)
    if covered:
        raise HTTPException(
            400,
            f"URL already covered by source “{covered.source_name}” ({covered.reason})",
        )
    source = Source(**payload.model_dump())
    db.add(source)
    db.commit()
    db.refresh(source)
    return source


@router.get("/{source_id}", response_model=SourceOut)
def get_source(source_id: int, db: Session = Depends(get_db)) -> Source:
    source = db.get(Source, source_id)
    if not source:
        raise HTTPException(404, "Source not found")
    return source


@router.patch("/{source_id}", response_model=SourceOut)
def update_source(source_id: int, payload: SourceUpdate, db: Session = Depends(get_db)) -> Source:
    source = db.get(Source, source_id)
    if not source:
        raise HTTPException(404, "Source not found")
    if _is_system_crawl_source(source):
        raise HTTPException(400, "Open Web Crawl is managed by /api/crawl; cannot edit")
    updates = payload.model_dump(exclude_unset=True)
    name = updates.get("name", source.name)
    base_url = updates.get("base_url", source.base_url)
    config = updates.get("config", source.config)
    assert_source_allowed(
        name=name,
        base_url=base_url,
        list_url=_list_url_from_config(config if isinstance(config, dict) else None),
    )
    for key, value in updates.items():
        setattr(source, key, value)
    db.commit()
    db.refresh(source)
    return source


@router.delete("/{source_id}")
def delete_source(source_id: int, db: Session = Depends(get_db)) -> dict[str, bool]:
    source = db.get(Source, source_id)
    if not source:
        raise HTTPException(404, "Source not found")
    if _is_system_crawl_source(source):
        raise HTTPException(400, "Open Web Crawl is a system source and cannot be deleted")
    listing_ids = list(
        db.scalars(select(Listing.id).where(Listing.source_id == source.id)).all()
    )
    if listing_ids:
        db.execute(delete(Classification).where(Classification.listing_id.in_(listing_ids)))
        db.execute(delete(Review).where(Review.listing_id.in_(listing_ids)))
        db.execute(delete(Listing).where(Listing.id.in_(listing_ids)))
    db.execute(delete(ScanRun).where(ScanRun.source_id == source.id))
    db.delete(source)
    db.commit()
    return {"ok": True}
