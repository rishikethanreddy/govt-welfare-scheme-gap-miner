"""
Train and evaluate the intent, awareness-gap and gap-type classifiers.

Training corpus (all files in data/raw/):
  original_en        welfare_awareness_dataset_with_split.csv — 127 manually labelled
                     English records with a provided train / val / test split.
  translated_hi      translations_hi.csv       — Hindi (Devanagari) translations of the
  translated_hi_latn translations_hi_latn.csv  — same records and romanized-Hindi translations.
                     A translation inherits its record's labels AND split, so a translated
                     test record never appears in training.
  live_ai            live_comments_ai_annotated.csv — a stratified random sample of real
                     collected public comments, labelled by an AI assistant following the
                     same annotation guidelines (docs/NLP_PIPELINE.md). These labels are not
                     human ground truth and are reported as a separate slice.

Protocol (per task):
  1. Fit each candidate on train; select by validation macro-F1 (majority baseline reported).
  2. Awareness gap only: choose a narrow uncertainty band on validation ("unclear").
     Intent and gap type always output their most probable label with its confidence.
  3. Refit the selected candidate on train+val; evaluate ONCE on test, overall and per slice.
  4. Robustness: 5-fold cross-validation grouped so that a record and its translations
     (and records from the same source page) are always on the same side of a fold.
  5. Save versioned artifacts + the labelled reference set, write docs/evaluation/*,
     register the versions in model_versions.

Usage:
  python -m backend.app.nlp.training [--no-register]
"""

import argparse
import hashlib
import json
import logging
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from sklearn.dummy import DummyClassifier
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix, precision_recall_fscore_support
from sklearn.model_selection import GroupKFold

from backend.app.config import PROJECT_ROOT, get_settings
from backend.app.nlp import artifacts
from backend.app.nlp.estimators import EmbeddingLogReg, SoftVotingEnsemble, tfidf_logreg

logger = logging.getLogger(__name__)

RAW = PROJECT_ROOT / "data" / "raw"
BASE_FILE = RAW / "welfare_awareness_dataset_with_split.csv"
TRANSLATION_FILES = {"translated_hi": RAW / "translations_hi.csv", "translated_hi_latn": RAW / "translations_hi_latn.csv"}
LIVE_FILE = RAW / "live_comments_ai_annotated.csv"
DATA_FILES = [BASE_FILE, *TRANSLATION_FILES.values(), LIVE_FILE]
REPORT_DIR = PROJECT_ROOT / "docs" / "evaluation"
SLICES = ("original_en", "translated_hi", "translated_hi_latn", "live_ai")
SLICE_NAMES = {"original_en": "Original English records", "translated_hi": "Hindi translations",
               "translated_hi_latn": "Romanized-Hindi translations", "live_ai": "Live comments (AI-annotated)"}
LABEL_COLS = ("intent", "awareness_gap", "gap_type")


def _clean(df: pd.DataFrame) -> pd.DataFrame:
    df["text"] = df["text"].astype(str).str.strip()
    for col in (*LABEL_COLS, "split"):
        df[col] = df[col].astype(str).str.strip().str.lower()
    return df


def load_corpus() -> pd.DataFrame:
    base = pd.read_csv(BASE_FILE)
    base["is_synthetic"] = base["is_synthetic"].astype(str).str.lower().isin(["yes", "true", "1"])
    base["slice"] = "original_en"
    base["group"] = "rec-" + base["id"].astype(str)
    frames = [base]
    labels = base.set_index("id")[["intent", "awareness_gap", "gap_type", "split", "is_synthetic"]]
    for slice_name, path in TRANSLATION_FILES.items():
        if not path.exists():
            continue
        t = pd.read_csv(path)
        t = t.join(labels, on="id")
        t["slice"] = slice_name
        t["group"] = "rec-" + t["id"].astype(str)   # same group as its source record
        frames.append(t)
    if LIVE_FILE.exists():
        live = pd.read_csv(LIVE_FILE)
        live["slice"] = "live_ai"
        live["is_synthetic"] = False
        # Comments from the same page stay together in grouped cross-validation.
        live["group"] = "page-" + live["source_url"].fillna(live["doc_id"].astype(str)).astype(str)
        frames.append(live)
    df = _clean(pd.concat(frames, ignore_index=True)[["text", *LABEL_COLS, "split", "slice", "group", "is_synthetic"]])
    # A translation that is identical to its original (record 97 is already Hindi) adds nothing.
    return df.drop_duplicates(subset=["text", "split"]).reset_index(drop=True)


