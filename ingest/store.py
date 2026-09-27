"""Persist chunks in ChromaDB (ingestion stage 4).

Upserts by chunk_id so re-ingest is idempotent. No query service, no LLM.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Any, Sequence

import numpy as np

from shared.config import CHROMA_DIR, COLLECTION_NAME, EMBEDDING_DIM, RETRIEVE_K
from shared.embedder import embed_text
from shared.schemas import Chunk

logger = logging.getLogger(__name__)

CHROMA_DISTANCE = "cosine"
SMOKE_QUERY = "expense ratio HDFC large cap"


def get_client(persist_dir: Path | None = None) -> Any:
    """Open the persistent client; data survives process restarts."""
    import chromadb

    path = persist_dir or CHROMA_DIR
    path.mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(path=str(path))


def get_collection(client: Any, *, name: str = COLLECTION_NAME) -> Any:
    return client.get_or_create_collection(
        name=name,
        metadata={"hnsw:space": CHROMA_DISTANCE, "embedding_dim": EMBEDDING_DIM},
    )


def chunk_metadata(chunk: Chunk) -> dict[str, str | int]:
    """Chroma metadata accepts only str/int/float/bool, so datetime is ISO text."""
    return {
        "doc_id": chunk.doc_id,
        "url": chunk.url,
        "scheme_name": chunk.scheme_name,
        "category": chunk.category,
        "amc": chunk.amc,
        "chunk_index": int(chunk.chunk_index),
        "fetched_at": chunk.fetched_at.isoformat(),
    }


def upsert_chunks(
    collection: Any,
    chunks: Sequence[Chunk],
    vectors: np.ndarray,
) -> int:
    """Upsert chunk text + metadata + vectors keyed on chunk_id."""
    if len(chunks) != len(vectors):
        raise ValueError(f"{len(chunks)} chunks but {len(vectors)} vectors")
    if not chunks:
        return 0
    collection.upsert(
        ids=[c.chunk_id for c in chunks],
        documents=[c.text for c in chunks],
        metadatas=[chunk_metadata(c) for c in chunks],
        embeddings=[v.tolist() for v in vectors],
    )
    return len(chunks)


def corpus_last_updated(chunks: Sequence[Chunk]) -> str:
    """Corpus-level stamp = newest fetched_at across ingested chunks."""
    return max(c.fetched_at for c in chunks).isoformat()


def record_last_updated(collection: Any, last_updated: str) -> None:
    collection.modify(metadata={"last_updated_from_sources": last_updated})


def get_last_updated(collection: Any) -> str | None:
    return (collection.metadata or {}).get("last_updated_from_sources")


def smoke_query(
    collection: Any,
    question: str = SMOKE_QUERY,
    *,
    k: int = RETRIEVE_K,
) -> list[dict[str, Any]]:
    """One-off similarity check. Phase 5 builds the real query service."""
    if collection.count() == 0:
        logger.error("Collection %s is empty; run ingest first", collection.name)
        return []
    query_vec = embed_text(question)
    result = collection.query(
        query_embeddings=[query_vec.tolist()],
        n_results=min(k, collection.count()),
        include=["documents", "metadatas", "distances"],
    )
    hits: list[dict[str, Any]] = []
    documents = (result.get("documents") or [[]])[0]
    metadatas = (result.get("metadatas") or [[]])[0]
    distances = (result.get("distances") or [[]])[0]
    for doc, meta, dist in zip(documents, metadatas, distances):
        hits.append(
            {
                "scheme_name": meta.get("scheme_name"),
                "url": meta.get("url"),
                "distance": float(dist),
                "preview": (doc or "").replace("\n", " | ")[:160],
            }
        )
    return hits


def print_smoke_query(collection: Any, question: str = SMOKE_QUERY) -> None:
    hits = smoke_query(collection, question)
    if not hits:
        return
    print(f"Smoke query: {question!r}")
    for rank, hit in enumerate(hits, start=1):
        print(f"  {rank}. distance={hit['distance']:.4f}  {hit['scheme_name']}")
        print(f"     {hit['url']}")
        print(f"     {hit['preview']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inspect the persistent Chroma store (Phase 4).")
    parser.add_argument("--query", default=SMOKE_QUERY, help="Smoke query text")
    parser.add_argument("--k", type=int, default=RETRIEVE_K)
    parser.add_argument("--persist-dir", type=Path, default=CHROMA_DIR)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if not args.persist_dir.exists():
        logger.error("%s not found; run: python -m ingest.run", args.persist_dir)
        return 1

    client = get_client(args.persist_dir)
    collection = get_collection(client)
    print(f"persist dir:    {args.persist_dir}")
    print(f"collection:     {collection.name}")
    print(f"distance:       {CHROMA_DISTANCE}")
    print(f"chunks stored:  {collection.count()}")
    print(f"last updated:   {get_last_updated(collection) or 'not recorded'}")
    print()
    print_smoke_query(collection, args.query)
    return 0 if collection.count() > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
