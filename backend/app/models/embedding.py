"""Persisted sentence embeddings (one row per document per embedding model)."""

from sqlalchemy import Column, ForeignKey, Integer, LargeBinary, String

from backend.app.database import Base
from backend.app.models.coltypes import UTCDateTime, utcnow


class DocumentEmbedding(Base):
    __tablename__ = "document_embeddings"

    document_id = Column(Integer, ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True)
    model = Column(String(100), nullable=False, index=True)
    dim = Column(Integer, nullable=False)
    vector = Column(LargeBinary, nullable=False, doc="L2-normalised float32 vector")
    content_hash = Column(String(64), nullable=True, doc="Hash of the text that was embedded")
    created_at = Column(UTCDateTime, nullable=False, default=utcnow)


class SystemState(Base):
    """Small key/value store for operational state (worker heartbeat, autopilot)."""
    __tablename__ = "system_state"

    key = Column(String(100), primary_key=True)
    value = Column(String(4000), nullable=True)
    updated_at = Column(UTCDateTime, nullable=False, default=utcnow, onupdate=utcnow)
