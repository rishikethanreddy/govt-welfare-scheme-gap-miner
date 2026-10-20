"""
Estimator definitions used for training. Kept in their own module so that
joblib artifacts can be unpickled without importing the training script.
"""

import numpy as np
from sklearn.base import BaseEstimator, ClassifierMixin
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import FeatureUnion, Pipeline

from backend.app.nlp.text import model_text


def tfidf_logreg(C: float = 4.0) -> Pipeline:
    """Word 1-2 grams + character 2-5 grams (robust to spelling variants) → logistic regression."""
    features = FeatureUnion([
        ("word", TfidfVectorizer(preprocessor=model_text, ngram_range=(1, 2), min_df=1, sublinear_tf=True)),
        ("char", TfidfVectorizer(preprocessor=model_text, analyzer="char_wb", ngram_range=(2, 5),
                                 min_df=2, sublinear_tf=True)),
    ])
    return Pipeline([
        ("features", features),
        ("clf", LogisticRegression(C=C, max_iter=5000, class_weight="balanced", random_state=42)),
    ])


class EmbeddingLogReg(BaseEstimator, ClassifierMixin):
    """Sentence-Transformer embeddings → logistic regression.

    Embeddings are computed at fit/predict time from the configured model, so the
    artifact stores only the (small) linear layer plus the embedding model name.
    """

    def __init__(self, C: float = 2.0, embedding_model: str = "paraphrase-multilingual-MiniLM-L12-v2"):
        self.C = C
        self.embedding_model = embedding_model

    def _embed(self, X):
        from backend.app.nlp import embeddings
        if embeddings.model_name() != self.embedding_model:
            raise RuntimeError(
                f"Classifier was trained on '{self.embedding_model}' embeddings but "
                f"EMBEDDING_MODEL is '{embeddings.model_name()}'. Retrain or change the setting."
            )
        return embeddings.encode([model_text(x) for x in X])

    def fit(self, X, y):
        self.clf_ = LogisticRegression(C=self.C, max_iter=5000, class_weight="balanced", random_state=42)
        self.clf_.fit(self._embed(X), y)
        self.classes_ = self.clf_.classes_
        return self

    def predict_proba(self, X):
        return self.clf_.predict_proba(self._embed(X))

    def predict(self, X):
        return self.classes_[np.argmax(self.predict_proba(X), axis=1)]


def top_terms(pipeline: Pipeline, text: str, label, k: int = 6) -> list[dict]:
    """Highest-weighted n-grams supporting `label` for a TF-IDF pipeline (explanation aid)."""
    if not isinstance(pipeline, Pipeline):
        return []
    feats = pipeline.named_steps["features"]
    clf = pipeline.named_steps["clf"]
    x = feats.transform([text])
    names = feats.get_feature_names_out()
    classes = list(clf.classes_)
    if label not in classes:
        return []
    if clf.coef_.shape[0] == 1:  # binary: row 0 is the positive (classes_[1]) direction
        coef = clf.coef_[0] if classes.index(label) == 1 else -clf.coef_[0]
    else:
        coef = clf.coef_[classes.index(label)]
    contrib = x.multiply(coef).tocsr()
    idx = contrib.indices[np.argsort(-contrib.data)][:k]
    out = []
    for i in idx:
        w = float(contrib[0, i])
        if w <= 0:
            break
        out.append({"term": names[i].split("__", 1)[-1], "weight": round(w, 4)})
    return out


class SoftVotingEnsemble(BaseEstimator, ClassifierMixin):
    """Average of the class probabilities of the TF-IDF and embedding classifiers.
    Character n-grams handle romanized spelling variants; embeddings carry meaning
    across languages."""

    def __init__(self, embedding_model: str = "paraphrase-multilingual-MiniLM-L12-v2"):
        self.embedding_model = embedding_model

    def fit(self, X, y):
        self.tfidf_ = tfidf_logreg(C=4.0).fit(X, y)
        self.emb_ = EmbeddingLogReg(C=2.0, embedding_model=self.embedding_model).fit(X, y)
        self.classes_ = self.tfidf_.classes_
        return self

    def predict_proba(self, X, vecs=None):
        emb = self.emb_.clf_.predict_proba(vecs) if vecs is not None else self.emb_.predict_proba(X)
        return (self.tfidf_.predict_proba(list(X)) + emb) / 2

    def predict(self, X):
        return self.classes_[np.argmax(self.predict_proba(X), axis=1)]
