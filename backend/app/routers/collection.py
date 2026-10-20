"""
Collection API — campaigns (jobs), live progress via Server-Sent Events, worker
status and the scheduler (autopilot).

Campaigns are executed by the worker process (python -m backend.worker); the API
only queues, cancels and reports. Progress, events and the live record feed are
read from the database, so they reflect exactly what the worker persisted.
"""

import asyncio
import json
from datetime import timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.app.database import SessionLocal, get_db
from backend.app.models.audit import AuditLog
from backend.app.models.coltypes import utcnow
from backend.app.models.crawl import (ACTIVE_CAMPAIGN_STATUSES, TERMINAL_CAMPAIGN_STATUSES, CollectionCampaign,
                                      CollectionEvent, CrawlUrl)
from backend.app.models.document import Document
from backend.app.models.embedding import SystemState
from backend.app.models.source import Source, SourceRun
from backend.app.security import require_admin

router = APIRouter(prefix="/api/collection", tags=["Collection"])


def campaign_dict(c: CollectionCampaign) -> dict:
    end = c.finished_at or (utcnow() if c.started_at and c.status in ACTIVE_CAMPAIGN_STATUSES else None)
    return {
        "id": c.id, "name": c.name, "status": c.status, "stage": c.stage, "trigger": c.trigger,
        "source_ids": c.source_ids, "max_pages_per_source": c.max_pages_per_source, "max_depth": c.max_depth,
        "error_message": c.error_message,
        "metrics": {k: getattr(c, k) for k in (
            "urls_discovered", "urls_accepted", "urls_processed", "urls_failed", "urls_blocked", "urls_unchanged",
            "pages_downloaded", "pages_useful", "records_extracted", "records_duplicate", "records_rejected",
            "records_final", "records_processed")},
        "created_at": c.created_at, "crawl_started_at": c.started_at, "crawl_finished_at": c.finished_at,
        "heartbeat_at": c.heartbeat_at,
        "elapsed_seconds": round((end - c.started_at).total_seconds()) if c.started_at and end else None,
    }


def _event(e: CollectionEvent) -> dict:
    return {"id": e.id, "kind": e.kind, "level": e.level, "message": e.message, "url": e.url,
            "source_id": e.source_id, "document_id": e.document_id, "created_at": e.created_at}


class CampaignCreate(BaseModel):
    name: str = Field(..., min_length=3, max_length=200)
    source_ids: Optional[list[int]] = None
    max_pages_per_source: int = Field(20, ge=1, le=200)
    max_depth: int = Field(1, ge=0, le=3)


@router.post("/campaigns")
def create_campaign(body: CampaignCreate, db: Session = Depends(get_db), who: str = Depends(require_admin)):
    if body.source_ids:
        found = db.query(Source).filter(Source.id.in_(body.source_ids)).all()
        unusable = [s.name for s in found if not s.active or s.policy_status != "allowed"]
        if len(found) != len(set(body.source_ids)):
            raise HTTPException(422, "One or more source ids do not exist")
        if unusable:
            raise HTTPException(409, f"Sources not enabled for collection: {', '.join(unusable)}")
    c = CollectionCampaign(name=body.name, source_ids=body.source_ids, max_pages_per_source=body.max_pages_per_source,
                           max_depth=body.max_depth, status="queued", trigger="manual")
    db.add(c)
    db.add(AuditLog(action="campaign_queued", entity_type="campaign", user=who, description=f"Queued '{body.name}'"))
    db.commit()
    return campaign_dict(c)


@router.get("/campaigns")
def list_campaigns(include_archived: bool = False, limit: int = Query(50, ge=1, le=500), db: Session = Depends(get_db)):
    q = db.query(CollectionCampaign)
    if not include_archived:
        q = q.filter(CollectionCampaign.status != "archived")
    archived = db.query(func.count(CollectionCampaign.id)).filter(CollectionCampaign.status == "archived").scalar()
    return {"items": [campaign_dict(c) for c in q.order_by(CollectionCampaign.id.desc()).limit(limit).all()],
            "archived_count": archived}


