"""
Crawl models — URL frontier, fetched pages, and collection campaigns (jobs).

Campaign lifecycle (status):
  queued → running → completed | completed_with_errors | failed | cancelled
  running may be interrupted (worker restart); the worker resumes it.
  cancel_requested is set by the API and honoured by the worker between URLs.
  archived marks historical records hidden from default listings.
"""

from sqlalchemy import Boolean, Column, Float, ForeignKey, Index, Integer, JSON, LargeBinary, String, Text

from backend.app.database import Base
from backend.app.models.coltypes import UTCDateTime, utcnow

ACTIVE_CAMPAIGN_STATUSES = ("queued", "running", "cancel_requested")
TERMINAL_CAMPAIGN_STATUSES = ("completed", "completed_with_errors", "failed", "cancelled", "archived")


class CrawlUrl(Base):
    """URL frontier — every URL discovered for potential crawling."""
    __tablename__ = "crawl_urls"

    id = Column(Integer, primary_key=True, index=True)
    source_id = Column(Integer, ForeignKey("sources.id"), nullable=True, index=True)
    campaign_id = Column(Integer, ForeignKey("collection_campaigns.id"), nullable=True, index=True)

    url = Column(String(2048), nullable=False, index=True)
    canonical_url = Column(String(2048), nullable=True, index=True)
    domain = Column(String(255), nullable=True, index=True)

    discovered_from = Column(String(2048), nullable=True)
    discovery_method = Column(String(30), nullable=False, default="manual",
                              doc="seed / sitemap / rss / pagination / internal_link / api")
    discovery_query = Column(String(500), nullable=True)
    depth = Column(Integer, nullable=False, default=0)

    priority = Column(Integer, nullable=False, default=5, doc="1=highest, 10=lowest")
    status = Column(String(20), nullable=False, default="queued", index=True,
                    doc="queued / processing / success / unchanged / failed / blocked / skipped")

    attempt_count = Column(Integer, nullable=False, default=0)
    last_attempt_at = Column(UTCDateTime, nullable=True)
    next_attempt_at = Column(UTCDateTime, nullable=True)

    http_status = Column(Integer, nullable=True)
    content_type = Column(String(100), nullable=True)
    content_hash = Column(String(64), nullable=True)
    content_length = Column(Integer, nullable=True)
    etag = Column(String(255), nullable=True)
    last_modified = Column(String(100), nullable=True)

    records_extracted = Column(Integer, nullable=False, default=0)
    error_message = Column(Text, nullable=True)

    created_at = Column(UTCDateTime, nullable=False, default=utcnow)
    updated_at = Column(UTCDateTime, nullable=False, default=utcnow, onupdate=utcnow)

    __table_args__ = (
        Index("ix_crawl_urls_status_priority", "status", "priority"),
        Index("ix_crawl_urls_domain_status", "domain", "status"),
        Index("ix_crawl_urls_campaign", "campaign_id", "status"),
    )


