"""
GeographicEntity model — India state and district reference data.

Provides a normalized geographic hierarchy:
  India → State → District → Sub-district → Village

Used for geographic aggregation and map rendering.
"""

from sqlalchemy import Column, Integer, String, Float, ForeignKey, Index
from sqlalchemy.orm import relationship
from backend.app.database import Base
from backend.app.models.coltypes import UTCDateTime, utcnow


class GeographicEntity(Base):
    __tablename__ = "geographic_entities"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), nullable=False, index=True)
    name_local = Column(String(200), nullable=True, doc="Name in local script")
    entity_type = Column(
        String(30), nullable=False, index=True,
        doc="country / state / union_territory / district / sub_district / city"
    )
    code = Column(String(20), nullable=True, unique=True, index=True, doc="Official code (e.g., state code, LGD code)")
    parent_id = Column(Integer, ForeignKey("geographic_entities.id"), nullable=True, index=True)

    # ── Geo Coordinates (centroid for map display) ────────────────────────
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)

    # ── Census / Reference ────────────────────────────────────────────────
    population = Column(Integer, nullable=True)
    iso_code = Column(String(10), nullable=True, doc="ISO 3166-2 code for states")

    # ── Timestamps ────────────────────────────────────────────────────────
    created_at = Column(UTCDateTime, nullable=False, default=utcnow)

    # ── Relationships ─────────────────────────────────────────────────────
    parent = relationship("GeographicEntity", remote_side=[id], backref="children", lazy="select")

    __table_args__ = (
        Index("ix_geo_type_parent", "entity_type", "parent_id"),
        Index("ix_geo_name_type", "name", "entity_type"),
    )

    def __repr__(self):
        return f"<GeographicEntity(id={self.id}, name={self.name}, type={self.entity_type})>"