@router.get("/campaigns/{campaign_id}")
def get_campaign(campaign_id: int, db: Session = Depends(get_db)):
    c = db.get(CollectionCampaign, campaign_id)
    if c is None:
        raise HTTPException(404, "Campaign not found")
    runs = db.query(SourceRun, Source.name).join(Source, Source.id == SourceRun.source_id) \
        .filter(SourceRun.campaign_id == c.id).order_by(SourceRun.id).all()
    url_status = dict(db.query(CrawlUrl.status, func.count(CrawlUrl.id)).filter(CrawlUrl.campaign_id == c.id)
                      .group_by(CrawlUrl.status).all())
    return {**campaign_dict(c), "url_status": url_status,
            "source_runs": [{"source_id": r.source_id, "source_name": n, "status": r.status, "started_at": r.started_at,
                             "finished_at": r.finished_at, "successful": r.successful, "failed": r.failed,
                             "blocked": r.blocked, "records_accepted": r.records_accepted,
                             "duplicates": r.duplicates_found, "rejected": r.records_rejected,
                             "error": r.error_message} for r, n in runs]}


@router.get("/campaigns/{campaign_id}/events")
def campaign_events(campaign_id: int, after_id: int = 0, limit: int = Query(200, ge=1, le=1000),
                    db: Session = Depends(get_db)):
    ev = db.query(CollectionEvent).filter(CollectionEvent.campaign_id == campaign_id, CollectionEvent.id > after_id) \
        .order_by(CollectionEvent.id).limit(limit).all()
    return [_event(e) for e in ev]


@router.get("/campaigns/{campaign_id}/urls")
def campaign_urls(campaign_id: int, status: Optional[str] = None, limit: int = Query(100, ge=1, le=500),
                  db: Session = Depends(get_db)):
    q = db.query(CrawlUrl).filter(CrawlUrl.campaign_id == campaign_id)
    if status:
        q = q.filter(CrawlUrl.status == status)
    return [{"id": u.id, "url": u.url, "status": u.status, "http_status": u.http_status, "depth": u.depth,
             "discovery_method": u.discovery_method, "records_extracted": u.records_extracted,
             "error": u.error_message, "last_attempt_at": u.last_attempt_at}
            for u in q.order_by(CrawlUrl.id.desc()).limit(limit).all()]


@router.post("/campaigns/{campaign_id}/cancel")
def cancel_campaign(campaign_id: int, db: Session = Depends(get_db), who: str = Depends(require_admin)):
    c = db.get(CollectionCampaign, campaign_id)
    if c is None:
        raise HTTPException(404, "Campaign not found")
    if c.status == "queued":
        c.status, c.finished_at = "cancelled", utcnow()
    elif c.status == "running":
        c.status = "cancel_requested"
    else:
        raise HTTPException(409, f"Campaign is already {c.status}")
    db.add(AuditLog(action="campaign_cancel", entity_type="campaign", entity_id=str(c.id), user=who,
                    description=f"Cancellation requested for '{c.name}'"))
    db.commit()
    return campaign_dict(c)


@router.post("/campaigns/{campaign_id}/retry-failed")
def retry_failed(campaign_id: int, db: Session = Depends(get_db), who: str = Depends(require_admin)):
    """Re-queue failed URLs of a finished campaign and run it again (resumes the same frontier)."""
    c = db.get(CollectionCampaign, campaign_id)
    if c is None:
        raise HTTPException(404, "Campaign not found")
    if c.status in ACTIVE_CAMPAIGN_STATUSES:
        raise HTTPException(409, "Campaign is still active")
    n = db.query(CrawlUrl).filter(CrawlUrl.campaign_id == c.id, CrawlUrl.status == "failed") \
        .update({"status": "queued", "error_message": None})
    if n == 0:
        raise HTTPException(409, "No failed URLs to retry")
    db.query(SourceRun).filter(SourceRun.campaign_id == c.id).update({"status": "queued"})
    c.status, c.finished_at = "queued", None
    c.urls_processed -= n
    c.urls_failed = max(0, c.urls_failed - n)
    db.add(AuditLog(action="campaign_retry", entity_type="campaign", entity_id=str(c.id), user=who,
                    description=f"Re-queued {n} failed URLs"))
    db.commit()
    return {**campaign_dict(c), "requeued_urls": n}


# ── Worker / scheduler status ─────────────────────────────────────────────

def _state(db: Session, key: str) -> Optional[str]:
    row = db.get(SystemState, key)
    return row.value if row else None


def worker_status_dict(db: Session) -> dict:
    hb = db.get(SystemState, "worker:heartbeat")
    alive = bool(hb and hb.updated_at and utcnow() - hb.updated_at < timedelta(seconds=45))
    active = db.query(CollectionCampaign).filter(CollectionCampaign.status.in_(ACTIVE_CAMPAIGN_STATUSES)) \
        .order_by(CollectionCampaign.id).all()
    return {"worker_alive": alive, "last_heartbeat": hb.updated_at if hb else None,
            "worker_info": json.loads(hb.value) if hb and hb.value else None,
            "autopilot_enabled": _state(db, "autopilot:enabled") == "true",
            "active_campaigns": [campaign_dict(c) for c in active]}


