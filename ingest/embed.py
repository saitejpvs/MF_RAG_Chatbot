"""Batch-embed Phase 2 chunks (ingestion stage 3).

Thin wrapper around shared/embedder.py so the model is never loaded twice.
Dry-run only: prints shapes and a similarity check, writes nothing to Chroma.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from ingest.chunk import chunk_documents, read_chunks_jsonl
from ingest.load import load_documents
from shared.config import (
    DEBUG_DIR,
    EMBEDDING_DIM,
    EMBEDDING_MODEL,
    EMBED_BATCH_SIZE,
    USE_SCHEME_PREFIX,
)
from shared.embedder import build_embedding_input, embed_text, embed_texts, get_model
from shared.schemas import Chunk

logger = logging.getLogger(__name__)

PROBE_QUERY = "expense ratio HDFC large cap"


def embed_chunks(chunks: list[Chunk], *, batch_size: int = EMBED_BATCH_SIZE) -> np.ndarray:
    """Encode chunk text (scheme-name prefix applied per config) into (n, 384)."""
    return embed_texts(
        [c.text for c in chunks],
        scheme_names=[c.scheme_name for c in chunks],
        batch_size=batch_size,
    )


def format_vector(vector: np.ndarray, *, per_line: int = 8) -> str:
    parts = [f"{v:+.6f}" for v in vector]
    lines = [" ".join(parts[i : i + per_line]) for i in range(0, len(parts), per_line)]
    return "\n".join(f"      {line}" for line in lines)


def write_embedding_txt(
    chunks: list[Chunk],
    vectors: np.ndarray,
    path: Path,
    *,
    dims: int = EMBEDDING_DIM,
    probe: str = PROBE_QUERY,
) -> Path:
    """Dump chunks and their vectors to a human-readable txt file."""
    shown = min(dims, EMBEDDING_DIM)
    query_vec = embed_text(probe)
    # einsum, not `@`: numpy's matmul emits spurious fp warnings on this build.
    scores = np.einsum("ij,j->i", vectors.astype(np.float64), query_vec.astype(np.float64))

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        handle.write("MiniLM chunk + embedding dump\n")
        handle.write(f"generated:     {datetime.now(timezone.utc).isoformat()}\n")
        handle.write(f"model:         {EMBEDDING_MODEL}\n")
        handle.write(f"dimension:     {EMBEDDING_DIM} (showing first {shown})\n")
        handle.write(f"chunks:        {len(chunks)}\n")
        handle.write(f"vector dtype:  {vectors.dtype}\n")
        handle.write(f"norm min/max:  {np.linalg.norm(vectors, axis=1).min():.4f} / "
                     f"{np.linalg.norm(vectors, axis=1).max():.4f}\n")
        handle.write(f"scheme prefix: {USE_SCHEME_PREFIX}\n")
        handle.write(f"encoded text:  {build_embedding_input('Expense ratio: 1.03%', 'HDFC Large Cap Fund')}\n")
        handle.write(f"probe query:   {probe!r}\n")

        for position, (chunk, vector) in enumerate(zip(chunks, vectors)):
            handle.write("\n" + "=" * 96 + "\n")
            handle.write(f"[{position}] {chunk.chunk_id}\n")
            handle.write(f"    scheme:     {chunk.scheme_name}\n")
            handle.write(f"    category:   {chunk.category}   amc: {chunk.amc}\n")
            handle.write(f"    url:        {chunk.url}\n")
            handle.write(f"    chars:      {len(chunk.text)}\n")
            handle.write(f"    fetched_at: {chunk.fetched_at.isoformat()}\n")
            handle.write(f"    vector:     norm {float(np.linalg.norm(vector)):.4f}, "
                         f"cosine to probe {float(scores[position]):.4f}\n")
            handle.write(format_vector(vector[:shown]) + "\n")
            handle.write("    text:\n")
            for line in chunk.text.splitlines():
                handle.write(f"      | {line}\n")

        handle.write("\n" + "=" * 96 + "\n")
        handle.write(f"Query vector for {probe!r} (norm {float(np.linalg.norm(query_vec)):.4f})\n")
        handle.write(format_vector(query_vec[:shown]) + "\n")
        handle.write("\nTop matches by cosine\n")
        for rank, idx in enumerate(np.argsort(-scores)[:4], start=1):
            handle.write(f"  {rank}. cosine {float(scores[idx]):.4f}  {chunks[int(idx)].chunk_id}\n")
            handle.write(f"     {chunks[int(idx)].scheme_name}\n")
            handle.write(f"     {chunks[int(idx)].url}\n")
    return path


def collect_chunks(jsonl: Path | None, *, save_raw: bool = True) -> list[Chunk]:
    if jsonl and jsonl.exists():
        chunks = read_chunks_jsonl(jsonl)
        logger.info("Read %s chunk(s) from %s", len(chunks), jsonl)
        return chunks
    if jsonl:
        logger.warning("%s not found; running Load -> Chunk instead", jsonl)
    documents = load_documents(save_raw=save_raw)
    if not documents:
        logger.error("No documents loaded; nothing to embed")
        return []
    return chunk_documents(documents)


def inspect_embeddings(chunks: list[Chunk], vectors: np.ndarray, *, probe: str) -> None:
    norms = np.linalg.norm(vectors, axis=1)
    print(f"model:        {get_model()}")
    print(f"dimension:    {EMBEDDING_DIM}")
    print(f"chunks:       {len(chunks)}")
    print(f"shape:        {vectors.shape}")
    print(f"dtype:        {vectors.dtype}")
    print(f"norm min/max: {norms.min():.4f} / {norms.max():.4f}")
    print(f"prefix rule:  {build_embedding_input('Expense ratio: 0.52%', 'HDFC Large Cap Fund – Direct Growth')}")
    print()

    query_vec = embed_text(probe)
    # einsum, not `@`: numpy's matmul emits spurious fp warnings on this build.
    scores = np.einsum("ij,j->i", vectors.astype(np.float64), query_vec.astype(np.float64))
    order = np.argsort(-scores)[:3]
    print(f"Similarity check for: {probe!r}")
    for rank, idx in enumerate(order, start=1):
        chunk = chunks[int(idx)]
        preview = chunk.text.replace("\n", " | ")[:160]
        print(f"  {rank}. {float(scores[idx]):.3f}  {chunk.chunk_id}")
        print(f"     {chunk.scheme_name} | {preview}")
    print()
    print("Nothing written to Chroma; that is Phase 4.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Dry-run chunk embeddings (Phase 3).")
    parser.add_argument(
        "--jsonl",
        type=Path,
        default=DEBUG_DIR / "chunks.jsonl",
        help="Reuse Phase 2 chunks from this JSONL instead of re-fetching pages",
    )
    parser.add_argument("--limit", type=int, default=0, help="Embed only the first N chunks")
    parser.add_argument("--batch-size", type=int, default=EMBED_BATCH_SIZE)
    parser.add_argument("--probe", default=PROBE_QUERY, help="Question used for the similarity check")
    parser.add_argument(
        "--dump",
        type=Path,
        default=DEBUG_DIR / "embeddings.txt",
        help="Write chunks + vectors to this txt file",
    )
    parser.add_argument(
        "--no-dump",
        action="store_true",
        help="Skip the txt dump",
    )
    parser.add_argument(
        "--dims",
        type=int,
        default=EMBEDDING_DIM,
        help="How many of the 384 dims to print per vector",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    chunks = collect_chunks(args.jsonl)
    if not chunks:
        return 1
    if args.limit > 0:
        chunks = chunks[: args.limit]

    vectors = embed_chunks(chunks, batch_size=args.batch_size)
    inspect_embeddings(chunks, vectors, probe=args.probe)

    if not args.no_dump:
        dump_path = write_embedding_txt(chunks, vectors, args.dump, dims=args.dims, probe=args.probe)
        print(f"Wrote {dump_path} ({dump_path.stat().st_size} bytes)")

    if vectors.shape != (len(chunks), EMBEDDING_DIM):
        logger.error("Expected (%s, %s), got %s", len(chunks), EMBEDDING_DIM, vectors.shape)
        return 1
    if any(not c.url or not c.scheme_name for c in chunks):
        logger.error("Every chunk must carry url and scheme_name")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
