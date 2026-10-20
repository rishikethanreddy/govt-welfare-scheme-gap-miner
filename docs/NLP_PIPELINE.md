# NLP pipeline

Every record, whether imported or collected, goes through `services/pipeline.py`:

1. **Validation**: 15–10,000 characters, mostly alphabetic, few non-printable characters.
   Failures are stored as rejections with a reason.
2. **Normalization** (`nlp/text.py:normalize_text`): Unicode NFKC, zero-width removal and
   whitespace collapse. Meaning is preserved; this is the stored text.
3. **PII redaction** (`redact_pii`): phone numbers, Aadhaar, e-mail, PAN, 9–18 digit
   account/application numbers and postal PIN codes are replaced with tokens (`[PHONE]` …).
   Six-digit numbers next to a currency word are treated as amounts and kept. Personal names
   cannot be detected reliably and are **not** removed (see limitations).
4. **Exact deduplication**: SHA-256 of case-folded normalized text, scoped per workspace.
   Live duplicates are skipped and counted. Dataset duplicates are stored but flagged, so every
   imported row stays traceable.
5. **Language detection** (`detect_language`): Unicode script detection for Indic scripts, a
   function-word lexicon for romanized Hindi (`hi-Latn`) and Marathi (`mr-Latn`), and
   `langdetect` for the rest. Latin-script labels that are implausible for Indian sources
   (Indonesian, Swahili …) fall back to the lexicon or to `und`.
6. **Embedding**: `paraphrase-multilingual-MiniLM-L12-v2` (384-d, L2-normalised; 50+ languages
   including Hindi and Marathi), persisted in
   `document_embeddings` with the model name and the hash of the embedded text.
7. **Near-duplicate detection**: cosine ≥ `NEAR_DUPLICATE_THRESHOLD` (0.96) to an earlier
   canonical record in the same workspace. The record is flagged and linked to its original.
8. **Inference** (`nlp/service.py`) with the decision rules below.
9. **Persistence**: effective labels, model predictions (`predicted_*`), explanation JSON and
   model versions. Manual labels and operator corrections are never overwritten.

## Scheme detection

`nlp/schemes.py`. A configurable registry of 15 schemes (PM-KISAN, PMFBY, PM-KUSUM, PMAY,
Ayushman Bharat PM-JAY, MGNREGA, PMJDY, PMMY, PM SVANidhi, APY, PMJJBY, PMSBY, NSAP, PMUY,
PM Vishwakarma). Extra aliases can be added on the `schemes` table.

* Aliases match on Unicode-aware token boundaries, and separators are flexible
  (`pm kisan` ≈ `PM-KISAN`). "apy" does not match "happy".
