"""Datasets API — preview, upload (with column mapping), history, rejected rows, reprocessing."""

import json
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from backend.app.config import get_settings
from backend.app.database import get_db
from backend.app.models.processing import DatasetVersion, ProcessingJob
from backend.app.security import require_admin
from backend.app.services import jobs
from backend.app.services.dataset import DuplicateImport, ImportError_, import_dataset, preview

router = APIRouter(prefix="/api/datasets", tags=["Datasets"])


async def _read_limited(file: UploadFile) -> bytes:
    limit = get_settings().MAX_UPLOAD_SIZE_MB * 1024 * 1024
    buf = bytearray()
    while chunk := await file.read(1024 * 1024):
        buf.extend(chunk)
        if len(buf) > limit:
            raise HTTPException(413, f"File exceeds the {get_settings().MAX_UPLOAD_SIZE_MB} MB limit.")
    if not buf:
        raise HTTPException(400, "The uploaded file is empty.")
    return bytes(buf)


def _check_name(file: UploadFile) -> str:
    name = file.filename or ""
    ext = name[name.rfind("."):].lower() if "." in name else ""
    if ext not in get_settings().allowed_extension_list:
        raise HTTPException(400, f"Unsupported file type '{ext or 'none'}'. Allowed: {get_settings().ALLOWED_EXTENSIONS}")
    return name


def _version(dv: DatasetVersion, job: Optional[ProcessingJob] = None) -> dict:
    return {"id": dv.id, "version": dv.version, "name": dv.name, "description": dv.description,
            "source_file": dv.source_file, "file_sha256": dv.file_sha256, "record_count": dv.record_count,
            "valid_records": dv.valid_records, "duplicate_records": dv.duplicate_records,
            "rejected_records": dv.rejected_records, "processed_records": dv.processed_records,
            "processing_status": dv.processing_status,
            "column_mapping": json.loads(dv.column_mapping) if dv.column_mapping else None,
            "created_at": dv.created_at, "updated_at": dv.updated_at,
            "job": _job(job) if job else None}


def _job(j: ProcessingJob) -> dict:
    return {"id": j.id, "type": j.job_type, "status": j.status, "progress": j.progress,
            "total_items": j.total_items, "processed_items": j.processed_items, "failed_items": j.failed_items,
            "error": j.error_message, "result": json.loads(j.result) if j.result else None,
            "created_at": j.created_at, "started_at": j.started_at, "finished_at": j.finished_at,
            "dataset_version_id": j.dataset_version_id}


@router.post("/preview")
async def preview_upload(file: UploadFile = File(...), _: str = Depends(require_admin)):
    """Parse a file without storing anything: columns, suggested mapping, first rows."""
    name = _check_name(file)
    content = await _read_limited(file)
    try:
        return preview(content, name)
    except ImportError_ as e:
        raise HTTPException(422, str(e))


@router.post("/upload")
async def upload_dataset(file: UploadFile = File(...), mapping: Optional[str] = Form(None),
                         name: Optional[str] = Form(None), description: Optional[str] = Form(None),
                         force: bool = Form(False), default_role: str = Form("query"),
                         db: Session = Depends(get_db), _: str = Depends(require_admin)):
    fname = _check_name(file)
    content = await _read_limited(file)
    try:
        mapping_obj = json.loads(mapping) if mapping else None
        if mapping_obj is not None and not isinstance(mapping_obj, dict):
            raise ValueError
    except ValueError:
        raise HTTPException(422, "mapping must be a JSON object of {canonical_field: column_name}")
    if default_role not in ("query", "question", "complaint", "discussion", "faq", "news", "article"):
        raise HTTPException(422, "default_role is not a recognised text role")
    try:
        dv, job, summary = import_dataset(db, content, fname, mapping_obj, name, description, force, default_role)
    except DuplicateImport as e:
        raise HTTPException(409, {"message": str(e), "existing_version_id": e.existing.id})
    except ImportError_ as e:
        raise HTTPException(422, str(e))
    jobs.start_in_background(job.id)
    return {"dataset": _version(dv, job), "summary": summary}


@router.get("")
def list_datasets(db: Session = Depends(get_db)):
    out = []
    for dv in db.query(DatasetVersion).order_by(DatasetVersion.id.desc()).all():
        job = (db.query(ProcessingJob).filter(ProcessingJob.dataset_version_id == dv.id)
               .order_by(ProcessingJob.id.desc()).first())
        out.append(_version(dv, job))
    return out


@router.get("/{dataset_id}")
def get_dataset(dataset_id: int, db: Session = Depends(get_db)):
    dv = db.get(DatasetVersion, dataset_id)
    if dv is None:
        raise HTTPException(404, "Dataset not found")
    jl = db.query(ProcessingJob).filter(ProcessingJob.dataset_version_id == dv.id).order_by(ProcessingJob.id.desc()).all()
    return {**_version(dv, jl[0] if jl else None), "jobs": [_job(j) for j in jl],
            "rejections": json.loads(dv.rejections) if dv.rejections else []}


@router.post("/{dataset_id}/reprocess")
def reprocess_dataset(dataset_id: int, db: Session = Depends(get_db), _: str = Depends(require_admin)):
    dv = db.get(DatasetVersion, dataset_id)
    if dv is None:
        raise HTTPException(404, "Dataset not found")
    job = jobs.create_job(db, "reprocess", {"dataset_version_id": dv.id, "cluster_scope": "dataset"}, dv.id)
    jobs.start_in_background(job.id)
    return _job(job)


jobs_router = APIRouter(prefix="/api/jobs", tags=["Jobs"])


@jobs_router.get("")
def list_jobs(limit: int = 50, db: Session = Depends(get_db)):
    return [_job(j) for j in db.query(ProcessingJob).order_by(ProcessingJob.id.desc()).limit(min(limit, 200)).all()]


@jobs_router.get("/{job_id}")
def get_job(job_id: int, db: Session = Depends(get_db)):
    j = db.get(ProcessingJob, job_id)
    if j is None:
        raise HTTPException(404, "Job not found")
    return _job(j)


@jobs_router.post("/reprocess")
def reprocess(origin: str = "live", only_failed: bool = False, db: Session = Depends(get_db),
              _: str = Depends(require_admin)):
    """Re-run NLP for a workspace (idempotent; manual and reviewed labels are preserved)."""
    if origin not in ("dataset", "live"):
        raise HTTPException(422, "origin must be dataset or live")
    params = {"origin": origin, "cluster_scope": origin}
    if only_failed:
        params["only_status"] = ["failed", "pending"]
    job = jobs.create_job(db, "reprocess", params)
    jobs.start_in_background(job.id)
    return _job(job)
