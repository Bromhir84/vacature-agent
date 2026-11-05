from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.discovery.coverage import find_duplicate_sources
from app.discovery.service import (
    approve_proposal,
    propose_from_queries,
    run_portal_harvest,
)
from app.models import SourceProposal
from app.schemas import (
    DiscoveryHarvestResult,
    DiscoveryProposeRequest,
    DiscoveryProposeResult,
    ProposalApproveRequest,
    SourceDuplicateOut,
    SourceOut,
    SourceProposalOut,
)

router = APIRouter(prefix="/api/discovery", tags=["discovery"])


@router.post("/propose", response_model=DiscoveryProposeResult)
def propose_sources(
    payload: DiscoveryProposeRequest,
    db: Session = Depends(get_db),
) -> DiscoveryProposeResult:
    queries = [q.strip() for q in payload.queries if q and q.strip()]
    if not queries:
        raise HTTPException(400, "Provide at least one company name, domain, or URL")
    if len(queries) > 40:
        raise HTTPException(400, "Max 40 queries per request")
    result = propose_from_queries(db, queries, use_llm=True)
    return DiscoveryProposeResult(
        created=result["created"],
        updated=result["updated"],
        skipped=result["skipped"],
    )


@router.post("/harvest", response_model=DiscoveryHarvestResult)
def harvest_portals(db: Session = Depends(get_db)) -> DiscoveryHarvestResult:
    result = run_portal_harvest(db)
    return DiscoveryHarvestResult(
        created=result["created"],
        updated=result["updated"],
        blocked=result["blocked"],
    )


@router.get("/proposals", response_model=list[SourceProposalOut])
def list_proposals(
    status: str | None = Query(default="pending"),
    db: Session = Depends(get_db),
) -> list[SourceProposal]:
    stmt = select(SourceProposal).order_by(SourceProposal.created_at.desc())
    if status:
        stmt = stmt.where(SourceProposal.status == status)
    return list(db.scalars(stmt).all())


@router.get("/duplicates", response_model=list[SourceDuplicateOut])
def list_source_duplicates(db: Session = Depends(get_db)) -> list[SourceDuplicateOut]:
    return [SourceDuplicateOut(**row) for row in find_duplicate_sources(db)]


@router.post("/proposals/{proposal_id}/approve", response_model=SourceOut)
def approve(
    proposal_id: int,
    payload: ProposalApproveRequest = ProposalApproveRequest(),
    db: Session = Depends(get_db),
) -> SourceOut:
    proposal = db.get(SourceProposal, proposal_id)
    if not proposal:
        raise HTTPException(404, "Proposal not found")
    if proposal.status == "approved":
        raise HTTPException(400, "Proposal already approved")
    if proposal.status == "rejected":
        raise HTTPException(400, "Proposal was rejected")
    source = approve_proposal(db, proposal, force=payload.force)
    return source


@router.post("/proposals/{proposal_id}/reject", response_model=SourceProposalOut)
def reject(proposal_id: int, db: Session = Depends(get_db)) -> SourceProposal:
    proposal = db.get(SourceProposal, proposal_id)
    if not proposal:
        raise HTTPException(404, "Proposal not found")
    if proposal.status == "approved":
        raise HTTPException(400, "Proposal already approved")
    proposal.status = "rejected"
    db.commit()
    db.refresh(proposal)
    return proposal
