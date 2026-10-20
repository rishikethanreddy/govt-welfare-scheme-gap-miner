"""
Source and SourceRun models — data source registry and per-source collection history.

verification_status distinguishes how much is actually known about a source:
  configured — registered, never fetched
  reachable  — last fetch succeeded but nothing was extracted yet
  collected  — at least one record has been persisted from it
  failing    — last attempt failed (see last_error)
  blocked    — robots.txt / policy disallows collection
"""

from sqlalchemy import Boolean, Column, Float, ForeignKey, Index, Integer, JSON, String, Text
from sqlalchemy.orm import relationship

from backend.app.database import Base
from backend.app.models.coltypes import UTCDateTime, utcnow


class Source(Base):
    __tablename__ = "sources"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), nullable=False, index=True)
    url = Column(String(2048), nullable=True)
    source_type = Column(String(50), nullable=False, default="manual", index=True,
                         doc="official / open_data / news / publication / csv_upload / other")
    organization = Column(String(200), nullable=True)
    country = Column(String(50), nullable=True, default="India")
    language = Column(String(50), nullable=True, default="en")
    description = Column(Text, nullable=True)
    category = Column(String(50), nullable=True)

    # ── Collection policy ─────────────────────────────────────────────────
    collection_method = Column(String(50), nullable=True, default="manual")
    content_type = Column(String(100), nullable=True, doc="Adapter: html / rss / sitemap / json_api / csv / pdf / datagovin")
    config = Column(JSON, nullable=True, doc="Adapter options (e.g. data.gov.in resource id, JSON field map)")
    policy_status = Column(String(30), nullable=False, default="manual_review",
                           doc="allowed / manual_review / blocked / unsupported / credentials_required")
    policy_note = Column(Text, nullable=True, doc="Why the policy status was assigned")
    robots_checked = Column(Boolean, nullable=False, default=False)
    robots_allowed = Column(Boolean, nullable=True)
    terms_checked = Column(Boolean, nullable=False, default=False)
    api_available = Column(Boolean, nullable=False, default=False)
    auth_required = Column(Boolean, nullable=False, default=False)
    crawl_delay = Column(Float, nullable=True)
    rate_limit = Column(String(100), nullable=True)
    max_pages = Column(Integer, nullable=True)

    # ── Operational ───────────────────────────────────────────────────────
    active = Column(Boolean, nullable=False, default=True, index=True)
    schedule = Column(String(20), nullable=True, default="manual", doc="manual / daily / weekly")
    verification_status = Column(String(20), nullable=False, default="configured")
    last_run_at = Column(UTCDateTime, nullable=True)
    last_success_at = Column(UTCDateTime, nullable=True)
    last_error = Column(Text, nullable=True)
    consecutive_failures = Column(Integer, nullable=False, default=0)
    total_records_collected = Column(Integer, nullable=False, default=0)
    total_runs = Column(Integer, nullable=False, default=0)
    health_score = Column(Float, nullable=True)

    created_at = Column(UTCDateTime, nullable=False, default=utcnow)
    updated_at = Column(UTCDateTime, nullable=False, default=utcnow, onupdate=utcnow)

    documents = relationship("Document", back_populates="source", lazy="select")
    runs = relationship("SourceRun", back_populates="source", lazy="select", order_by="SourceRun.started_at.desc()")

    def __repr__(self):
        return f"<Source(id={self.id}, name={self.name}, type={self.source_type})>"


class SourceRun(Base):
    """One source's portion of a campaign (or a legacy single-source scrape)."""
    __tablename__ = "source_runs"

    id = Column(Integer, primary_key=True, index=True)
    source_id = Column(Integer, ForeignKey("sources.id"), nullable=False, index=True)
    campaign_id = Column(Integer, ForeignKey("collection_campaigns.id"), nullable=True, index=True)

    status = Column(String(30), nullable=False, default="running",
                    doc="running / completed / completed_with_errors / failed / blocked / cancelled")
    started_at = Column(UTCDateTime, nullable=False, default=utcnow)
    finished_at = Column(UTCDateTime, nullable=True)

    urls_discovered = Column(Integer, nullable=False, default=0)
    urls_attempted = Column(Integer, nullable=False, default=0)
    successful = Column(Integer, nullable=False, default=0)
    skipped = Column(Integer, nullable=False, default=0)
    blocked = Column(Integer, nullable=False, default=0)
    failed = Column(Integer, nullable=False, default=0)
    records_extracted = Column(Integer, nullable=False, default=0)
    records_accepted = Column(Integer, nullable=False, default=0)
    records_rejected = Column(Integer, nullable=False, default=0)
    duplicates_found = Column(Integer, nullable=False, default=0)

    error_message = Column(Text, nullable=True)
    error_details = Column(Text, nullable=True)

    source = relationship("Source", back_populates="runs")

    __table_args__ = (
        Index("ix_source_runs_source_status", "source_id", "status"),
    )
