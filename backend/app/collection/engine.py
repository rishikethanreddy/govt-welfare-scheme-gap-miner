"""
Campaign execution engine.

A campaign runs every selected source (in parallel up to
COLLECTION_SOURCE_CONCURRENCY). For each source:

  seed URLs → frontier (crawl_urls) → safe fetch (robots, SSRF, size/type limits,
  retries, per-host delay) → change detection (ETag / Last-Modified / content hash)
  → extraction (HTML / feed / sitemap / PDF / JSON / CSV) → relevance filter →
  shared ingest pipeline (PII redaction, exact dedup) → NLP + embeddings +
  near-duplicate detection → persisted documents → events.

All counters are incremented atomically in SQL from what actually happened.
The frontier lives in the database, so an interrupted campaign resumes where it
stopped (URLs left in "processing" are re-queued). Cancellation is checked
between URLs.
"""

import hashlib
import logging
import re
import threading
import zlib
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from typing import Callable, Optional
from urllib.parse import urlencode

from sqlalchemy import update
from sqlalchemy.orm import Session

from backend.app.collection import extractors
from backend.app.collection.robots import RobotsPolicy
from backend.app.collection.safe_http import FetchError, HostRateLimiter, SafeFetcher
from backend.app.collection.urls import absolute, canonicalize
from backend.app.config import get_settings
from backend.app.database import SessionLocal
from backend.app.models.audit import AuditLog
from backend.app.models.coltypes import utcnow
from backend.app.models.crawl import CollectionCampaign, CollectionEvent, CrawlPage, CrawlUrl
from backend.app.models.source import Source, SourceRun
from backend.app.nlp.schemes import default_registry
from backend.app.services.pipeline import IncomingRecord, ingest_records, process_documents

logger = logging.getLogger(__name__)

# Torch inference and SQLite writes are serialized across source threads.
_nlp_lock = threading.Lock()

ADAPTER_ACCEPT = {
    "rss": ("application/rss+xml", "application/atom+xml", "application/xml", "text/xml"),
    "sitemap": ("application/xml", "text/xml", "application/x-gzip"),
    "json_api": ("application/json",),
    "datagovin": ("application/json",),
    "csv": ("text/csv", "application/csv", "text/plain"),
}
PAGE_ACCEPT = ("text/html", "application/xhtml+xml", "application/pdf")
FAILURE_KINDS_BLOCKED = {"robots", "unsafe_url"}
RECORD_EVENTS_PER_PAGE = 25
RUN_COUNTERS = ("urls_discovered", "urls_attempted", "successful", "skipped", "blocked", "failed",
                "records_extracted", "records_accepted", "records_rejected", "duplicates_found")


def _redact_secrets(text: str) -> str:
    return re.sub(r"(api-key=)[^&\s]+", r"\1***", text)


def emit(db: Session, campaign_id: int, kind: str, message: str, level: str = "info",
         source_id: Optional[int] = None, url: Optional[str] = None, document_id: Optional[int] = None) -> None:
    db.add(CollectionEvent(campaign_id=campaign_id, kind=kind, message=message[:2000], level=level,
                           source_id=source_id, url=url, document_id=document_id))


def bump(db: Session, campaign_id: int, **deltas) -> None:
    """Atomic counter increments (safe across source threads)."""
    values = {k: getattr(CollectionCampaign, k) + v for k, v in deltas.items() if v}
    values["heartbeat_at"] = utcnow()
    db.execute(update(CollectionCampaign).where(CollectionCampaign.id == campaign_id).values(**values))


