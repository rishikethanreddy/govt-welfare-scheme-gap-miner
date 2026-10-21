# Government Welfare Scheme Awareness Gap Miner

Collects public text about Indian government welfare schemes, runs it through an NLP pipeline, and finds **awareness-gap signals**. These are questions, complaints and comments showing that people lack or misunderstand scheme information. The text comes from imported datasets and from permitted public web sources.

> Results describe the analysed text only. They are not estimates of population-wide awareness.

| | |
|---|---|
| **Schemes** | 15 central schemes (PM-KISAN, PMAY, Ayushman Bharat PM-JAY, PMMY/Mudra, MGNREGA, PMFBY, NSAP, PM Vishwakarma, …) |
| **Languages** | English, Hindi (Devanagari), romanized Hindi / Hinglish |
| **Labels per record** | scheme, language, intent, awareness gap (yes / no / unclear / not applicable), gap type, evidence |
| **Stack** | FastAPI · SQLAlchemy · Alembic · sentence-transformers · scikit-learn · HDBSCAN · Next.js 16 · React 19 · Tailwind 4 |

---

## Contents
1. [How it works](#how-it-works)
2. [Requirements](#requirements)
3. [Run it from a fresh clone](#run-it-from-a-fresh-clone)
4. [Configuration (.env)](#configuration-env)
5. [Using the application](#using-the-application)
6. [Getting a data.gov.in API key](#getting-a-datagovin-api-key)
7. [Commands](#commands)
8. [Docker (PostgreSQL)](#docker-postgresql)
9. [Troubleshooting](#troubleshooting)
10. [Project structure](#project-structure)
11. [Models and evaluation](#models-and-evaluation)
12. [Limitations](#limitations)
13. [Team](#team)

---

## How it works

```
 Inputs                  Collection (worker)          Ingest pipeline                   Store / serve
 Public web pages  ──┐   SafeFetcher: SSRF guard,      validate + normalise              Database
 (RSS, comments,     ├─► robots.txt, rate limit,  ──►  PII redaction               ──►   (SQLite / PostgreSQL)
  FAQs, PDFs)        │   5 MB cap                      exact + near-duplicate check         │
 Kisan Call Centre ──┘   Extractors: comments, FAQ,    multilingual embedding               ▼
 (data.gov.in API)       RSS, PDF, JSON/CSV            NLP: scheme, language, intent,    FastAPI (REST + SSE)
 Dataset upload ──────── via the UI / API ──────────►  gap, gap type, evidence              │
 (CSV / JSON)                                          HDBSCAN clustering                   ▼
                                                                                         Next.js dashboard
```

* **One pipeline.** Uploaded datasets and collected text go through the same `backend/app/services/pipeline.py`. They are kept in separate workspaces (`dataset` and `live`).
* **NLP.**
  * Every record is embedded with `paraphrase-multilingual-MiniLM-L12-v2`, giving a 384-dimensional vector.
  * Intent, awareness gap and gap type are predicted by logistic-regression classifiers. They work on TF-IDF n-grams, on the embeddings, or on a soft-voting ensemble of the two.
  * A gap is decided only when the model is confident (≥ 0.55) and the text resembles the labelled training data (cosine ≥ 0.423). Otherwise the record is marked **unclear**.
  * Every label stores its three nearest labelled examples as evidence.
* **Collection** runs in a separate worker process. Progress is streamed live to the browser over Server-Sent Events.

More detail is in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), [docs/NLP_PIPELINE.md](docs/NLP_PIPELINE.md) and [docs/DATA_COLLECTION.md](docs/DATA_COLLECTION.md).

---

## Requirements

| Tool | Version | Check with |
|---|---|---|
| Python | 3.11 or newer (tested on 3.13) | `python --version` |
| Node.js | 20.9 or newer (tested on 22) | `node --version` |
| Git | any | `git --version` |
| Free RAM | about **1 GB** for the embedding model | |
| Disk | about 2 GB (Python packages + model download) | |
| Internet | needed on first run to download the embedding model (~470 MB) | |

Works on Windows, macOS and Linux.

---

## Run it from a fresh clone

### 1. Clone

```bash
git clone https://github.com/rishikethanreddy/govt-welfare-scheme-gap-miner.git
cd govt-welfare-scheme-gap-miner
```

### 2. Python virtual environment and packages

**Windows (PowerShell)**
```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1      # if blocked: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
pip install -r requirements.txt
```

**macOS / Linux**
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

The folder must be named `venv`. The npm scripts look for `venv/` and use its Python automatically, so you don't need to activate it every time you use `npm run …`.

### 3. Configuration

```bash
copy .env.example .env      # Windows
cp .env.example .env        # macOS / Linux
```

Open `.env` and set at least `ADMIN_API_KEY`. Without it, uploads and collection are disabled. Generate a key with:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Paste the output after `ADMIN_API_KEY=`. Optional: set `DATA_GOV_IN_API_KEY` ([how to get one](#getting-a-datagovin-api-key)).

### 4. Node packages

```bash
npm install
npm --prefix frontend install
```

### 5. Database and initial data

```bash
npm run db:migrate     # create the database schema (SQLite file welfare_awareness.db)
npm run seed           # schemes, states, curated sources and the labelled dataset (+ NLP processing)
```

The first `seed` downloads the embedding model from Hugging Face, so it takes a few minutes.

### 6. Start

```bash
npm run dev
```

This starts three processes:

| Process | Address |
|---|---|
| UI (Next.js) | http://localhost:3000 |
| API (FastAPI) | http://localhost:8000 (interactive docs at http://localhost:8000/docs) |
| Worker | runs collection jobs in the background |

Open **http://localhost:3000**. Wait a few seconds after startup for the NLP model to load before using the text analyzer. Stop everything with **Ctrl+C**.

> **Shortcut:** once Python and Node are installed and `.env` exists, `npm run setup` performs steps 2 (package install only, the `venv` folder must already exist), 4 and 5 in one go.

---

## Configuration (.env)

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./welfare_awareness.db` | Database. Use a `postgresql+psycopg2://…` URL for PostgreSQL. |
| `ADMIN_API_KEY` | *(empty)* | Operator key for uploads, collection and source management. Empty = those actions are disabled. |
| `DATA_GOV_IN_API_KEY` | *(empty)* | Enables the Kisan Call Centre source. |
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000` | API address used by the UI. If you change it, also put it in `frontend/.env.local` and rebuild the UI. |
| `CORS_ORIGINS` | `http://localhost:3000,…` | Browser origins allowed to call the API. |
| `EMBEDDING_MODEL` | `paraphrase-multilingual-MiniLM-L12-v2` | Must match the model the classifiers were trained with. |
| `NEAR_DUPLICATE_THRESHOLD` | `0.96` | Cosine similarity above which a record is a near-duplicate. |
| `SCRAPER_DEFAULT_DELAY` | `2.0` | Minimum seconds between requests to the same host. |
| `MAX_UPLOAD_SIZE_MB` / `MAX_UPLOAD_ROWS` | `20` / `50000` | Upload limits. |

**Never commit `.env`.** It is already listed in `.gitignore`.

---

## Using the application

1. **Unlock operator actions.** Click **Operator access** (top right) and paste your `ADMIN_API_KEY`. Viewing works without it.
2. **Dataset workspace** (*Dataset intelligence* in the left menu):
   * **Import & history**: upload a CSV/JSON file, preview it and map columns. Text is required; scheme, state, date and labels are optional.
   * **Analytics**, **Records**, **Semantic clusters** and **Geography** show the processed data.
3. **Live collection** (*Live collection* in the left menu):
   * **Source registry** lists the curated sources and their policy status.
   * **Collection jobs**: start a job, then follow it in **Live monitor**.
   * **Analytics**, **Records** and **Semantic clusters** cover the collected data.
4. **Analysis**:
   * **Text analyzer** labels any text you type (nothing is stored).
   * **Semantic search** finds records by meaning.
   * **Schemes** has per-scheme views.
   * **Models & evaluation** shows the test metrics.
5. **Correct a label.** Open any record and use *Correct labels*. Corrections survive reprocessing.

A fresh clone has **no collected (live) data**, because the database is not committed. Run a collection job to fill the live workspace. The dataset workspace is filled by `npm run seed`.

---

## Getting a data.gov.in API key

This key is needed only for the Kisan Call Centre source.

1. Go to https://data.gov.in and sign up or log in.
2. Open **My Account** and copy the **API key** shown there.
3. Put it in `.env`: `DATA_GOV_IN_API_KEY=your_key_here`.
4. Update the source registry:
   ```bash
   .\venv\Scripts\python.exe -m backend.app.maintenance sync-sources     # Windows
   venv/bin/python -m backend.app.maintenance sync-sources               # macOS / Linux
   ```
5. **Restart** `npm run dev`. The worker reads `.env` only when it starts.
6. In **Collection jobs**, start a job that includes *Kisan Call Centre query logs*.

The source uses resource `cef25fe2-9231-4128-8aec-2c948fedd43f`, filtered to `QueryType = Government Schemes`. The key is added only at request time and is never stored or logged.

---

## Commands

| Command | What it does |
|---|---|
| `npm run setup` | Install Python + Node packages, migrate, seed |
| `npm run dev` | Start UI, API and worker together |
| `npm run db:migrate` | Apply database migrations (`alembic upgrade head`) |
| `npm run seed` | Load schemes, states, sources and the labelled dataset |
| `npm test` | Backend tests (pytest, isolated temporary database, no network) |
| `npm run test:frontend` | Frontend lint, type check and production build |
| `npm run check` | Both of the above |
| `npm run train` | Retrain the classifiers; writes `data/models/*` and `docs/evaluation/EVALUATION.md` |
| `npm run reprocess` | Re-run NLP on all stored records (manual labels are kept) |
| `npm run backup` | Copy the SQLite database into `backups/` |
| `python -m backend.app.maintenance --help` | Maintenance tasks: `sync-sources`, `cluster`, `redact`, `repair-legacy` |

Run `python -m …` commands with the venv's Python: `.\venv\Scripts\python.exe` on Windows, `venv/bin/python` on macOS/Linux. Alternatively, activate the venv first.

---

## Docker (PostgreSQL)

```bash
cp .env.example .env        # set ADMIN_API_KEY and POSTGRES_PASSWORD
docker compose up --build
docker compose run --rm api python -m backend.app.seed
```

Services: `db` (PostgreSQL 16), `migrate`, `api`, `worker`, `web`. This configuration is provided, but it was not run end to end during development. The tested path is the SQLite setup above.

---

## Troubleshooting

| Problem | Cause and fix |
|---|---|
| `[WinError 10013]` or `address already in use` on port 8000 / 3000 | Another program is using the port. Find it with `netstat -ano \| findstr :8000` (Windows) or `lsof -i :8000` (macOS/Linux) and stop it. |
| `ModuleNotFoundError: No module named 'pydantic_settings'` (or similar) | You ran the system Python. Use the venv (`.\venv\Scripts\python.exe -m …`) or activate it. |
| `npm run …` does not use the venv | The folder must be named exactly `venv` and sit in the project root. |
| First start is slow, or the analyzer waits | The embedding model is downloading (first run) or loading (each start). Wait until the API log shows `NLP models loaded`. |
| Process crashes / out-of-memory | The model needs ~1 GB of free RAM. Close other heavy applications. |
| Upload or collection buttons are disabled | `ADMIN_API_KEY` is empty, or you have not entered it under **Operator access**. |
| Kisan Call Centre job fails with "DATA_GOV_IN_API_KEY is not set" | Add the key to `.env` and **restart** `npm run dev`. |
| A source shows *paused* | It failed 3 runs in a row. Fix the cause, then re-enable it in the Source registry. |
| Some official portals fail (403, TLS error, timeout) | Expected. Those sites block automated access, have broken certificates or need JavaScript. The failure is recorded, never bypassed. |
| `Database schema is at … but code expects …` | Run `npm run db:migrate`. |
| Working offline after the first run | Set `HF_HUB_OFFLINE=1` so the cached model is used without contacting Hugging Face. |

---

## Project structure

```
backend/
  app/
    collection/     safe HTTP, robots.txt, extractors, source registry, collection engine
    nlp/            text cleaning, language + scheme detection, classifiers, embeddings, training
    services/       ingest/NLP pipeline, analytics, clustering, dataset import, jobs, vector index
    routers/        FastAPI endpoints
    models/         SQLAlchemy models
    main.py         FastAPI app;  seed.py, maintenance.py
  migrations/       Alembic migrations
  worker.py         collection + background-processing worker
frontend/           Next.js app (src/app = pages, src/components, src/lib)
data/raw/           labelled training data (original, Hindi and romanized-Hindi translations, live sample)
data/models/        trained, versioned model artifacts
docs/               architecture, NLP, data collection, operations, limitations, evaluation, screenshots
reports/            project report (PDF / DOCX) and its figures
scripts/            cross-platform Python runner used by the npm scripts
tests/              pytest suite
```

---

## Models and evaluation

These are held-out test results from `npm run train`. The full report is in [docs/evaluation/EVALUATION.md](docs/evaluation/EVALUATION.md).

| Task | Selected model | Test macro-F1 | Majority baseline |
|---|---|---|---|
| Awareness gap | Embedding + logistic regression | 0.65 | 0.34 |
| Intent (8 classes) | TF-IDF + embedding ensemble | 0.43 | 0.05 |
| Gap type (7 classes) | TF-IDF + embedding ensemble | 0.35 | 0.08 |

The training data consists of:
* 127 manually labelled English records;
* their Hindi and romanized-Hindi translations;
* 252 labelled live comments.

The translations and the live labels were produced with AI assistance.

---

## Limitations

* The labelled data set is small and partly AI-assisted. Intent and gap-type predictions are indicative.
* Scheme detection is rule-based, so state schemes appear as *Other / Unknown*.
* Location is used only when a source states it, mainly Kisan Call Centre records. Most web comments have no location.
* Personal names in public comments may not be removed. Phone, Aadhaar, PAN, e-mail and PIN codes are.
* Vector search is brute force, which is fine for thousands of records but not millions.

See [docs/LIMITATIONS.md](docs/LIMITATIONS.md).

---

## Team

Rishi Kethan Reddy · Sanjai · Abid · Purna

Natural Language Processing and Computational Linguistics (CSI4001), VIT Vellore, Fall Semester 2026-27.
