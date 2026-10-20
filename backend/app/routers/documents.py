"""
Documents API — explorer listing, record detail with provenance and explanation,
similar records, filtered export, and manual review of classifications.
"""

import csv
import io
import json
import math
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import asc, desc
from sqlalchemy.orm import Session

from backend.app.config import get_settings
from backend.app.database import get_db
from backend.app.models.audit import AuditLog
from backend.app.models.cluster import Cluster, DocumentCluster
from backend.app.models.coltypes import utcnow
from backend.app.models.document import Document
from backend.app.models.embedding import DocumentEmbedding
from backend.app.nlp import embeddings
from backend.app.routers.deps import filters
from backend.app.security import require_admin
from backend.app.services.analytics import SORTABLE, Filters, apply_filters
from backend.app.services.vector_index import VectorIndex

router = APIRouter(prefix="/api/documents", tags=["Documents"])

LIST_FIELDS = ("id", "original_text", "scheme_name", "schemes", "scheme_match_strength", "intent", "intent_confidence",
               "awareness_gap", "gap_confidence", "gap_type", "gap_type_confidence", "label_source", "needs_review",
               "language", "text_role", "origin", "state", "district", "source_id", "source_name", "source_type",
               "source_url", "source_published_at", "collected_at", "processed_at", "processing_status",
               "is_duplicate", "is_synthetic", "split", "dataset_version_id", "campaign_id")
DETAIL_FIELDS = LIST_FIELDS + (
    "normalized_text", "content_hash", "language_method", "language_supported", "scheme_context",
    "predicted_intent", "predicted_intent_confidence", "predicted_gap", "predicted_gap_confidence",
    "predicted_gap_type", "predicted_gap_type_confidence", "explanation", "reviewed_at", "reviewed_by", "review_note",
    "source_document_id", "extraction_method", "crawl_page_id", "scrape_run_id", "original_csv_id",
    "source_updated_at", "first_seen_at", "created_at", "updated_at", "pii_redacted", "duplicate_of_id",
    "near_duplicate_of_id", "near_duplicate_similarity", "confidence", "notes", "processing_error",
    "intent_model_version", "gap_model_version", "embedding_model_version", "scheme_detection_version",
)
EXPORT_FIELDS = ("id", "origin", "original_text", "scheme_name", "intent", "intent_confidence", "awareness_gap",
                 "gap_confidence", "gap_type", "label_source", "language", "text_role", "state", "district",
                 "source_name", "source_url", "source_published_at", "collected_at", "processed_at",
                 "is_synthetic", "split", "intent_model_version", "gap_model_version")


def _row(d: Document, fields) -> dict:
    return {f: getattr(d, f) for f in fields}


@router.get("")
def list_documents(
    f: Filters = Depends(filters),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
    sort_by: str = Query("id"),
    sort_order: str = Query("desc", pattern="^(asc|desc)$"),
    db: Session = Depends(get_db),
):
    if sort_by not in SORTABLE:
        raise HTTPException(400, f"sort_by must be one of: {', '.join(sorted(SORTABLE))}")
    q = apply_filters(db.query(Document), f)
    total = q.count()
    col = getattr(Document, sort_by)
    order = asc(col) if sort_order == "asc" else desc(col)
    items = q.order_by(order, desc(Document.id)).offset((page - 1) * page_size).limit(page_size).all()
    return {"items": [_row(d, LIST_FIELDS) for d in items], "total": total, "page": page, "page_size": page_size,
            "total_pages": math.ceil(total / page_size) if total else 0}