def _task_frame(df: pd.DataFrame, task: str) -> pd.DataFrame:
    if task == "gap_type":
        return df[df["awareness_gap"] == "yes"].copy()  # only defined for gap = yes
    return df.copy()


def _metrics(y_true, y_pred, labels) -> dict:
    p, r, f, _ = precision_recall_fscore_support(y_true, y_pred, labels=labels, average="macro", zero_division=0)
    _, _, fw, _ = precision_recall_fscore_support(y_true, y_pred, labels=labels, average="weighted", zero_division=0)
    return {
        "n": int(len(y_true)),
        "accuracy": round(float(accuracy_score(y_true, y_pred)), 4) if len(y_true) else None,
        "macro_precision": round(float(p), 4),
        "macro_recall": round(float(r), 4),
        "macro_f1": round(float(f), 4),
        "weighted_f1": round(float(fw), 4),
        "per_class": classification_report(y_true, y_pred, labels=labels, output_dict=True, zero_division=0),
        "confusion_matrix": {"labels": list(labels), "matrix": confusion_matrix(y_true, y_pred, labels=labels).tolist()},
    }


def _short(m: dict) -> dict:
    return {k: m[k] for k in ("n", "accuracy", "macro_f1", "weighted_f1")}


def _candidates(embedding_model: str) -> dict:
    return {
        "majority_baseline": lambda: DummyClassifier(strategy="most_frequent"),
        "tfidf_logreg": lambda: tfidf_logreg(C=4.0),
        "embedding_logreg": lambda: EmbeddingLogReg(C=2.0, embedding_model=embedding_model),
        "ensemble_tfidf_embedding": lambda: SoftVotingEnsemble(embedding_model=embedding_model),
    }


def _gap_band(probs: np.ndarray, classes, y_val) -> float:
    """Narrow uncertainty band for the yes/no decision: the lowest threshold in
    [0.55, 0.70] that keeps >= 85% of validation records decided while maximising
    accuracy on them. Below it the outcome is 'unclear'."""
    y_val = np.asarray(y_val)
    pred = np.asarray(classes)[probs.argmax(axis=1)]
    top = probs.max(axis=1)
    best_t, best_acc = 0.55, -1.0
    for t in (0.55, 0.6, 0.65, 0.7):
        keep = top >= t
        if keep.mean() < 0.85 or not keep.any():
            continue
        acc = (pred[keep] == y_val[keep]).mean()
        if acc > best_acc + 1e-9:
            best_t, best_acc = t, acc
    return best_t


def _band_report(probs, classes, y_true, threshold) -> dict:
    y_true = np.asarray(y_true)
    pred = np.asarray(classes)[probs.argmax(axis=1)]
    keep = probs.max(axis=1) >= threshold
    return {"threshold": threshold, "coverage": round(float(keep.mean()), 4) if len(keep) else 0.0,
            "accuracy_on_covered": round(float((pred[keep] == y_true[keep]).mean()), 4) if keep.any() else None,
            "unclear": int((~keep).sum())}


