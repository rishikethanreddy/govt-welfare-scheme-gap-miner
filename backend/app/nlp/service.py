"""
NLP inference service.

analyze_batch() is the single entry point used by the analyzer API, dataset
processing and live collection, so all three produce identical outputs.

Decision rules (documented, deterministic):
  * Languages: the embedding model is multilingual and the classifiers were trained on
    English, Hindi and romanized-Hindi text, so every record is classified. The detected
    language is stored for reporting.
  * Text role: awareness-gap detection applies only to public-voice text (queries,
    questions, complaints, comments). News, articles and official FAQ entries get
    awareness_gap = "not_applicable" — they describe schemes; they are not evidence
    of anyone's information gap. Intent is also predicted for FAQ entries.
  * Intent and gap type: always the most probable label, with its probability.
    Predictions below 1.5x the uniform probability are marked status "low_confidence".
  * Awareness gap: "yes"/"no" when the model's confidence reaches the threshold chosen
    on validation data; inside the narrow band below it the outcome is "unclear".
    Text unlike every labelled training example (out-of-distribution guard) is also
    "unclear". Only "unclear" records are flagged for review.
"""

import logging
import threading
from typing import Optional, Sequence

import numpy as np

from backend.app.nlp import artifacts, embeddings
from backend.app.nlp.estimators import EmbeddingLogReg, SoftVotingEnsemble
from backend.app.nlp.schemes import SchemeRegistry, default_registry
from backend.app.nlp.text import detect_language, normalize_text

logger = logging.getLogger(__name__)

SCHEME_DETECTION_VERSION = "rules-v2"

PUBLIC_VOICE_ROLES = {"query", "question", "complaint", "discussion", "comment", "grievance"}
INTENT_ROLES = PUBLIC_VOICE_ROLES | {"faq"}


class _TaskModel:
    def __init__(self, task: str):
        self.task = task
        self.model, self.meta = artifacts.load(task)

    @property
    def available(self) -> bool:
        return self.model is not None

    @property
    def version(self) -> Optional[str]:
        return self.meta["version"] if self.meta else None

    @property
    def threshold(self) -> float:
        if not self.meta:
            return 0.0
        return float(self.meta.get("uncertainty_threshold", self.meta.get("abstention_threshold", 0.0)))

    def proba(self, texts: Sequence[str], vecs: Optional[np.ndarray]) -> np.ndarray:
        # Reuse already-computed embeddings instead of encoding twice.
        if isinstance(self.model, EmbeddingLogReg) and vecs is not None:
            return self.model.clf_.predict_proba(vecs)
        if isinstance(self.model, SoftVotingEnsemble) and vecs is not None:
            return self.model.predict_proba(list(texts), vecs=vecs)
        return self.model.predict_proba(list(texts))