* **Strong** aliases are unambiguous names. **Weak** aliases are generic phrases ("crop
  insurance", "job card", "solar pump") and count only when no strong alias is present.
* **Exclusions** handle look-alike schemes: "PM Kisan *Maan-dhan*" is not PM-KISAN.
* Every scheme found is kept (`schemes`). The primary scheme is the one with the most
  mentions, then the earliest mention.
* No numeric confidence is invented. The output records the match strength (`strong`,
  `weak`, `manual`, or `context` when a comment inherits the scheme of the page it was posted on).

## Text roles and applicability

Awareness-gap detection is meaningful only for **public-voice** text: `query`, `question`,
`complaint`, `discussion` (reader comments) and `grievance`. Informational text (`news`,
`article`, `faq`, `site_reply`) is labelled `not_applicable`. Intent is also predicted for
`faq`. The role is assigned from **where** the text came from (comment block, FAQ markup, feed
entry, dataset column), never from its wording.

## Classifiers

`nlp/training.py` trains three tasks:

| Task | Labels |
|---|---|
| intent | eligibility, application, documentation, benefits, payment, deadline, complaint, general_information |
| awareness_gap | yes, no |
| gap_type (only for gap = yes) | eligibility_gap, application_gap, documentation_gap, benefit_gap, payment_gap, deadline_gap, misconception |

### Training corpus

| Slice | Records | Labels |
|---|---|---|
| Original English (`welfare_awareness_dataset_with_split.csv`) | 127 | manual, by the dataset author; provided 85/21/21 split |
| Hindi translations (`translations_hi.csv`) | 126 | inherited from the original record |
| Romanized-Hindi translations (`translations_hi_latn.csv`) | 127 | inherited from the original record |
| Live comments (`live_comments_ai_annotated.csv`) | 252 | AI-assisted annotation (see below), 70/15/15 split |

**Translations** were written by an AI assistant from the original English records. A
translation inherits its record's labels *and split*, so a translated test record never appears in
training, and a record and its translations are always in the same cross-validation fold.

**Live comments** are a fixed random sample (seed 42) of real collected public comments,
stratified by detected language (English 90, romanized Hindi 100, Hindi 40, undetermined 20,
romanized Marathi 2). An AI assistant labelled them following the guidelines below. These labels
are not independent human ground truth; results on this slice are reported separately.

**Annotation guidelines** (the convention of the original dataset):
* **Gap = yes** when the writer shows missing or incorrect information: how or where to apply,
  whether they are eligible, which documents are needed, benefit amounts or coverage, how to
  check status or a list, dates, or a mistaken belief (gap type = the kind of information).
* **Gap = no** for praise or thanks; pleas for a benefit that ask nothing ("please give me a
  house"); grievances about corruption or non-delivery that do not ask for scheme information;
  addresses or phone numbers only; replies by other people; off-topic text.
* Intent describes what the text is about (pleas for a benefit are `application`, praise and
  bare contact details are `general_information`, grievances are `complaint`).

### Protocol
1. Candidates: majority-class baseline; TF-IDF (word 1–2 + char 2–5 grams) with logistic
   regression; multilingual sentence embeddings with logistic regression; and a soft-voting
   ensemble averaging the two learned models (character n-grams cope with romanized spelling,
   embeddings carry meaning across languages).
2. Each candidate is fitted on train and compared on validation by macro-F1.
3. The selected model is refit on train+val and evaluated **once** on test, overall and per slice.
4. 5-fold cross-validation grouped by record (with its translations) and by source page.
5. Artifacts are saved as `data/models/<task>/<version>/{model.joblib, metadata.json}`; the
   gap model also stores the labelled reference set used for evidence. `active.json` selects
   the deployed version, which is also registered in `model_versions` with its metrics.

Training and inference share `nlp/text.py:model_text`, so preprocessing cannot drift.

### Decision rules

* **Intent and gap type** always receive the most probable label and its probability. A
  prediction below 1.5 × the uniform probability is marked `low_confidence` but still labelled.
* **Awareness gap** is `yes`/`no` when the model's confidence reaches the threshold chosen on
  validation (0.55); inside the narrow band below it the outcome is `unclear`.
* **Out-of-distribution guard**: if a text's nearest labelled example has cosine similarity
  below the 1st percentile of held-out similarities minus 0.01 (currently 0.423), the gap
  outcome is `unclear` (status `out_of_distribution`).
* All languages are classified. English, Hindi and romanized Hindi have labelled training
  examples; other languages rely on the multilingual embedding space and are untested.

### Explanations

Each prediction stores the reason and status, P(gap), alternative intents and gap types with
probabilities, the matched scheme aliases, and the **three most similar labelled training
examples** with their labels. The record page and the text analyzer show all of them.

### Why a question is not a gap

The old heuristic flagged any text containing "?". The current classifier is trained on
labels where many questions are *not* gaps; for example, a farmer who knows the cause of a
delayed installment and asks whom to contact is labelled `no`. A test asserts that adding a
question mark moves the gap probability by less than 0.1 and never turns a "no" into a "yes".

## Clustering

`services/clustering.py`, run per workspace after processing, on public-voice and FAQ records:

1. Embeddings are reduced with PCA to 20 dimensions and re-normalised. Density estimates
   degrade in 384 dimensions; without the reduction, the live corpus collapsed into 3 giant
   clusters or more than 80% outliers.
2. HDBSCAN (leaf selection, `min_samples=2`, `min_cluster_size = max(4, √n / 3)`).
   Outliers stay unclustered.
3. Each cluster stores c-TF-IDF keywords (Indic-script aware), the five members closest to
   the centroid, cohesion (mean cosine to centroid), HDBSCAN persistence, dominant scheme,
   intent and gap type, and its gap-signal count. Clusters with cohesion < 0.40 are flagged
   "loose".
4. Run summaries record the silhouette score (cosine, original space), outlier count and
   parameters. The previous run is kept for comparison.

Configurations compared during development. The silhouette is computed in the original
embedding space, so dimensionality reduction cannot inflate it.

| Corpus | Configuration | Clusters | Outliers | Silhouette | Mean cohesion |
|---|---|---|---|---|---|
| dataset (n=127) | raw 384-d, EOM, mcs 6, ms 2 | 6 | 52% | 0.174 | 0.68 |
| dataset (n=127) | **PCA-20, leaf, mcs 4, ms 2 (chosen)** | 10 | 43% | 0.169 | 0.72 |
| live (n=549) | raw 384-d, EOM, mcs 10, ms 2 | 3 | 68% | 0.318 | 0.82 |
| live (n=549) | raw 384-d, leaf, mcs 6, ms 2 | 11 | 82% | 0.321 | 0.87 |
| live (n=549) | PCA-20, leaf, mcs 10, ms 2 | 13 | 58% | 0.149 | 0.77 |

The chosen setting gives more, smaller, coherent themes with fewer outliers. On the raw
vectors, the live corpus split mainly by language rather than by topic.

## Semantic search and similar records

`services/vector_index.py` loads persisted embeddings per workspace and runs exact cosine
search (brute force; adequate for tens of thousands of records). Results below
`SIMILARITY_SEARCH_MIN` (0.35) are not shown.
