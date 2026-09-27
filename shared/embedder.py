"""Shared MiniLM embedder (ingestion stage 3, reused by query at Phase 5).

Single wrapper so ingest and query encode with the same model, the same
prefix rule, and the same normalization. Does not write to Chroma.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Sequence

import numpy as np

from shared.config import (
    EMBED_BATCH_SIZE,
    EMBED_NORMALIZE,
    EMBEDDING_DIM,
    EMBEDDING_MODEL,
    USE_SCHEME_PREFIX,
)

logger = logging.getLogger(__name__)

__all__ = [
    "EMBEDDING_MODEL",
    "EMBEDDING_DIM",
    "USE_SCHEME_PREFIX",
    "build_embedding_input",
    "embed_texts",
    "embed_text",
    "get_model",
]


@lru_cache(maxsize=1)
def get_model():
    """Load all-MiniLM-L6-v2 once per process."""
    from sentence_transformers import SentenceTransformer

    logger.info("Loading embedding model %s", EMBEDDING_MODEL)
    model = SentenceTransformer(EMBEDDING_MODEL)
    dimension = model.get_sentence_embedding_dimension()
    if dimension != EMBEDDING_DIM:
        raise ValueError(
            f"{EMBEDDING_MODEL} returns {dimension}-dim vectors, expected {EMBEDDING_DIM}"
        )
    return model


def build_embedding_input(text: str, scheme_name: str | None = None) -> str:
    """Apply the one prefix rule shared by ingest and query.

    With USE_SCHEME_PREFIX on, a known scheme name is prepended as
    "{scheme_name}. {text}". When the scheme is unknown (e.g. a user question
    with no scheme matched) the text is encoded unchanged.
    """
    text = text.strip()
    if USE_SCHEME_PREFIX and scheme_name and scheme_name.strip():
        return f"{scheme_name.strip()}. {text}"
    return text


def embed_texts(
    texts: Sequence[str],
    *,
    scheme_names: Sequence[str | None] | None = None,
    batch_size: int = EMBED_BATCH_SIZE,
) -> np.ndarray:
    """Encode texts into an (n, 384) float32 array.

    scheme_names, when given, must align with texts and drives the prefix rule.
    """
    items = [str(t) for t in texts]
    if not items:
        return np.zeros((0, EMBEDDING_DIM), dtype=np.float32)
    if scheme_names is not None:
        if len(scheme_names) != len(items):
            raise ValueError("scheme_names must be the same length as texts")
        items = [build_embedding_input(t, s) for t, s in zip(items, scheme_names)]

    vectors = get_model().encode(
        items,
        batch_size=batch_size,
        convert_to_numpy=True,
        normalize_embeddings=EMBED_NORMALIZE,
        show_progress_bar=False,
    )
    vectors = np.asarray(vectors, dtype=np.float32)
    if vectors.shape != (len(items), EMBEDDING_DIM):
        raise ValueError(f"unexpected embedding shape {vectors.shape}")
    return vectors


def embed_text(text: str, *, scheme_name: str | None = None) -> np.ndarray:
    """Encode a single text into a (384,) float32 vector."""
    return embed_texts([text], scheme_names=[scheme_name])[0]
