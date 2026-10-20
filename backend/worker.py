"""
Collection & processing worker.

Loop (every few seconds):
  1. Write a heartbeat (system_state 'worker:heartbeat') so the UI can show liveness.
  2. Resume campaigns left 'running' by a previous worker that stopped.
  3. Run the oldest queued campaign (one at a time), then cluster the live workspace.
  4. Run pending processing jobs (dataset NLP, reprocessing, clustering).
  5. Process any live documents still 'pending' (e.g. after a crash mid-campaign).
  6. Scheduler: if autopilot is enabled, queue one scheduled campaign when sources
     are due (daily/weekly) and none is active, at most every AUTOPILOT_INTERVAL_HOURS.
  7. Prune old collection events.

Run: python -m backend.worker   (npm run dev:worker)
"""

import json
import logging
import os
import signal
import socket
import threading
import time
from datetime import timedelta

from backend.app.collection.engine import CampaignRunner, stale_running_campaigns
from backend.app.config import get_settings
from backend.app.database import SessionLocal
from backend.app.models.coltypes import utcnow
from backend.app.models.crawl import ACTIVE_CAMPAIGN_STATUSES, CollectionCampaign, CollectionEvent
from backend.app.models.document import Document
from backend.app.models.embedding import SystemState
from backend.app.models.processing import ProcessingJob
from backend.app.models.source import Source

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger("worker")

_stop = False
SCHEDULE_HOURS = {"daily": 24, "weekly": 24 * 7}


def _handle_stop(*_):
    global _stop
    _stop = True
    logger.info("Stop requested; finishing current step")


_status = {"state": "starting"}


def heartbeat(db, state: str, detail: dict | None = None) -> None:
    """Record what the worker is doing; only the heartbeat thread writes it (every 10 s),
    so there is a single writer for the heartbeat row."""
    _status.clear()
    _status.update({"state": state, **(detail or {})})


def _write_heartbeat(db) -> None:
    row = db.get(SystemState, "worker:heartbeat") or SystemState(key="worker:heartbeat")
    row.value = json.dumps({"pid": os.getpid(), "host": socket.gethostname(), **_status})
    row.updated_at = utcnow()
    db.add(row)
    db.commit()


def _heartbeat_loop() -> None:
    while not _stop:
        db = SessionLocal()
        try:
            _write_heartbeat(db)
        except Exception:
            logger.warning("Heartbeat write failed", exc_info=True)
        finally:
            db.close()
        for _ in range(20):
            if _stop:
                return
            time.sleep(0.5)


def due_sources(db) -> list[int]:
    now = utcnow()
    ids = []
    for s in db.query(Source).filter(Source.active == True, Source.policy_status == "allowed").all():  # noqa: E712
        hours = SCHEDULE_HOURS.get(s.schedule or "manual")
        if hours and (s.last_run_at is None or now - s.last_run_at >= timedelta(hours=hours)):
            ids.append(s.id)
    return ids


def maybe_schedule(db) -> None:
    settings = get_settings()
    row = db.get(SystemState, "autopilot:enabled")
    if not row or row.value != "true":
        return
    if db.query(CollectionCampaign.id).filter(CollectionCampaign.status.in_(ACTIVE_CAMPAIGN_STATUSES)).first():
        return
    last = db.query(CollectionCampaign).filter(CollectionCampaign.trigger == "schedule") \
        .order_by(CollectionCampaign.id.desc()).first()
    if last and last.created_at and utcnow() - last.created_at < timedelta(hours=settings.AUTOPILOT_INTERVAL_HOURS):
        return
    ids = due_sources(db)
    if not ids:
        return
    c = CollectionCampaign(name=f"Scheduled collection {utcnow():%Y-%m-%d %H:%M} UTC", trigger="schedule",
                           source_ids=ids, status="queued", max_pages_per_source=20, max_depth=1)
    db.add(c)
    db.commit()
    logger.info("Scheduler queued campaign %s for %d due source(s)", c.id, len(ids))


def run_campaign(campaign_id: int) -> None:
    from backend.app.services.clustering import run_clustering
    logger.info("Running campaign %s", campaign_id)
    result = CampaignRunner(campaign_id).run()
    logger.info("Campaign %s finished: %s", campaign_id, result.get("status"))
    if result.get("records_final"):
        db = SessionLocal()
        try:
            run_clustering(db, "live")
        except Exception:
            logger.exception("Live clustering failed")
        finally:
            db.close()


def run_pending_jobs(db) -> None:
    from backend.app.services import jobs
    for (job_id,) in db.query(ProcessingJob.id).filter(ProcessingJob.status == "pending").order_by(ProcessingJob.id).all():
        if _stop:
            return
        jobs.run_job(job_id)


def process_stragglers(db) -> None:
    from backend.app.services.pipeline import process_documents
    cutoff = utcnow() - timedelta(minutes=5)
    ids = [i for (i,) in db.query(Document.id).filter(
        Document.origin == "live", Document.processing_status.in_(("pending", "processing")),
        Document.created_at < cutoff, Document.processing_attempts < 3).limit(500).all()]
    if ids:
        logger.info("Processing %d leftover live documents", len(ids))
        process_documents(db, ids)


def prune_events(db, keep_days: int = 30) -> None:
    db.query(CollectionEvent).filter(CollectionEvent.created_at < utcnow() - timedelta(days=keep_days)) \
        .delete(synchronize_session=False)
    db.commit()


def run_worker(poll_seconds: float = 5.0) -> None:
    signal.signal(signal.SIGINT, _handle_stop)
    signal.signal(signal.SIGTERM, _handle_stop)
    logger.info("Worker started (pid %s)", os.getpid())
    threading.Thread(target=_heartbeat_loop, name="heartbeat", daemon=True).start()
    last_prune = 0.0
    while not _stop:
        db = SessionLocal()
        try:
            heartbeat(db, "idle")
            for cid in stale_running_campaigns(db):
                heartbeat(db, "resuming", {"campaign_id": cid})
                run_campaign(cid)
            nxt = db.query(CollectionCampaign).filter(CollectionCampaign.status == "queued") \
                .order_by(CollectionCampaign.id).first()
            if nxt:
                heartbeat(db, "collecting", {"campaign_id": nxt.id})
                run_campaign(nxt.id)
                continue
            heartbeat(db, "processing")
            run_pending_jobs(db)
            process_stragglers(db)
            maybe_schedule(db)
            if time.time() - last_prune > 3600:
                prune_events(db)
                last_prune = time.time()
            heartbeat(db, "idle")
        except Exception:
            logger.exception("Worker iteration failed")
            db.rollback()
        finally:
            db.close()
        for _ in range(int(poll_seconds * 2)):
            if _stop:
                break
            time.sleep(0.5)
    logger.info("Worker stopped")


if __name__ == "__main__":
    run_worker()
