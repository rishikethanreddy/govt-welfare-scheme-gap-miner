"""
ModelVersion — tracks NLP model versions and their evaluation metrics.

Only displays actual metrics from real evaluations.
If no evaluation exists, metrics remain null.
"""

from sqlalchemy import Column, Integer, String, Text, Float, Boolean
from backend.app.database import Base
from backend.app.models.coltypes import UTCDateTime, utcnow


class ModelVersion(Base):
    __tablename__ = "model_versions"

    id = Column(Integer, primary_key=True, index=True)
    model_name = Column(String(100), nullable=False, index=True, doc="e.g., intent_classifier, gap_classifier")
    model_type = Column(
        String(50), nullable=False,
        doc="tfidf_logreg / transformer / rule_based / sentence_transformer / hdbscan"
    )
    version = Column(String(50), nullable=False, index=True)
    description = Column(Text, nullable=True)

    # ── Training ──────────────────────────────────────────────────────────
    training_dataset_version = Column(String(50), nullable=True)
    training_samples = Column(Integer, nullable=True)
    training_date = Column(UTCDateTime, nullable=True)

    # ── Evaluation Metrics (null until actual evaluation) ─────────────────
    accuracy = Column(Float, nullable=True)
    precision_score = Column(Float, nullable=True)
    recall = Column(Float, nullable=True)
    f1_score = Column(Float, nullable=True)
    validation_samples = Column(Integer, nullable=True)
    confusion_matrix = Column(Text, nullable=True, doc="JSON serialized confusion matrix")
    class_report = Column(Text, nullable=True, doc="JSON serialized classification report")
    evaluation_notes = Column(Text, nullable=True)

    # ── Storage ───────────────────────────────────────────────────────────
    model_path = Column(String(500), nullable=True, doc="Path to saved model file")
    file_size_bytes = Column(Integer, nullable=True)

    # ── Status ────────────────────────────────────────────────────────────
    status = Column(
        String(20), nullable=False, default="trained",
        doc="training / trained / evaluated / deployed / archived"
    )
    is_active = Column(Boolean, nullable=False, default=False, doc="Currently active model for inference")

    # ── Timestamps ────────────────────────────────────────────────────────
    created_at = Column(UTCDateTime, nullable=False, default=utcnow)

    def __repr__(self):
        return f"<ModelVersion(name={self.model_name}, version={self.version}, status={self.status})>"
