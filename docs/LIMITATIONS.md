# Known limitations

These are stated plainly so that results are not over-read.

## Data and evaluation
* **Small labelled corpus.** 127 manually labelled English records (29 of them synthetic
  augmentations from the original dataset), their Hindi and romanized-Hindi translations, and 252
  AI-annotated live comments. There is no inter-annotator agreement measurement.
* **Not all labels are human.** The translations were produced by an AI assistant (labels inherited
  from the original record). The live comments were labelled by an AI assistant following the
  documented guidelines. Results on these slices measure agreement with those labels, not with
  independent human judgement.
* Held-out test results (macro-F1; full report in `docs/evaluation/EVALUATION.md`):

  | Task | All test records | Original English | Hindi | Romanized Hindi | Live (AI-annotated) | Majority baseline |
  |---|---|---|---|---|---|---|
  | Awareness gap | 0.65 (n=101) | 0.53 | 0.74 | 0.56 | 0.61 | 0.34 |
  | Intent | 0.43 | 0.43 | 0.33 | 0.42 | 0.28 | 0.05 |
  | Gap type | 0.35 (n=51) | 0.34 | 0.27 | 0.36 | 0.18 | 0.08 |

  Each slice has 12–38 test records, so a single record moves a slice score by several points.
  Grouped cross-validation macro-F1: gap 0.60, intent 0.34, gap type 0.28.
* Intent and gap type are hard with this little data. Every record receives a label, but
  low-probability predictions are marked `low_confidence`. Rare classes (`payment_gap`,
  `deadline_gap`, `documentation_gap`) have only a handful of examples.
* Languages other than English, Hindi and romanized Hindi (for example Marathi, Gujarati) are
  classified through the multilingual embedding space but have no labelled examples, so
  accuracy on them is unknown.
* Scheme detection is rule-based. Schemes outside the 15-scheme registry (state schemes such as
  Ladki Bahin or Kanya Sumangala) appear as "Other / Unknown"; generic phrases count only as
  weak matches.

## Collection
* Several official portals cannot be collected as configured. Some have incomplete TLS
  certificate chains (verification is not disabled), some return HTTP 403 to automated
  requests, some time out, and some render their content with JavaScript (no headless browser
  is used). The real failure status is reported.
* Kisan Call Centre `QueryText` is the call-centre operator's short summary of the farmer's
  question, not the farmer's own words. Each call is a separate record (deduplicated by call
  id, not by text), so repeated questions are counted. The API is paged from the start of the
  "Government Schemes" subset; each run collects the configured number of pages.
* Web comments rarely state a location. Geographic analysis relies on sources with explicit
  state and district fields (the imported dataset and Kisan Call Centre records).
* Comment extraction targets WordPress-style markup. Other comment systems need selectors.

## Privacy
* Identifier patterns (phones, Aadhaar, PAN, e-mail, account numbers, PIN codes) are redacted.
  Personal **names** and street addresses in free text are not reliably detectable and may
  remain in public comments.

## Engineering
* The multilingual embedding model needs about 1 GB of free memory. On a machine close to its
  memory limit, PyTorch can fail to allocate and the process may crash.
* Verified on SQLite. The migrations generate valid PostgreSQL DDL, but they were not executed
  against a running PostgreSQL server, and the Docker images were not built, because the Docker
  engine was not running in the development environment.
* The vector index is brute force and in-process; for millions of records, use pgvector or an
  ANN index.
* A single operator API key suits one research team. Multi-user roles would need real accounts.
