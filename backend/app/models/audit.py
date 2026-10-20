"""
AuditLog — system activity tracking for accountability and debugging.

Logs important system events: data imports, NLP runs, source operations,
configuration changes, etc. Never logs passwords, tokens, or PII.
"""

from sqlalchemy import Column, Integer, String, Text, Index
from backend.app.database import Base
from backend.app.models.coltypes import UTCDateTime, utcnow


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    action = Column(
        String(50), nullable=False, index=True,
        doc="dataset_import / nlp_process / source_run / scheme_update / model_train / system / error"
    )
    entity_type = Column(String(50), nullable=True, doc="document / source / dataset / model / scheme")
    entity_id = Column(String(50), nullable=True)
    description = Column(Text, nullable=True)
    details = Column(Text, nullable=True, doc="JSON additional details")
    user = Column(String(100), nullable=True, default="system")
    ip_address = Column(String(50), nullable=True)
    severity = Column(String(20), nullable=False, default="info", doc="info / warning / error / critical")

    # ── Timestamps ────────────────────────────────────────────────────────
    created_at = Column(UTCDateTime, nullable=False, default=utcnow)

    __table_args__ = (
        Index("ix_audit_action_date", "action", "created_at"),
        Index("ix_audit_entity", "entity_type", "entity_id"),
    )

    def __repr__(self):
        return f"<AuditLog(id={self.id}, action={self.action})>"
