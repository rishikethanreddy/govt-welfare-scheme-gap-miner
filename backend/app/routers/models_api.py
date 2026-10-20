"""Models API — registered model versions and their held-out evaluation results."""

import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.app.config import PROJECT_ROOT
from backend.app.database import get_db
from backend.app.models.model_version import ModelVersion
from backend.app.nlp.service import get_nlp_service

router = APIRouter(prefix="/api/models", tags=["Models"])
EVAL_DIR = PROJECT_ROOT / "docs" / "evaluation"


@router.get("")
def list_models(db: Session = Depends(get_db)):
    rows = db.query(ModelVersion).order_by(ModelVersion.model_name, ModelVersion.created_at.desc()).all()
    return [{"id": m.id, "task": m.model_name, "version": m.version, "algorithm": m.model_type,
             "is_active": m.is_active, "status": m.status, "training_samples": m.training_samples,
             "training_dataset_version": m.training_dataset_version, "training_date": m.training_date,
             "test_samples": m.validation_samples, "accuracy": m.accuracy, "macro_precision": m.precision_score,
             "macro_recall": m.recall, "macro_f1": m.f1_score, "model_path": m.model_path,
             "notes": json.loads(m.evaluation_notes) if m.evaluation_notes else None} for m in rows]


@router.get("/status")
def status():
    return get_nlp_service().status()


@router.get("/evaluation/{task}")
def evaluation(task: str):
    if task not in ("intent", "awareness_gap", "gap_type"):
        raise HTTPException(404, "Unknown task")
    f = EVAL_DIR / f"{task}.json"
    if not f.exists():
        raise HTTPException(404, "No evaluation report. Run: python -m backend.app.nlp.training")
    return json.loads(f.read_text(encoding="utf-8"))
