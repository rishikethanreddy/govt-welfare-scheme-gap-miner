# Model evaluation report

Generated: 2026-10-20 16:13 UTC  
Training data hash: `2b45b32e6ce2` · embedding model: `paraphrase-multilingual-MiniLM-L12-v2`  
Out-of-distribution similarity threshold: 0.423

Produced by `python -m backend.app.nlp.training`. All test figures are on held-out records.

## Corpus

| Slice | Train | Val | Test | Label source |
|---|---|---|---|---|
| Original English records | 85 | 21 | 21 | manual (dataset author) |
| Hindi translations | 84 | 21 | 21 | inherited from the original record |
| Romanized-Hindi translations | 85 | 21 | 21 | inherited from the original record |
| Live comments (AI-annotated) | 176 | 38 | 38 | AI-assisted annotation |

Translations were written by an AI assistant from the original English records; the live slice was labelled by an AI assistant following the annotation guidelines. Neither is independent human ground truth.

## intent

- Model version: `intent-ensemble-tfidf-embedding-20261020-2b45b32e` (selected on validation: **ensemble_tfidf_embedding**)
- Labels: application, benefits, complaint, deadline, documentation, eligibility, general_information, payment

| Evaluation | n | Accuracy | Macro-F1 | Weighted-F1 |
|---|---|---|---|---|
| val · majority_baseline | 101 | 0.208 | 0.043 | 0.072 |
| val · tfidf_logreg | 101 | 0.366 | 0.224 | 0.337 |
| val · embedding_logreg | 101 | 0.366 | 0.372 | 0.386 |
| val · ensemble_tfidf_embedding | 101 | 0.436 | 0.446 | 0.444 |
| **test · majority baseline** | 101 | 0.277 | 0.054 | 0.120 |
| **test · ensemble_tfidf_embedding (all)** | 101 | 0.584 | 0.434 | 0.560 |
| test · Original English records | 21 | 0.619 | 0.433 | 0.521 |
| test · Hindi translations | 21 | 0.476 | 0.334 | 0.394 |
| test · Romanized-Hindi translations | 21 | 0.571 | 0.417 | 0.543 |
| test · Live comments (AI-annotated) | 38 | 0.632 | 0.284 | 0.570 |

Grouped 5-fold CV: macro-F1 0.3444 ± 0.0998, accuracy 0.434.

| Class | Precision | Recall | F1 | Support |
|---|---|---|---|---|
| application | 0.65 | 0.61 | 0.63 | 28 |
| benefits | 0.57 | 0.50 | 0.53 | 8 |
| complaint | 0.84 | 0.70 | 0.76 | 23 |
| deadline | 0.00 | 0.00 | 0.00 | 2 |
| documentation | 0.44 | 0.89 | 0.59 | 9 |
| eligibility | 0.36 | 0.31 | 0.33 | 13 |
| general_information | 0.50 | 0.83 | 0.62 | 12 |
| payment | 0.00 | 0.00 | 0.00 | 6 |

Confusion matrix (rows = true, columns = predicted):

| | application | benefits | complaint | deadline | documentation | eligibility | general_information | payment |
|---|---|---|---|---|---|---|---|---|
| **application** | 17 | 2 | 0 | 0 | 5 | 1 | 3 | 0 |
| **benefits** | 1 | 4 | 0 | 0 | 0 | 2 | 1 | 0 |
| **complaint** | 3 | 0 | 16 | 0 | 1 | 1 | 2 | 0 |
| **deadline** | 1 | 0 | 0 | 0 | 0 | 0 | 1 | 0 |
| **documentation** | 0 | 0 | 1 | 0 | 8 | 0 | 0 | 0 |
| **eligibility** | 3 | 0 | 1 | 0 | 4 | 4 | 1 | 0 |
| **general_information** | 1 | 1 | 0 | 0 | 0 | 0 | 10 | 0 |
| **payment** | 0 | 0 | 1 | 0 | 0 | 3 | 2 | 0 |

Misclassified test records: 42 (listed in `intent.json`).

## awareness_gap

- Model version: `awareness_gap-embedding-logreg-20261020-2b45b32e` (selected on validation: **embedding_logreg**)
- Labels: no, yes
- Uncertainty band: outcomes with confidence below 0.55 are 'unclear' (test: 81% decided, accuracy on decided 0.7317)

