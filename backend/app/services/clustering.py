"""
Semantic clustering of question-like records with HDBSCAN.

Why HDBSCAN: it does not need the number of clusters in advance and labels
low-density points as outliers instead of forcing them into a cluster, which
matters for small, noisy public-text corpora.

Inputs: L2-normalised sentence embeddings (Euclidean distance on unit vectors is
monotonic in cosine distance). Only public-voice and FAQ records are clustered —
news and article summaries are a different kind of text.

Each cluster stores: c-TF-IDF keywords (traceable to member texts), the members
closest to the centroid as representatives, cohesion (mean cosine similarity to
the centroid), HDBSCAN persistence, and dominant scheme/intent/gap type. The run
summary (including silhouette score) is stored in system_state.
"""

import json
import logging
import math
import uuid
from collections import Counter

import numpy as np
from sqlalchemy.orm import Session

from backend.app.config import get_settings
from backend.app.models.cluster import Cluster, DocumentCluster
from backend.app.models.coltypes import utcnow
from backend.app.models.document import Document
from backend.app.models.embedding import DocumentEmbedding, SystemState
from backend.app.nlp import embeddings

logger = logging.getLogger(__name__)

CLUSTER_ROLES = ("query", "question", "complaint", "discussion", "comment", "grievance", "faq")
MIN_DOCS = 12
PCA_DIMS = 20
LOW_COHESION = 0.40
_EXTRA_STOP = {"yojana", "scheme", "pm", "pradhan", "mantri", "govt", "government", "sir", "ji", "please", "plz",
               "ke", "ki", "ka", "hai", "se", "ko", "mein", "me", "nahi", "kya", "aur"}


def _keywords(texts_by_cluster: dict, top_n: int = 6) -> dict:
    """Class-based TF-IDF (as in BERTopic): weight terms frequent in one cluster but rare overall."""
    from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS, CountVectorizer
    labels = list(texts_by_cluster)
    docs = [" ".join(texts_by_cluster[k]) for k in labels]
    # Indic vowel signs are combining marks, which \w does not match; include the
    # Indic blocks explicitly so Hindi words are not split into fragments.
    cv = CountVectorizer(stop_words=list(ENGLISH_STOP_WORDS | _EXTRA_STOP), ngram_range=(1, 2),
                         token_pattern=r"(?u)(?![\d_])[\wऀ-෿]{3,}", min_df=1)
    tf = cv.fit_transform(docs).toarray().astype(float)
    if tf.size == 0:
        return {k: [] for k in labels}
    terms = cv.get_feature_names_out()
    tf_norm = tf / np.maximum(tf.sum(axis=1, keepdims=True), 1)
    avg_words = tf.sum() / len(labels)
    idf = np.log(1 + avg_words / np.maximum(tf.sum(axis=0), 1))
    scores = tf_norm * idf
    return {k: [terms[i] for i in np.argsort(-scores[j])[:top_n] if scores[j, i] > 0] for j, k in enumerate(labels)}


def _mode(values):
    vals = [v for v in values if v and v not in ("none", "unknown", "not_applicable")]
    return Counter(vals).most_common(1)[0][0] if vals else None


