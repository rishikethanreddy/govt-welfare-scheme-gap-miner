"""Shared request dependencies."""

from datetime import datetime
from typing import Optional

from fastapi import Query

from backend.app.services.analytics import Filters


def filters(
    scope: str = Query("dataset", pattern="^(dataset|live|all)$", description="Workspace"),
    scheme: Optional[str] = Query(None, description="Scheme code; '__unknown__' for Other/Unknown"),
    state: Optional[str] = Query(None, description="State; '__unknown__' for records without a stated location"),
    district: Optional[str] = None,
    intent: Optional[str] = None,
    awareness_gap: Optional[str] = Query(None, pattern="^(yes|no|unclear|not_applicable)$"),
    gap_type: Optional[str] = None,
    language: Optional[str] = None,
    source_id: Optional[int] = None,
    text_role: Optional[str] = None,
    label_source: Optional[str] = Query(None, pattern="^(manual|review|model)$"),
    needs_review: Optional[bool] = None,
    processing_status: Optional[str] = None,
    dataset_version_id: Optional[int] = None,
    campaign_id: Optional[int] = None,
    split: Optional[str] = None,
    min_confidence: Optional[float] = Query(None, ge=0, le=1),
    date_field: str = Query("published", pattern="^(published|collected)$"),
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    search: Optional[str] = Query(None, max_length=200),
    include_duplicates: bool = False,
    include_synthetic: bool = False,
) -> Filters:
    return Filters(**{k: v for k, v in locals().items()})
