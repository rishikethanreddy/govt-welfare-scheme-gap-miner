"""
Test configuration.

Every test session runs against a fresh SQLite database created by the Alembic
migrations (not create_all), so the migrations themselves are exercised.
Environment variables are set before any application module is imported,
because the engine and settings are created at import time.
"""

import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_tmp = Path(tempfile.mkdtemp(prefix="gapminer-test-"))
TEST_DB = _tmp / "test.db"
ADMIN_KEY = "test-admin-key-0123456789abcdef"
os.environ.update({
    "DATABASE_URL": f"sqlite:///{TEST_DB.as_posix()}",
    "ADMIN_API_KEY": ADMIN_KEY,
    "ENVIRONMENT": "test",
    "UPLOAD_DIR": str(_tmp / "uploads"),
    "RATE_LIMIT_PER_MINUTE": "10000",
    "HF_HUB_OFFLINE": os.environ.get("HF_HUB_OFFLINE", "1"),
})


def _migrate(url: str) -> None:
    from alembic import command
    from alembic.config import Config
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")


_migrate(os.environ["DATABASE_URL"])


@pytest.fixture(scope="session")
def app():
    from backend.app.main import app as fastapi_app
    return fastapi_app


@pytest.fixture()
def client(app):
    from fastapi.testclient import TestClient
    from backend.app.security import limiter
    limiter.reset()
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def admin():
    return {"X-API-Key": ADMIN_KEY}


@pytest.fixture()
def db():
    from backend.app.database import SessionLocal
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture(autouse=True)
def _clean_tables():
    """Each test starts from empty data tables (schema is kept)."""
    yield
    import threading
    for t in threading.enumerate():   # let background jobs started by the test finish first
        if t.name.startswith("job-"):
            t.join(timeout=120)
    from sqlalchemy import text
    from backend.app.database import engine
    from backend.app.services import vector_index
    tables = ["collection_events", "document_clusters", "clusters", "document_embeddings", "documents",
              "crawl_pages", "crawl_urls", "source_runs", "collection_campaigns", "processing_jobs",
              "dataset_versions", "sources", "audit_logs", "system_state", "model_versions"]
    with engine.begin() as conn:
        conn.execute(text("PRAGMA foreign_keys=OFF"))
        for t in tables:
            conn.execute(text(f"DELETE FROM {t}"))
        conn.execute(text("PRAGMA foreign_keys=ON"))
    vector_index.invalidate()


def wait_for_job(client, job_id: int, timeout: float = 120.0) -> dict:
    import time
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("completed", "failed"):
            return job
        time.sleep(0.25)
    raise AssertionError(f"job {job_id} did not finish")
