"""
In-memory cosine-similarity index over persisted embeddings.

Embeddings live in the database (document_embeddings); this index loads them
per workspace (origin) on demand and is invalidated whenever embeddings change.
Brute-force dot products are exact and fast enough for tens of thousands of
384-dimensional vectors; no approximate index is needed at this scale.
"""

import threading
from typing import Optional

import numpy as np
from sqlalchemy.orm import Session

from backend.app.models.document import Document
from backend.app.models.embedding import DocumentEmbedding
from backend.app.nlp import embeddings

_lock = threading.Lock()
_cache: dict = {}
_generation = 0


def invalidate() -> None:
    global _generation
    with _lock:
        _generation += 1
        _cache.clear()


class VectorIndex:
    def __init__(self, ids: np.ndarray, matrix: np.ndarray):
        self.ids = ids
        self.matrix = matrix

    @classmethod
    def for_origin(cls, db: Session, origin: Optional[str], include_duplicates: bool = False) -> "VectorIndex":
        key = (origin, include_duplicates, embeddings.model_name())
        with _lock:
            hit = _cache.get(key)
            gen = _generation
        if hit is not None:
            return hit
        q = (db.query(DocumentEmbedding.document_id, DocumentEmbedding.vector)
             .join(Document, Document.id == DocumentEmbedding.document_id)
             .filter(DocumentEmbedding.model == embeddings.model_name(), Document.is_demo == False))  # noqa: E712
        if origin:
            q = q.filter(Document.origin == origin)
        if not include_duplicates:
            q = q.filter(Document.is_duplicate == False)  # noqa: E712
        rows = q.all()
        if rows:
            ids = np.array([r[0] for r in rows], dtype=np.int64)
            matrix = np.vstack([embeddings.from_bytes(r[1]) for r in rows])
        else:
            ids = np.zeros(0, dtype=np.int64)
            matrix = np.zeros((0, 0), dtype=np.float32)
        idx = cls(ids, matrix)
        with _lock:
            if gen == _generation:
                _cache[key] = idx
        return idx

    def add(self, doc_id: int, vec: np.ndarray) -> None:
        """Append a vector to this (local) copy — used during batch processing."""
        vec = vec.reshape(1, -1)
        self.matrix = vec if self.matrix.size == 0 else np.vstack([self.matrix, vec])
        self.ids = np.append(self.ids, doc_id)

    def search(self, vec: np.ndarray, k: int = 10, exclude: Optional[set] = None,
               min_similarity: float = -1.0) -> list[tuple[int, float]]:
        if self.matrix.size == 0:
            return []
        sims = self.matrix @ vec
        order = np.argsort(-sims)
        out = []
        for i in order:
            did = int(self.ids[i])
            if exclude and did in exclude:
                continue
            s = float(sims[i])
            if s < min_similarity:
                break
            out.append((did, s))
            if len(out) >= k:
                break
        return out
