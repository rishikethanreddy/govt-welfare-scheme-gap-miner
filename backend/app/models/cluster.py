"""
Cluster models — semantic clusters of documents from a clustering run.

A run clusters one scope (dataset or live) at a time. Only the latest run per
scope is marked is_active; older runs are kept for comparison.
"""

from sqlalchemy import Boolean, Column, Float, ForeignKey, Index, Integer, JSON, String, Text
from sqlalchemy.orm import relationship

from backend.app.database import Base
from backend.app.models.coltypes import UTCDateTime, utcnow


class Cluster(Base):
    __tablename__ = "clusters"

    id = Column(Integer, primary_key=True, index=True)
    cluster_label = Column(Integer, nullable=False)
    name = Column(String(200), nullable=True, doc="Generated from top c-TF-IDF keywords")
    description = Column(Text, nullable=True)
    scope = Column(String(20), nullable=True, index=True, doc="dataset / live")
    is_active = Column(Boolean, nullable=False, default=True, index=True)

    size = Column(Integer, nullable=False, default=0)
    keywords = Column(JSON, nullable=True)
    cohesion = Column(Float, nullable=True, doc="Mean cosine similarity of members to centroid")
    persistence = Column(Float, nullable=True, doc="HDBSCAN cluster persistence (stability)")
    representative_text = Column(Text, nullable=True)
    representative_texts = Column(Text, nullable=True, doc="JSON array of top-N representative texts")

    dominant_scheme = Column(String(100), nullable=True)
    dominant_intent = Column(String(50), nullable=True)
    dominant_gap_type = Column(String(50), nullable=True)
    dominant_state = Column(String(100), nullable=True)
    gap_signals = Column(Integer, nullable=True)

    algorithm = Column(String(50), nullable=True)
    model_version = Column(String(80), nullable=True)
    embedding_model = Column(String(100), nullable=True)
    run_id = Column(String(50), nullable=True, index=True)

    created_at = Column(UTCDateTime, nullable=False, default=utcnow)

    document_clusters = relationship("DocumentCluster", back_populates="cluster", lazy="select",
                                     cascade="all, delete-orphan")


class DocumentCluster(Base):
    __tablename__ = "document_clusters"

    id = Column(Integer, primary_key=True, index=True)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=False, index=True)
    cluster_id = Column(Integer, ForeignKey("clusters.id"), nullable=False, index=True)
    similarity_score = Column(Float, nullable=True, doc="Cosine similarity to cluster centroid")
    membership_probability = Column(Float, nullable=True, doc="HDBSCAN membership strength")
    is_representative = Column(Integer, nullable=False, default=0)

    cluster = relationship("Cluster", back_populates="document_clusters")

    __table_args__ = (
        Index("ix_doc_clusters_doc_cluster", "document_id", "cluster_id", unique=True),
    )
