"""Sources API — registry, freshness/health, run history, and operator controls."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.app.collection.registry import sync_registry
from backend.app.collection.robots import RobotsPolicy
from backend.app.collection.safe_http import FetchError, SafeFetcher, UnsafeUrlError, UrlPolicy
from backend.app.config import get_settings
from backend.app.database import get_db
from backend.app.models.audit import AuditLog
from backend.app.models.coltypes import utcnow
from backend.app.models.document import Document
from backend.app.models.source import Source, SourceRun
from backend.app.security import require_admin

router = APIRouter(prefix="/api/sources", tags=["Sources"])

ADAPTERS = ("html", "rss", "sitemap", "json_api", "csv", "datagovin")


def _source(s: Source, docs: int = 0) -> dict:
    age_h = round((utcnow() - s.last_success_at).total_seconds() / 3600, 1) if s.last_success_at else None
    return {"id": s.id, "name": s.name, "url": s.url, "source_type": s.source_type, "category": s.category,
            "adapter": s.content_type, "config": s.config or {}, "policy_status": s.policy_status,
            "policy_note": s.policy_note, "active": s.active, "schedule": s.schedule, "max_pages": s.max_pages,
            "verification_status": s.verification_status, "last_run_at": s.last_run_at,
            "last_success_at": s.last_success_at, "hours_since_success": age_h, "last_error": s.last_error,
            "consecutive_failures": s.consecutive_failures, "health_score": s.health_score,
            "total_runs": s.total_runs, "records_collected": docs, "crawl_delay": s.crawl_delay}


@router.get("")
def list_sources(include_retired: bool = False, db: Session = Depends(get_db)):
    q = db.query(Source).filter(Source.source_type != "csv_upload")
    if not include_retired:
        q = q.filter(Source.policy_status != "retired")
    counts = dict(db.query(Document.source_id, func.count(Document.id))
                  .filter(Document.origin == "live", Document.is_duplicate == False, Document.is_demo == False)  # noqa: E712
                  .group_by(Document.source_id).all())
    return [_source(s, counts.get(s.id, 0)) for s in q.order_by(Source.active.desc(), Source.name).all()]


@router.get("/{source_id}")
def get_source(source_id: int, db: Session = Depends(get_db)):
    s = db.get(Source, source_id)
    if s is None:
        raise HTTPException(404, "Source not found")
    docs = db.query(func.count(Document.id)).filter(Document.source_id == s.id, Document.is_duplicate == False).scalar()  # noqa: E712
    return _source(s, docs or 0)


@router.get("/{source_id}/runs")
def source_runs(source_id: int, limit: int = 20, db: Session = Depends(get_db)):
    runs = db.query(SourceRun).filter(SourceRun.source_id == source_id).order_by(SourceRun.id.desc()).limit(min(limit, 100))
    return [{"id": r.id, "campaign_id": r.campaign_id, "status": r.status, "started_at": r.started_at,
             "finished_at": r.finished_at, "urls_discovered": r.urls_discovered, "urls_attempted": r.urls_attempted,
             "successful": r.successful, "failed": r.failed, "blocked": r.blocked,
             "records_extracted": r.records_extracted, "records_accepted": r.records_accepted,
             "duplicates": r.duplicates_found, "rejected": r.records_rejected, "error": r.error_message} for r in runs]


class SourceCreate(BaseModel):
    name: str = Field(..., min_length=3, max_length=200)
    url: str = Field(..., max_length=2048)
    adapter: str = Field("html")
    source_type: str = Field("other", max_length=50)
    category: Optional[str] = Field(None, max_length=50)
    max_pages: int = Field(20, ge=1, le=500)
    config: dict = Field(default_factory=dict)


class SourceUpdate(BaseModel):
    active: Optional[bool] = None
    schedule: Optional[str] = Field(None, pattern="^(manual|daily|weekly)$")
    max_pages: Optional[int] = Field(None, ge=1, le=500)
    config: Optional[dict] = None


def _check_robots(url: str) -> tuple[bool, str]:
    robots = RobotsPolicy(get_settings().SCRAPER_USER_AGENT)
    with SafeFetcher(robots=None, max_retries=0) as f:
        d = robots.check(url, f)
    return d.allowed, d.reason


@router.post("")
def create_source(body: SourceCreate, db: Session = Depends(get_db), who: str = Depends(require_admin)):
    if body.adapter not in ADAPTERS:
        raise HTTPException(422, f"adapter must be one of {ADAPTERS}")
    try:
        UrlPolicy().check(body.url)
    except UnsafeUrlError as e:
        raise HTTPException(422, f"URL rejected: {e}")
    except FetchError as e:
        raise HTTPException(422, f"URL could not be resolved: {e}")
    if db.query(Source.id).filter(Source.url == body.url).first():
        raise HTTPException(409, "A source with this URL is already registered")
    allowed, reason = _check_robots(body.url)
    s = Source(name=body.name, url=body.url, content_type=body.adapter, source_type=body.source_type,
               category=body.category, max_pages=body.max_pages, config=body.config,
               collection_method="crawler", robots_checked=True, robots_allowed=allowed,
               # New sources start inactive; the operator enables them after reviewing the site's terms.
               policy_status="manual_review" if allowed else "blocked", active=False,
               policy_note=f"Registered by operator. {reason}. Review the site's terms of use before enabling.")
    db.add(s)
    db.add(AuditLog(action="source_created", entity_type="source", entity_id=body.url[:50], user=who,
                    description=f"Registered source {body.name}"))
    db.commit()
    return _source(s)


@router.patch("/{source_id}")
def update_source(source_id: int, body: SourceUpdate, db: Session = Depends(get_db), who: str = Depends(require_admin)):
    s = db.get(Source, source_id)
    if s is None:
        raise HTTPException(404, "Source not found")
    if body.active is True and s.policy_status in ("blocked", "unsupported", "credentials_required", "retired"):
        raise HTTPException(409, f"Source cannot be enabled while its policy status is '{s.policy_status}'.")
    changes = body.model_dump(exclude_none=True)
    if body.active is True and s.policy_status in ("paused", "manual_review"):
        s.policy_status, s.consecutive_failures = "allowed", 0
    for k, v in changes.items():
        setattr(s, k, v)
    db.add(AuditLog(action="source_updated", entity_type="source", entity_id=str(s.id), user=who,
                    description=f"Updated {s.name}: {', '.join(changes)}"))
    db.commit()
    return _source(s)


@router.post("/sync")
def sync_sources(db: Session = Depends(get_db), _: str = Depends(require_admin)):
    return sync_registry(db)


@router.post("/{source_id}/check")
def check_source(source_id: int, db: Session = Depends(get_db), _: str = Depends(require_admin)):
    """One polite request to the source URL: reports robots decision, HTTP status and content type."""
    s = db.get(Source, source_id)
    if s is None:
        raise HTTPException(404, "Source not found")
    robots = RobotsPolicy(get_settings().SCRAPER_USER_AGENT)
    with SafeFetcher(robots=robots, max_retries=0) as f:
        try:
            res = f.fetch(s.url)
            out = {"ok": res.ok, "status": res.status, "content_type": res.content_type,
                   "bytes": len(res.content), "final_url": res.final_url, "redirects": res.redirects}
        except FetchError as e:
            out = {"ok": False, "error_kind": e.kind, "error": str(e), "status": e.status}
    s.robots_checked = True
    s.last_error = None if out["ok"] else out.get("error") or f"HTTP {out.get('status')}"
    db.commit()
    return out
