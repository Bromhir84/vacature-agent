from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


AdapterKey = Literal["json", "html", "agent", "crawl"]
ListingStatus = Literal[
    "new",
    "open",
    "removed",
    "discarded",
    # Legacy statuses still accepted by API filters
    "candidate",
    "needs_review",
    "approved",
    "rejected",
    "ignored",
]
ReviewDecision = Literal["approved", "rejected", "snoozed"]


class SourceCreate(BaseModel):
    name: str
    base_url: str
    adapter_key: AdapterKey
    enabled: bool = True
    config: dict[str, Any] = Field(default_factory=dict)


class SourceUpdate(BaseModel):
    name: str | None = None
    base_url: str | None = None
    adapter_key: AdapterKey | None = None
    enabled: bool | None = None
    config: dict[str, Any] | None = None


class SourceOut(BaseModel):
    id: int
    name: str
    base_url: str
    adapter_key: str
    enabled: bool
    config: dict[str, Any]
    last_scan_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ListingOut(BaseModel):
    id: int
    source_id: int
    external_id: str
    title: str
    url: str
    employment_type: str | None
    location: str | None
    description: str | None
    raw_snippet: str | None
    summary: str | None = None
    status: str
    relevance_score: float | None = None
    first_seen_at: datetime
    last_seen_at: datetime
    viewed_at: datetime | None = None
    disappeared: bool
    source_name: str | None = None
    latest_confidence: float | None = None
    latest_reason: str | None = None

    model_config = {"from_attributes": True}


class ReviewCreate(BaseModel):
    decision: ReviewDecision
    note: str | None = None


class ReviewOut(BaseModel):
    id: int
    listing_id: int
    decision: str
    note: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class ScanRunOut(BaseModel):
    id: int
    source_id: int | None
    started_at: datetime
    finished_at: datetime | None
    status: str
    discovered: int
    upserted: int
    classified: int
    candidates: int
    errors: str | None
    source_name: str | None = None

    model_config = {"from_attributes": True}


class SettingsOut(BaseModel):
    staffing_keywords: list[str]
    employment_allowlist: list[str]
    employment_blocklist: list[str]
    confidence_candidate: float
    confidence_review: float
    scan_interval_hours: float
    agent_max_listings: int
    agent_max_pages: int
    llm_model: str
    llm_base_url: str
    llm_api_key_set: bool = False
    llm_api_key_masked: str = ""
    llm_source: str = "none"


class SettingsUpdate(BaseModel):
    staffing_keywords: list[str] | None = None
    employment_allowlist: list[str] | None = None
    employment_blocklist: list[str] | None = None
    confidence_candidate: float | None = None
    confidence_review: float | None = None
    scan_interval_hours: float | None = None
    agent_max_listings: int | None = None
    agent_max_pages: int | None = None
    llm_model: str | None = None
    llm_base_url: str | None = None
    llm_api_key: str | None = None
    clear_llm_api_key: bool | None = None


class ListingDraft(BaseModel):
    external_id: str
    title: str
    url: str
    employment_type: str | None = None
    location: str | None = None
    description: str | None = None
    raw_snippet: str | None = None
    tags: list[str] = Field(default_factory=list)


class DiscoveryProposeRequest(BaseModel):
    queries: list[str] = Field(default_factory=list)


class SourceProposalOut(BaseModel):
    id: int
    name: str
    career_url: str
    base_url: str
    origin: str
    kind: str
    broker_risk: float
    reasons: list[str] | dict | None = None
    status: str
    raw_snippet: str | None = None
    query: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class DiscoveryProposeResult(BaseModel):
    created: list[SourceProposalOut]
    updated: list[SourceProposalOut]
    skipped: list[dict[str, str]]


class DiscoveryHarvestResult(BaseModel):
    created: list[SourceProposalOut]
    updated: list[SourceProposalOut]
    blocked: int


class ProposalApproveRequest(BaseModel):
    force: bool = False


class SourceDuplicateOut(BaseModel):
    left_id: int
    left_name: str
    left_url: str | None = None
    right_id: int
    right_name: str
    right_url: str | None = None
    reasons: list[str]


class CrawlRunRequest(BaseModel):
    max_pages: int | None = None
    max_new_urls: int | None = None
    min_relevance: float | None = None
    queries: list[str] | None = None
    seed_urls: list[str] | None = None


class CrawlRunResult(BaseModel):
    run: ScanRunOut
    source_id: int
    pages_fetched: int
    discovered: int
    upserted: int
    skipped_broker: int
    skipped_low_score: int
    skipped_dup: int
    skipped_domain: int = 0
    skipped_unusable: int = 0
    skipped_recent: int = 0
    rejudged_discarded: int = 0
    proposals_created: int
    avg_relevance: float
    errors: list[str] = Field(default_factory=list)


class CrawlRejudgeResult(BaseModel):
    reviewed: int
    kept: int
    discarded: int


class CrawlClearResult(BaseModel):
    listings: int
    classifications: int
    reviews: int
    runs: int
    proposals: int
    visits: int = 0
