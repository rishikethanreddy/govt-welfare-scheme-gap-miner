"""
Dataset import: CSV/JSON parsing → column mapping → shared ingest pipeline →
background NLP job.

Re-import protection: every file's SHA-256 is stored on its DatasetVersion; the
same file is refused unless force=True. Rows whose text already exists in the
dataset workspace are stored but flagged as duplicates (and excluded from
analytics), so each import remains fully traceable row by row.
"""

import csv
import hashlib
import io
import json
import re
import uuid
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from backend.app.config import PROJECT_ROOT, get_settings
from backend.app.models.audit import AuditLog
from backend.app.models.processing import DatasetVersion, ProcessingJob
from backend.app.services.pipeline import IncomingRecord, ingest_records

COLUMN_MAP = {
    "text": ["text", "query", "question", "querytext", "content", "message", "body", "original_text"],
    "scheme": ["scheme", "scheme_name", "welfare_scheme", "program"],
    "intent": ["intent", "intent_label"],
    "awareness_gap": ["awareness_gap", "gap", "has_gap"],
    "gap_type": ["gap_type", "gap_category", "awareness_gap_type"],
    "state": ["state", "state_name", "statename"],
    "district": ["district", "district_name", "districtname"],
    "source": ["source", "source_name", "data_source"],
    "source_type": ["source_type"],
    "source_url": ["source_url", "url", "link"],
    "published_at": ["published_at", "date", "created_on", "createdon", "timestamp"],
    "text_role": ["text_role", "role"],
    "language": ["language", "lang"],
    "is_synthetic": ["is_synthetic", "synthetic"],
    "confidence": ["confidence", "confidence_level"],
    "notes": ["notes", "remarks"],
    "split": ["split", "data_split"],
    "id": ["id", "record_id", "row_id"],
}
TRUE_VALUES = {"yes", "true", "1", "y"}


class ImportError_(ValueError):
    """Raised for invalid uploads; message is safe to show to users."""


class DuplicateImport(Exception):
    def __init__(self, existing: DatasetVersion):
        super().__init__(f"This exact file was already imported as {existing.version} (id {existing.id}).")
        self.existing = existing


def auto_map_columns(columns: list[str]) -> dict:
    lower = {re.sub(r"[\s\-]+", "_", c.strip().lower()): c for c in columns}
    mapping = {}
    for canonical, aliases in COLUMN_MAP.items():
        mapping[canonical] = next((lower[a] for a in aliases if a in lower), None)
    return mapping


def _decode(content: bytes) -> str:
    for enc in ("utf-8-sig", "utf-16", "cp1252"):
        try:
            text = content.decode(enc)
            if enc == "utf-16" and "\x00" in text:
                continue
            return text
        except UnicodeDecodeError:
            continue
    raise ImportError_("File is not valid UTF-8, UTF-16 or Windows-1252 text.")


def parse_rows(content: bytes, filename: str) -> tuple[list[dict], list[str]]:
    settings = get_settings()
    ext = Path(filename).suffix.lower()
    text = _decode(content)
    if ext == ".json":
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            raise ImportError_(f"Invalid JSON: {e.msg} at line {e.lineno}.")
        if isinstance(data, dict):
            data = data.get("records") or data.get("data") or data.get("items")
        if not isinstance(data, list) or not all(isinstance(r, dict) for r in data):
            raise ImportError_("JSON must be an array of objects, or an object with a 'records' array.")
        rows = data
        columns = list(dict.fromkeys(k for r in rows[:200] for k in r))
    elif ext == ".csv":
        try:
            dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|")
        except csv.Error:
            dialect = csv.excel
        reader = csv.DictReader(io.StringIO(text), dialect=dialect)
        if not reader.fieldnames:
            raise ImportError_("CSV has no header row.")
        try:
            rows = list(reader)
        except csv.Error as e:
            raise ImportError_(f"Malformed CSV: {e}")
        columns = [c for c in reader.fieldnames if c is not None]
    else:
        raise ImportError_(f"Unsupported file type '{ext}'. Upload .csv or .json.")
    if len(rows) > settings.MAX_UPLOAD_ROWS:
        raise ImportError_(f"File has {len(rows)} rows; the limit is {settings.MAX_UPLOAD_ROWS}.")
    if not rows:
        raise ImportError_("File contains no data rows.")
    return rows, columns


def preview(content: bytes, filename: str) -> dict:
    rows, columns = parse_rows(content, filename)
    mapping = auto_map_columns(columns)
    return {"columns": columns, "row_count": len(rows), "mapping": mapping,
            "sample": [{k: (str(v)[:200] if v is not None else None) for k, v in r.items()} for r in rows[:5]],
            "missing_text_column": mapping.get("text") is None}