@router.get("/export")
def export_documents(f: Filters = Depends(filters), fmt: str = Query("csv", pattern="^(csv|json)$"),
                     limit: int = Query(50000, ge=1, le=100000), db: Session = Depends(get_db)):
    """Exports exactly the records matched by the given filters (same semantics as the explorer)."""
    q = apply_filters(db.query(Document), f).order_by(Document.id).limit(limit)
    stamp = utcnow().strftime("%Y%m%dT%H%M%SZ")
    filt = {k: v for k, v in f.model_dump().items() if v not in (None, False)}
    if fmt == "json":
        body = json.dumps({"exported_at": utcnow().isoformat(), "filters": filt,
                           "records": [_row(d, EXPORT_FIELDS) for d in q]}, default=str, ensure_ascii=False)
        return StreamingResponse(iter([body]), media_type="application/json",
                                 headers={"Content-Disposition": f'attachment; filename="records-{f.scope}-{stamp}.json"'})

    def gen():
        buf = io.StringIO()
        w = csv.writer(buf)
        buf.write("# filters: " + json.dumps(filt, default=str) + "\n")
        w.writerow(EXPORT_FIELDS)
        for d in q.yield_per(500):
            w.writerow([getattr(d, c) if getattr(d, c) is not None else "" for c in EXPORT_FIELDS])
            if buf.tell() > 65536:
                yield buf.getvalue()
                buf.seek(0)
                buf.truncate()
        yield buf.getvalue()

    return StreamingResponse(gen(), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": f'attachment; filename="records-{f.scope}-{stamp}.csv"'})


@router.get("/{document_id}")
def get_document(document_id: int, db: Session = Depends(get_db)):
    d = db.get(Document, document_id)
    if d is None:
        raise HTTPException(404, "Document not found")
    out = _row(d, DETAIL_FIELDS)
    if d.source is not None:
        out["source"] = {"id": d.source.id, "name": d.source.name, "url": d.source.url,
                         "type": d.source.source_type, "policy_status": d.source.policy_status}
    if d.dataset_version is not None:
        out["dataset"] = {"id": d.dataset_version.id, "version": d.dataset_version.version,
                          "name": d.dataset_version.name}
    membership = (db.query(DocumentCluster, Cluster).join(Cluster, Cluster.id == DocumentCluster.cluster_id)
                  .filter(DocumentCluster.document_id == d.id, Cluster.is_active == True).first())  # noqa: E712
    out["cluster"] = ({"id": membership[1].id, "name": membership[1].name, "size": membership[1].size,
                       "similarity": membership[0].similarity_score} if membership else None)
    return out


@router.get("/{document_id}/similar")
def similar_documents(document_id: int, k: int = Query(8, ge=1, le=50),
                      scope: Optional[str] = Query(None, pattern="^(dataset|live|all)$"),
                      db: Session = Depends(get_db)):
    d = db.get(Document, document_id)
    if d is None:
        raise HTTPException(404, "Document not found")
    emb = db.get(DocumentEmbedding, document_id)
    if emb is None or emb.model != embeddings.model_name():
        return {"items": [], "note": "This record has no embedding yet (not processed)."}
    origin = None if scope == "all" else (scope or d.origin)
    hits = VectorIndex.for_origin(db, origin).search(embeddings.from_bytes(emb.vector), k=k, exclude={d.id},
                                                     min_similarity=get_settings().SIMILARITY_SEARCH_MIN)
    return {"items": _hydrate(db, hits)}


def _hydrate(db: Session, hits: list[tuple[int, float]]) -> list[dict]:
    if not hits:
        return []
    docs = {x.id: x for x in db.query(Document).filter(Document.id.in_([h[0] for h in hits])).all()}
    return [{**_row(docs[i], LIST_FIELDS), "similarity": round(s, 4)} for i, s in hits if i in docs]


class ReviewRequest(BaseModel):
    awareness_gap: Optional[str] = Field(None, pattern="^(yes|no|unclear|not_applicable)$")
    intent: Optional[str] = Field(None, max_length=50)
    gap_type: Optional[str] = Field(None, max_length=50)
    note: Optional[str] = Field(None, max_length=2000)


@router.patch("/{document_id}/review")
def review_document(document_id: int, body: ReviewRequest, db: Session = Depends(get_db),
                    who: str = Depends(require_admin)):
    """Record a reviewer's labels. Model predictions stay in predicted_* for comparison."""
    d = db.get(Document, document_id)
    if d is None:
        raise HTTPException(404, "Document not found")
    before = {"awareness_gap": d.awareness_gap, "intent": d.intent, "gap_type": d.gap_type}
    for field in ("awareness_gap", "intent", "gap_type"):
        v = getattr(body, field)
        if v is not None:
            setattr(d, field, v.strip().lower())
    if d.awareness_gap != "yes" and body.gap_type is None:
        d.gap_type = "none" if d.awareness_gap == "no" else None
    d.label_source, d.needs_review = "review", False
    d.reviewed_at, d.reviewed_by, d.review_note = utcnow(), who, body.note
    db.add(AuditLog(action="document_reviewed", entity_type="document", entity_id=str(d.id), user=who,
                    description="Manual review", details=json.dumps({"before": before, "after": {
                        "awareness_gap": d.awareness_gap, "intent": d.intent, "gap_type": d.gap_type}})))
    db.commit()
    return _row(d, DETAIL_FIELDS)


search_router = APIRouter(prefix="/api/search", tags=["Search"])


class SemanticQuery(BaseModel):
    query: str = Field(..., min_length=3, max_length=1000)
    scope: str = Field("all", pattern="^(dataset|live|all)$")
    k: int = Field(10, ge=1, le=50)


@search_router.post("/semantic")
def semantic_search(body: SemanticQuery, db: Session = Depends(get_db)):
    vec = embeddings.encode([body.query])[0]
    origin = None if body.scope == "all" else body.scope
    hits = VectorIndex.for_origin(db, origin).search(vec, k=body.k, min_similarity=get_settings().SIMILARITY_SEARCH_MIN)
    return {"query": body.query, "scope": body.scope, "embedding_model": embeddings.model_name(),
            "min_similarity": get_settings().SIMILARITY_SEARCH_MIN, "items": _hydrate(db, hits)}
