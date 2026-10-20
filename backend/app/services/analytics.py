"""
Analytics over stored documents. Every number is computed from the database.

Conventions (also returned to the client in `definitions`):
  * Records are scoped to one workspace: dataset or live (or both with scope=all).
  * Demo/fixture records are always excluded. Duplicates (exact and near) are
    excluded unless include_duplicates=true. Synthetic records are excluded unless
    include_synthetic=true.
  * Gap rate = gap "yes" / (gap "yes" + gap "no") among public-voice records.
    "unclear" (model abstained / unsupported language) and "not_applicable"
    (informational text) are reported separately, never folded into the rate.
  * These are signals in the analysed text, not estimates of population awareness.
"""

from collections import Counter, defaultdict
from datetime import datetime
from typing import Optional

from pydantic import BaseModel
from sqlalchemy import case, func
from sqlalchemy.orm import Session

from backend.app.models.document import Document
from backend.app.models.source import Source
from backend.app.nlp.service import PUBLIC_VOICE_ROLES

DEFINITIONS = {
    "total_records": "Unique records in scope after filters (duplicates, demo and — by default — synthetic records excluded).",
    "public_voice_records": "Records whose text is a public query, question, complaint or comment; the population for gap detection.",
    "gap_rate": "Records labelled 'yes' divided by records labelled 'yes' or 'no'. Unclear and not-applicable records are excluded from both numerator and denominator.",
    "unclear": "The model abstained (probability inside the uncertainty band) or the language is not supported; these await manual review.",
    "not_applicable": "Informational text (news, FAQ entries, articles) for which awareness-gap detection is not meaningful.",
    "location_coverage": "Share of records whose state is stated explicitly by the source. Locations are never inferred.",
    "scope": "dataset = imported files; live = records collected from registered public sources.",
}

SORTABLE = {"id", "created_at", "collected_at", "source_published_at", "processed_at", "scheme_name", "intent",
            "awareness_gap", "gap_type", "state", "gap_confidence", "intent_confidence", "language"}


class Filters(BaseModel):
    scope: str = "dataset"
    scheme: Optional[str] = None
    state: Optional[str] = None
    district: Optional[str] = None
    intent: Optional[str] = None
    awareness_gap: Optional[str] = None
    gap_type: Optional[str] = None
    language: Optional[str] = None
    source_id: Optional[int] = None
    text_role: Optional[str] = None
    label_source: Optional[str] = None
    needs_review: Optional[bool] = None
    processing_status: Optional[str] = None
    dataset_version_id: Optional[int] = None
    campaign_id: Optional[int] = None
    split: Optional[str] = None
    min_confidence: Optional[float] = None
    date_field: str = "published"   # published | collected
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None
    search: Optional[str] = None
    include_duplicates: bool = False
    include_synthetic: bool = False


def _date_col(f: Filters):
    return Document.source_published_at if f.date_field == "published" else Document.collected_at


