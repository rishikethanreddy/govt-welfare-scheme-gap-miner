"""
Processing models — DatasetVersion and ProcessingJob.

DatasetVersion tracks each imported file (with its SHA-256, so re-importing the
same file is detected). ProcessingJob tracks background NLP / import / clustering
work with progress, so long-running work is visible in the UI.
"""

from sqlalchemy import Column, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from backend.app.database import Base
from backend.app.models.coltypes import UTCDateTime, utcnow


class DatasetVersion(Base):
    __tablename__ = "dataset_versions"

    id = Column(Integer, primary_key=True, index=True)
    version = Column(String(50), nullable=False, unique=True, index=True)
    name = Column(String(200), nullable=True)
    description = Column(Text, nullable=True)
    source_file = Column(String(500), nullable=True)
    file_sha256 = Column(String(64), nullable=True, index=True)
    source_type = Column(String(50), nullable=True, default="csv_upload")

    record_count = Column(Integer, nullable=False, default=0)
    valid_records = Column(Integer, nullable=False, default=0)
    duplicate_records = Column(Integer, nullable=False, default=0)
    rejected_records = Column(Integer, nullable=False, default=0)
    processed_records = Column(Integer, nullable=False, default=0)

    processing_status = Column(String(20), nullable=False, default="imported",
                               doc="importing / imported / processed / partial (some rows failed NLP) / failed")
    column_mapping = Column(Text, nullable=True, doc="JSON mapping of canonical field → file column")
    rejections = Column(Text, nullable=True, doc="JSON list of rejected rows with reasons (first 200)")
    changes = Column(Text, nullable=True)

    created_at = Column(UTCDateTime, nullable=False, default=utcnow)
    updated_at = Column(UTCDateTime, nullable=False, default=utcnow, onupdate=utcnow)

    documents = relationship("Document", back_populates="dataset_version", lazy="select")


class ProcessingJob(Base):
    __tablename__ = "processing_jobs"

    id = Column(Integer, primary_key=True, index=True)
    job_type = Column(String(50), nullable=False, index=True,
                      doc="dataset_import / nlp_process / reprocess / clustering")
    status = Column(String(20), nullable=False, default="pending", index=True,
                    doc="pending / running / completed / failed / cancelled")
    dataset_version_id = Column(Integer, ForeignKey("dataset_versions.id"), nullable=True)

    total_items = Column(Integer, nullable=True)
    processed_items = Column(Integer, nullable=False, default=0)
    failed_items = Column(Integer, nullable=False, default=0)
    progress = Column(Float, nullable=False, default=0.0)

    params = Column(Text, nullable=True)
    result = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)
    error_details = Column(Text, nullable=True)

    created_at = Column(UTCDateTime, nullable=False, default=utcnow)
    started_at = Column(UTCDateTime, nullable=True)
    finished_at = Column(UTCDateTime, nullable=True)
