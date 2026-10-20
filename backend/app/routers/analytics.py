"""Analytics API — every figure is computed from stored documents (see services/analytics.py)."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.app.database import get_db
from backend.app.routers.deps import filters
from backend.app.services.analytics import DEFINITIONS, AnalyticsService, Filters

router = APIRouter(prefix="/api/analytics", tags=["Analytics"])

DIMENSIONS = {"scheme": "scheme_name", "intent": "intent", "gap_type": "gap_type", "awareness_gap": "awareness_gap",
              "language": "language", "text_role": "text_role", "source": "source_name", "state": "state",
              "label_source": "label_source", "split": "split"}


@router.get("/definitions")
def definitions():
    return DEFINITIONS


@router.get("/overview")
def overview(f: Filters = Depends(filters), db: Session = Depends(get_db)):
    return AnalyticsService(db).overview(f)


@router.get("/distribution/{dimension}")
def distribution(dimension: str, f: Filters = Depends(filters), db: Session = Depends(get_db)):
    if dimension not in DIMENSIONS:
        raise HTTPException(400, f"Unknown dimension. Use one of: {', '.join(DIMENSIONS)}")
    return AnalyticsService(db).distribution(f, DIMENSIONS[dimension])


@router.get("/breakdown/{dimension}")
def breakdown(dimension: str, f: Filters = Depends(filters), db: Session = Depends(get_db)):
    """Gap yes/no/unclear counts and gap rate per value of a dimension."""
    if dimension not in DIMENSIONS:
        raise HTTPException(400, f"Unknown dimension. Use one of: {', '.join(DIMENSIONS)}")
    return AnalyticsService(db).gap_breakdown(f, DIMENSIONS[dimension])


@router.get("/schemes")
def schemes(f: Filters = Depends(filters), db: Session = Depends(get_db)):
    return AnalyticsService(db).scheme_table(f)


@router.get("/timeline")
def timeline(f: Filters = Depends(filters), db: Session = Depends(get_db)):
    return AnalyticsService(db).timeline(f)


@router.get("/geography")
def geography(level: str = Query("state", pattern="^(state|district)$"), f: Filters = Depends(filters),
              db: Session = Depends(get_db)):
    return AnalyticsService(db).geography(f, level)


@router.get("/filters")
def filter_options(f: Filters = Depends(filters), db: Session = Depends(get_db)):
    return AnalyticsService(db).filter_options(f)


@router.get("/data-quality")
def data_quality(scope: str = Query("dataset", pattern="^(dataset|live|all)$"), db: Session = Depends(get_db)):
    return AnalyticsService(db).data_quality(scope)
