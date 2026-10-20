"""
Maintenance commands.

  python -m backend.app.maintenance backup
  python -m backend.app.maintenance repair-legacy     # one-time repair of pre-0002 data (idempotent)
  python -m backend.app.maintenance redact            # re-apply current PII rules to stored text
  python -m backend.app.maintenance reprocess [--origin dataset|live] [--only-pending]
  python -m backend.app.maintenance cluster --scope dataset|live
  python -m backend.app.maintenance sync-sources

repair-legacy never deletes rows. What it changes, and why, is written to the
audit log and summarised on stdout.
"""

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path

from backend.app.config import PROJECT_ROOT, get_settings
from backend.app.database import SessionLocal
from backend.app.models.audit import AuditLog
from backend.app.models.coltypes import utcnow
from backend.app.models.crawl import CollectionCampaign
from backend.app.models.document import Document
from backend.app.models.processing import DatasetVersion
from backend.app.models.source import Source
from backend.app.nlp.schemes import default_registry
from backend.app.nlp.text import content_hash, normalize_text, redact_pii

# Old extraction labels were stored in source_type; map them to text roles.
LEGACY_ROLE = {"html_comment": "discussion", "html_article": "article", "rss": "news",
               "question_pattern": "faq", "complaint_pattern": "article", "html_paragraph": "paragraph",
               "open_dataset": "query"}
WIDGET_DATE = re.compile(r"^(\d{1,2} [A-Z][a-z]{2}, \d{4}, \d{1,2}:\d{2} [AP]M)\s+")
INITIAL_DATASET = PROJECT_ROOT / "data" / "raw" / "welfare_awareness_dataset_with_split.csv"


def backup() -> Path:
    s = get_settings()
    if not s.is_sqlite:
        raise SystemExit("backup supports SQLite only; use pg_dump for PostgreSQL.")
    src = Path(s.DATABASE_URL.replace("sqlite:///", ""))
    src = src if src.is_absolute() else PROJECT_ROOT / src
    dest_dir = PROJECT_ROOT / "backups"
    dest_dir.mkdir(exist_ok=True)
    dest = dest_dir / f"{src.stem}.{utcnow():%Y%m%dT%H%M%SZ}.db"
    import sqlite3
    with sqlite3.connect(src) as a, sqlite3.connect(dest) as b:
        a.backup(b)  # consistent copy even with WAL
    print(f"Backup written to {dest}")
    return dest


def repair_legacy() -> dict:
    from backend.app.collection.dates import parse_date
    from backend.app.collection.registry import sync_registry
    db = SessionLocal()
    stats = Counter()
    try:
        # 1. Campaigns that were created by the old autopilot loop and never executed.
        junk = db.query(CollectionCampaign).filter(
            CollectionCampaign.status.in_(("created", "collecting", "discovering", "pending")),
            CollectionCampaign.started_at.is_(None), CollectionCampaign.urls_discovered == 0,
            CollectionCampaign.records_final == 0).all()
        for c in junk:
            c.status = "archived"
            c.error_message = ("Archived during repair: created by the former autopilot loop, which spawned a "
                               "campaign every 5 s that the worker never picked up (status mismatch). Never executed.")
            stats["campaigns_archived"] += 1

        # 2. The former "live" dataset scraper replayed a hand-written JSON file in a loop.
        for d in db.query(Document).filter((Document.source_type == "open_dataset") |
                                           (Document.source_url == "backend/data/trusted_queries.json")).all():
            if not d.is_demo:
                d.is_demo = True
                d.notes = ("Unverified fixture replayed by the former demo 'live' scraper "
                           "(backend/data/trusted_queries.json); excluded from analytics.")
                stats["demo_flagged"] += 1

        registry = default_registry()
        src_types = {s.id: s.source_type for s in db.query(Source).all()}
        docs = db.query(Document).order_by(Document.id).all()
        for d in docs:
            if d.origin == "live" and d.extraction_method is None and d.source_type in LEGACY_ROLE | {"html_faq": 1}:
                legacy = d.source_type
                d.extraction_method = legacy
                if legacy == "html_faq":
                    m = WIDGET_DATE.match(d.original_text or "")
                    if m:  # sidebar news widget item with its own stated timestamp
                        d.text_role = "news"
                        pub = parse_date(m.group(1), "legacy widget timestamp")
                        d.source_published_at = d.source_published_at or (pub.value if pub else None)
                        stats["widget_dates_recovered"] += int(pub is not None)
                    else:
                        d.text_role = "faq"
                else:
                    d.text_role = LEGACY_ROLE[legacy]
                if d.text_role == "discussion" and d.source_url and not d.scheme_context:
                    # The page a comment was posted on (its URL slug names the scheme).
                    d.scheme_context = registry.detect(d.source_url.replace("-", " ").replace("/", " ")).primary
                d.source_type = src_types.get(d.source_id) or "publication"
                stats["roles_assigned"] += 1
            if d.origin == "dataset":
                d.text_role = d.text_role or "query"
                if d.scheme_name:
                    d.scheme_name = registry.canonicalize(d.scheme_name)
                    d.scheme_match_strength = "manual"
                for f in ("intent", "awareness_gap", "gap_type", "split"):
                    v = getattr(d, f)
                    if v:
                        setattr(d, f, v.strip().lower())
                if d.intent or d.awareness_gap:
                    d.label_source = "manual"
            elif d.label_source != "review":
                # Live labels came from the removed question-mark heuristic: discard them.
                if d.awareness_gap or d.intent:
                    stats["heuristic_labels_cleared"] += 1
                d.intent = d.awareness_gap = d.gap_type = None
                d.intent_confidence = d.gap_confidence = d.gap_type_confidence = None
                d.label_source = None
                if d.scheme_match_strength != "manual":
                    d.scheme_name = None  # recomputed by the boundary-aware detector
            text = normalize_text(d.original_text)
            red = redact_pii(text)
            if red.redacted:
                stats["pii_redacted"] += 1
            d.original_text = red.text
            d.normalized_text = red.text
            d.pii_detected = d.pii_redacted = red.redacted or d.pii_redacted
            d.content_hash = content_hash(red.text)
            d.language = None
            d.first_seen_at = d.first_seen_at or d.collected_at or d.created_at
            d.processing_status = "pending"
            d.is_duplicate, d.duplicate_of_id, d.duplicate_group_id = False, None, None
            d.near_duplicate_of_id = d.near_duplicate_similarity = None

        # 3. Exact duplicates per workspace (earliest record is canonical).
        first: dict = {}
        for d in docs:
            key = (d.origin, d.content_hash)
            if d.is_demo:
                continue
            if key in first:
                d.is_duplicate, d.duplicate_of_id, d.duplicate_group_id = True, first[key], d.content_hash[:16]
                stats["exact_duplicates"] += 1
            else:
                first[key] = d.id

        # 4. Dataset version provenance.
        if INITIAL_DATASET.exists():
            sha = hashlib.sha256(INITIAL_DATASET.read_bytes()).hexdigest()
            for dv in db.query(DatasetVersion).filter(DatasetVersion.file_sha256.is_(None),
                                                      DatasetVersion.source_file == INITIAL_DATASET.name).all():
                dv.file_sha256 = sha
                stats["dataset_hash_recorded"] += 1
        db.commit()

        # 5. Sources: curated registry; legacy duplicates retired (kept for provenance).
        stats.update({f"sources_{k}": v for k, v in sync_registry(db).items()})
        db.add(AuditLog(action="legacy_repair", entity_type="system", user="maintenance", severity="warning",
                        description="Legacy data repaired (see details)", details=json.dumps(dict(stats))))
        db.commit()
        return dict(stats)
    finally:
        db.close()