@router.get("/status")
def worker_status(db: Session = Depends(get_db)):
    return worker_status_dict(db)


@router.post("/autopilot")
def set_autopilot(enabled: bool, db: Session = Depends(get_db), who: str = Depends(require_admin)):
    row = db.get(SystemState, "autopilot:enabled") or SystemState(key="autopilot:enabled")
    row.value = "true" if enabled else "false"
    db.add(row)
    db.add(AuditLog(action="autopilot", entity_type="system", user=who,
                    description=f"Scheduled collection {'enabled' if enabled else 'disabled'}"))
    db.commit()
    return worker_status_dict(db)


@router.get("/feed")
def live_feed(after_id: int = 0, limit: int = Query(30, ge=1, le=200), db: Session = Depends(get_db)):
    """Most recently persisted and processed live records (newest first)."""
    q = db.query(Document).filter(Document.origin == "live", Document.is_demo == False,  # noqa: E712
                                  Document.processing_status == "completed", Document.id > after_id)
    return [{"id": d.id, "text": d.original_text, "scheme": d.scheme_name, "text_role": d.text_role,
             "intent": d.intent, "awareness_gap": d.awareness_gap, "gap_type": d.gap_type,
             "language": d.language, "source_name": d.source_name, "source_url": d.source_url,
             "source_published_at": d.source_published_at, "collected_at": d.collected_at,
             "processed_at": d.processed_at, "campaign_id": d.campaign_id, "is_duplicate": d.is_duplicate}
            for d in q.order_by(Document.id.desc()).limit(limit).all()]


# ── Server-Sent Events ────────────────────────────────────────────────────

def _snapshot(campaign_id: Optional[int], after_event: int, after_doc: int) -> dict:
    db = SessionLocal()
    try:
        out = {"status": worker_status_dict(db)}
        ev_q = db.query(CollectionEvent).filter(CollectionEvent.id > after_event)
        if campaign_id:
            c = db.get(CollectionCampaign, campaign_id)
            out["campaign"] = campaign_dict(c) if c else None
            ev_q = ev_q.filter(CollectionEvent.campaign_id == campaign_id)
        out["events"] = [_event(e) for e in ev_q.order_by(CollectionEvent.id).limit(100).all()]
        out["records"] = live_feed(after_id=after_doc, limit=20, db=db) if after_doc >= 0 else []
        return out
    finally:
        db.close()


def _sse(event: str, data) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


async def _stream(request: Request, campaign_id: Optional[int]):
    import time
    last_event = int(request.query_params.get("after_event", 0))
    last_doc = int(request.query_params.get("after_record", 0))
    # Connections are recycled after `timeout` seconds; EventSource reconnects automatically
    # and resumes from the last ids it saw (sent back as after_event / after_record).
    deadline = time.monotonic() + min(max(float(request.query_params.get("timeout", 600)), 1), 3600)
    idle = 0
    while not await request.is_disconnected() and time.monotonic() < deadline:
        snap = await run_in_threadpool(_snapshot, campaign_id, last_event, last_doc)
        yield _sse("status", snap["status"])
        if campaign_id:
            yield _sse("campaign", snap["campaign"])
        for e in snap["events"]:
            last_event = max(last_event, e["id"])
            yield _sse("log", e)
        for r in reversed(snap["records"]):
            last_doc = max(last_doc, r["id"])
            yield _sse("record", r)
        done = campaign_id and snap.get("campaign") and snap["campaign"]["status"] in TERMINAL_CAMPAIGN_STATUSES
        idle = idle + 1 if done and not snap["events"] else 0
        if done and idle >= 2:
            yield _sse("end", {"status": snap["campaign"]["status"]})
            return
        await asyncio.sleep(1.5)
    yield _sse("reconnect", {"after_event": last_event, "after_record": last_doc})


SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"}


@router.get("/stream")
async def stream_all(request: Request):
    """Global live stream: worker status, all new collection events and newly processed records."""
    return StreamingResponse(_stream(request, None), media_type="text/event-stream", headers=SSE_HEADERS)


@router.get("/campaigns/{campaign_id}/stream")
async def stream_campaign(campaign_id: int, request: Request):
    return StreamingResponse(_stream(request, campaign_id), media_type="text/event-stream", headers=SSE_HEADERS)