def apply_filters(q, f: Filters, skip: tuple = ()):
    q = q.filter(Document.is_demo == False)  # noqa: E712
    if f.scope in ("dataset", "live", "manual"):
        q = q.filter(Document.origin == f.scope)
    if not f.include_duplicates:
        q = q.filter(Document.is_duplicate == False)  # noqa: E712
    if not f.include_synthetic:
        q = q.filter(Document.is_synthetic == False)  # noqa: E712
    if f.scheme and "scheme" not in skip:
        q = q.filter(Document.scheme_name.is_(None) if f.scheme == "__unknown__" else Document.scheme_name == f.scheme)
    if f.state and "state" not in skip:
        q = q.filter(Document.state.is_(None) if f.state == "__unknown__" else Document.state == f.state)
    if f.district:
        q = q.filter(Document.district == f.district)
    if f.intent and "intent" not in skip:
        q = q.filter(Document.intent == f.intent)
    if f.awareness_gap and "awareness_gap" not in skip:
        q = q.filter(Document.awareness_gap == f.awareness_gap)
    if f.gap_type and "gap_type" not in skip:
        q = q.filter(Document.gap_type == f.gap_type)
    if f.language:
        q = q.filter(Document.language == f.language)
    if f.source_id:
        q = q.filter(Document.source_id == f.source_id)
    if f.text_role:
        q = q.filter(Document.text_role == f.text_role)
    if f.label_source:
        q = q.filter(Document.label_source == f.label_source)
    if f.needs_review is not None:
        q = q.filter(Document.needs_review == f.needs_review)
    if f.processing_status:
        q = q.filter(Document.processing_status == f.processing_status)
    if f.dataset_version_id:
        q = q.filter(Document.dataset_version_id == f.dataset_version_id)
    if f.campaign_id:
        q = q.filter(Document.campaign_id == f.campaign_id)
    if f.split:
        q = q.filter(Document.split == f.split)
    if f.min_confidence is not None:
        q = q.filter(Document.gap_confidence >= f.min_confidence)
    col = _date_col(f)
    if f.date_from:
        q = q.filter(col >= f.date_from)
    if f.date_to:
        q = q.filter(col <= f.date_to)
    if f.search:
        q = q.filter(Document.original_text.ilike(f"%{f.search.strip()}%"))
    return q


def _share(n: int, d: int) -> Optional[float]:
    return round(n / d, 4) if d else None


