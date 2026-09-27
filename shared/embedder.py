"""Shared MiniLM embedder (ingestion stage 3, reused by query at Phase 5).

Single wrapper so ingest and query encode with the same model, the same
prefix rule, and the same normalization. Does not write to Chroma.

Runtime is ONNX, not sentence-transformers. Both paths serve the same
all-MiniLM-L6-v2 weights and produce vectors with cosine 1.0000 to each
other, so the Chroma store and every retrieval result carry over unchanged.
Torch was dropped because its 339 MB of shared libraries put the container
over Render's 512 MB free-tier limit (cgroup accounting counts the page
cache those mappings leave behind, which process-level RSS understates).
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
    """Load the MiniLM encoder once per process, on ONNX Runtime.

    chromadb ships this embedding function, so onnxruntime is the only
    inference dependency. The class is pinned to all-MiniLM-L6-v2, so fail
    loudly rather than silently serving a different model than the store.
    """
    from chromadb.utils.embedding_functions import ONNXMiniLM_L6_V2

    if EMBEDDING_MODEL != "sentence-transformers/all-MiniLM-L6-v2":
        raise ValueError(
            f"EMBEDDING_MODEL is {EMBEDDING_MODEL!r} but the ONNX embedder only "
            "implements sentence-transformers/all-MiniLM-L6-v2; the existing "
            "Chroma store would not match"
        )

    logger.info("Loading embedding model %s via ONNX Runtime", EMBEDDING_MODEL)
    return ONNXMiniLM_L6_V2()


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

    model = get_model()
    if batch_size and batch_size > 0 and len(items) > batch_size:
        # The ONNX embedder takes the whole list in one call, so chunk it here
        # to keep peak inference memory bounded for large batches.
        parts = [
            np.asarray(list(model(input=items[i : i + batch_size])), dtype=np.float32)
            for i in range(0, len(items), batch_size)
        ]
        vectors = np.concatenate(parts, axis=0)
    else:
        vectors = np.asarray(list(model(input=items)), dtype=np.float32)

    if vectors.shape != (len(items), EMBEDDING_DIM):
        raise ValueError(f"unexpected embedding shape {vectors.shape}")
    if EMBED_NORMALIZE:
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        if not np.allclose(norms, 1.0, atol=1e-3):
            vectors = vectors / np.clip(norms, 1e-12, None)
    return vectors


def embed_text(text: str, *, scheme_name: str | None = None) -> np.ndarray:
    """Encode a single text into a (384,) float32 vector."""
    return embed_texts([text], scheme_names=[scheme_name])[0]