class NLPService:
    def __init__(self, registry: Optional[SchemeRegistry] = None):
        self.registry = registry or default_registry()
        self.models = {t: _TaskModel(t) for t in artifacts.TASKS}
        self._reference = None
        self._ref_lock = threading.Lock()

    # ── Status ────────────────────────────────────────────────────────────

    def status(self) -> dict:
        return {
            "scheme_detection": {"version": SCHEME_DETECTION_VERSION, "schemes": len(self.registry.definitions)},
            "embedding_model": embeddings.model_name(),
            "models": {
                t: {"available": m.available, "version": m.version,
                    "algorithm": m.meta.get("algorithm") if m.meta else None,
                    "uncertainty_threshold": m.threshold if m.available else None,
                    "test_metrics": m.meta.get("test_metrics") if m.meta else None}
                for t, m in self.models.items()
            },
        }

    def model_versions(self) -> dict:
        return {
            "scheme_detection": SCHEME_DETECTION_VERSION,
            "intent": self.models["intent"].version,
            "awareness_gap": self.models["awareness_gap"].version,
            "gap_type": self.models["gap_type"].version,
            "embedding": embeddings.model_name(),
        }

    # ── Labelled reference set (evidence + out-of-distribution guard) ─────

    def _reference_set(self) -> dict:
        if self._reference is not None:
            return self._reference
        with self._ref_lock:
            if self._reference is None:
                ref = {}
                try:
                    records = artifacts.load_reference(self.models["awareness_gap"].version)
                    if records:
                        ref = {"records": records, "vecs": embeddings.encode([r["text"] for r in records])}
                except Exception as e:
                    logger.warning("Reference set unavailable: %s", e)
                self._reference = ref
        return self._reference

    def _evidence(self, vec: np.ndarray, k: int = 3) -> list:
        ref = self._reference_set()
        if not ref or vec is None:
            return []
        sims = ref["vecs"] @ vec
        out = []
        for i in np.argsort(-sims)[:k]:
            r = ref["records"][i]
            out.append({"text": r["text"], "intent": r["intent"], "awareness_gap": r["awareness_gap"],
                        "gap_type": r["gap_type"], "similarity": round(float(sims[i]), 3)})
        return out

    @property
    def ood_threshold(self) -> float:
        meta = self.models["awareness_gap"].meta or {}
        return float(meta.get("ood_similarity_threshold", -1.0))

    def _nearest_similarity(self, vecs: np.ndarray) -> Optional[np.ndarray]:
        ref = self._reference_set()
        if not ref or vecs is None or len(vecs) == 0:
            return None
        return (vecs @ ref["vecs"].T).max(axis=1)

    # ── Inference ─────────────────────────────────────────────────────────

    def analyze(self, text: str, text_role: Optional[str] = "query", with_evidence: bool = True) -> dict:
        return self.analyze_batch([text], [text_role], with_evidence=with_evidence)[0]

    def analyze_batch(self, texts: Sequence[str], roles: Optional[Sequence[Optional[str]]] = None,
                      with_evidence: bool = False, vecs: Optional[np.ndarray] = None) -> list[dict]:
        texts = [normalize_text(t) for t in texts]
        roles = [(r or "query") for r in roles] if roles is not None else ["query"] * len(texts)
        n = len(texts)
        if n == 0:
            return []
        if vecs is None:
            vecs = embeddings.encode(texts)
        nearest = self._nearest_similarity(vecs)
        in_dist = nearest >= self.ood_threshold if nearest is not None else np.ones(n, dtype=bool)

        intent_mask = np.array([r in INTENT_ROLES for r in roles])
        gap_mask = np.array([r in PUBLIC_VOICE_ROLES for r in roles])
        p_intent = self._proba("intent", texts, vecs, intent_mask)
        p_gap = self._proba("awareness_gap", texts, vecs, gap_mask)
        gm = self.models["awareness_gap"]
        yes_idx = list(gm.model.classes_).index("yes") if gm.available else None

        gaps = [self._gap(p_gap, i, yes_idx, roles[i], bool(in_dist[i]), None if nearest is None else float(nearest[i]))
                for i in range(n)]
        type_mask = np.array([g["label"] == "yes" for g in gaps])
        p_type = self._proba("gap_type", texts, vecs, type_mask)

        results = []
        for i in range(n):
            lang = detect_language(texts[i])
            gap = gaps[i]
            if gap["label"] == "yes":
                gap_type = self._label("gap_type", p_type, i)
            elif gap["label"] == "no":
                gap_type = {"label": "none", "confidence": None, "status": "not_applicable", "alternatives": []}
            else:
                gap_type = None
            out = {
                "text": texts[i],
                "normalized_text": texts[i],
                "text_role": roles[i],
                "language": {"code": lang.code, "script": lang.script, "method": lang.method, "supported": lang.supported},
                "scheme": self.registry.detect(texts[i]).to_dict(),
                "intent": self._label("intent", p_intent, i) if intent_mask[i] else
                {"label": None, "confidence": None, "status": "not_applicable", "alternatives": []},
                "awareness_gap": gap,
                "gap_type": gap_type,
                "nearest_labelled_similarity": None if nearest is None else round(float(nearest[i]), 3),
                "evidence": self._evidence(vecs[i]) if with_evidence else [],
                "needs_review": gap["label"] == "unclear",
                "model_versions": self.model_versions(),
            }
            results.append(out)
        return results

    def _proba(self, task: str, texts, vecs, mask: np.ndarray) -> Optional[np.ndarray]:
        m = self.models[task]
        if not m.available or not mask.any():
            return None
        p = np.zeros((len(texts), len(m.model.classes_)))
        idx = np.where(mask)[0]
        p[mask] = m.proba([texts[i] for i in idx], vecs[mask])
        return p

    def _label(self, task: str, probs: Optional[np.ndarray], i: int) -> dict:
        m = self.models[task]
        if not m.available or probs is None:
            return {"label": None, "confidence": None, "status": "model_unavailable", "alternatives": []}
        row, classes = probs[i], m.model.classes_
        order = np.argsort(-row)
        top = float(row[order[0]])
        alts = [{"label": str(classes[j]), "probability": round(float(row[j]), 3)} for j in order[:3]]
        status = "predicted" if top >= 1.5 / len(classes) else "low_confidence"
        return {"label": str(classes[order[0]]), "confidence": round(top, 3), "status": status, "alternatives": alts}

    def _gap(self, probs, i, yes_idx, role, in_dist, nearest) -> dict:
        m = self.models["awareness_gap"]
        if role not in PUBLIC_VOICE_ROLES:
            return {"label": "not_applicable", "p_yes": None, "confidence": None, "status": "not_applicable",
                    "reason": f"'{role}' text is informational content, not a public query or complaint."}
        if not m.available or probs is None:
            return {"label": None, "p_yes": None, "confidence": None, "status": "model_unavailable",
                    "reason": "No trained awareness-gap model is installed."}
        p_yes = float(probs[i, yes_idx])
        conf = max(p_yes, 1 - p_yes)
        if not in_dist:
            return {"label": "unclear", "p_yes": round(p_yes, 3), "confidence": round(conf, 3),
                    "status": "out_of_distribution",
                    "reason": f"Text is unlike every labelled example (nearest similarity {nearest:.2f} < "
                              f"{self.ood_threshold:.2f}), so the model's output is not relied on."}
        if conf < m.threshold:
            return {"label": "unclear", "p_yes": round(p_yes, 3), "confidence": round(conf, 3), "status": "uncertain",
                    "reason": f"Model probability of a gap is {p_yes:.2f}, inside the uncertainty band "
                              f"(a decision needs ≥ {m.threshold:.2f} confidence)."}
        label = "yes" if p_yes >= 0.5 else "no"
        return {"label": label, "p_yes": round(p_yes, 3), "confidence": round(conf, 3), "status": "predicted",
                "reason": f"Classifier probability of a gap is {p_yes:.2f}; see the most similar labelled examples."}


_service: Optional[NLPService] = None
_service_lock = threading.Lock()


def get_nlp_service() -> NLPService:
    global _service
    if _service is None:
        with _service_lock:
            if _service is None:
                _service = NLPService()
    return _service


def reload_nlp_service(registry: Optional[SchemeRegistry] = None) -> NLPService:
    global _service
    with _service_lock:
        _service = NLPService(registry)
    return _service
