"""
Document model — the core entity of the system.

Each document is one text record (question, complaint, FAQ entry, news item, …)
about a government welfare scheme, with NLP annotations and full provenance.

Labels: `intent`, `awareness_gap` and `gap_type` are the *effective* labels used by
analytics. `label_source` says where they came from:
  manual — supplied with an imported dataset (never overwritten by reprocessing)
  review — set by a reviewer in the manual-review queue
  model  — copied from the model prediction
Model outputs are always stored separately in the `predicted_*` columns, so manual
labels and predictions can be compared.

Timestamps (all UTC):
  source_published_at / source_updated_at — supplied by the original source; NULL
      when the source does not state them (never substituted with crawl time)
  first_seen_at — first time this system observed this content
  collected_at  — when the system retrieved this copy
  processed_at  — when NLP processing last completed
"""

from sqlalchemy import (
    Boolean, Column, Float, ForeignKey, Index, Integer, JSON, String, Text,
)
from sqlalchemy.orm import relationship

from backend.app.database import Base
from backend.app.models.coltypes import UTCDateTime, utcnow


class Document(Base):
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True, index=True)

    # ── Content ───────────────────────────────────────────────────────────
    original_text = Column(Text, nullable=False, doc="Text as collected (PII identifiers redacted)")
    normalized_text = Column(Text, nullable=True, doc="NFKC-normalized, whitespace-collapsed text")
    content_hash = Column(String(64), nullable=True, index=True, doc="SHA-256 of normalized text")
    language = Column(String(20), nullable=True, index=True, doc="ISO code, hi-Latn, or und")
    language_method = Column(String(30), nullable=True)
    language_supported = Column(Boolean, nullable=True, doc="Whether the trained models support this language")
    text_role = Column(String(50), nullable=True, default="query",
                       doc="query / question / complaint / discussion / faq / news / article / paragraph")
    origin = Column(String(20), nullable=False, default="live", index=True, doc="dataset / live / manual")

    # ── Effective labels (used by analytics) ──────────────────────────────
    scheme_id = Column(Integer, ForeignKey("schemes.id"), nullable=True, index=True)
    scheme_name = Column(String(100), nullable=True, index=True, doc="Primary scheme code; NULL = Other/Unknown")
    schemes = Column(JSON, nullable=True, doc="All detected scheme codes, primary first")
    scheme_match_strength = Column(String(10), nullable=True, doc="strong / weak / manual / context")
    scheme_context = Column(String(100), nullable=True,
                            doc="Scheme of the page a comment was posted on (used only if the text names none)")
    intent = Column(String(50), nullable=True, index=True)
    intent_confidence = Column(Float, nullable=True)
    awareness_gap = Column(String(20), nullable=True, index=True, doc="yes / no / unclear / not_applicable")
    gap_confidence = Column(Float, nullable=True)
    gap_type = Column(String(50), nullable=True, index=True)
    gap_type_confidence = Column(Float, nullable=True)
    label_source = Column(String(20), nullable=True, index=True, doc="manual / review / model")

    # ── Model predictions (always from the model, never manual) ───────────
    predicted_intent = Column(String(50), nullable=True)
    predicted_intent_confidence = Column(Float, nullable=True)
    predicted_gap = Column(String(20), nullable=True)
    predicted_gap_confidence = Column(Float, nullable=True)
    predicted_gap_type = Column(String(50), nullable=True)
    predicted_gap_type_confidence = Column(Float, nullable=True)
    explanation = Column(JSON, nullable=True, doc="Reasons, abstention cause, nearest labelled examples")

    # ── Manual review ─────────────────────────────────────────────────────
    needs_review = Column(Boolean, nullable=False, default=False, index=True)
    reviewed_at = Column(UTCDateTime, nullable=True)
    reviewed_by = Column(String(100), nullable=True)
    review_note = Column(Text, nullable=True)

    # ── Geography (only from explicit source metadata; never inferred) ────
    state = Column(String(100), nullable=True, index=True)
    district = Column(String(100), nullable=True, index=True)
    state_id = Column(Integer, ForeignKey("geographic_entities.id"), nullable=True)
    district_id = Column(Integer, ForeignKey("geographic_entities.id"), nullable=True)

    # ── Provenance ────────────────────────────────────────────────────────
    source_id = Column(Integer, ForeignKey("sources.id"), nullable=True, index=True)
    source_name = Column(String(200), nullable=True)
    source_type = Column(String(50), nullable=True)
    source_url = Column(String(2048), nullable=True)
    source_document_id = Column(String(200), nullable=True, doc="ID within the original source")
    scrape_run_id = Column(Integer, ForeignKey("source_runs.id"), nullable=True)
    campaign_id = Column(Integer, ForeignKey("collection_campaigns.id"), nullable=True, index=True)
    crawl_page_id = Column(Integer, ForeignKey("crawl_pages.id"), nullable=True)
    extraction_method = Column(String(30), nullable=True)

    # ── Dataset ───────────────────────────────────────────────────────────
    dataset_version_id = Column(Integer, ForeignKey("dataset_versions.id"), nullable=True, index=True)
    original_csv_id = Column(String(50), nullable=True, doc="Row ID from the imported file")

    # ── Processing ────────────────────────────────────────────────────────
    processing_status = Column(String(20), nullable=False, default="pending", index=True,
                               doc="pending / processing / completed / failed")
    processing_error = Column(Text, nullable=True)
    processing_attempts = Column(Integer, nullable=False, default=0)
    quality_score = Column(Float, nullable=True)
    confidence = Column(String(20), nullable=True, doc="Annotator confidence from imported datasets")
    notes = Column(Text, nullable=True)

    # ── Flags ─────────────────────────────────────────────────────────────
    is_synthetic = Column(Boolean, nullable=False, default=False)
    is_demo = Column(Boolean, nullable=False, default=False, doc="Fixture/demo content, excluded from analytics")
    is_duplicate = Column(Boolean, nullable=False, default=False, index=True)
    duplicate_group_id = Column(String(64), nullable=True)
    duplicate_of_id = Column(Integer, ForeignKey("documents.id"), nullable=True)
    near_duplicate_of_id = Column(Integer, ForeignKey("documents.id"), nullable=True)
    near_duplicate_similarity = Column(Float, nullable=True)

    # ── PII ───────────────────────────────────────────────────────────────
    pii_detected = Column(Boolean, nullable=False, default=False)
    pii_redacted = Column(Boolean, nullable=False, default=False)

    # ── Model versions ────────────────────────────────────────────────────
    embedding_model = Column(String(100), nullable=True)
    intent_model_version = Column(String(80), nullable=True)
    gap_model_version = Column(String(80), nullable=True)
    embedding_model_version = Column(String(80), nullable=True)
    scheme_detection_version = Column(String(50), nullable=True)

    split = Column(String(10), nullable=True, index=True, doc="train / val / test (imported datasets)")

    # ── Timestamps ────────────────────────────────────────────────────────
    source_published_at = Column(UTCDateTime, nullable=True)
    source_updated_at = Column(UTCDateTime, nullable=True)
    first_seen_at = Column(UTCDateTime, nullable=True)
    collected_at = Column(UTCDateTime, nullable=True, default=utcnow)
    processed_at = Column(UTCDateTime, nullable=True)
    created_at = Column(UTCDateTime, nullable=False, default=utcnow)
    updated_at = Column(UTCDateTime, nullable=False, default=utcnow, onupdate=utcnow)

    # ── Relationships ─────────────────────────────────────────────────────
    scheme = relationship("Scheme", back_populates="documents", lazy="select")
    source = relationship("Source", back_populates="documents", lazy="select")
    dataset_version = relationship("DatasetVersion", back_populates="documents", lazy="select")

    __table_args__ = (
        Index("ix_documents_scheme_intent", "scheme_name", "intent"),
        Index("ix_documents_scheme_gap", "scheme_name", "awareness_gap"),
        Index("ix_documents_state_scheme", "state", "scheme_name"),
        Index("ix_documents_gap_type_state", "gap_type", "state"),
        Index("ix_documents_processing", "processing_status", "created_at"),
        Index("ix_documents_origin_dup", "origin", "is_duplicate", "is_demo"),
    )

    def __repr__(self):
        return f"<Document(id={self.id}, scheme={self.scheme_name}, intent={self.intent})>"
