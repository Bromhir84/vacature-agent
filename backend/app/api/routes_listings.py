from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Classification, Listing, Review, Source
from app.schemas import ListingOut, ReviewCreate, ReviewOut

router = APIRouter(prefix="/api/listings", tags=["listings"])


def _to_out(db: Session, listing: Listing) -> ListingOut:
    source = db.get(Source, listing.source_id)
    latest = db.scalar(
        select(Classification)
        .where(Classification.listing_id == listing.id)
        .order_by(Classification.id.desc())
    )
    reason = None
    if latest and latest.llm_json and isinstance(latest.llm_json, dict):
        reason = latest.llm_json.get("reason")
    return ListingOut(
        id=listing.id,
        source_id=listing.source_id,
        external_id=listing.external_id,
        title=listing.title,
        url=listing.url,
        employment_type=listing.employment_type,
        location=listing.location,
        description=listing.description,
        raw_snippet=listing.raw_snippet,
        summary=listing.summary,
        status=listing.status,
        relevance_score=listing.relevance_score,
        first_seen_at=listing.first_seen_at,
        last_seen_at=listing.last_seen_at,
        viewed_at=listing.viewed_at,
        disappeared=listing.disappeared,
        source_name=source.name if source else None,
        latest_confidence=latest.confidence if latest else None,
        latest_reason=reason,
    )


@router.get("", response_model=list[ListingOut])
def list_listings(
    status: str | None = Query(None),
    source_id: int | None = Query(None),
    db: Session = Depends(get_db),
) -> list[ListingOut]:
    stmt = select(Listing).order_by(Listing.last_seen_at.desc())
    if status:
        stmt = stmt.where(Listing.status == status)
    if source_id is not None:
        stmt = stmt.where(Listing.source_id == source_id)
    listings = db.scalars(stmt.limit(500)).all()
    return [_to_out(db, listing) for listing in listings]


@router.get("/{listing_id}", response_model=ListingOut)
def get_listing(listing_id: int, db: Session = Depends(get_db)) -> ListingOut:
    listing = db.get(Listing, listing_id)
    if not listing:
        raise HTTPException(404, "Listing not found")
    return _to_out(db, listing)


@router.post("/{listing_id}/view", response_model=ListingOut)
def mark_listing_viewed(listing_id: int, db: Session = Depends(get_db)) -> ListingOut:
    """Mark a listing as viewed: New → Open. Removed stays Removed."""
    listing = db.get(Listing, listing_id)
    if not listing:
        raise HTTPException(404, "Listing not found")
    listing.viewed_at = datetime.utcnow()
    if listing.status == "new":
        listing.status = "open"
    elif listing.status in {"candidate", "needs_review", "approved"}:
        # Migrate legacy inbox statuses to Open on first view.
        listing.status = "open"
    db.commit()
    db.refresh(listing)
    return _to_out(db, listing)


@router.post("/{listing_id}/review", response_model=ReviewOut)
def review_listing(
    listing_id: int,
    payload: ReviewCreate,
    db: Session = Depends(get_db),
) -> Review:
    listing = db.get(Listing, listing_id)
    if not listing:
        raise HTTPException(404, "Listing not found")
    review = Review(listing_id=listing.id, decision=payload.decision, note=payload.note)
    db.add(review)
    if payload.decision == "approved":
        listing.status = "open"
        listing.viewed_at = listing.viewed_at or datetime.utcnow()
    elif payload.decision == "rejected":
        listing.status = "discarded"
    elif payload.decision == "snoozed":
        listing.status = "open"
        listing.viewed_at = listing.viewed_at or datetime.utcnow()
    db.commit()
    db.refresh(review)
    return review
