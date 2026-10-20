"""
Application configuration using Pydantic Settings.

All configuration is driven by environment variables (loaded from .env).
Never hard-code credentials or secrets.
"""

import os
from pathlib import Path
from functools import lru_cache
from pydantic_settings import BaseSettings
from pydantic import Field, computed_field

# Project root is two levels up from this file: backend/app/config.py -> NLP/
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    """Application settings, loaded from environment variables."""

    # ── Environment ───────────────────────────────────────────────────────
    ENVIRONMENT: str = Field(default="development", description="development | test | production")
    DEBUG: bool = Field(default=False)
    SQL_ECHO: bool = Field(default=False, description="Log every SQL statement (very verbose)")
    APP_NAME: str = Field(default="Welfare Awareness Gap Miner")
    APP_VERSION: str = Field(default="0.1.0")

    # ── Database ──────────────────────────────────────────────────────────
    # Primary: PostgreSQL via DATABASE_URL
    # Fallback: SQLite for local development if DATABASE_URL is not set
    DATABASE_URL: str = Field(
        default="sqlite:///./welfare_awareness.db",
        description="PostgreSQL connection string (or SQLite for dev fallback)"
    )

    # ── Security ──────────────────────────────────────────────────────────
    ADMIN_API_KEY: str = Field(
        default="",
        description=(
            "Key required (X-API-Key header) for write, collection and admin endpoints. "
            "There is no default: when unset, protected endpoints are disabled (HTTP 503)."
        ),
    )
    RATE_LIMIT_PER_MINUTE: int = Field(default=120, description="Per-client limit for write/compute endpoints")

    # ── CORS ──────────────────────────────────────────────────────────────
    CORS_ORIGINS: str = Field(
        default="http://localhost:3000,http://127.0.0.1:3000",
        description="Comma-separated allowed origins"
    )

    # ── Frontend ──────────────────────────────────────────────────────────
    NEXT_PUBLIC_API_URL: str = Field(
        default="http://localhost:8000",
        description="Backend URL as seen by the frontend"
    )

    # ── NLP ───────────────────────────────────────────────────────────────
    EMBEDDING_MODEL: str = Field(
        default="paraphrase-multilingual-MiniLM-L12-v2",
        description="SentenceTransformer model name"
    )
    EMBEDDING_DIMENSION: int = Field(default=384)
    NLP_BATCH_SIZE: int = Field(default=64)
    NEAR_DUPLICATE_THRESHOLD: float = Field(
        default=0.96, description="Cosine similarity at or above which a record is a near-duplicate")
    SIMILARITY_SEARCH_MIN: float = Field(default=0.35, description="Minimum cosine similarity for 'similar records'")
    CLUSTER_MIN_SIZE: int = Field(default=0, description="HDBSCAN min_cluster_size; 0 = derive from corpus size")

    # ── File uploads ──────────────────────────────────────────────────────
    MAX_UPLOAD_SIZE_MB: int = Field(default=20)
    MAX_UPLOAD_ROWS: int = Field(default=50000)
    UPLOAD_DIR: str = Field(default="data/uploads")
    ALLOWED_EXTENSIONS: str = Field(default=".csv,.json")

    # ── Collection ────────────────────────────────────────────────────────
    SCRAPER_USER_AGENT: str = Field(
        default="WelfareAwarenessResearchBot/1.0 (+academic research; respects robots.txt)",
        description="User-Agent for web collection requests"
    )
    SCRAPER_DEFAULT_DELAY: float = Field(default=2.0, description="Minimum seconds between requests to one host")
    SCRAPER_DEFAULT_TIMEOUT: int = Field(default=20, description="Request timeout in seconds")
    SCRAPER_MAX_RETRIES: int = Field(default=2)
    SCRAPER_MAX_BYTES: int = Field(default=5 * 1024 * 1024, description="Maximum response body size")
    COLLECTION_SOURCE_CONCURRENCY: int = Field(default=2, description="Sources collected in parallel")
    SOURCE_FAILURE_PAUSE_THRESHOLD: int = Field(
        default=3, description="Consecutive failed runs after which a source is paused automatically")
    AUTOPILOT_INTERVAL_HOURS: float = Field(default=12.0, description="Minimum hours between scheduled campaigns")
    DATA_GOV_IN_API_KEY: str = Field(default="", description="API key for api.data.gov.in (optional)")

    # ── Paths ─────────────────────────────────────────────────────────────
    DATA_DIR: str = Field(default="data")
    MODELS_DIR: str = Field(default="data/models")
    LOGS_DIR: str = Field(default="logs")

    @computed_field
    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]

    @computed_field
    @property
    def allowed_extension_list(self) -> list[str]:
        return [ext.strip() for ext in self.ALLOWED_EXTENSIONS.split(",") if ext.strip()]

    @computed_field
    @property
    def is_sqlite(self) -> bool:
        return self.DATABASE_URL.startswith("sqlite")

    @computed_field
    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"

    def startup_problems(self) -> list[str]:
        """Configuration errors that must stop a production start."""
        problems = []
        if self.is_production:
            if len(self.ADMIN_API_KEY) < 24:
                problems.append("ADMIN_API_KEY must be set to a random value of at least 24 characters in production")
            if any(o.strip() == "*" for o in self.cors_origin_list):
                problems.append("CORS_ORIGINS must list explicit origins in production")
            if self.is_sqlite:
                problems.append("SQLite is for development; set DATABASE_URL to PostgreSQL in production")
        if not 0 < self.NEAR_DUPLICATE_THRESHOLD <= 1:
            problems.append("NEAR_DUPLICATE_THRESHOLD must be in (0, 1]")
        return problems

    model_config = {
        "env_file": str(PROJECT_ROOT / ".env"),
        "env_file_encoding": "utf-8",
        "case_sensitive": True,
        "extra": "ignore",
    }


@lru_cache()
def get_settings() -> Settings:
    """Cached settings singleton."""
    return Settings()
