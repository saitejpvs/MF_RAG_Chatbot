"""Recursive, section-aware chunking (ingestion stage 2).

Not semantic chunking. Does not embed or write to Chroma.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from ingest.load import load_documents
from shared.config import (
    CHUNK_OVERLAP,
    CHUNK_SIZE,
    DEBUG_DIR,
    MIN_CHUNK_SIZE,
)
from shared.schemas import Chunk, Document

logger = logging.getLogger(__name__)

# Headings first, then paragraph / line / sentence / word / character.
SEPARATORS = (
    "\n## ",
    "\n# ",
    "\n\n",
    "\n",
    ". ",
    " ",
    "",
)


def split_text(
    text: str,
    *,
    chunk_size: int = CHUNK_SIZE,
    chunk_overlap: int = CHUNK_OVERLAP,
    separators: tuple[str, ...] = SEPARATORS,
) -> list[str]:
    text = text.strip()
    if not text:
        return []
    raw = _split_recursive(text, list(separators), chunk_size, chunk_overlap)
    return _coalesce_small(raw, min_size=MIN_CHUNK_SIZE, chunk_size=chunk_size)


def _split_recursive(
    text: str,
    separators: list[str],
    chunk_size: int,
    chunk_overlap: int,
) -> list[str]:
    if len(text) <= chunk_size:
        return [text] if text else []

    if not separators:
        return _sliding_windows(text, chunk_size, chunk_overlap)

    separator, rest = separators[0], separators[1:]
    if separator == "":
        return _sliding_windows(text, chunk_size, chunk_overlap)

    parts = text.split(separator)
    if len(parts) <= 1:
        return _split_recursive(text, rest, chunk_size, chunk_overlap)

    pieces: list[str] = []
    for part in parts:
        if len(part) > chunk_size:
            pieces.extend(_split_recursive(part, rest, chunk_size, chunk_overlap))
        else:
            pieces.append(part)
    return _merge_splits(pieces, separator, chunk_size, chunk_overlap)


def _overlap_suffix(text: str, overlap: int) -> str:
    """Prefer a newline-aligned suffix so labeled facts are not cut mid-line."""
    if overlap <= 0 or not text:
        return ""
    suffix = text[-overlap:]
    newline = suffix.find("\n")
    if newline >= 0 and newline + 1 < len(suffix):
        return suffix[newline + 1 :]
    return suffix


def _sliding_windows(text: str, chunk_size: int, chunk_overlap: int) -> list[str]:
    if chunk_overlap >= chunk_size:
        raise ValueError("chunk_overlap must be smaller than chunk_size")
    step = chunk_size - chunk_overlap
    windows: list[str] = []
    start = 0
    while start < len(text):
        windows.append(text[start : start + chunk_size])
        if start + chunk_size >= len(text):
            break
        start += step
    return windows


def _merge_splits(
    pieces: list[str],
    separator: str,
    chunk_size: int,
    chunk_overlap: int,
) -> list[str]:
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    sep_len = len(separator)

    def flush() -> None:
        nonlocal current, current_len
        if not current:
            return
        chunks.append(separator.join(current).strip())
        current = []
        current_len = 0

    for piece in pieces:
        extra = len(piece) + (sep_len if current else 0)
        if current and current_len + extra > chunk_size:
            flush()
            if chunk_overlap > 0 and chunks:
                overlap_text = _overlap_suffix(chunks[-1], chunk_overlap)
                if overlap_text:
                    current = [overlap_text]
                    current_len = len(overlap_text)
                else:
                    current = []
                    current_len = 0
                extra = len(piece) + (sep_len if current else 0)
                if current_len + extra > chunk_size:
                    flush()
        if not piece and not current:
            continue
        current.append(piece)
        current_len += extra if current_len else len(piece)
    flush()
    return [c for c in chunks if c]


def _coalesce_small(chunks: list[str], *, min_size: int, chunk_size: int) -> list[str]:
    if not chunks:
        return []
    merged: list[str] = []
    for chunk in chunks:
        if merged and len(chunk) < min_size:
            candidate = f"{merged[-1].rstrip()}\n{chunk.lstrip()}"
            if len(candidate) <= chunk_size + min_size:
                merged[-1] = candidate
                continue
        if len(chunk) < min_size and merged:
            merged[-1] = f"{merged[-1].rstrip()}\n{chunk.lstrip()}"
            continue
        merged.append(chunk)
    if len(merged) > 1 and len(merged[-1]) < min_size:
        tail = merged.pop()
        merged[-1] = f"{merged[-1].rstrip()}\n{tail.lstrip()}"
    return merged


def chunk_document(document: Document) -> list[Chunk]:
    parts = split_text(document.text)
    chunks: list[Chunk] = []
    for index, part in enumerate(parts):
        chunks.append(
            Chunk(
                chunk_id=f"{document.doc_id}::{index}",
                doc_id=document.doc_id,
                text=part,
                url=document.url,
                scheme_name=document.scheme_name,
                category=document.category,
                amc=document.amc,
                chunk_index=index,
                fetched_at=document.fetched_at,
            )
        )
    return chunks


def chunk_documents(documents: list[Document]) -> list[Chunk]:
    chunks: list[Chunk] = []
    for document in documents:
        doc_chunks = chunk_document(document)
        logger.info("%s -> %s chunk(s)", document.doc_id, len(doc_chunks))
        chunks.extend(doc_chunks)
    return chunks


def _chunk_to_json(chunk: Chunk) -> dict:
    return {
        "chunk_id": chunk.chunk_id,
        "doc_id": chunk.doc_id,
        "chunk_index": chunk.chunk_index,
        "url": chunk.url,
        "scheme_name": chunk.scheme_name,
        "category": chunk.category,
        "amc": chunk.amc,
        "fetched_at": chunk.fetched_at.isoformat(),
        "chars": len(chunk.text),
        "text": chunk.text,
    }


def write_chunks_jsonl(chunks: list[Chunk], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for chunk in chunks:
            handle.write(json.dumps(_chunk_to_json(chunk), ensure_ascii=False) + "\n")


def read_chunks_jsonl(path: Path) -> list[Chunk]:
    """Load chunks written by write_chunks_jsonl, so later stages can skip re-fetching."""
    chunks: list[Chunk] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            raw = json.loads(line)
            chunks.append(
                Chunk(
                    chunk_id=raw["chunk_id"],
                    doc_id=raw["doc_id"],
                    text=raw["text"],
                    url=raw["url"],
                    scheme_name=raw["scheme_name"],
                    category=raw["category"],
                    amc=raw["amc"],
                    chunk_index=int(raw["chunk_index"]),
                    fetched_at=datetime.fromisoformat(raw["fetched_at"]),
                )
            )
    return chunks


def inspect_chunks(chunks: list[Chunk]) -> None:
    by_doc: dict[str, list[Chunk]] = defaultdict(list)
    for chunk in chunks:
        by_doc[chunk.doc_id].append(chunk)

    print(f"Total chunks: {len(chunks)} across {len(by_doc)} document(s)\n")
    for doc_id, doc_chunks in by_doc.items():
        sizes = [len(c.text) for c in doc_chunks]
        missing_meta = [c.chunk_id for c in doc_chunks if not c.url or not c.scheme_name]
        print("=" * 80)
        print(f"doc_id:        {doc_id}")
        print(f"chunk count:   {len(doc_chunks)}")
        print(f"chars min/max: {min(sizes)} / {max(sizes)}")
        print(f"url+name ok:   {not missing_meta}")
        for sample in doc_chunks[:3]:
            preview = sample.text.replace("\n", " | ")
            if len(preview) > 220:
                preview = preview[:220] + "…"
            print(f"  [{sample.chunk_index}] {sample.chunk_id} ({len(sample.text)} chars)")
            print(f"      {preview}")
        print()

    print("Spot-check: Exit load / lock-in lines kept intact")
    for chunk in chunks:
        for line in chunk.text.splitlines():
            if line.lower().startswith("exit load:") or line.lower().startswith("lock-in:"):
                print(f"  {chunk.chunk_id}: {line}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inspect recursive chunking (Phase 2).")
    parser.add_argument(
        "--out",
        type=Path,
        default=DEBUG_DIR / "chunks.jsonl",
        help="JSONL path for all chunks",
    )
    parser.add_argument("--no-raw", action="store_true", help="Pass through to loader")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    documents = load_documents(save_raw=not args.no_raw)
    if not documents:
        logger.error("No documents loaded; cannot chunk")
        return 1

    chunks = chunk_documents(documents)
    write_chunks_jsonl(chunks, args.out)
    inspect_chunks(chunks)
    print(f"Wrote {args.out}")

    by_doc: dict[str, list[Chunk]] = defaultdict(list)
    for chunk in chunks:
        by_doc[chunk.doc_id].append(chunk)
    if len(by_doc) != 5:
        logger.error("Expected 5 documents, got %s", len(by_doc))
        return 1
    if any(len(items) < 2 for items in by_doc.values()):
        logger.error("Each document should produce multiple chunks")
        return 1
    if any(not c.url or not c.scheme_name for c in chunks):
        logger.error("Every chunk must have url and scheme_name")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
