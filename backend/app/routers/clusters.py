"""Clusters API — semantic clusters of the latest clustering run per workspace."""

import json
import math

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.app.database import get_db
from backend.app.models.cluster import Cluster, DocumentCluster
from backend.app.models.document import Document
from backend.app.security import require_admin
from backend.app.services import jobs
from backend.app.services.clustering import LOW_COHESION, last_summary

router = APIRouter(prefix="/api/clusters", tags=["Clusters"])


def _cluster(c: Cluster) -> dict:
    return {"id": c.id, "label": c.cluster_label, "name": c.name, "keywords": c.keywords or [], "size": c.size,
            "cohesion": c.cohesion, "persistence": c.persistence, "low_cohesion": (c.cohesion or 0) < LOW_COHESION,
            "representative_texts": json.loads(c.representative_texts or "[]"),
            "dominant_scheme": c.dominant_scheme, "dominant_intent": c.dominant_intent,
            "dominant_gap_type": c.dominant_gap_type, "dominant_state": c.dominant_state,
            "gap_signals": c.gap_signals, "run_id": c.run_id, "algorithm": c.algorithm,
            "model_version": c.model_version, "embedding_model": c.embedding_model, "created_at": c.created_at,
            "description": c.description}


@router.get("")
def list_clusters(scope: str = Query("dataset", pattern="^(dataset|live)$"),
                  sort: str = Query("size", pattern="^(size|gap_signals|cohesion)$"),
                  db: Session = Depends(get_db)):
    q = db.query(Cluster).filter(Cluster.scope == scope, Cluster.is_active == True)  # noqa: E712
    order = {"size": Cluster.size.desc(), "gap_signals": Cluster.gap_signals.desc(), "cohesion": Cluster.cohesion.desc()}
    return {"scope": scope, "run": last_summary(db, scope), "items": [_cluster(c) for c in q.order_by(order[sort]).all()]}


@router.get("/{cluster_id}")
def get_cluster(cluster_id: int, page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100),
                db: Session = Depends(get_db)):
    c = db.get(Cluster, cluster_id)
    if c is None:
        raise HTTPException(404, "Cluster not found")
    q = (db.query(Document, DocumentCluster).join(DocumentCluster, DocumentCluster.document_id == Document.id)
         .filter(DocumentCluster.cluster_id == c.id).order_by(DocumentCluster.similarity_score.desc()))
    total = q.count()
    rows = q.offset((page - 1) * page_size).limit(page_size).all()
    members = [{"id": d.id, "original_text": d.original_text, "scheme_name": d.scheme_name, "intent": d.intent,
                "awareness_gap": d.awareness_gap, "gap_type": d.gap_type, "source_name": d.source_name,
                "source_url": d.source_url, "source_published_at": d.source_published_at,
                "collected_at": d.collected_at, "state": d.state, "language": d.language,
                "similarity": m.similarity_score, "membership_probability": m.membership_probability,
                "is_representative": bool(m.is_representative)} for d, m in rows]
    return {**_cluster(c), "scope": c.scope, "members": members, "total_members": total, "page": page,
            "total_pages": math.ceil(total / page_size) if total else 0}


@router.post("/run")
def run_clustering(scope: str = Query(..., pattern="^(dataset|live)$"), db: Session = Depends(get_db),
                   _: str = Depends(require_admin)):
    job = jobs.create_job(db, "clustering", {"cluster_scope": scope})
    jobs.start_in_background(job.id)
    return {"job_id": job.id, "status": "pending"}