def run_clustering(db: Session, scope: str) -> dict:
    import hdbscan
    settings = get_settings()
    model = embeddings.model_name()
    rows = (db.query(Document, DocumentEmbedding.vector)
            .join(DocumentEmbedding, DocumentEmbedding.document_id == Document.id)
            .filter(Document.origin == scope, Document.is_duplicate == False, Document.is_demo == False,  # noqa: E712
                    Document.text_role.in_(CLUSTER_ROLES), DocumentEmbedding.model == model)
            .order_by(Document.id).all())
    n = len(rows)
    summary = {"scope": scope, "documents": n, "embedding_model": model, "algorithm": "hdbscan",
               "run_at": utcnow().isoformat()}
    if n < MIN_DOCS:
        summary.update(status="skipped", reason=f"Only {n} eligible records; at least {MIN_DOCS} are needed.")
        _store_summary(db, scope, summary)
        return summary

    docs = [r[0] for r in rows]
    X = np.vstack([embeddings.from_bytes(r[1]) for r in rows])
    # Density estimates degrade in 384 dimensions; a 20-component PCA (re-normalised)
    # keeps the dominant semantic directions. Chosen by comparing outlier share,
    # cohesion and silhouette across configurations (docs/NLP_PIPELINE.md).
    Z = X
    dims = min(PCA_DIMS, n - 1)
    if n >= 40 and dims < X.shape[1]:
        from sklearn.decomposition import PCA
        Z = PCA(n_components=dims, random_state=0).fit_transform(X)
        Z /= np.maximum(np.linalg.norm(Z, axis=1, keepdims=True), 1e-9)
    mcs = settings.CLUSTER_MIN_SIZE or max(4, min(25, int(round(math.sqrt(n) / 3))))
    clusterer = hdbscan.HDBSCAN(min_cluster_size=mcs, min_samples=2, metric="euclidean",
                                cluster_selection_method="leaf")
    labels = clusterer.fit_predict(Z)
    probs = clusterer.probabilities_
    persistence = getattr(clusterer, "cluster_persistence_", None)
    cluster_ids = sorted(set(labels) - {-1})

    silhouette = None
    mask = labels >= 0
    if len(cluster_ids) >= 2 and mask.sum() > len(cluster_ids):
        from sklearn.metrics import silhouette_score
        silhouette = round(float(silhouette_score(X[mask], labels[mask], metric="cosine")), 4)

    texts_by = {k: [docs[i].normalized_text or docs[i].original_text for i in np.where(labels == k)[0]]
                for k in cluster_ids}
    kw = _keywords(texts_by) if cluster_ids else {}

    run_id = utcnow().strftime("%Y%m%d%H%M%S") + "-" + uuid.uuid4().hex[:6]
    # Keep the previous run for comparison; delete older ones.
    old_runs = [r[0] for r in db.query(Cluster.run_id).filter(Cluster.scope == scope)
                .distinct().order_by(Cluster.run_id.desc()).all()]
    for rid in old_runs[1:]:
        for cl in db.query(Cluster).filter(Cluster.run_id == rid).all():
            db.delete(cl)
    db.query(Cluster).filter(Cluster.scope == scope).update({"is_active": False})

    created = []
    for k in cluster_ids:
        idx = np.where(labels == k)[0]
        centroid = X[idx].mean(axis=0)
        centroid /= np.linalg.norm(centroid) or 1.0
        sims = X[idx] @ centroid
        order = idx[np.argsort(-sims)]
        members = [docs[i] for i in idx]
        cohesion = float(sims.mean())
        reps = [docs[i].original_text for i in order[:5]]
        keywords = kw.get(k, [])
        cl = Cluster(
            cluster_label=int(k), scope=scope, is_active=True, size=len(idx),
            name=" · ".join(keywords[:3]) or f"Cluster {k}", keywords=keywords,
            description=("Low cohesion — members are loosely related; inspect before drawing conclusions."
                         if cohesion < LOW_COHESION else None),
            cohesion=round(cohesion, 4),
            persistence=round(float(persistence[k]), 4) if persistence is not None and k < len(persistence) else None,
            representative_text=reps[0], representative_texts=json.dumps(reps),
            dominant_scheme=_mode(d.scheme_name for d in members),
            dominant_intent=_mode(d.intent for d in members),
            dominant_gap_type=_mode(d.gap_type for d in members),
            dominant_state=_mode(d.state for d in members),
            gap_signals=sum(1 for d in members if d.awareness_gap == "yes"),
            algorithm="hdbscan", model_version=f"pca{Z.shape[1]}-hdbscan-leaf-mcs{mcs}", embedding_model=model,
            run_id=run_id,
        )
        rank = {int(i): r for r, i in enumerate(order)}
        for i in idx:
            cl.document_clusters.append(DocumentCluster(
                document_id=docs[i].id, similarity_score=round(float(X[i] @ centroid), 4),
                membership_probability=round(float(probs[i]), 4), is_representative=int(rank[int(i)] < 5)))
        db.add(cl)
        created.append(cl)
    summary.update(status="completed", run_id=run_id, clusters=len(created), outliers=int((labels == -1).sum()),
                   min_cluster_size=mcs, silhouette_cosine=silhouette,
                   low_cohesion_clusters=sum(1 for c in created if (c.cohesion or 0) < LOW_COHESION))
    _store_summary(db, scope, summary)
    db.commit()
    logger.info("Clustering %s: %s", scope, summary)
    return summary


def _store_summary(db: Session, scope: str, summary: dict) -> None:
    key = f"clustering:{scope}"
    row = db.get(SystemState, key) or SystemState(key=key)
    row.value = json.dumps(summary)
    db.add(row)
    db.commit()


def last_summary(db: Session, scope: str) -> dict | None:
    row = db.get(SystemState, f"clustering:{scope}")
    return json.loads(row.value) if row and row.value else None