class CrawlPage(Base):
    """A successfully fetched document (HTML page, feed, PDF, JSON, CSV)."""
    __tablename__ = "crawl_pages"

    id = Column(Integer, primary_key=True, index=True)
    crawl_url_id = Column(Integer, ForeignKey("crawl_urls.id"), nullable=False, index=True)
    source_id = Column(Integer, ForeignKey("sources.id"), nullable=True)
    campaign_id = Column(Integer, ForeignKey("collection_campaigns.id"), nullable=True)
    run_id = Column(Integer, ForeignKey("source_runs.id"), nullable=True)

    url = Column(String(2048), nullable=False)
    final_url = Column(String(2048), nullable=True, doc="URL after validated redirects")
    http_status = Column(Integer, nullable=True)
    content_type = Column(String(100), nullable=True)
    content_hash = Column(String(64), nullable=True, index=True)
    content_length = Column(Integer, nullable=True)
    raw_content = Column(LargeBinary, nullable=True, doc="zlib-compressed response body (for reprocessing)")

    page_type = Column(String(30), nullable=True, doc="html / rss / sitemap / pdf / json / csv")
    has_useful_content = Column(Boolean, nullable=False, default=False)
    relevance_score = Column(Float, nullable=True)

    records_extracted = Column(Integer, nullable=False, default=0)
    extraction_method = Column(String(30), nullable=True)

    title = Column(String(500), nullable=True)
    description = Column(Text, nullable=True)
    published_at = Column(UTCDateTime, nullable=True, doc="From page metadata; NULL if not stated")
    modified_at = Column(UTCDateTime, nullable=True, doc="From page metadata; NULL if not stated")
    date_source = Column(String(50), nullable=True, doc="Which metadata field supplied published_at")
    language = Column(String(20), nullable=True)

    fetched_at = Column(UTCDateTime, nullable=False, default=utcnow)
    processed_at = Column(UTCDateTime, nullable=True)

    __table_args__ = (
        Index("ix_crawl_pages_source_type", "source_id", "page_type"),
    )


class CollectionCampaign(Base):
    """A collection job over one or more registered sources."""
    __tablename__ = "collection_campaigns"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    trigger = Column(String(20), nullable=False, default="manual", doc="manual / schedule")

    # Config
    schemes = Column(JSON, nullable=True)
    topics = Column(JSON, nullable=True)
    languages = Column(JSON, nullable=True)
    source_ids = Column(JSON, nullable=True, doc="Source IDs to include; NULL = all active sources")
    max_urls = Column(Integer, nullable=True, default=200)
    max_depth = Column(Integer, nullable=True, default=1)
    max_pages_per_source = Column(Integer, nullable=True, default=40)

    status = Column(String(30), nullable=False, default="queued", index=True)
    stage = Column(String(30), nullable=True, doc="discovering / fetching / processing / clustering")
    error_message = Column(Text, nullable=True)

    # Metrics (all derived from actual job execution)
    urls_discovered = Column(Integer, nullable=False, default=0)
    urls_accepted = Column(Integer, nullable=False, default=0)
    urls_processed = Column(Integer, nullable=False, default=0)
    urls_failed = Column(Integer, nullable=False, default=0)
    urls_blocked = Column(Integer, nullable=False, default=0)
    urls_unchanged = Column(Integer, nullable=False, default=0)
    pages_downloaded = Column(Integer, nullable=False, default=0)
    pages_useful = Column(Integer, nullable=False, default=0)
    records_extracted = Column(Integer, nullable=False, default=0)
    records_duplicate = Column(Integer, nullable=False, default=0)
    records_rejected = Column(Integer, nullable=False, default=0)
    records_final = Column(Integer, nullable=False, default=0)
    records_processed = Column(Integer, nullable=False, default=0)

    started_at = Column(UTCDateTime, nullable=True, doc="crawl_started_at")
    finished_at = Column(UTCDateTime, nullable=True, doc="crawl_finished_at")
    heartbeat_at = Column(UTCDateTime, nullable=True, doc="Last progress write by the worker")
    created_at = Column(UTCDateTime, nullable=False, default=utcnow)


class CollectionEvent(Base):
    """Append-only event log for a campaign (drives the live activity view)."""
    __tablename__ = "collection_events"

    id = Column(Integer, primary_key=True)
    campaign_id = Column(Integer, ForeignKey("collection_campaigns.id"), nullable=False, index=True)
    source_id = Column(Integer, ForeignKey("sources.id"), nullable=True)
    level = Column(String(10), nullable=False, default="info", doc="info / warning / error")
    kind = Column(String(30), nullable=False, doc="stage / fetch / extract / record / error / summary")
    message = Column(Text, nullable=False)
    url = Column(String(2048), nullable=True)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=True)
    created_at = Column(UTCDateTime, nullable=False, default=utcnow, index=True)
