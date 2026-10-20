"""
Scheme model — configurable registry of government welfare schemes.

Schemes are NOT hard-coded in NLP code. Admins can add/edit schemes
without modifying source code.
"""

from sqlalchemy import Column, Integer, String, Text, Boolean
from sqlalchemy.orm import relationship
from backend.app.database import Base
from backend.app.models.coltypes import UTCDateTime, utcnow


class Scheme(Base):
    __tablename__ = "schemes"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), nullable=False, unique=True, index=True, doc="Full canonical name")
    short_name = Column(String(50), nullable=True, unique=True, index=True, doc="Abbreviated name e.g. PM-KISAN")
    description = Column(Text, nullable=True, doc="Official scheme description")
    category = Column(
        String(50), nullable=True, index=True,
        doc="agriculture / housing / health / employment / financial / insurance / energy / social / other"
    )
    ministry = Column(String(200), nullable=True, doc="Responsible ministry")
    aliases = Column(Text, nullable=True, doc="Comma-separated unambiguous aliases (strong matches)")
    weak_aliases = Column(Text, nullable=True, doc="Comma-separated generic phrases, used only without a strong match")
    official_url = Column(String(2048), nullable=True)
    active = Column(Boolean, nullable=False, default=True)
    display_order = Column(Integer, nullable=True, default=0)

    # ── Timestamps ────────────────────────────────────────────────────────
    created_at = Column(UTCDateTime, nullable=False, default=utcnow)
    updated_at = Column(UTCDateTime, nullable=False, default=utcnow, onupdate=utcnow)

    # ── Relationships ─────────────────────────────────────────────────────
    documents = relationship("Document", back_populates="scheme", lazy="select")

    def __repr__(self):
        return f"<Scheme(id={self.id}, short_name={self.short_name})>"

    @property
    def alias_list(self) -> list[str]:
        """Returns aliases as a list."""
        if not self.aliases:
            return []
        return [a.strip().lower() for a in self.aliases.split(",") if a.strip()]
