"""
Sentence embeddings (Sentence-Transformers) with lazy loading.

Vectors are L2-normalised so cosine similarity is a plain dot product, and are
persisted as float32 bytes (see models.embedding.DocumentEmbedding).
"""

import logging
import threading
from typing import Optional, Sequence

import numpy as np

from backend.app.config import get_settings

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_infer_lock = threading.Lock()
_model = None
_model_name: Optional[str] = None


def model_name() -> str:
    return get_settings().EMBEDDING_MODEL


def get_encoder():
    global _model, _model_name
    name = model_name()
    if _model is not None and _model_name == name:
        return _model
    with _lock:
        if _model is None or _model_name != name:
            from sentence_transformers import SentenceTransformer
            logger.info("Loading embedding model %s", name)
            _model = SentenceTransformer(name)
            _model_name = name
    return _model


def encode(texts: Sequence[str], batch_size: int = 64) -> np.ndarray:
    if not texts:
        return np.zeros((0, get_settings().EMBEDDING_DIMENSION), dtype=np.float32)
    model = get_encoder()
    # One inference at a time per process: concurrent torch forward passes from API threads
    # and background jobs multiply peak memory and were observed to crash under pressure.
    with _infer_lock:
        vecs = model.encode(list(texts), batch_size=batch_size, normalize_embeddings=True,
                            show_progress_bar=False, convert_to_numpy=True)
    return vecs.astype(np.float32)


def to_bytes(vec: np.ndarray) -> bytes:
    return np.asarray(vec, dtype=np.float32).tobytes()


def from_bytes(blob: bytes) -> np.ndarray:
    return np.frombuffer(blob, dtype=np.float32)