class CampaignRunner:
    def __init__(self, campaign_id: int, session_factory: Callable[[], Session] = SessionLocal,
                 fetcher_factory: Optional[Callable[..., SafeFetcher]] = None):
        self.campaign_id = campaign_id
        self.session_factory = session_factory
        settings = get_settings()
        self.settings = settings
        self.robots = RobotsPolicy(settings.SCRAPER_USER_AGENT)
        self.rate_limiter = HostRateLimiter()
        self.fetcher_factory = fetcher_factory or (
            lambda: SafeFetcher(robots=self.robots, rate_limiter=self.rate_limiter))
        self.registry = default_registry()

    # ── Campaign level ────────────────────────────────────────────────────

    def run(self) -> dict:
        db = self.session_factory()
        try:
            c = db.get(CollectionCampaign, self.campaign_id)
            if c is None:
                return {"error": "campaign not found"}
            resumed = c.started_at is not None
            c.status, c.stage = "running", "collecting"
            c.started_at = c.started_at or utcnow()
            c.heartbeat_at = utcnow()
            c.error_message = None
            # Resume: URLs interrupted mid-fetch go back to the queue.
            db.query(CrawlUrl).filter(CrawlUrl.campaign_id == c.id, CrawlUrl.status == "processing") \
                .update({"status": "queued"})
            q = db.query(Source).filter(Source.active == True, Source.policy_status == "allowed")  # noqa: E712
            if c.source_ids:
                q = q.filter(Source.id.in_(c.source_ids))
            source_ids = [s.id for s in q.order_by(Source.id).all()]
            emit(db, c.id, "stage", f"{'Resumed' if resumed else 'Started'} collection over {len(source_ids)} source(s)")
            db.commit()
        finally:
            db.close()

        if not source_ids:
            return self._finish({}, note="No active, allowed sources matched this campaign.")

        workers = max(1, min(self.settings.COLLECTION_SOURCE_CONCURRENCY, len(source_ids)))
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="source") as pool:
            outcomes = dict(zip(source_ids, pool.map(self._run_source_safe, source_ids)))
        return self._finish(outcomes)

    def _cancelled(self, db: Session) -> bool:
        status = db.query(CollectionCampaign.status).filter(CollectionCampaign.id == self.campaign_id).scalar()
        return status == "cancel_requested"

    def _finish(self, outcomes: dict, note: Optional[str] = None) -> dict:
        db = self.session_factory()
        try:
            c = db.get(CollectionCampaign, self.campaign_id)
            statuses = list(outcomes.values())
            if c.status == "cancel_requested" or "cancelled" in statuses:
                final = "cancelled"
            elif not statuses:
                final = "failed"
            elif all(s in ("failed", "blocked") for s in statuses):
                final = "failed"
            elif any(s in ("failed", "blocked", "completed_with_errors") for s in statuses):
                final = "completed_with_errors"
            else:
                final = "completed"
            c.status, c.stage = final, None
            c.finished_at = utcnow()
            if note:
                c.error_message = note
            elapsed = (c.finished_at - c.started_at).total_seconds() if c.started_at else 0
            summary = (f"Campaign {final}: {c.urls_processed} URLs processed ({c.urls_failed} failed, "
                       f"{c.urls_blocked} blocked, {c.urls_unchanged} unchanged), {c.records_final} new records, "
                       f"{c.records_duplicate} duplicates, {c.records_rejected} rejected in {elapsed:.0f}s")
            emit(db, c.id, "summary", summary + (f". {note}" if note else ""),
                 level="info" if final == "completed" else "warning")
            db.add(AuditLog(action="campaign_finished", entity_type="campaign", entity_id=str(c.id),
                            description=summary, user="collector",
                            severity="info" if final in ("completed", "completed_with_errors") else "warning"))
            db.commit()
            return {"campaign_id": c.id, "status": final, "sources": outcomes,
                    "records_final": c.records_final, "records_processed": c.records_processed}
        finally:
            db.close()

    # ── Source level ──────────────────────────────────────────────────────

    def _run_source_safe(self, source_id: int) -> str:
        try:
            return self._run_source(source_id)
        except Exception as e:  # never let one source kill the campaign
            logger.exception("Source %s crashed", source_id)
            db = self.session_factory()
            try:
                emit(db, self.campaign_id, "error", f"Source crashed: {type(e).__name__}: {e}", "error", source_id)
                db.commit()
            finally:
                db.close()
            return "failed"

    def _seed_urls(self, src: Source) -> list[tuple[str, str]]:
        cfg = src.config or {}
        if src.content_type == "datagovin":
            rid = cfg.get("resource_id")
            if not rid:
                return []
            size = int(cfg.get("page_size", 100))
            filters = {f"filters[{k}]": v for k, v in (cfg.get("filters") or {}).items()}
            return [(f"https://api.data.gov.in/resource/{rid}?" + urlencode(
                {"format": "json", "offset": o * size, "limit": size, **filters}), "api")
                    for o in range(src.max_pages or 5)]
        seeds = [(src.url, "seed")] + [(u, "seed") for u in cfg.get("seed_urls", [])]
        return [(absolute(u) or u, m) for u, m in seeds]

    def _enqueue(self, db: Session, src: Source, url: str, method: str, depth: int, priority: int,
                 parent: Optional[str] = None, anchor: str = "") -> bool:
        canon = canonicalize(url) or url
        exists = db.query(CrawlUrl.id).filter(CrawlUrl.campaign_id == self.campaign_id,
                                              CrawlUrl.canonical_url == canon).first()
        if exists:
            return False
        db.add(CrawlUrl(source_id=src.id, campaign_id=self.campaign_id, url=url, canonical_url=canon,
                        domain=(canon.split("/")[2] if "://" in canon else None), discovered_from=parent,
                        discovery_method=method, discovery_query=anchor[:500] or None, depth=depth,
                        priority=priority, status="queued"))
        return True

    def _run_source(self, source_id: int) -> str:
        db = self.session_factory()
        fetcher = self.fetcher_factory()
        try:
            src = db.get(Source, source_id)
            c = db.get(CollectionCampaign, self.campaign_id)
            run = db.query(SourceRun).filter(SourceRun.campaign_id == c.id, SourceRun.source_id == src.id).first()
            if run is None:
                run = SourceRun(source_id=src.id, campaign_id=c.id, status="running", started_at=utcnow(),
                                **{k: 0 for k in RUN_COUNTERS})
                db.add(run)
                seeds = self._seed_urls(src)
                missing_key = src.content_type == "datagovin" and not self.settings.DATA_GOV_IN_API_KEY
                if not seeds or missing_key:
                    run.status, run.finished_at = "failed", utcnow()
                    run.error_message = (
                        "DATA_GOV_IN_API_KEY is not set for the running worker. Add it to .env and restart the worker."
                        if missing_key else "No seed URLs (missing configuration or credentials)")
                    emit(db, c.id, "error", f"{src.name}: {run.error_message}", "error", src.id)
                    db.commit()
                    return "failed"
                added = sum(self._enqueue(db, src, u, m, 0, 1) for u, m in seeds)
                bump(db, c.id, urls_discovered=added, urls_accepted=added)
                run.urls_discovered += added
            else:
                run.status = "running"
            src.last_run_at = utcnow()
            emit(db, c.id, "stage", f"{src.name}: collecting (adapter {src.content_type})", source_id=src.id)
            db.commit()

            # The stricter of the source's own limit and the campaign's per-source limit.
            budget = min(x for x in (src.max_pages, c.max_pages_per_source, 200) if x)
            max_depth = c.max_depth if c.max_depth is not None else 1
            errors = 0
            while True:
                if self._cancelled(db):
                    run.status = "cancelled"
                    break
                fetched = db.query(CrawlUrl).filter(
                    CrawlUrl.campaign_id == c.id, CrawlUrl.source_id == src.id,
                    CrawlUrl.status.in_(("success", "unchanged", "failed", "blocked"))).count()
                if fetched >= budget:
                    emit(db, c.id, "stage", f"{src.name}: page budget of {budget} reached", source_id=src.id)
                    break
                cu = (db.query(CrawlUrl)
                      .filter(CrawlUrl.campaign_id == c.id, CrawlUrl.source_id == src.id, CrawlUrl.status == "queued")
                      .order_by(CrawlUrl.priority, CrawlUrl.depth, CrawlUrl.id).first())
                if cu is None:
                    break
                ok = self._process_url(db, fetcher, src, run, cu, max_depth)
                errors += 0 if ok else 1
                db.commit()

            if run.status != "cancelled":
                if run.successful == 0 and (run.failed or run.blocked):
                    run.status = "blocked" if run.blocked and not run.failed else "failed"
                elif run.failed or run.blocked:
                    run.status = "completed_with_errors"
                else:
                    run.status = "completed"
            run.finished_at = utcnow()
            self._update_source_health(db, src, run)
            emit(db, c.id, "stage",
                 f"{src.name}: {run.status} — {run.successful} fetched, {run.failed} failed, {run.blocked} blocked, "
                 f"{run.records_accepted} new records", level="info" if run.status == "completed" else "warning",
                 source_id=src.id)
            db.commit()
            return run.status
        finally:
            fetcher.close()
            db.close()

    def _update_source_health(self, db: Session, src: Source, run: SourceRun) -> None:
        src.total_runs = (src.total_runs or 0) + 1
        src.total_records_collected = (src.total_records_collected or 0) + run.records_accepted
        if run.status in ("completed", "completed_with_errors") and run.successful > 0:
            src.last_success_at = run.finished_at
            src.consecutive_failures = 0
            src.last_error = None if run.status == "completed" else run.error_message
            has_records = src.total_records_collected > 0 or db.query(CrawlUrl.id).filter(
                CrawlUrl.source_id == src.id, CrawlUrl.records_extracted > 0).first() is not None
            src.verification_status = "collected" if has_records else "reachable"
        elif run.status == "cancelled":
            return
        else:
            src.consecutive_failures = (src.consecutive_failures or 0) + 1
            src.last_error = run.error_message
            src.verification_status = "blocked" if run.status == "blocked" else "failing"
            if src.consecutive_failures >= self.settings.SOURCE_FAILURE_PAUSE_THRESHOLD:
                src.active = False
                src.policy_status = "paused"
                src.policy_note = (f"Paused automatically after {src.consecutive_failures} consecutive failed runs. "
                                   f"Last error: {src.last_error}")
                emit(db, self.campaign_id, "error", f"{src.name}: paused after repeated failures", "error", src.id)
        ok_runs = db.query(SourceRun).filter(SourceRun.source_id == src.id).order_by(SourceRun.id.desc()).limit(10).all()
        if ok_runs:
            src.health_score = round(sum(r.status in ("completed", "completed_with_errors") for r in ok_runs) / len(ok_runs), 2)

    # ── URL level ─────────────────────────────────────────────────────────

    def _fetch_url(self, src: Source, url: str) -> str:
        if src.content_type == "datagovin":
            # The API key is added only at request time so it is never stored or logged.
            return url + "&" + urlencode({"api-key": self.settings.DATA_GOV_IN_API_KEY})
        return url

    def _process_url(self, db: Session, fetcher: SafeFetcher, src: Source, run: SourceRun,
                     cu: CrawlUrl, max_depth: int) -> bool:
        c_id = self.campaign_id
        cu.status = "processing"
        cu.attempt_count += 1
        cu.last_attempt_at = utcnow()
        db.commit()
        run.urls_attempted += 1
        prior = (db.query(CrawlUrl).filter(CrawlUrl.canonical_url == cu.canonical_url, CrawlUrl.id != cu.id,
                                           CrawlUrl.status.in_(("success", "unchanged")),
                                           CrawlUrl.content_hash != None)  # noqa: E711
                 .order_by(CrawlUrl.id.desc()).first())
        is_seed_feed = src.content_type in ADAPTER_ACCEPT and cu.depth == 0
        accept = ADAPTER_ACCEPT[src.content_type] if is_seed_feed else PAGE_ACCEPT
        if cu.discovery_method == "sitemap_index":
            accept = ADAPTER_ACCEPT["sitemap"]
        try:
            res = fetcher.fetch(self._fetch_url(src, cu.url), accept=accept + ("text/html",) if is_seed_feed else accept,
                                delay=src.crawl_delay,
                                etag=prior.etag if prior else None,
                                last_modified=prior.last_modified if prior else None)
        except FetchError as e:
            blocked = e.kind in FAILURE_KINDS_BLOCKED
            cu.status = "blocked" if blocked else "failed"
            cu.error_message = _redact_secrets(f"{e.kind}: {e}")[:1000]
            cu.http_status = e.status
            run.blocked += int(blocked)
            run.failed += int(not blocked)
            run.error_message = cu.error_message
            bump(db, c_id, urls_processed=1, urls_blocked=int(blocked), urls_failed=int(not blocked))
            emit(db, c_id, "fetch", f"{'Blocked' if blocked else 'Failed'}: {cu.error_message}",
                 "warning", src.id, cu.url)
            return False

        cu.http_status, cu.content_type = res.status, res.content_type
        if res.not_modified:
            cu.status, cu.content_hash = "unchanged", prior.content_hash if prior else None
            cu.etag, cu.last_modified = prior.etag if prior else None, prior.last_modified if prior else None
            run.successful += 1
            bump(db, c_id, urls_processed=1, urls_unchanged=1)
            added = self._expand_from_stored(db, src, cu, fetcher, max_depth)
            emit(db, c_id, "fetch", "Not modified since last collection (HTTP 304)"
                 + (f"; re-checking {added} linked pages" if added else ""), source_id=src.id, url=cu.url)
            return True
        if not res.ok:
            blocked = res.status in (401, 403, 451)
            cu.status = "blocked" if blocked else "failed"
            cu.error_message = f"HTTP {res.status}"
            run.blocked += int(blocked)
            run.failed += int(not blocked)
            run.error_message = f"HTTP {res.status} for {cu.url}"
            bump(db, c_id, urls_processed=1, urls_blocked=int(blocked), urls_failed=int(not blocked))
            emit(db, c_id, "fetch", f"HTTP {res.status}", "warning", src.id, cu.url)
            return False

        digest = hashlib.sha256(res.content).hexdigest()
        cu.content_hash, cu.content_length = digest, len(res.content)
        cu.etag, cu.last_modified = res.etag, res.last_modified
        run.successful += 1
        if prior is not None and prior.content_hash == digest:
            cu.status = "unchanged"
            bump(db, c_id, urls_processed=1, urls_unchanged=1)
            added = self._expand_from_stored(db, src, cu, fetcher, max_depth, res.content)
            emit(db, c_id, "fetch", "Content unchanged since last collection (same hash)"
                 + (f"; re-checking {added} linked pages" if added else ""), source_id=src.id, url=cu.url)
            return True

        # Parse and make all network calls (robots.txt for discovered links) *before*
        # writing anything, so no SQLite write transaction is held across I/O.
        try:
            ex = self._extract(src, cu, res)
        except Exception as e:
            cu.status, cu.error_message = "failed", f"extraction: {type(e).__name__}: {e}"[:1000]
            run.failed += 1
            bump(db, c_id, urls_processed=1, urls_failed=1, pages_downloaded=1)
            emit(db, c_id, "extract", f"Extraction failed: {cu.error_message}", "warning", src.id, cu.url)
            return False
        links = [l for l in ex.links if self.robots.check(l[0], fetcher).allowed]
        skipped_links = len(ex.links) - len(links)

        page = CrawlPage(crawl_url_id=cu.id, source_id=src.id, campaign_id=c_id, run_id=run.id, url=cu.url,
                         final_url=res.final_url if "api-key=" not in res.final_url else cu.url,
                         http_status=res.status, content_type=res.content_type, content_hash=digest,
                         content_length=len(res.content), raw_content=zlib.compress(res.content),
                         fetched_at=utcnow(), page_type=ex.page_type, title=(ex.title or "")[:500] or None,
                         published_at=ex.published.value if ex.published else None,
                         modified_at=ex.modified.value if ex.modified else None,
                         date_source=ex.published.source[:50] if ex.published else None)
        db.add(page)
        db.flush()

        added = self._expand(db, src, cu, links, max_depth)
        if added:
            run.urls_discovered += added
            bump(db, c_id, urls_discovered=added, urls_accepted=added)

        # Relevance: keep records that mention a scheme; comments may inherit the page's scheme.
        page_scheme = self.registry.detect(f"{ex.title or ''} {cu.url.replace('-', ' ')}").primary
        incoming, off_topic = [], 0
        for r in ex.records:
            own = self.registry.detect(r.text).primary
            if own is None and not (r.role in ("discussion", "query") and page_scheme):
                off_topic += 1
                continue
            incoming.append(IncomingRecord(
                text=r.text, origin="live", role=r.role, source_id=src.id, source_name=src.name,
                source_type=src.source_type, source_url=r.source_url, source_document_id=r.source_document_id,
                extraction_method=r.method,
                published_at=r.published.value if r.published else None,
                updated_at=r.updated.value if r.updated else None,
                state=r.state, district=r.district, campaign_id=c_id, crawl_page_id=page.id,
                scrape_run_id=run.id, scheme_context=page_scheme if r.role in ("discussion", "query") else None,
            ))
        with _nlp_lock:
            result = ingest_records(db, incoming, commit=False)
            new_ids = result.stored
            db.commit()
            processed = {"processed": 0, "failed": 0}
            if new_ids:
                logged = [0]

                def _on_doc(d):
                    # The activity log shows the first records per page; all are in the live feed.
                    logged[0] += 1
                    if logged[0] > RECORD_EVENTS_PER_PAGE:
                        return
                    emit(db, c_id, "record", f"[{d.scheme_name or 'Other/Unknown'} · {d.text_role} · gap: "
                         f"{d.awareness_gap or 'n/a'}] {d.original_text[:160]}", source_id=src.id,
                         url=d.source_url, document_id=d.id)
                processed = process_documents(db, new_ids, on_document=_on_doc)

        page.records_extracted = len(ex.records)
        page.has_useful_content = bool(new_ids)
        page.processed_at = utcnow()
        cu.status, cu.records_extracted = "success", len(ex.records)
        run.records_extracted += len(ex.records)
        run.records_accepted += len(new_ids)
        run.duplicates_found += len(result.duplicates)
        run.records_rejected += len(result.rejected) + off_topic
        bump(db, c_id, urls_processed=1, pages_downloaded=1, pages_useful=int(bool(new_ids)),
             records_extracted=len(ex.records), records_duplicate=len(result.duplicates),
             records_rejected=len(result.rejected) + off_topic, records_final=len(new_ids),
             records_processed=processed["processed"])
        emit(db, c_id, "extract",
             f"{ex.page_type}: {len(ex.records)} candidate records → {len(new_ids)} new, "
             f"{len(result.duplicates)} duplicate, {len(result.rejected) + off_topic} rejected "
             f"({off_topic} off-topic); {added} new URLs"
             + (f" ({skipped_links} links disallowed by robots.txt)" if skipped_links else "")
             + (f"; published {page.published_at:%Y-%m-%d}" if page.published_at else "; publication date unavailable"),
             source_id=src.id, url=cu.url)
        return True

    def _expand_from_stored(self, db: Session, src: Source, cu: CrawlUrl, fetcher: SafeFetcher, max_depth: int,
                            content: Optional[bytes] = None) -> int:
        """An unchanged feed / sitemap / listing still links to pages that may have changed
        (e.g. new comments), so its links are re-queued from the stored copy. Each linked page
        is then cheaply re-validated (ETag / Last-Modified / content hash)."""
        if cu.depth != 0:
            return 0
        if content is None:
            page = (db.query(CrawlPage).join(CrawlUrl, CrawlUrl.id == CrawlPage.crawl_url_id)
                    .filter(CrawlUrl.canonical_url == cu.canonical_url, CrawlPage.raw_content != None)  # noqa: E711
                    .order_by(CrawlPage.id.desc()).first())
            if page is None:
                return 0
            content, ctype = zlib.decompress(page.raw_content), page.content_type or ""
        else:
            ctype = cu.content_type or ""
        from backend.app.collection.safe_http import FetchResult
        stored = FetchResult(cu.url, cu.url, 200, {"content-type": ctype}, content, ctype)
        try:
            ex = self._extract(src, cu, stored)
        except Exception:
            return 0
        links = [l for l in ex.links if self.robots.check(l[0], fetcher).allowed]
        added = self._expand(db, src, cu, links, max_depth)
        if added:
            bump(db, self.campaign_id, urls_discovered=added, urls_accepted=added)
        return added

    def _extract(self, src: Source, cu: CrawlUrl, res) -> extractors.Extraction:
        cfg = src.config or {}
        ctype = res.content_type
        body = res.text() if ctype != "application/pdf" else None
        if ctype == "application/pdf":
            return extractors.extract_pdf(res.content, cu.url)
        if src.content_type in ("datagovin", "json_api") and cu.depth == 0:
            cfg = {"records_path": "records", **cfg} if src.content_type == "datagovin" else cfg
            return extractors.extract_json(body, cu.url, cfg)
        if src.content_type == "csv" and cu.depth == 0:
            return extractors.extract_csv(body, cu.url, cfg)
        stripped = (body or "").lstrip()[:500].lower()
        if "<urlset" in stripped or "<sitemapindex" in stripped:
            return extractors.extract_sitemap(body, cu.url)
        if "<rss" in stripped or "<feed" in stripped or ("xml" in ctype and "<channel" in stripped):
            return extractors.extract_feed(body, cu.url)
        return extractors.extract_html(body, cu.url)

    def _expand(self, db: Session, src: Source, cu: CrawlUrl, links: list, max_depth: int) -> int:
        """Queue discovered links (already filtered by robots.txt)."""
        cfg = src.config or {}
        added = 0
        for url, method, anchor in links:
            if method == "sitemap_index":
                if cu.depth < 2:
                    added += self._enqueue(db, src, url, method, cu.depth, 2, cu.url)
            elif method in ("sitemap", "rss"):
                if method == "rss" and not cfg.get("follow_links", True):
                    continue
                added += self._enqueue(db, src, url, method, cu.depth + 1, 3, cu.url, anchor)
            elif method == "pagination":
                if cu.depth <= max_depth:
                    added += self._enqueue(db, src, url, method, cu.depth, 4, cu.url, anchor)
            elif cfg.get("follow_links") and cu.depth < max_depth:
                added += self._enqueue(db, src, url, method, cu.depth + 1, 6, cu.url, anchor)
        return added


def stale_running_campaigns(db: Session, minutes: int = 3) -> list[int]:
    cutoff = utcnow() - timedelta(minutes=minutes)
    return [c.id for c in db.query(CollectionCampaign).filter(
        CollectionCampaign.status.in_(("running",)),
        (CollectionCampaign.heartbeat_at == None) | (CollectionCampaign.heartbeat_at < cutoff)).all()]  # noqa: E711
