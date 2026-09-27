"""Full ingest CLI: Load -> Chunk -> Embed -> Store.

    python -m ingest.run

Each stage stays in its own module; this file only orchestrates them.
Idempotent: re-running upserts the same chunk_ids.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Any, NamedTuple, Sequence

from ingest.chunk import write_chunks_jsonl
from ingest.embed import collect_chunks, embed_chunks
from ingest.store import (
    SMOKE_QUERY,
    corpus_last_updated,
    get_client,
    get_collection,
    print_smoke_query,
    record_last_updated,
    upsert_chunks,
)
from shared.config import CHROMA_DIR, DEBUG_DIR
from shared.schemas import Chunk

logger = logging.getLogger(__name__)


class IngestResult(NamedTuple):
    written: int
    count_before: int
    count_after: int
    persist_dir: Path
    collection_name: str
    last_updated: str
    collection: Any


def ingest(
    chunks: Sequence[Chunk],
    *,
    persist_dir: Path = CHROMA_DIR,
    save_chunks_to: Path | None = None,
) -> IngestResult | None:
    """Embed chunks and upsert them into the persistent Chroma collection."""
    if not chunks:
        logger.error("No chunks to ingest")
        return None

    if save_chunks_to is not None:
        write_chunks_jsonl(chunks, save_chunks_to)

    vectors = embed_chunks(chunks)
    client = get_client(persist_dir)
    collection = get_collection(client)
    before = collection.count()
    written = upsert_chunks(collection, chunks, vectors)
    last_updated = corpus_last_updated(chunks)
    record_last_updated(collection, last_updated)

    return IngestResult(
        written=written,
        count_before=before,
        count_after=collection.count(),
        persist_dir=persist_dir,
        collection_name=collection.name,
        last_updated=last_updated,
        collection=collection,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Load -> Chunk -> Embed -> Store (Phase 4).")
    parser.add_argument(
        "--jsonl",
        type=Path,
        default=DEBUG_DIR / "chunks.jsonl",
        help="Reuse Phase 2 chunks from this JSONL instead of re-fetching the five pages",
    )
    parser.add_argument("--persist-dir", type=Path, default=CHROMA_DIR)
    parser.add_argument(
        "--no-chunk-dump",
        action="store_true",
        help="Do not rewrite the Phase 2 JSONL debug file",
    )
    parser.add_argument("--no-raw", action="store_true", help="Do not write data/raw/*.html")
    parser.add_argument("--smoke-query", default=SMOKE_QUERY, help="Similarity check after ingest")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    logger.info("Stages 1-3: Load -> Chunk -> Embed")
    chunks = collect_chunks(args.jsonl, save_raw=not args.no_raw)
    if not chunks:
        return 1

    logger.info("Stage 4: Store")
    result = ingest(
        chunks,
        persist_dir=args.persist_dir,
        save_chunks_to=None if args.no_chunk_dump else args.jsonl,
    )
    if result is None:
        return 1

    print()
    print(f"chunks upserted:  {result.written}")
    print(f"collection count: {result.count_before} -> {result.count_after} (upsert by chunk_id)")
    print(f"persist path:     {result.persist_dir}")
    print(f"collection:       {result.collection_name}")
    print(f"max fetched_at:   {result.last_updated}")
    print()
    print_smoke_query(result.collection, args.smoke_query)
    return 0 if result.count_after == len(chunks) else 1


if __name__ == "__main__":
    sys.exit(main())