class AnalyticsService:
    def __init__(self, db: Session):
        self.db = db

    def _q(self, f: Filters, *cols, skip=()):
        return apply_filters(self.db.query(*cols), f, skip)

    # ── Overview ─────────────────────────────────────────────────────────

    def overview(self, f: Filters) -> dict:
        D = Document
        pv = D.text_role.in_(PUBLIC_VOICE_ROLES)
        row = self._q(
            f,
            func.count(D.id),
            func.sum(case((pv, 1), else_=0)),
            func.sum(case((D.awareness_gap == "yes", 1), else_=0)),
            func.sum(case((D.awareness_gap == "no", 1), else_=0)),
            func.sum(case((D.awareness_gap == "unclear", 1), else_=0)),
            func.sum(case((D.awareness_gap == "not_applicable", 1), else_=0)),
            func.sum(case((D.scheme_name.is_(None), 1), else_=0)),
            func.sum(case((D.state.isnot(None), 1), else_=0)),
            func.sum(case((D.needs_review == True, 1), else_=0)),  # noqa: E712
            func.sum(case((D.processing_status == "completed", 1), else_=0)),
            func.sum(case((D.processing_status == "pending", 1), else_=0)),
            func.sum(case((D.processing_status == "failed", 1), else_=0)),
            func.sum(case((D.source_published_at.is_(None), 1), else_=0)),
            func.count(func.distinct(D.scheme_name)),
            func.count(func.distinct(D.state)),
            func.count(func.distinct(D.district)),
            func.count(func.distinct(D.source_id)),
            func.min(D.source_published_at), func.max(D.source_published_at),
            func.min(D.collected_at), func.max(D.collected_at),
        ).one()
        counts, (pub_min, pub_max, col_min, col_max) = [v or 0 for v in row[:17]], row[17:]
        (total, public, yes, no, unclear, na, unknown_scheme, located, review, done, pending, failed, no_pub,
         schemes, states, districts, sources) = counts
        excluded = self.excluded_counts(f)
        labels = dict(self._q(f, D.label_source, func.count(D.id)).group_by(D.label_source).all())
        return {
            "scope": f.scope,
            "total_records": total,
            "public_voice_records": public,
            "awareness_gap": {"yes": yes, "no": no, "unclear": unclear, "not_applicable": na,
                              "unlabelled": total - yes - no - unclear - na,
                              "gap_rate": _share(yes, yes + no), "decided": yes + no},
            "schemes_detected": schemes, "unknown_scheme_records": unknown_scheme,
            "states_covered": states, "districts_covered": districts,
            "location_coverage": _share(located, total), "records_with_location": located,
            "sources": sources,
            "needs_review": review,
            "processing": {"completed": done, "pending": pending, "failed": failed},
            "label_sources": {str(k or "none"): v for k, v in labels.items()},
            "publication_date_missing": no_pub,
            "published_range": [pub_min, pub_max],
            "collected_range": [col_min, col_max],
            "excluded": excluded,
            "definitions": DEFINITIONS,
        }

    def excluded_counts(self, f: Filters) -> dict:
        D = Document
        q = self.db.query(func.sum(case((D.is_duplicate == True, 1), else_=0)),  # noqa: E712
                          func.sum(case((D.near_duplicate_of_id.isnot(None), 1), else_=0)),
                          func.sum(case((D.is_demo == True, 1), else_=0)),  # noqa: E712
                          func.sum(case((D.is_synthetic == True, 1), else_=0)))  # noqa: E712
        if f.scope in ("dataset", "live"):
            q = q.filter(D.origin == f.scope)
        dup, near, demo, synth = [v or 0 for v in q.one()]
        return {"duplicates": dup, "near_duplicates": near, "exact_duplicates": dup - near, "demo": demo,
                "synthetic": synth, "synthetic_included": f.include_synthetic,
                "duplicates_included": f.include_duplicates}

    # ── Distributions ────────────────────────────────────────────────────

    def distribution(self, f: Filters, field: str, limit: int = 50) -> dict:
        col = getattr(Document, field)
        rows = self._q(f, col, func.count(Document.id), skip=(field,)).group_by(col) \
            .order_by(func.count(Document.id).desc()).all()
        total = sum(r[1] for r in rows)
        items = [{"value": r[0], "count": r[1], "share": _share(r[1], total)} for r in rows[:limit]]
        return {"field": field, "total": total, "items": items}

    def gap_breakdown(self, f: Filters, field: str, limit: int = 50) -> list[dict]:
        D = Document
        col = getattr(D, field)
        rows = self._q(
            f, col, func.count(D.id),
            func.sum(case((D.awareness_gap == "yes", 1), else_=0)),
            func.sum(case((D.awareness_gap == "no", 1), else_=0)),
            func.sum(case((D.awareness_gap == "unclear", 1), else_=0)),
            func.sum(case((D.text_role.in_(PUBLIC_VOICE_ROLES), 1), else_=0)),
            skip=(field,),
        ).group_by(col).order_by(func.count(D.id).desc()).limit(limit).all()
        out = []
        for value, total, yes, no, unclear, public in rows:
            yes, no, unclear, public = yes or 0, no or 0, unclear or 0, public or 0
            out.append({"value": value, "total": total, "public_voice": public, "yes": yes, "no": no,
                        "unclear": unclear, "gap_rate": _share(yes, yes + no)})
        return out

    def scheme_table(self, f: Filters) -> list[dict]:
        rows = self.gap_breakdown(f, "scheme_name", limit=100)
        D = Document
        top = defaultdict(Counter)
        for scheme, gt, n in self._q(f, D.scheme_name, D.gap_type, func.count(D.id), skip=("scheme",)) \
                .filter(D.awareness_gap == "yes", D.gap_type.isnot(None), D.gap_type.notin_(("none", "unknown"))) \
                .group_by(D.scheme_name, D.gap_type).all():
            top[scheme][gt] += n
        for r in rows:
            c = top.get(r["value"])
            r["top_gap_type"] = c.most_common(1)[0][0] if c else None
        return rows

    def timeline(self, f: Filters) -> dict:
        col = _date_col(f)
        rows = self._q(f, col, Document.awareness_gap).all()
        buckets = defaultdict(lambda: {"total": 0, "yes": 0})
        missing = 0
        for dt, gap in rows:
            if dt is None:
                missing += 1
                continue
            key = dt.strftime("%Y-%m")
            buckets[key]["total"] += 1
            buckets[key]["yes"] += int(gap == "yes")
        return {"date_field": f.date_field, "missing_date": missing,
                "items": [{"month": k, **v} for k, v in sorted(buckets.items())]}

    def geography(self, f: Filters, level: str = "state") -> dict:
        field = "district" if level == "district" else "state"
        rows = self.gap_breakdown(f, field, limit=1000)
        if level == "district":
            states = dict(self._q(f, Document.district, Document.state).filter(Document.district.isnot(None))
                          .group_by(Document.district, Document.state).all())
            for r in rows:
                r["state"] = states.get(r["value"])
        unknown = next((r for r in rows if r["value"] is None), None)
        known = [r for r in rows if r["value"] is not None]
        total = sum(r["total"] for r in rows)
        return {"level": level, "regions": known,
                "unknown_location": unknown["total"] if unknown else 0,
                "total_records": total, "location_coverage": _share(total - (unknown["total"] if unknown else 0), total),
                "note": "Only locations stated explicitly by the source are used; nothing is inferred."}

    def filter_options(self, f: Filters) -> dict:
        def distinct(col):
            q = apply_filters(self.db.query(col).distinct(), Filters(scope=f.scope, include_synthetic=True,
                                                                      include_duplicates=True))
            return sorted(v for (v,) in q.all() if v)
        sources = apply_filters(self.db.query(Source.id, Source.name).join(Document, Document.source_id == Source.id),
                                Filters(scope=f.scope, include_synthetic=True)).distinct().all()
        return {
            "schemes": distinct(Document.scheme_name), "states": distinct(Document.state),
            "districts": distinct(Document.district), "intents": distinct(Document.intent),
            "gap_types": distinct(Document.gap_type), "languages": distinct(Document.language),
            "text_roles": distinct(Document.text_role), "label_sources": distinct(Document.label_source),
            "splits": distinct(Document.split),
            "sources": [{"id": i, "name": n} for i, n in sorted(sources, key=lambda s: s[1] or "")],
        }

    def data_quality(self, scope: str) -> dict:
        f_all = Filters(scope=scope, include_synthetic=True)
        D = Document
        base = self.db.query(func.count(D.id)).filter(D.is_demo == False)  # noqa: E712
        if scope in ("dataset", "live"):
            base = base.filter(D.origin == scope)
        raw_total = base.scalar() or 0
        lang = self.distribution(f_all, "language")
        roles = self.distribution(f_all, "text_role")
        q = apply_filters(self.db.query(
            func.count(D.id),
            func.sum(case((D.pii_redacted == True, 1), else_=0)),  # noqa: E712
            func.sum(case((D.language_supported == False, 1), else_=0)),  # noqa: E712
            func.sum(case((D.source_published_at.is_(None), 1), else_=0)),
            func.sum(case((D.scheme_name.is_(None), 1), else_=0)),
            func.sum(case((D.scheme_match_strength == "weak", 1), else_=0)),
            func.sum(case((D.scheme_match_strength == "context", 1), else_=0)),
            func.sum(case((D.state.is_(None), 1), else_=0)),
            func.sum(case((D.processing_status == "failed", 1), else_=0)),
            func.sum(case((D.needs_review == True, 1), else_=0)),  # noqa: E712
        ), f_all).one()
        total, pii, unsupported, no_date, no_scheme, weak, ctx, no_loc, failed, review = [v or 0 for v in q]
        return {
            "scope": scope, "stored_records": raw_total, "unique_records": total,
            "excluded": self.excluded_counts(f_all),
            "pii_redacted": pii, "unsupported_language": unsupported,
            "publication_date_missing": no_date, "unknown_scheme": no_scheme,
            "weak_scheme_match": weak, "scheme_from_page_context": ctx,
            "unknown_location": no_loc, "processing_failed": failed, "needs_review": review,
            "languages": lang, "text_roles": roles,
            "shares": {k: _share(v, total) for k, v in {
                "pii_redacted": pii, "unsupported_language": unsupported, "publication_date_missing": no_date,
                "unknown_scheme": no_scheme, "unknown_location": no_loc, "needs_review": review}.items()},
        }
