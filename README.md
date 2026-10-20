# Government Welfare Scheme Awareness Gap Miner

Collects public text about Indian government welfare schemes (imported datasets and permitted
public web sources), runs it through a traceable NLP pipeline, and surfaces **recurring
awareness-gap signals**: questions, complaints and comments indicating that people lack or
misunderstand scheme information.

> Results describe the analysed text only. They are not estimates of population-wide awareness.

## What it does

| Area | Implementation |
|---|---|
| **Dataset workspace** | CSV/JSON upload with preview and column mapping → validation → normalization → PII redaction → exact and near-duplicate detection → NLP → embeddings → clustering. Manual labels are kept as ground truth; model predictions are stored alongside. |
| **Live collection workspace** | Curated source registry → collection jobs run by a worker → SSRF-safe fetching (robots.txt, rate limits, retries, size and type limits) → HTML/RSS/sitemap/PDF/JSON/CSV extraction → the same ingest and NLP pipeline. Progress is streamed live over Server-Sent Events. |
| **NLP** | Word-boundary multi-scheme detection (15 schemes); language detection; intent, awareness-gap and gap-type classifiers on a **multilingual** embedding model (English, Hindi, romanized Hindi), with a narrow uncertainty band, an out-of-distribution guard and nearest-labelled-example evidence; HDBSCAN semantic clustering; semantic search. |
| **Timestamps** | `source_published_at` / `source_updated_at` come only from the source. `first_seen_at`, `collected_at` and `processed_at` are system times. A missing publication date stays empty and is shown as "Publication date unavailable". |
| **Analytics** | Workspace-scoped dashboards with explicit denominators, scheme and state breakdowns, timeline, clusters, data-quality report, filtered CSV/JSON export. |
| **Corrections** | Every record is labelled by the models; an operator can still correct a record's labels from its page, and corrections survive reprocessing. |
| **Security** | Operator API key for all write, collection and admin endpoints (no default credential), rate limiting, upload limits, SSRF protection, PII redaction, and an audit trail. |

Documentation:
- [Architecture & data model](docs/ARCHITECTURE.md)
- [NLP pipeline](docs/NLP_PIPELINE.md)
- [Data collection & source policy](docs/DATA_COLLECTION.md)
- [Operations, API & security](docs/OPERATIONS.md)
- [Model evaluation](docs/evaluation/EVALUATION.md) (generated)
- [Known limitations](docs/LIMITATIONS.md)
- [Screenshots](docs/screenshots/)

## Quick start (local development)

Requirements: Python 3.11+ (tested on 3.13), Node.js 20.9+ (tested on 22).

```bash
# 1. Python environment
python -m venv venv
venv\Scripts\activate            # Windows   (macOS/Linux: source venv/bin/activate)
pip install -r requirements.txt

# 2. Configuration
cp .env.example .env             # then set ADMIN_API_KEY (see below)
python -c "import secrets; print(secrets.token_urlsafe(32))"

# 3. Frontend dependencies and root tooling
npm install
npm --prefix frontend install

# 4. Database schema, reference data and the labelled dataset
npm run db:migrate               # alembic upgrade head
npm run seed                     # schemes, states, curated sources, labelled dataset (+ NLP processing)

# 5. Run UI (3000) + API (8000) + worker
npm run dev
```

Open http://localhost:3000. The API documentation is at http://localhost:8000/docs.
To upload data, run collection or review records, click **Operator access** and enter `ADMIN_API_KEY`.

The first run downloads the `paraphrase-multilingual-MiniLM-L12-v2` embedding model (~470 MB) from Hugging Face; it needs about 1 GB of free RAM.
After that, `HF_HUB_OFFLINE=1` lets everything run offline.

### Useful commands

| Command | Purpose |
|---|---|
| `npm test` | Backend test suite (pytest, isolated temporary database). |
| `npm run test:frontend` | ESLint, TypeScript and the production build. |
| `npm run train` | Retrain and evaluate the classifiers; writes `data/models/*` and `docs/evaluation/*`. |
| `npm run reprocess` | Re-run NLP on all records (idempotent; manual and reviewed labels are kept). |
| `npm run backup` | Consistent SQLite backup into `backups/`. |
| `python -m backend.app.maintenance --help` | `repair-legacy`, `redact`, `cluster`, `sync-sources`. |

### Docker (PostgreSQL)

```bash
cp .env.example .env     # set ADMIN_API_KEY and POSTGRES_PASSWORD
docker compose up --build
docker compose run --rm api python -m backend.app.seed
```

Compose runs `db` (PostgreSQL 16), `migrate` (Alembic), `api`, `worker` and `web`.

## Repository layout

```
backend/
  app/
    collection/     safe HTTP, robots, extractors, source registry, campaign engine
    nlp/            text processing, schemes, classifiers, embeddings, training
    services/       ingest/process pipeline, analytics, clustering, datasets, jobs, vector index
    routers/        FastAPI endpoints
    models/         SQLAlchemy models
    main.py         FastAPI app;  maintenance.py, seed.py
  migrations/       Alembic migrations
  worker.py         collection + processing worker
frontend/           Next.js 16 app (src/app routes, src/components, src/lib)
data/raw/           labelled training data: original dataset, Hindi / romanized-Hindi translations, AI-annotated live sample
data/models/        versioned model artifacts (joblib + metadata)
docs/               documentation, evaluation report, screenshots
tests/              pytest suite (crawler tests use mock HTTP; no external requests)
```
