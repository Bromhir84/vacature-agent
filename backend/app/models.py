from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def utcnow() -> datetime:
    return datetime.utcnow()


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    base_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    adapter_key: Mapped[str] = mapped_column(String(32), nullable=False)  # json | html | agent
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    last_scan_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    listings: Mapped[list[Listing]] = relationship(back_populates="source")
    scan_runs: Mapped[list[ScanRun]] = relationship(back_populates="source")


class Listing(Base):
    __tablename__ = "listings"
    __table_args__ = (UniqueConstraint("source_id", "external_id", name="uq_source_external"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), nullable=False)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    employment_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_snippet: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="new")
    # Inbox: new | open | removed. Internal: discarded (failed staffing gate).
    # Legacy: candidate | needs_review | approved | rejected | ignored
    relevance_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    viewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    disappeared: Mapped[bool] = mapped_column(Boolean, default=False)

    source: Mapped[Source] = relationship(back_populates="listings")
    classifications: Mapped[list[Classification]] = relationship(back_populates="listing")
    reviews: Mapped[list[Review]] = relationship(back_populates="listing")


class Classification(Base):
    __tablename__ = "classifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    listing_id: Mapped[int] = mapped_column(ForeignKey("listings.id"), nullable=False)
    rule_hit: Mapped[bool] = mapped_column(Boolean, default=False)
    rule_reasons: Mapped[list | dict | None] = mapped_column(JSON, nullable=True)
    llm_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    listing: Mapped[Listing] = relationship(back_populates="classifications")


class Review(Base):
    __tablename__ = "reviews"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    listing_id: Mapped[int] = mapped_column(ForeignKey("listings.id"), nullable=False)
    decision: Mapped[str] = mapped_column(String(32), nullable=False)  # approved | rejected | snoozed
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    listing: Mapped[Listing] = relationship(back_populates="reviews")


class ScanRun(Base):
    __tablename__ = "scan_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int | None] = mapped_column(ForeignKey("sources.id"), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="running")  # running | success | error
    discovered: Mapped[int] = mapped_column(Integer, default=0)
    upserted: Mapped[int] = mapped_column(Integer, default=0)
    classified: Mapped[int] = mapped_column(Integer, default=0)
    candidates: Mapped[int] = mapped_column(Integer, default=0)
    errors: Mapped[str | None] = mapped_column(Text, nullable=True)

    source: Mapped[Source | None] = relationship(back_populates="scan_runs")


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[dict | list | str | int | float | bool | None] = mapped_column(JSON, nullable=True)


class CrawlVisit(Base):
    """Persisted crawl fetches so open-web runs do not rehit the same pages."""

    __tablename__ = "crawl_visits"
    __table_args__ = (UniqueConstraint("url", name="uq_crawl_visit_url"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    host: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    outcome: Mapped[str] = mapped_column(String(32), default="fetched")
    # fetched | error | skipped
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class SourceProposal(Base):
    __tablename__ = "source_proposals"
    __table_args__ = (UniqueConstraint("career_url", name="uq_proposal_career_url"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    career_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    base_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    origin: Mapped[str] = mapped_column(String(32), nullable=False)  # paste | portal | crawl
    kind: Mapped[str] = mapped_column(String(32), default="unknown")
    # employer | portal | broker | unknown
    broker_risk: Mapped[float] = mapped_column(Float, default=0.5)
    reasons: Mapped[list | dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    # pending | approved | rejected | blocked
    raw_snippet: Mapped[str | None] = mapped_column(Text, nullable=True)
    query: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
