"""Schemes API — the configurable scheme registry and per-scheme intelligence."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.app.database import get_db
from backend.app.models.document import Document
from backend.app.models.scheme import Scheme
from backend.app.nlp.schemes import DEFAULT_SCHEMES
from backend.app.routers.deps import filters
from backend.app.services.analytics import AnalyticsService, Filters, apply_filters

router = APIRouter(prefix="/api/schemes", tags=["Schemes"])


@router.get("")
def list_schemes(db: Session = Depends(get_db)):
    rows = {s.short_name: s for s in db.query(Scheme).all()}
    out = []
    for d in DEFAULT_SCHEMES:
        r = rows.get(d.code)
        out.append({"code": d.code, "name": d.name, "category": d.category, "ministry": d.ministry,
                    "official_url": d.official_url, "aliases": list(d.strong), "weak_aliases": list(d.weak),
                    "extra_aliases": r.alias_list if r else [], "active": r.active if r else True})
    return out


@router.get("/{code}")
def scheme_detail(code: str, f: Filters = Depends(filters), db: Session = Depends(get_db)):
    defn = next((d for d in DEFAULT_SCHEMES if d.code == code), None)
    if defn is None:
        raise HTTPException(404, "Unknown scheme code")
    f = f.model_copy(update={"scheme": code})
    svc = AnalyticsService(db)
    q = apply_filters(db.query(Document), f)
    D = Document
    examples = {}
    for label in ("yes", "unclear", "no"):
        examples[label] = [{"id": d.id, "text": d.original_text, "gap_type": d.gap_type, "intent": d.intent,
                            "source_name": d.source_name, "source_published_at": d.source_published_at}
                           for d in q.filter(D.awareness_gap == label).order_by(D.gap_confidence.desc()).limit(8)]
    misconceptions = [{"id": d.id, "text": d.original_text}
                      for d in q.filter(D.gap_type == "misconception").limit(8)]
    return {"scheme": {"code": defn.code, "name": defn.name, "category": defn.category, "ministry": defn.ministry,
                       "official_url": defn.official_url, "aliases": list(defn.strong)},
            "overview": svc.overview(f),
            "intents": svc.distribution(f, "intent"),
            "gap_types": svc.distribution(f.model_copy(update={"awareness_gap": "yes"}), "gap_type"),
            "states": svc.gap_breakdown(f, "state", limit=15),
            "co_mentioned": _co_mentions(db, f, code),
            "examples": examples, "misconceptions": misconceptions}


def _co_mentions(db: Session, f: Filters, code: str) -> list[dict]:
    from collections import Counter
    c = Counter()
    for (schemes,) in apply_filters(db.query(Document.schemes), f).filter(Document.schemes.isnot(None)).all():
        for s in schemes or []:
            if s != code:
                c[s] += 1
    return [{"scheme": s, "count": n} for s, n in c.most_common(8)]
