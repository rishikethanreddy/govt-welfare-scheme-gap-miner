"""
FastAPI application.

Run with: uvicorn backend.app.main:app
The schema must be migrated first: alembic upgrade head (npm run db:migrate).
"""

import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.config import get_settings
from backend.app.middleware.error_handler import ErrorHandlerMiddleware, RequestLoggingMiddleware
from backend.app.routers import (analytics, analyze, clusters, collection, datasets, documents, models_api,
                                 schemes, sources, system)
from backend.app.security import BodySizeLimitMiddleware

settings = get_settings()

logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    problems = settings.startup_problems()
    if problems:
        for p in problems:
            logger.error("Configuration error: %s", p)
        if settings.is_production:
            sys.exit("Refusing to start with an unsafe production configuration.")
    if not settings.ADMIN_API_KEY:
        logger.warning("ADMIN_API_KEY is not set: uploads, collection and review endpoints are disabled.")
    from backend.app.database import SessionLocal
    from backend.app.routers.system import migration_state
    db = SessionLocal()
    try:
        mig = migration_state(db)
        if not mig["up_to_date"]:
            logger.error("Database schema is at %s but code expects %s. Run: alembic upgrade head",
                         mig["current"], mig["head"])
        # Jobs interrupted by a previous shutdown are re-queued for the worker.
        from backend.app.models.processing import ProcessingJob
        db.query(ProcessingJob).filter(ProcessingJob.status == "running").update({"status": "pending"})
        db.commit()
    except Exception as e:
        logger.error("Startup database check failed: %s", e)
    finally:
        db.close()
    logger.info("%s v%s started (%s, %s)", settings.APP_NAME, settings.APP_VERSION, settings.ENVIRONMENT,
                "SQLite" if settings.is_sqlite else "PostgreSQL")
    if settings.ENVIRONMENT != "test":
        # Load the embedding model and labelled reference set in the background so the
        # first analysis request does not wait for it.
        import threading

        def _warm_up():
            try:
                from backend.app.nlp.service import get_nlp_service
                get_nlp_service().analyze("PM-KISAN warm-up", "query")
                logger.info("NLP models loaded")
            except Exception as e:
                logger.warning("NLP warm-up failed: %s", e)

        threading.Thread(target=_warm_up, name="nlp-warmup", daemon=True).start()
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="Government Welfare Scheme Awareness Gap Miner",
        description=(
            "Collects and analyses public text about Indian welfare schemes and surfaces recurring "
            "awareness-gap *signals* in the analysed records. Figures describe the stored text only; "
            "they are not estimates of population-wide awareness.\n\n"
            "Write, collection and admin endpoints require the `X-API-Key` header."
        ),
        version=settings.APP_VERSION,
        lifespan=lifespan,
    )
    app.add_middleware(ErrorHandlerMiddleware)
    app.add_middleware(RequestLoggingMiddleware)
    app.add_middleware(BodySizeLimitMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
        allow_headers=["Content-Type", "X-API-Key"],
        expose_headers=["Content-Disposition", "X-Request-ID"],
    )
    for r in (system.router, analytics.router, documents.router, documents.search_router, clusters.router,
              schemes.router, datasets.router, datasets.jobs_router, sources.router, collection.router,
              analyze.router, models_api.router):
        app.include_router(r)

    @app.get("/", include_in_schema=False)
    def root():
        return {"name": settings.APP_NAME, "version": settings.APP_VERSION, "docs": "/docs", "health": "/api/health"}

    return app


app = create_app()