def _grouped_cv(data: pd.DataFrame, col: str, labels, make, folds: int = 5) -> dict:
    groups = data["group"].values
    folds = min(folds, len(set(groups)))
    scores, accs = [], []
    for tr, te in GroupKFold(n_splits=folds).split(data, groups=groups):
        a, b = data.iloc[tr], data.iloc[te]
        if a[col].nunique() < 2:
            continue
        pred = make().fit(a.text.tolist(), a[col].tolist()).predict(b.text.tolist())
        scores.append(precision_recall_fscore_support(b[col], pred, labels=labels, average="macro", zero_division=0)[2])
        accs.append(accuracy_score(b[col], pred))
    return {"folds": len(scores), "grouping": "record (with its translations) / source page",
            "macro_f1_mean": round(float(np.mean(scores)), 4) if scores else None,
            "macro_f1_std": round(float(np.std(scores)), 4) if scores else None,
            "accuracy_mean": round(float(np.mean(accs)), 4) if accs else None}


def train_task(df: pd.DataFrame, task: str, embedding_model: str) -> dict:
    col = task
    data = _task_frame(df, task)
    train, val, test = (data[data.split == s] for s in ("train", "val", "test"))
    labels = sorted(data[col].unique())
    cands = _candidates(embedding_model)

    comparison, fitted = {}, {}
    for name, make in cands.items():
        fitted[name] = make().fit(train.text.tolist(), train[col].tolist())
        comparison[name] = _short(_metrics(val[col], fitted[name].predict(val.text.tolist()), labels))
    learned = {k: v for k, v in comparison.items() if k != "majority_baseline"}
    selected = max(learned, key=lambda k: (learned[k]["macro_f1"], learned[k]["accuracy"]))
    threshold = 0.0
    if task == "awareness_gap":
        threshold = _gap_band(fitted[selected].predict_proba(val.text.tolist()), fitted[selected].classes_, val[col])

    trval = pd.concat([train, val])
    final = cands[selected]().fit(trval.text.tolist(), trval[col].tolist())
    baseline = cands["majority_baseline"]().fit(trval.text.tolist(), trval[col].tolist())
    test_pred = final.predict(test.text.tolist())
    per_slice = {}
    for s in SLICES:
        part = test[test["slice"] == s]
        if len(part):
            per_slice[s] = _short(_metrics(part[col], test_pred[test["slice"].values == s], labels))
    report = {
        "task": task, "labels": labels, "selected": selected,
        "uncertainty_threshold": threshold,
        "training_records": {s: int((trval["slice"] == s).sum()) for s in SLICES},
        "class_distribution": {s: data[data.split == s][col].value_counts().to_dict() for s in ("train", "val", "test")},
        "validation_comparison": comparison,
        "test": _metrics(test[col], test_pred, labels),
        "test_by_slice": per_slice,
        "test_baseline": _short(_metrics(test[col], baseline.predict(test.text.tolist()), labels)),
        "grouped_cv": _grouped_cv(data, col, labels, cands[selected]),
        "errors": [{"text": t, "slice": s, "true": a, "pred": b}
                   for t, s, a, b in zip(test.text, test["slice"], test[col], test_pred) if a != b],
    }
    if task == "awareness_gap":
        report["test_uncertainty"] = _band_report(final.predict_proba(test.text.tolist()), final.classes_, test[col], threshold)
    return {"model": final, "report": report, "n_train": len(trval)}


def ood_threshold(df: pd.DataFrame) -> float:
    """Out-of-distribution guard: 1st percentile (minus 0.01) of held-out records'
    nearest-neighbour cosine similarity to the training records."""
    from backend.app.nlp import embeddings
    train = embeddings.encode(df[df.split == "train"].text.tolist())
    held = embeddings.encode(df[df.split.isin(["val", "test"])].text.tolist())
    return round(float(np.percentile((held @ train.T).max(axis=1), 1)) - 0.01, 3)


def _files_hash() -> str:
    h = hashlib.sha256()
    for p in DATA_FILES:
        if p.exists():
            h.update(p.read_bytes())
    return h.hexdigest()


