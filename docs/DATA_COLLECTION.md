# Data collection & source policy

## Principles

* Collect only from public pages that robots.txt permits for our user agent
  (`WelfareAwarenessResearchBot/1.0`). Never bypass logins, CAPTCHAs, paywalls or anti-bot
  measures. A 401/403/451 response is recorded as **blocked**, not retried around.
* No headless browser. Sites whose content requires JavaScript are marked `unsupported`.
* Every source records why it is (or is not) collected (`policy_status` + `policy_note`).
  `verification_status` changes only as a result of real runs:
  `configured → reachable → collected`, or `failing` / `blocked`.
* No fabricated records, dates or counts. The former demo scraper that replayed a
  hand-written JSON file as "live" data was removed, and its 4 records are flagged `is_demo`
  and excluded from analytics.

## Source registry (`backend/app/collection/registry.py`)

| Policy | Meaning | Examples |
|---|---|---|
| `allowed` | collected when enabled | SarkariYojana RSS + scheme guides (reader comments), Down To Earth and Gaon Connection sitemaps, Krishi Jagran, Vikaspedia, official scheme portals |
| `credentials_required` | official API whose key is not configured (becomes `allowed` once `DATA_GOV_IN_API_KEY` is set) | Kisan Call Centre query logs (data.gov.in OGD API) |
| `unsupported` | content rendered client-side | MyScheme.gov.in, PMFBY portal |
| `manual_review` | terms restrict automated reuse; not collected | commercial news topic pages |
| `blocked` | login wall or terms prohibit scraping | Quora |
| `paused` | circuit breaker after 3 consecutive failed runs | (set automatically) |
| `retired` | superseded legacy registrations, kept for provenance | 56 legacy rows |

Operators can register additional sources in the UI. New sources start **disabled**; their URL
is SSRF-checked and their robots.txt is evaluated, and the operator enables them after
reviewing the site's terms.

### Observed source status (verification jobs #548 and #550, 5 and 3 pages per source)

| Source | Outcome |
|---|---|
| Kisan Call Centre (data.gov.in API, job #550) | collected: 195 government-scheme calls from 3 pages, with state, district and call time from the dataset |
| SarkariYojana RSS / scheme guides | collected (reader comments with their own timestamps) |
| PM Jan Dhan, MGNREGA, Vikaspedia, Down To Earth, Gaon Connection | reachable; no scheme-relevant records within the budget |
| PM Vishwakarma | collected; one 11 MB page refused by the 5 MB limit |
| PIB | HTTP 403 for automated requests → blocked |
| PM-KISAN, Mudra | TLS certificate chain incomplete → robots.txt unreachable → not fetched |
| PM-JAY | timeouts → robots.txt unreachable → not fetched |
| NSAP | DNS resolution failed |
| Krishi Jagran (old seed) | HTTP 404 → seed moved to the site root |

TLS verification is never disabled to work around misconfigured government certificates.

## Collection engine (`backend/app/collection/`)

* **Safe fetching** (`safe_http.py`): http/https only, ports 80/443, no credentials in URLs, no
  `localhost` / `*.local` / `*.internal`. Every resolved address must be globally routable.
  Each redirect hop is re-validated, the connected peer IP is checked (DNS-rebinding defence),
  and environment proxies are ignored. Responses are streamed and cut at 5 MB, and the content
  type is whitelisted. Retries use exponential backoff with jitter on timeouts, connection
  errors, 408/425/429/5xx, honouring `Retry-After` (capped at 60 s).
* **Politeness**: per-host spacing of at least `SCRAPER_DEFAULT_DELAY` (2 s) or robots
  `Crawl-delay`, at most 2 sources in parallel, and per-source and per-campaign page budgets.
* **robots.txt** (`robots.py`) follows RFC 9309: 4xx means allow, 5xx or unreachable means
  disallow. Disallowed links are never queued.
* **Discovery**: RSS/Atom entries, sitemaps and sitemap indexes (relevance-filtered, most
  recent first), `rel=next` / pagination containers, and same-site welfare-related links up to
  `max_depth`. URL guessing (`?page=N`) was removed.
* **Extraction** (`extractors.py`): WordPress-style comments (each with its own
  `<time datetime>`; post-author replies are tagged `site_reply`), FAQ entries (JSON-LD
  `FAQPage`, `<details>`, `<dl>`, question headings), article summaries, feed entries, PDF FAQs
  (`pypdf`), JSON APIs and CSV (field maps).
* **Relevance**: a record is kept only if it names a scheme, or is a comment on a page about a
  scheme.
* **Incremental collection**: conditional requests (ETag / Last-Modified) and content hashes.
  Unchanged pages are not re-extracted, but links from an unchanged feed are re-checked, so new
  comments on old articles are still found.
* **Frontier and resumability**: `crawl_urls` (canonical-URL dedup per campaign). Raw responses
  are kept zlib-compressed in `crawl_pages` for reprocessing.

## Timestamps

| Field | Meaning | Source |
|---|---|---|
| `source_published_at` | when the source says the text was published | comment `<time>`, JSON-LD `datePublished`, `article:published_time`, RSS `pubDate`, PDF `CreationDate`, dataset column |
| `source_updated_at` | source's last-modified time | JSON-LD `dateModified`, `article:modified_time`, RSS `updated` |
| `first_seen_at` | first time this system stored the content | system |
| `collected_at` | when this copy was retrieved | system |
| `processed_at` | when NLP last completed | system |
| `started_at` / `finished_at` on a campaign | real crawl execution window | system |

Offsets are converted to UTC. Timestamps without an offset are interpreted as IST, and the
assumption is recorded in `crawl_pages.date_source`. Dates before 1990 or in the future are
rejected. A missing date stays `NULL` and the UI shows "Publication date unavailable"; crawl
time is never substituted. Example from job #547: a comment collected on 2026-10-18 keeps its
stated publication date of 2017-01-24.

## Geography

State and district are stored only when a source states them explicitly (a dataset column or
an official API field). They are normalized against the list of 36 states and UTs, with
aliases such as Orissa → Odisha. Nothing is inferred from names, language or the website's
own location. Web comments therefore have no location, and the analytics report that as
coverage rather than guessing.

## Kisan Call Centre (data.gov.in)

* Resource `cef25fe2-9231-4128-8aec-2c948fedd43f` ("Kisan Call Centre (KCC) – Transcripts of farmers
  queries & answers"), filtered server-side with `filters[QueryType]=Government Schemes`.
* Field map: `QueryText` → text, `StateName` → state, `DistrictName` → district, `CreatedOn` → call
  time (stated without an offset; IST assumed), `KCCCallID` → record id.
* Each call is one record, deduplicated by `KCCCallID`, not by text: identical operator summaries
  from different calls are different events and are all counted.
* The API key is read from `DATA_GOV_IN_API_KEY`, added only at request time and never stored
  or logged. If it is missing, a job fails immediately with an explicit message rather than
  sending unauthenticated requests. Restart the worker after editing `.env`.
