"""System API — health (database, migrations, models, worker), audit trail, auth check."""

import json
from datetime import timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from backend.app.config import get_settings
from backend.app.database import get_db
from backend.app.models.audit import AuditLog
from backend.app.models.coltypes import utcnow
from backend.app.models.document import Document
from backend.app.models.embedding import SystemState
from backend.app.models.processing import ProcessingJob
from backend.app.nlp import artifacts
from backend.app.security import require_admin

router = APIRouter(tags=["System"])


def migration_state(db: Session) -> dict:
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from backend.app.config import PROJECT_ROOT
    head = ScriptDirectory.from_config(Config(str(PROJECT_ROOT / "alembic.ini"))).get_current_head()
    try:
        current = db.execute(text("SELECT version_num FROM alembic_version")).scalar()
    except Exception:
        db.rollback()
        current = None
    return {"current": current, "head": head, "up_to_date": current == head}


@router.get("/api/health")
def health(db: Session = Depends(get_db)):
    s = get_settings()
    try:
        db.execute(text("SELECT 1"))
        database = "connected"
    except Exception:
        database = "unreachable"
    mig = migration_state(db) if database == "connected" else None
    active = artifacts.read_active()
    models_ok = all(artifacts.load(t)[0] is not None for t in artifacts.TASKS) if active else False
    hb = db.get(SystemState, "worker:heartbeat") if database == "connected" else None
    worker_alive = bool(hb and utcnow() - hb.updated_at < timedelta(seconds=45))
    healthy = database == "connected" and bool(mig and mig["up_to_date"]) and models_ok
    return {"status": "healthy" if healthy else "degraded", "environment": s.ENVIRONMENT, "version": s.APP_VERSION,
            "database": database, "database_type": "sqlite" if s.is_sqlite else "postgresql", "migrations": mig,
            "models_loaded": models_ok, "model_versions": active, "worker_alive": worker_alive,
            "admin_enabled": bool(s.ADMIN_API_KEY), "timestamp": utcnow()}


@router.get("/api/system/summary")
def summary(db: Session = Depends(get_db)):
    by_origin = dict(db.query(Document.origin, func.count(Document.id)).group_by(Document.origin).all())
    jobs = dict(db.query(ProcessingJob.status, func.count(ProcessingJob.id)).group_by(ProcessingJob.status).all())
    cutoff = utcnow() - timedelta(hours=24)
    failed_24h = db.query(func.count(ProcessingJob.id)).filter(ProcessingJob.status == "failed",
                                                               ProcessingJob.created_at >= cutoff).scalar()
    return {"documents_by_origin": by_origin, "jobs_by_status": jobs, "failed_jobs_24h": failed_24h}


@router.get("/api/system/audit-logs")
def audit_logs(limit: int = Query(50, ge=1, le=500), action: str = None, db: Session = Depends(get_db)):
    q = db.query(AuditLog).order_by(AuditLog.id.desc())
    if action:
        q = q.filter(AuditLog.action == action)
    return [{"id": a.id, "action": a.action, "entity_type": a.entity_type, "entity_id": a.entity_id,
             "description": a.description, "details": json.loads(a.details) if a.details and a.details.startswith("{") else a.details,
             "user": a.user, "severity": a.severity, "created_at": a.created_at} for a in q.limit(limit).all()]


@router.get("/api/auth/check")
def auth_check(_: str = Depends(require_admin)):
    return {"authenticated": True}