def _write_markdown(results: dict, data_hash: str, ood: float, df: pd.DataFrame) -> None:
    s = get_settings()
    sizes = df.groupby(["slice", "split"]).size().unstack(fill_value=0)
    lines = [
        "# Model evaluation report", "",
        f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}  ",
        f"Training data hash: `{data_hash[:12]}` · embedding model: `{s.EMBEDDING_MODEL}`  ",
        f"Out-of-distribution similarity threshold: {ood}", "",
        "Produced by `python -m backend.app.nlp.training`. All test figures are on held-out records.", "",
        "## Corpus", "",
        "| Slice | Train | Val | Test | Label source |", "|---|---|---|---|---|",
    ]
    src = {"original_en": "manual (dataset author)", "translated_hi": "inherited from the original record",
           "translated_hi_latn": "inherited from the original record", "live_ai": "AI-assisted annotation"}
    for sl in SLICES:
        if sl in sizes.index:
            r = sizes.loc[sl]
            lines.append(f"| {SLICE_NAMES[sl]} | {r.get('train', 0)} | {r.get('val', 0)} | {r.get('test', 0)} | {src[sl]} |")
    lines += ["", "Translations were written by an AI assistant from the original English records; "
              "the live slice was labelled by an AI assistant following the annotation guidelines. "
              "Neither is independent human ground truth.", ""]
    for task, res in results.items():
        r, t = res["report"], res["report"]["test"]
        lines += [f"## {task}", "", f"- Model version: `{res['version']}` (selected on validation: **{r['selected']}**)",
                  f"- Labels: {', '.join(r['labels'])}"]
        if task == "awareness_gap":
            u = r["test_uncertainty"]
            lines.append(f"- Uncertainty band: outcomes with confidence below {r['uncertainty_threshold']} are 'unclear' "
                         f"(test: {u['coverage']:.0%} decided, accuracy on decided {u['accuracy_on_covered']})")
        lines += ["", "| Evaluation | n | Accuracy | Macro-F1 | Weighted-F1 |", "|---|---|---|---|---|"]
        for name, m in r["validation_comparison"].items():
            lines.append(f"| val · {name} | {m['n']} | {m['accuracy']:.3f} | {m['macro_f1']:.3f} | {m['weighted_f1']:.3f} |")
        b = r["test_baseline"]
        lines.append(f"| **test · majority baseline** | {b['n']} | {b['accuracy']:.3f} | {b['macro_f1']:.3f} | {b['weighted_f1']:.3f} |")
        lines.append(f"| **test · {r['selected']} (all)** | {t['n']} | {t['accuracy']:.3f} | {t['macro_f1']:.3f} | {t['weighted_f1']:.3f} |")
        for sl, m in r["test_by_slice"].items():
            lines.append(f"| test · {SLICE_NAMES[sl]} | {m['n']} | {m['accuracy']:.3f} | {m['macro_f1']:.3f} | {m['weighted_f1']:.3f} |")
        cv = r["grouped_cv"]
        lines += ["", f"Grouped {cv['folds']}-fold CV: macro-F1 {cv['macro_f1_mean']} ± {cv['macro_f1_std']}, "
                      f"accuracy {cv['accuracy_mean']}.", "",
                  "| Class | Precision | Recall | F1 | Support |", "|---|---|---|---|---|"]
        for lbl in r["labels"]:
            pc = t["per_class"].get(lbl, {})
            lines.append(f"| {lbl} | {pc.get('precision', 0):.2f} | {pc.get('recall', 0):.2f} | {pc.get('f1-score', 0):.2f} | {int(pc.get('support', 0))} |")
        cm = t["confusion_matrix"]
        lines += ["", "Confusion matrix (rows = true, columns = predicted):", "",
                  "| | " + " | ".join(cm["labels"]) + " |", "|---" * (len(cm["labels"]) + 1) + "|"]
        lines += [f"| **{lbl}** | " + " | ".join(str(v) for v in row) + " |" for lbl, row in zip(cm["labels"], cm["matrix"])]
        lines += ["", f"Misclassified test records: {len(r['errors'])} (listed in `{task}.json`).", ""]
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "EVALUATION.md").write_text("\n".join(lines), encoding="utf-8")