def redact() -> dict:
    """Re-apply the current PII rules to stored text (idempotent; run after rules change)."""
    db = SessionLocal()
    changed = 0
    try:
        for d in db.query(Document).yield_per(500):
            red = redact_pii(d.original_text)
            if red.redacted:
                d.original_text = d.normalized_text = red.text
                d.content_hash = content_hash(red.text)
                d.pii_detected = d.pii_redacted = True
                changed += 1
        db.add(AuditLog(action="pii_redaction", entity_type="system", user="maintenance",
                        description=f"Re-applied PII redaction rules to {changed} records"))
        db.commit()
        return {"records_redacted": changed}
    finally:
        db.close()


def reprocess(origin=None, only_pending=False) -> dict:
    from backend.app.services.clustering import run_clustering
    from backend.app.services.pipeline import process_documents
    db = SessionLocal()
    try:
        out = {}
        for o in ([origin] if origin else ["dataset", "live"]):
            q = db.query(Document.id).filter(Document.origin == o)
            if only_pending:
                q = q.filter(Document.processing_status.in_(("pending", "failed")))
            ids = [i for (i,) in q.order_by(Document.id).all()]
            print(f"Processing {len(ids)} {o} documents …")
            res = process_documents(db, ids, progress=lambda seen, ok, bad: print(f"  {seen}/{len(ids)} "
                                                                                  f"(ok {ok}, failed {bad})"))
            res["clustering"] = run_clustering(db, o)
            out[o] = res
        db.add(AuditLog(action="reprocess", entity_type="system", user="maintenance",
                        description="Bulk reprocessing", details=json.dumps(out, default=str)))
        db.commit()
        return out
    finally:
        db.close()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("backup")
    sub.add_parser("repair-legacy")
    sub.add_parser("redact")
    p = sub.add_parser("reprocess")
    p.add_argument("--origin", choices=["dataset", "live"])
    p.add_argument("--only-pending", action="store_true")
    c = sub.add_parser("cluster")
    c.add_argument("--scope", choices=["dataset", "live"], required=True)
    sub.add_parser("sync-sources")
    args = ap.parse_args()
    if args.cmd == "backup":
        backup()
    elif args.cmd == "repair-legacy":
        print(json.dumps(repair_legacy(), indent=2))
    elif args.cmd == "redact":
        print(json.dumps(redact(), indent=2))
    elif args.cmd == "reprocess":
        print(json.dumps(reprocess(args.origin, args.only_pending), indent=2, default=str))
    elif args.cmd == "cluster":
        from backend.app.services.clustering import run_clustering
        db = SessionLocal()
        try:
            print(json.dumps(run_clustering(db, args.scope), indent=2, default=str))
        finally:
            db.close()
    elif args.cmd == "sync-sources":
        from backend.app.collection.registry import sync_registry
        db = SessionLocal()
        try:
            print(sync_registry(db))
        finally:
            db.close()


if __name__ == "__main__":
    main()
