"""
Shared record pipeline used by dataset imports and live collection.

  ingest_records():   validate → normalize → redact PII → language → exact dedup → persist
  process_documents(): embed → near-duplicate check → NLP inference → persist labels

Both workspaces call the same two functions; the only difference is `origin`
(dataset / live), which scopes deduplication and analytics.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Iterable, Optional

from sqlalchemy.orm import Session

from backend.app.config import get_settings
from backend.app.models.coltypes import utcnow
from backend.app.models.document import Document
from backend.app.models.embedding import DocumentEmbedding
from backend.app.nlp import embeddings
from backend.app.nlp.geo import normalize_state
from backend.app.nlp.schemes import default_registry
from backend.app.nlp.service import SCHEME_DETECTION_VERSION, get_nlp_service
from backend.app.nlp.text import content_hash, normalize_text, redact_pii
from backend.app.services import vector_index

logger = logging.getLogger(__name__)

MIN_TEXT_CHARS = 15
MAX_TEXT_CHARS = 10000
VALID_GAP_LABELS = {"yes", "no", "unclear", "not_applicable"}


@dataclass
class IncomingRecord:
    text: str
    origin: str                               # dataset / live / manual
    role: str = "query"
    source_id: Optional[int] = None
    source_name: Optional[str] = None
    source_type: Optional[str] = None
    source_url: Optional[str] = None
    source_document_id: Optional[str] = None
    extraction_method: Optional[str] = None
    published_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    state: Optional[str] = None
    district: Optional[str] = None
    campaign_id: Optional[int] = None
    crawl_page_id: Optional[int] = None
    scrape_run_id: Optional[int] = None
    dataset_version_id: Optional[int] = None
    original_csv_id: Optional[str] = None
    scheme_context: Optional[str] = None      # scheme of the containing page (comments)
    # Manual labels supplied with a dataset (kept as ground truth).
    scheme: Optional[str] = None
    intent: Optional[str] = None
    awareness_gap: Optional[str] = None
    gap_type: Optional[str] = None
    split: Optional[str] = None
    confidence: Optional[str] = None
    notes: Optional[str] = None
    language_hint: Optional[str] = None
    is_synthetic: bool = False
    is_demo: bool = False
    row_number: Optional[int] = None


@dataclass
class IngestResult:
    stored: list = field(default_factory=list)       # Document ids
    duplicates: list = field(default_factory=list)   # (row_number/text preview, duplicate_of_id)
    rejected: list = field(default_factory=list)     # (row_number/text preview, reason)

    def summary(self) -> dict:
        return {"stored": len(self.stored), "duplicates": len(self.duplicates), "rejected": len(self.rejected)}


def _district(name: Optional[str]) -> Optional[str]:
    """District as stated by the source; all-caps values (e.g. KCC's "PATAN") are title-cased."""
    v = " ".join((name or "").split())
    if v.lower() in ("", "unknown", "na", "n/a", "none", "-"):
        return None
    return v.title() if v.isupper() else v


def validation_error(text: str) -> Optional[str]:
    if not text:
        return "empty text"
    if len(text) < MIN_TEXT_CHARS:
        return f"text shorter than {MIN_TEXT_CHARS} characters"
    if len(text) > MAX_TEXT_CHARS:
        return f"text longer than {MAX_TEXT_CHARS} characters"
    letters = sum(c.isalpha() for c in text)
    if letters < 0.4 * len(text.replace(" ", "")):
        return "text is mostly non-alphabetic (likely boilerplate or garbled)"
    bad = sum(1 for c in text if not c.isprintable())
    if bad / len(text) > 0.05:
        return "too many non-printable characters"
    return None


def _norm_label(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    v = str(value).strip().lower().replace(" ", "_")
    return v or None


def ingest_records(db: Session, records: Iterable[IncomingRecord], persist_duplicates: bool = False,
                   commit: bool = True) -> IngestResult:
    """Persist new records as `pending` documents. Exact duplicates (same normalized
    text within the same workspace) are skipped, or stored flagged when
    persist_duplicates=True (dataset imports keep every row for traceability)."""
    result = IngestResult()
    registry = default_registry()
    now = utcnow()
    prepared = []
    for rec in records:
        ref = rec.row_number if rec.row_number is not None else (rec.text or "")[:80]
        text = normalize_text(rec.text)
        reason = validation_error(text)
        if reason:
            result.rejected.append((ref, reason))
            continue
        red = redact_pii(text)
        prepared.append((rec, ref, red, content_hash(red.text)))

    hashes_by_origin: dict[str, set] = {}
    for rec, _, _, h in prepared:
        hashes_by_origin.setdefault(rec.origin, set()).add(h)
    existing: dict[tuple, int] = {}
    for origin, hashes in hashes_by_origin.items():
        hl = list(hashes)
        for i in range(0, len(hl), 500):
            rows = (db.query(Document.content_hash, Document.id)
                    .filter(Document.origin == origin, Document.content_hash.in_(hl[i:i + 500]),
                            Document.is_duplicate == False)  # noqa: E712
                    .all())
            for h, did in rows:
                existing.setdefault((origin, h), did)

    # Structured sources (call logs, API rows) identify records by their own id: two farmers
    # asking the same summarised question are two events, not a duplicate.
    by_source_id: dict[tuple, int] = {}
    structured = [r for r, *_ in prepared if r.source_document_id and r.source_id and _is_structured(r)]
    for sid in {r.source_id for r in structured}:
        ids = [r.source_document_id for r in structured if r.source_id == sid]
        for i in range(0, len(ids), 500):
            for did, sdid in (db.query(Document.id, Document.source_document_id)
                              .filter(Document.source_id == sid, Document.source_document_id.in_(ids[i:i + 500])).all()):
                by_source_id[(sid, sdid)] = did

    batch_seen: dict[tuple, Document] = {}
    for rec, ref, red, h in prepared:
        if _is_structured(rec) and rec.source_document_id and rec.source_id:
            key = ("id", rec.source_id, rec.source_document_id)
            dup_of = by_source_id.get((rec.source_id, rec.source_document_id))
        else:
            key = (rec.origin, h)
            dup_of = existing.get(key)
        dup_doc = batch_seen.get(key)
        is_dup = dup_of is not None or dup_doc is not None
        if is_dup and not persist_duplicates:
            result.duplicates.append((ref, dup_of))
            continue
        manual = any(v for v in (rec.intent, rec.awareness_gap, rec.gap_type))
        gap = _norm_label(rec.awareness_gap)
        doc = Document(
            original_text=red.text,
            normalized_text=red.text,
            content_hash=h,
            text_role=rec.role or "query",
            origin=rec.origin,
            scheme_name=registry.canonicalize(rec.scheme) if rec.scheme else None,
            scheme_match_strength="manual" if rec.scheme else None,
            scheme_context=rec.scheme_context,
            intent=_norm_label(rec.intent),
            awareness_gap=gap if gap in VALID_GAP_LABELS else None,
            gap_type=_norm_label(rec.gap_type),
            label_source="manual" if manual else None,
            state=normalize_state(rec.state),
            district=_district(rec.district),
            source_id=rec.source_id, source_name=rec.source_name, source_type=rec.source_type,
            source_url=rec.source_url, source_document_id=rec.source_document_id,
            extraction_method=rec.extraction_method,
            campaign_id=rec.campaign_id, crawl_page_id=rec.crawl_page_id, scrape_run_id=rec.scrape_run_id,
            dataset_version_id=rec.dataset_version_id, original_csv_id=rec.original_csv_id,
            split=_norm_label(rec.split), confidence=rec.confidence, notes=rec.notes,
            is_synthetic=rec.is_synthetic, is_demo=rec.is_demo,
            is_duplicate=is_dup, duplicate_of_id=dup_of if dup_of else None,
            duplicate_group_id=h[:16] if is_dup else None,
            pii_detected=red.redacted, pii_redacted=red.redacted,
            source_published_at=rec.published_at, source_updated_at=rec.updated_at,
            first_seen_at=now, collected_at=now,
            processing_status="pending",
        )
        db.add(doc)
        if is_dup:
            result.duplicates.append((ref, dup_of))
        else:
            batch_seen[key] = doc
        result.stored.append(doc)
    db.flush()
    result.stored = [d.id for d in result.stored]
    # Link in-batch duplicates (persisted) to the first occurrence.
    if persist_duplicates:
        for doc_id in result.stored:
            d = db.get(Document, doc_id)
            if d.is_duplicate and d.duplicate_of_id is None:
                first = batch_seen.get((d.origin, d.content_hash))
                if first is not None and first.id != d.id:
                    d.duplicate_of_id = first.id
    if commit:
        db.commit()
    return result


STRUCTURED_METHODS = ("json_api", "csv")


def _is_structured(rec) -> bool:
    return getattr(rec, "extraction_method", None) in STRUCTURED_METHODS


def _apply_analysis(doc: Document, r: dict, now) -> None:
    lang = r["language"]
    doc.language = lang["code"]
    doc.language_method = lang["method"]
    doc.language_supported = lang["supported"]

    sch = r["scheme"]
    if doc.scheme_match_strength == "manual" and doc.scheme_name:
        others = [s for s in sch["schemes"] if s != doc.scheme_name]
        doc.schemes = [doc.scheme_name] + others
    elif sch["primary"] is None and doc.scheme_context:
        # A comment that names no scheme inherits the scheme of the page it was posted on.
        doc.scheme_name = doc.scheme_context
        doc.schemes = [doc.scheme_context]
        doc.scheme_match_strength = "context"
    else:
        doc.scheme_name = sch["primary"]
        doc.schemes = sch["schemes"] or None
        doc.scheme_match_strength = sch["strength"]

    intent, gap, gtype = r["intent"], r["awareness_gap"], r["gap_type"]
    doc.predicted_intent = intent["label"]
    doc.predicted_intent_confidence = intent["confidence"]
    doc.predicted_gap = gap["label"]
    doc.predicted_gap_confidence = gap["confidence"]
    doc.predicted_gap_type = gtype["label"] if gtype else None
    doc.predicted_gap_type_confidence = gtype["confidence"] if gtype else None

    if doc.label_source not in ("manual", "review"):
        doc.intent = intent["label"]
        doc.intent_confidence = intent["confidence"]
        doc.awareness_gap = gap["label"]
        doc.gap_confidence = gap["confidence"]
        doc.gap_type = gtype["label"] if gtype else None
        doc.gap_type_confidence = gtype["confidence"] if gtype else None
        doc.label_source = "model" if gap["label"] is not None or intent["label"] is not None else None
        doc.needs_review = bool(r["needs_review"])
    else:
        doc.needs_review = False

    doc.explanation = {
        "gap_status": gap["status"], "gap_reason": gap.get("reason"), "p_yes": gap.get("p_yes"),
        "intent_status": intent["status"], "intent_alternatives": intent.get("alternatives", []),
        "gap_type_status": gtype["status"] if gtype else None,
        "gap_type_alternatives": gtype.get("alternatives", []) if gtype else [],
        "scheme_matches": sch["matches"][:5],
        "evidence": r.get("evidence", []),
    }
    mv = r["model_versions"]
    doc.intent_model_version = mv["intent"]
    doc.gap_model_version = mv["awareness_gap"]
    doc.scheme_detection_version = SCHEME_DETECTION_VERSION
    doc.processed_at = now
    doc.processing_status = "completed"
    doc.processing_error = None


def process_documents(db: Session, doc_ids: list[int], batch_size: int = 64,
                      progress: Optional[Callable[[int, int, int], None]] = None,
                      on_document: Optional[Callable[[Document], None]] = None) -> dict:
    """Run embeddings + near-duplicate detection + NLP on the given documents.
    Idempotent: re-running recomputes predictions but never overwrites manual/review labels."""
    settings = get_settings()
    nlp = get_nlp_service()
    model = embeddings.model_name()
    done = failed = near_dups = 0
    indexes: dict[str, vector_index.VectorIndex] = {}
    total = len(doc_ids)
    for start in range(0, total, batch_size):
        ids = doc_ids[start:start + batch_size]
        docs = db.query(Document).filter(Document.id.in_(ids)).order_by(Document.id).all()
        if not docs:
            continue
        for d in docs:
            d.processing_status = "processing"
            d.processing_attempts = (d.processing_attempts or 0) + 1
        texts = [d.normalized_text or normalize_text(d.original_text) for d in docs]
        try:
            vecs = embeddings.encode(texts)
            results = nlp.analyze_batch(texts, [d.text_role for d in docs], with_evidence=True, vecs=vecs)
        except Exception as e:
            logger.exception("NLP batch failed")
            for d in docs:
                d.processing_status = "failed"
                d.processing_error = f"{type(e).__name__}: {e}"[:1000]
            failed += len(docs)
            db.commit()
            continue
        now = utcnow()
        batch_ids = {d.id for d in docs}
        for d, r, vec in zip(docs, results, vecs):
            try:
                emb = db.get(DocumentEmbedding, d.id) or DocumentEmbedding(document_id=d.id)
                emb.model, emb.dim, emb.vector, emb.content_hash = model, int(vec.shape[0]), embeddings.to_bytes(vec), d.content_hash
                db.add(emb)
                d.embedding_model = model
                d.embedding_model_version = model

                # Near-duplicate: very high cosine similarity to an earlier canonical record in the same workspace.
                if not d.is_duplicate and not d.is_demo and not (d.source_document_id and _is_structured(d)):
                    idx = indexes.get(d.origin)
                    if idx is None:
                        idx = indexes[d.origin] = vector_index.VectorIndex.for_origin(db, d.origin)
                        idx = indexes[d.origin] = vector_index.VectorIndex(idx.ids.copy(), idx.matrix.copy())
                    # The earliest record is canonical, so only earlier ids can be "originals".
                    hits = idx.search(vec, k=20, exclude={d.id} | {i for i in batch_ids if i >= d.id},
                                      min_similarity=settings.NEAR_DUPLICATE_THRESHOLD)
                    hits = [(i, s) for i, s in hits if i < d.id][:1]
                    if hits:
                        d.is_duplicate = True
                        d.near_duplicate_of_id, d.near_duplicate_similarity = hits[0][0], round(hits[0][1], 4)
                        d.duplicate_group_id = f"near:{hits[0][0]}"
                        near_dups += 1
                    else:
                        idx.add(d.id, vec)
                _apply_analysis(d, r, now)
                done += 1
                if on_document:
                    on_document(d)
            except Exception as e:
                logger.exception("Processing failed for document %s", d.id)
                d.processing_status = "failed"
                d.processing_error = f"{type(e).__name__}: {e}"[:1000]
                failed += 1
        db.commit()
        if progress:
            progress(min(start + batch_size, total), done, failed)
    vector_index.invalidate()
    return {"processed": done, "failed": failed, "near_duplicates": near_dups, "total": total}