def _next_version(db: Session) -> str:
    n = db.query(DatasetVersion).count()
    while True:
        n += 1
        v = f"v{n}"
        if not db.query(DatasetVersion.id).filter(DatasetVersion.version == v).first():
            return v


def _safe_store(content: bytes, filename: str) -> str:
    settings = get_settings()
    upload_dir = Path(settings.UPLOAD_DIR)
    upload_dir = upload_dir if upload_dir.is_absolute() else PROJECT_ROOT / upload_dir
    upload_dir.mkdir(parents=True, exist_ok=True)
    ext = Path(filename).suffix.lower()
    if ext not in (".csv", ".json"):
        ext = ".bin"
    # Never use the client-supplied name as a path component.
    path = upload_dir / f"{uuid.uuid4().hex}{ext}"
    path.write_bytes(content)
    return path.relative_to(PROJECT_ROOT).as_posix() if path.is_relative_to(PROJECT_ROOT) else str(path)


def import_dataset(db: Session, content: bytes, filename: str, mapping: Optional[dict] = None,
                   name: Optional[str] = None, description: Optional[str] = None,
                   force: bool = False, default_role: str = "query") -> tuple[DatasetVersion, ProcessingJob, dict]:
    sha = hashlib.sha256(content).hexdigest()
    existing = db.query(DatasetVersion).filter(DatasetVersion.file_sha256 == sha).first()
    if existing and not force:
        raise DuplicateImport(existing)
    rows, columns = parse_rows(content, filename)
    mapping = {**auto_map_columns(columns), **(mapping or {})}
    unknown = [v for v in mapping.values() if v and v not in columns]
    if unknown:
        raise ImportError_(f"Mapped columns not found in file: {', '.join(unknown)}")
    if not mapping.get("text"):
        raise ImportError_("No text column found. Map one of the columns to 'text'.")

    stored_path = _safe_store(content, filename)
    safe_name = re.sub(r"[^\w.\- ]", "_", Path(filename).name)[:200]
    dv = DatasetVersion(version=_next_version(db), name=name or safe_name, description=description,
                        source_file=safe_name, file_sha256=sha, source_type="upload", record_count=len(rows),
                        processing_status="importing", column_mapping=json.dumps(mapping),
                        changes=f"Stored copy: {stored_path}")
    db.add(dv)
    db.flush()

    from backend.app.collection.dates import parse_date

    def get(row, key):
        col = mapping.get(key)
        v = row.get(col) if col else None
        if v is None:
            return None
        v = str(v).strip()
        return v or None

    records = []
    for i, row in enumerate(rows, start=1):
        pub = parse_date(get(row, "published_at"), "dataset column") if get(row, "published_at") else None
        records.append(IncomingRecord(
            text=get(row, "text") or "", origin="dataset", role=(get(row, "text_role") or default_role).lower(),
            source_name=get(row, "source") or safe_name, source_type=get(row, "source_type") or "dataset",
            source_url=get(row, "source_url"), published_at=pub.value if pub else None,
            state=get(row, "state"), district=get(row, "district"),
            dataset_version_id=dv.id, original_csv_id=get(row, "id") or str(i),
            scheme=get(row, "scheme"), intent=get(row, "intent"), awareness_gap=get(row, "awareness_gap"),
            gap_type=get(row, "gap_type"), split=get(row, "split"), confidence=get(row, "confidence"),
            notes=get(row, "notes"), is_synthetic=(get(row, "is_synthetic") or "").lower() in TRUE_VALUES,
            row_number=i,
        ))
    result = ingest_records(db, records, persist_duplicates=True, commit=False)
    dv.valid_records = len(result.stored) - len(result.duplicates)
    dv.duplicate_records = len(result.duplicates)
    dv.rejected_records = len(result.rejected)
    dv.rejections = json.dumps([{"row": r, "reason": why} for r, why in result.rejected[:200]])
    dv.processing_status = "imported"
    job = ProcessingJob(job_type="nlp_process", status="pending", dataset_version_id=dv.id,
                        total_items=len(result.stored),
                        params=json.dumps({"dataset_version_id": dv.id, "cluster_scope": "dataset"}))
    db.add(job)
    db.add(AuditLog(action="dataset_import", entity_type="dataset", entity_id=str(dv.id), user="admin",
                    description=f"Imported {safe_name} as {dv.version}: {len(rows)} rows, "
                                f"{dv.valid_records} unique, {dv.duplicate_records} duplicates, "
                                f"{dv.rejected_records} rejected"))
    db.commit()
    return dv, job, {"rows": len(rows), "mapping": mapping, **result.summary()}
