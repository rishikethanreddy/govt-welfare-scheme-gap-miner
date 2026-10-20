"""Migrations from a clean database (up, down, up) and semantic clustering behaviour."""

import tempfile
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from tests.conftest import ROOT


def _cfg(url):
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


def test_migrations_up_down_up_and_match_models():
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext
    from backend.app.database import Base
    db = Path(tempfile.mkdtemp()) / "m.db"
    url = f"sqlite:///{db.as_posix()}"
    command.upgrade(_cfg(url), "head")
    command.downgrade(_cfg(url), "base")
    assert set(inspect(create_engine(url)).get_table_names()) <= {"alembic_version"}
    command.upgrade(_cfg(url), "head")
    eng = create_engine(url)
    with eng.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == [], f"models and migrations differ: {diff}"
    cols = {c["name"] for c in inspect(eng).get_columns("documents")}
    assert {"source_published_at", "source_updated_at", "first_seen_at", "collected_at", "processed_at",
            "content_hash", "predicted_gap", "label_source", "origin"} <= cols


TOPICS = {
    "kisan": ["When will my next PM-KISAN installment be credited?", "PM-KISAN installment not received after ekyc",
              "Why is my PM Kisan payment pending this cycle?", "PM-KISAN money not credited to my bank account",
              "How to check PM Kisan installment payment status", "My PM KISAN instalment is delayed, why?",
              "PM-KISAN 18th installment still not credited", "Did the PM Kisan installment get released yet?"],
    "ujjwala": ["How do I get a free Ujjwala LPG connection?", "Ujjwala gas refill subsidy amount this year",
                "Documents needed for an Ujjwala gas connection", "Is the Ujjwala LPG cylinder refill free?",
                "Ujjwala connection application rejected, what now?", "Can I transfer my Ujjwala gas connection?",
                "Ujjwala yojana new LPG connection eligibility", "Who gets Ujjwala refill subsidy on LPG?"],
    "pension": ["What is the age limit for Atal Pension Yojana?", "How much monthly pension will APY give at 60?",
                "Can I exit Atal Pension Yojana before sixty?", "Atal Pension contribution auto debit failed",
                "APY pension amount for a contribution of 210 rupees", "Is there a penalty for late APY contribution?",
                "Can my spouse get my Atal Pension after death?", "Atal Pension Yojana nominee change process"],
}


def test_clustering_groups_topics_and_traces_members(db):
    from backend.app.models.cluster import Cluster, DocumentCluster
    from backend.app.models.document import Document
    from backend.app.services.clustering import run_clustering
    from backend.app.services.pipeline import IncomingRecord, ingest_records, process_documents
    recs = [IncomingRecord(text=t, origin="dataset", role="query") for ts in TOPICS.values() for t in ts]
    ids = ingest_records(db, recs).stored
    process_documents(db, ids)
    summary = run_clustering(db, "dataset")
    assert summary["status"] == "completed" and summary["clusters"] >= 2
    clusters = db.query(Cluster).filter(Cluster.is_active == True).all()  # noqa: E712
    for c in clusters:
        members = db.query(Document).join(DocumentCluster, DocumentCluster.document_id == Document.id) \
            .filter(DocumentCluster.cluster_id == c.id).all()
        assert len(members) == c.size and c.keywords and c.representative_text in [m.original_text for m in members]
        topics = {k for m in members for k, ts in TOPICS.items() if m.original_text in ts}
        assert len(topics) == 1, f"cluster {c.name} mixes topics {topics}"


def test_clustering_skips_tiny_corpora(db):
    from backend.app.services.clustering import run_clustering
    assert run_clustering(db, "live")["status"] == "skipped"