def register_versions(results: dict, data_version: str) -> None:
    from backend.app.database import SessionLocal
    from backend.app.models.model_version import ModelVersion
    db = SessionLocal()
    try:
        for task, res in results.items():
            r = res["report"]
            db.query(ModelVersion).filter(ModelVersion.model_name == task).update({"is_active": False})
            mv = db.query(ModelVersion).filter(ModelVersion.model_name == task, ModelVersion.version == res["version"]).first() \
                or ModelVersion(model_name=task, version=res["version"])
            mv.model_type, mv.training_dataset_version = r["selected"], data_version
            mv.description = f"Selected on validation macro-F1; uncertainty threshold {r['uncertainty_threshold']}"
            mv.training_samples, mv.training_date = res["n_train"], datetime.now(timezone.utc)
            mv.accuracy, mv.precision_score = r["test"]["accuracy"], r["test"]["macro_precision"]
            mv.recall, mv.f1_score, mv.validation_samples = r["test"]["macro_recall"], r["test"]["macro_f1"], r["test"]["n"]
            mv.confusion_matrix = json.dumps(r["test"]["confusion_matrix"])
            mv.class_report = json.dumps(r["test"]["per_class"])
            mv.evaluation_notes = json.dumps({"baseline": r["test_baseline"], "grouped_cv": r["grouped_cv"],
                                              "by_slice": r["test_by_slice"], "validation": r["validation_comparison"]})
            mv.model_path = (artifacts.models_root() / task / res["version"]).relative_to(PROJECT_ROOT).as_posix()
            mv.status, mv.is_active = "deployed", True
            db.add(mv)
        db.commit()
    finally:
        db.close()


def run(register: bool = True) -> dict:
    settings = get_settings()
    df = load_corpus()
    data_hash = _files_hash()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    ood = ood_threshold(df)
    reference = df[df.split.isin(["train", "val"])][["text", *LABEL_COLS, "slice"]].to_dict("records")
    results = {}
    for task in artifacts.TASKS:
        logger.info("Training %s", task)
        res = train_task(df, task, settings.EMBEDDING_MODEL)
        r = res["report"]
        res["version"] = version = f"{task}-{r['selected'].replace('_', '-')}-{stamp}-{data_hash[:8]}"
        meta = {
            "task": task, "version": version, "algorithm": r["selected"], "labels": r["labels"],
            "uncertainty_threshold": r["uncertainty_threshold"], "ood_similarity_threshold": ood,
            "embedding_model": settings.EMBEDDING_MODEL,
            "preprocessing": "backend.app.nlp.text.model_text (NFKC, zero-width removal, lowercase, URL removal)",
            "training_data": {"files": [p.relative_to(PROJECT_ROOT).as_posix() for p in DATA_FILES if p.exists()],
                              "sha256": data_hash, "train_plus_val_records": res["n_train"]},
            "trained_at": datetime.now(timezone.utc).isoformat(),
            "test_metrics": _short(r["test"]), "test_by_slice": r["test_by_slice"],
        }
        artifacts.save(task, version, res["model"], meta)
        artifacts.set_active(task, version)
        if task == "awareness_gap":
            artifacts.save_reference(version, reference)
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        (REPORT_DIR / f"{task}.json").write_text(json.dumps(r, indent=2, default=str, ensure_ascii=False), encoding="utf-8")
        results[task] = res
    _write_markdown(results, data_hash, ood, df)
    if register:
        try:
            register_versions(results, data_version=f"corpus:{data_hash[:12]}")
        except Exception as e:
            logger.warning("Could not register model versions in DB: %s", e)
    return results


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--no-register", action="store_true")
    args = ap.parse_args()
    for task, res in run(register=not args.no_register).items():
        r = res["report"]
        sl = " ".join(f"{k}={v['macro_f1']:.2f}" for k, v in r["test_by_slice"].items())
        print(f"{task:14s} {r['selected']:17s} test F1={r['test']['macro_f1']:.3f} acc={r['test']['accuracy']:.3f} "
              f"baseline F1={r['test_baseline']['macro_f1']:.3f} cv F1={r['grouped_cv']['macro_f1_mean']} | {sl}")


if __name__ == "__main__":
    main()