| Evaluation | n | Accuracy | Macro-F1 | Weighted-F1 |
|---|---|---|---|---|
| val · majority_baseline | 101 | 0.416 | 0.294 | 0.244 |
| val · tfidf_logreg | 101 | 0.693 | 0.689 | 0.695 |
| val · embedding_logreg | 101 | 0.743 | 0.740 | 0.744 |
| val · ensemble_tfidf_embedding | 101 | 0.703 | 0.696 | 0.704 |
| **test · majority baseline** | 101 | 0.505 | 0.336 | 0.339 |
| **test · embedding_logreg (all)** | 101 | 0.653 | 0.652 | 0.652 |
| test · Original English records | 21 | 0.619 | 0.533 | 0.562 |
| test · Hindi translations | 21 | 0.762 | 0.741 | 0.751 |
| test · Romanized-Hindi translations | 21 | 0.571 | 0.555 | 0.567 |
| test · Live comments (AI-annotated) | 38 | 0.658 | 0.613 | 0.640 |

Grouped 5-fold CV: macro-F1 0.5954 ± 0.0396, accuracy 0.6418.

| Class | Precision | Recall | F1 | Support |
|---|---|---|---|---|
| no | 0.67 | 0.60 | 0.63 | 50 |
| yes | 0.64 | 0.71 | 0.67 | 51 |

Confusion matrix (rows = true, columns = predicted):

| | no | yes |
|---|---|---|
| **no** | 30 | 20 |
| **yes** | 15 | 36 |

Misclassified test records: 35 (listed in `awareness_gap.json`).

## gap_type

- Model version: `gap_type-ensemble-tfidf-embedding-20261020-2b45b32e` (selected on validation: **ensemble_tfidf_embedding**)
- Labels: application_gap, benefit_gap, deadline_gap, documentation_gap, eligibility_gap, misconception, payment_gap

| Evaluation | n | Accuracy | Macro-F1 | Weighted-F1 |
|---|---|---|---|---|
| val · majority_baseline | 59 | 0.305 | 0.067 | 0.143 |
| val · tfidf_logreg | 59 | 0.475 | 0.227 | 0.398 |
| val · embedding_logreg | 59 | 0.424 | 0.378 | 0.476 |
| val · ensemble_tfidf_embedding | 59 | 0.525 | 0.387 | 0.507 |
| **test · majority baseline** | 51 | 0.372 | 0.078 | 0.202 |
| **test · ensemble_tfidf_embedding (all)** | 51 | 0.588 | 0.351 | 0.578 |
| test · Original English records | 12 | 0.583 | 0.342 | 0.614 |
| test · Hindi translations | 12 | 0.583 | 0.273 | 0.580 |
| test · Romanized-Hindi translations | 12 | 0.667 | 0.357 | 0.667 |
| test · Live comments (AI-annotated) | 15 | 0.533 | 0.184 | 0.425 |

Grouped 5-fold CV: macro-F1 0.2804 ± 0.0696, accuracy 0.5017.

| Class | Precision | Recall | F1 | Support |
|---|---|---|---|---|
| application_gap | 0.41 | 0.44 | 0.42 | 16 |
| benefit_gap | 0.00 | 0.00 | 0.00 | 2 |
| deadline_gap | 0.00 | 0.00 | 0.00 | 2 |
| documentation_gap | 0.43 | 1.00 | 0.60 | 3 |
| eligibility_gap | 0.60 | 0.67 | 0.63 | 9 |
| misconception | 0.88 | 0.74 | 0.80 | 19 |
| payment_gap | 0.00 | 0.00 | 0.00 | 0 |

Confusion matrix (rows = true, columns = predicted):

| | application_gap | benefit_gap | deadline_gap | documentation_gap | eligibility_gap | misconception | payment_gap |
|---|---|---|---|---|---|---|---|
| **application_gap** | 7 | 0 | 0 | 4 | 3 | 2 | 0 |
| **benefit_gap** | 2 | 0 | 0 | 0 | 0 | 0 | 0 |
| **deadline_gap** | 2 | 0 | 0 | 0 | 0 | 0 | 0 |
| **documentation_gap** | 0 | 0 | 0 | 3 | 0 | 0 | 0 |
| **eligibility_gap** | 3 | 0 | 0 | 0 | 6 | 0 | 0 |
| **misconception** | 3 | 1 | 0 | 0 | 1 | 14 | 0 |
| **payment_gap** | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

Misclassified test records: 21 (listed in `gap_type.json`).
