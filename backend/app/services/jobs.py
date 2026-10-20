"""
Background processing jobs (NLP processing, reprocessing, clustering).

Jobs are rows in processing_jobs. Both the API (in a background thread right
after an upload) and the worker loop may try to run a pending job; an atomic
claim (UPDATE … WHERE status='pending') guarantees only one of them does.
"""

import json
import logging
import threading
from typing import Optional

from sqlalchemy import update

from backend.app.database import SessionLocal
from backend.app.models.audit import AuditLog
from backend.app.models.coltypes import utcnow
from backend.app.models.document import Document
from backend.app.models.processing import DatasetVersion, ProcessingJob

logger = logging.getLogger(__name__)
_run_lock = threading.Lock()  # one CPU-heavy NLP job at a time per process


def claim(db, job_id: int) -> bool:
    res = db.execute(update(ProcessingJob).where(ProcessingJob.id == job_id, ProcessingJob.status == "pending")
                     .values(status="running", started_at=utcnow()))
    db.commit()
    return res.rowcount == 1


def _target_ids(db, params: dict) -> list[int]:
    q = db.query(Document.id)
    if params.get("dataset_version_id"):
        q = q.filter(Document.dataset_version_id == params["dataset_version_id"])
    if params.get("origin"):
        q = q.filter(Document.origin == params["origin"])
    if params.get("document_ids"):
        q = q.filter(Document.id.in_(params["document_ids"]))
    if params.get("only_status"):
        q = q.filter(Document.processing_status.in_(params["only_status"]))
    return [r[0] for r in q.order_by(Document.id).all()]


def run_job(job_id: int) -> Optional[dict]:
    from backend.app.services.clustering import run_clustering
    from backend.app.services.pipeline import process_documents

    db = SessionLocal()
    try:
        if not claim(db, job_id):
            return None
        job = db.get(ProcessingJob, job_id)
        params = json.loads(job.params or "{}")
        with _run_lock:
            try:
                result = {}
                if job.job_type in ("nlp_process", "reprocess"):
                    ids = _target_ids(db, params)
                    job.total_items = len(ids)
                    db.commit()

                    def progress(seen, ok, failed):
                        job.processed_items, job.failed_items = ok, failed
                        job.progress = round(seen / max(len(ids), 1), 4)
                        db.commit()

                    result = process_documents(db, ids, progress=progress)
                    if job.dataset_version_id:
                        dv = db.get(DatasetVersion, job.dataset_version_id)
                        dv.processed_records = result["processed"]
                        dv.processing_status = "processed" if not result["failed"] else "partial"
                if params.get("cluster_scope"):
                    result["clustering"] = run_clustering(db, params["cluster_scope"])
                job.status = "completed"
                job.progress = 1.0
                job.result = json.dumps(result, default=str)
            except Exception as e:
                logger.exception("Job %s failed", job_id)
                db.rollback()
                job = db.get(ProcessingJob, job_id)
                if job is None:  # the job row was removed while running
                    return None
                job.status = "failed"
                job.error_message = f"{type(e).__name__}: {e}"[:2000]
                if job.dataset_version_id:
                    dv = db.get(DatasetVersion, job.dataset_version_id)
                    if dv:
                        dv.processing_status = "failed"
            job.finished_at = utcnow()
            db.add(AuditLog(action=f"job_{job.status}", entity_type="job", entity_id=str(job.id), user="system",
                            description=f"{job.job_type} job {job.status}: {job.result or job.error_message}"[:2000],
                            severity="info" if job.status == "completed" else "error"))
            db.commit()
            return json.loads(job.result) if job.result else None
    finally:
        db.close()


def start_in_background(job_id: int) -> None:
    threading.Thread(target=run_job, args=(job_id,), name=f"job-{job_id}", daemon=True).start()


def create_job(db, job_type: str, params: dict, dataset_version_id: Optional[int] = None) -> ProcessingJob:
    job = ProcessingJob(job_type=job_type, status="pending", params=json.dumps(params),
                        dataset_version_id=dataset_version_id)
    db.add(job)
    db.commit()
    return job
