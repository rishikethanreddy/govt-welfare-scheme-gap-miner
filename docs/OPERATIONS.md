# Operations, API & security

## Processes

| Process | Command | Notes |
|---|---|---|
| API | `uvicorn backend.app.main:app --port 8000` | Refuses to start in production with an unsafe configuration (no or short `ADMIN_API_KEY`, wildcard CORS, SQLite). Logs an error if the schema is not at the Alembic head. |
| Worker | `python -m backend.worker` | Runs queued collection jobs one at a time, resumes interrupted ones, runs pending processing jobs, processes stragglers, runs the scheduler, writes a heartbeat every 10 s, and prunes events older than 30 days. Stop with Ctrl+C / SIGTERM; the current step finishes. |
| UI | `npm --prefix frontend run build && npm --prefix frontend start` | `NEXT_PUBLIC_API_URL` is compiled into the bundle. |

Run exactly **one** worker per database. The scheduler ("autopilot", off by default) queues a
campaign for sources whose `schedule` is daily or weekly and that are due, at most every
`AUTOPILOT_INTERVAL_HOURS`, and never while another campaign is active.

### Persistence

* Database: `DATABASE_URL`. SQLite (WAL mode, 30 s busy timeout) for development; PostgreSQL
  for production. Schema: `alembic upgrade head`.
* `data/models/`: versioned model artifacts (committed; reproducible with `npm run train`).
* `data/uploads/`: stored copies of uploaded files (random file names).
* The Hugging Face cache holds the embedding model (downloaded on first use).
* Backups: `npm run backup` (SQLite online backup API) or `pg_dump`.

### Migrating an existing pre-0002 database

```bash
python -m backend.app.maintenance backup
alembic stamp 0001            # the existing schema equals the baseline
alembic upgrade head
python -m backend.app.maintenance repair-legacy
python -m backend.app.nlp.training
python -m backend.app.maintenance reprocess
```

`repair-legacy` deletes nothing. It archives never-executed campaigns, flags demo fixtures,
assigns text roles from the old extraction labels, recovers source-stated dates, redacts PII,
recomputes duplicates, clears labels produced by the removed question-mark heuristic, keeps
manual dataset labels, and syncs the curated source registry. All changes are written to the
audit log.

## Security

* **Authentication**: `ADMIN_API_KEY`, sent as `X-API-Key`, compared in constant time. It
  protects uploads and previews, collection jobs, the scheduler, source management, review,
  reprocessing and clustering. With no key configured, these endpoints return 503; there is no
  default credential. Read-only analytics are public by design.
  The UI never embeds the key: an operator types it in, and it stays in `sessionStorage` for
  that browser session only.
* **Rate limiting**: sliding window per client and path (`RATE_LIMIT_PER_MINUTE`) on protected
  and compute endpoints (`/api/analyze`).
* **Request limits**: 1 MB bodies in general and `MAX_UPLOAD_SIZE_MB` for uploads (checked on
  the declared length and while streaming), plus `MAX_UPLOAD_ROWS`. Uploaded file names are
  never used as paths.
* **SSRF**: see [DATA_COLLECTION.md](DATA_COLLECTION.md). This also applies to
  operator-registered sources and the "Test fetch" action.
* **SQL**: SQLAlchemy ORM and bound parameters throughout; sort columns are whitelisted.
* **Errors and logs**: unhandled errors return a generic message plus a request id. Request
  logs contain method, path, status and duration, never query strings or bodies. The
  data.gov.in API key is added only at request time and is redacted from stored errors.
* **Privacy**: PII redaction before storage. Location is never inferred.
* **HTTP headers (UI)**: `X-Content-Type-Options`, `X-Frame-Options: DENY`, `Referrer-Policy`.
* **CORS**: explicit origins and methods; only `Content-Type` and `X-API-Key` request headers.

## API overview

Interactive documentation (generated from the code): `http://localhost:8000/docs`.
🔒 = requires `X-API-Key`.

| Area | Endpoints |
|---|---|
| Health | `GET /api/health` (database, migration revision, models, worker), `GET /api/system/summary`, `GET /api/system/audit-logs`, `GET /api/auth/check` 🔒 |
| Analytics | `GET /api/analytics/{overview, schemes, timeline, geography, filters, data-quality, definitions}`, `GET /api/analytics/distribution/{dimension}`, `GET /api/analytics/breakdown/{dimension}`. All accept `scope=dataset\|live\|all` plus the shared filters. |
| Records | `GET /api/documents` (filter, sort, paginate), `GET /api/documents/export?fmt=csv\|json`, `GET /api/documents/{id}`, `GET /api/documents/{id}/similar`, `PATCH /api/documents/{id}/review` 🔒 |
| Search & NLP | `POST /api/search/semantic`, `POST /api/analyze` (rate-limited) |
| Clusters | `GET /api/clusters?scope=`, `GET /api/clusters/{id}`, `POST /api/clusters/run` 🔒 |
| Datasets & jobs | `POST /api/datasets/preview` 🔒, `POST /api/datasets/upload` 🔒, `GET /api/datasets`, `GET /api/datasets/{id}`, `POST /api/datasets/{id}/reprocess` 🔒, `GET /api/jobs`, `GET /api/jobs/{id}`, `POST /api/jobs/reprocess` 🔒 |
| Sources | `GET /api/sources`, `POST /api/sources` 🔒, `GET/PATCH /api/sources/{id}` (PATCH 🔒), `GET /api/sources/{id}/runs`, `POST /api/sources/sync` 🔒, `POST /api/sources/{id}/check` 🔒 |
| Collection | `POST /api/collection/campaigns` 🔒, `GET /api/collection/campaigns`, `GET /api/collection/campaigns/{id}`, `…/{id}/events`, `…/{id}/urls`, `POST …/{id}/cancel` 🔒, `POST …/{id}/retry-failed` 🔒, `GET /api/collection/status`, `POST /api/collection/autopilot` 🔒, `GET /api/collection/feed` |
| Live (SSE) | `GET /api/collection/stream`, `GET /api/collection/campaigns/{id}/stream`. Events: `status`, `campaign`, `log`, `record`, `end`, `reconnect`. Resume with `after_event` / `after_record`. |
| Models | `GET /api/models`, `GET /api/models/status`, `GET /api/models/evaluation/{task}` |
| Schemes | `GET /api/schemes`, `GET /api/schemes/{code}?scope=` |

## Testing

```bash
npm test                 # 131 pytest tests: fresh migrated DB per session, mock HTTP for crawler tests
npm run test:frontend    # eslint + tsc + next build
```

Crawler tests serve a fake website through `httpx.MockTransport` and inject a resolver, so no
external site is contacted. The suite covers:
- SSRF (private, loopback, metadata, IPv4-mapped IPv6 and rebinding hosts, unsafe redirects)
- robots semantics, retries, size and type limits
- extraction and dates (including missing dates)
- ingestion (validation, PII, exact and near duplicates, timestamps)
- NLP rules (question mark invariance, roles, language, out-of-distribution input, uncertainty band)
- idempotent reprocessing, manual-label preservation
- end-to-end collection (failures, robots-disallowed links, duplicates, unchanged re-runs, timestamp integrity)
- authorization on every protected endpoint
- upload → job → analytics workflow, re-import refusal, exports, review and audit, semantic search
- the SSE stream, request size limits
- migrations (up → down → up; models equal migrations), clustering
