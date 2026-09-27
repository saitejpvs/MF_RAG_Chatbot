"""Retrieve chunks for a question (retrieval stage 2, architecture 6.3).

Embeds with the same shared/embedder.py used at ingest, then queries the
persistent Chroma collection: metadata filter on a named scheme first,
unfiltered top-k as fallback. No LLM here.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from ingest.store import get_client, get_collection
from shared.config import CHROMA_DIR, RETRIEVE_K
from shared.embedder import embed_text
from shared.schemas import RetrievedChunk

logger = logging.getLogger(__name__)

# alias phrase -> doc_id (matches data/sources.csv)
SCHEME_ALIASES: dict[str, tuple[str, ...]] = {
    "hdfc-large-cap-direct-growth": (
        "hdfc large cap",
        "hdfc-large-cap",
        "large cap fund",
        "largecap fund",
    ),
    "hdfc-equity-direct-growth": (
        "hdfc equity",
        "hdfc-equity",
        "flexi cap fund",
        "flexicap",
        "equity fund",
    ),
    "hdfc-elss-tax-saver-direct-growth": (
        "hdfc elss",
        "hdfc-elss",
        "elss",
        "tax saver",
        "tax-saver",
    ),
    "hdfc-small-cap-direct-growth": (
        "hdfc small cap",
        "hdfc-small-cap",
        "small cap fund",
        "smallcap fund",
    ),
    "hdfc-balanced-advantage-direct-growth": (
        "hdfc balanced advantage",
        "balanced advantage fund",
        "balanced advantage",
    ),
}

# Longest aliases first so "hdfc large cap" wins over a shorter partial match.
_ALIAS_INDEX: list[tuple[str, str]] = sorted(
    ((alias, doc_id) for doc_id, aliases in SCHEME_ALIASES.items() for alias in aliases),
    key=lambda pair: len(pair[0]),
    reverse=True,
)


def _load_scheme_names() -> dict[str, str]:
    """doc_id -> scheme_name, from the same CSV the loader used."""
    from ingest.load import read_sources

    return {row.doc_id: row.scheme_name for row in read_sources()}


def match_scheme(question: str) -> str | None:
    """Return the scheme_name named in the question, else None."""
    lowered = question.lower()
    names = _load_scheme_names()
    for alias, doc_id in _ALIAS_INDEX:
        if re.search(rf"(?<!\w){re.escape(alias)}(?!\w)", lowered):
            return names.get(doc_id)
    return None


def open_collection() -> Any | None:
    """Open the Phase 4 collection, or None if ingest has not been run."""
    if not CHROMA_DIR.exists():
        logger.error("%s not found. Run: python -m ingest.run", CHROMA_DIR)
        return None
    return get_collection(get_client())


def get_corpus_stamp(collection: Any | None = None) -> str | None:
    """Corpus-level last_updated_from_sources recorded by ingest."""
    from ingest.store import get_last_updated

    target = collection if collection is not None else open_collection()
    if target is None:
        return None
    return get_last_updated(target)


def _to_hits(result: dict[str, Any]) -> list[RetrievedChunk]:
    ids = (result.get("ids") or [[]])[0]
    documents = (result.get("documents") or [[]])[0]
    metadatas = (result.get("metadatas") or [[]])[0]
    distances = (result.get("distances") or [[]])[0]
    hits: list[RetrievedChunk] = []
    for chunk_id, document, meta, distance in zip(ids, documents, metadatas, distances):
        hits.append(
            RetrievedChunk(
                chunk_id=chunk_id,
                text=document or "",
                url=meta.get("url", ""),
                scheme_name=meta.get("scheme_name", ""),
                category=meta.get("category", ""),
                amc=meta.get("amc", ""),
                chunk_index=int(meta.get("chunk_index", 0)),
                fetched_at=meta.get("fetched_at", ""),
                distance=float(distance),
            )
        )
    return hits


def retrieve(
    question: str,
    *,
    k: int = RETRIEVE_K,
    collection: Any | None = None,
    use_filter: bool = True,
) -> tuple[list[RetrievedChunk], str | None, bool]:
    """Return (hits, scheme_filter, used_fallback).

    Filters on scheme_name when the question names a known scheme, and falls
    back to global top-k when the filter returns too little. Pass
    use_filter=False to always take the unfiltered top-k.
    """
    collection = collection or open_collection()
    if collection is None:
        return [], None, False

    total = collection.count()
    if total == 0:
        logger.error("Collection is empty. Run: python -m ingest.run")
        return [], None, False

    n_results = min(k, total)
    query_embedding = embed_text(question).tolist()
    scheme_name = match_scheme(question) if use_filter else None

    if scheme_name:
        filtered = collection.query(
            query_embeddings=[query_embedding],
            n_results=n_results,
            where={"scheme_name": scheme_name},
            include=["documents", "metadatas", "distances"],
        )
        hits = _to_hits(filtered)
        if hits:
            return hits, scheme_name, False
        logger.warning("No hits for scheme %s; falling back to global top-k", scheme_name)

    global_hits = collection.query(
        query_embeddings=[query_embedding],
        n_results=n_results,
        include=["documents", "metadatas", "distances"],
    )
    return _to_hits(global_hits), scheme_name, bool(scheme_name)


# --- Retrieval test CLI -------------------------------------------------------
# Inspect-only helper: rank chunks for a question without calling an LLM.
#   python -m app.query.retrieve -q "expense ratio of HDFC large cap"

SUITE_CASES: tuple[tuple[str, str, str], ...] = (
    # (question, expected label in the winning scheme's text, expected doc_id)
    ("expense ratio HDFC large cap", "expense ratio:", "hdfc-large-cap-direct-growth"),
    ("minimum SIP amount HDFC small cap", "minimum sip:", "hdfc-small-cap-direct-growth"),
    ("lock-in period HDFC ELSS tax saver", "lock-in:", "hdfc-elss-tax-saver-direct-growth"),
    ("exit load HDFC equity flexi cap", "exit load", "hdfc-equity-direct-growth"),
    ("riskometer level HDFC balanced advantage", "riskometer:", "hdfc-balanced-advantage-direct-growth"),
    ("benchmark of HDFC large cap", "benchmark", "hdfc-large-cap-direct-growth"),
    ("NAV HDFC small cap", "nav:", "hdfc-small-cap-direct-growth"),
    ("minimum lumpsum HDFC ELSS", "minimum lumpsum", "hdfc-elss-tax-saver-direct-growth"),
)


def _print_hits(hits: list[RetrievedChunk], *, needle: str | None, full: bool) -> None:
    for rank, hit in enumerate(hits, start=1):
        has = needle is None or needle.lower() in hit.text.lower()
        mark = "" if needle is None else ("  <-- has needle" if has else "")
        print(f"{rank}. distance={hit.distance:.4f}  {hit.chunk_id}{mark}")
        print(f"   {hit.scheme_name}  ({len(hit.text)} chars, fetched {hit.fetched_at})")
        body = hit.text if full else hit.text.replace("\n", " | ")[:200]
        print(f"   {body}")


def run_suite(*, k: int) -> int:
    """Report, per question, whether the expected fact and scheme made top-k."""
    passed = 0
    print(f"Retrieval suite (top-{k}, cosine distance lower is better)\n")
    for question, needle, expected_doc in SUITE_CASES:
        hits, scheme_filter, _ = retrieve(question, k=k)
        docs = {hit.chunk_id.rsplit("::", 1)[0] for hit in hits}
        with_needle = [hit for hit in hits if needle.lower() in hit.text.lower()]
        needle_doc = with_needle[0].chunk_id.rsplit("::", 1)[0] if with_needle else None
        scheme_ok = expected_doc in docs
        fact_ok = bool(with_needle)
        right_fact = needle_doc == expected_doc
        status = "PASS" if (scheme_ok and fact_ok and right_fact) else "FAIL"
        passed += status == "PASS"
        best = f"{with_needle[0].distance:.4f}" if with_needle else "n/a"
        print(f"[{status}] rank of '{needle}': {hits.index(with_needle[0]) + 1 if with_needle else '-'}/{len(hits)}"
              f"  dist={best}  filter={'yes' if scheme_filter else 'no':3s}  | {question}")
    print(f"\n{passed}/{len(SUITE_CASES)} passed")
    return 0 if passed == len(SUITE_CASES) else 1


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Inspect retrieval quality, no LLM.")
    parser.add_argument("-q", "--q", "--question", dest="question", default=None)
    parser.add_argument("-k", type=int, default=4, help="hits to show (default 4)")
    parser.add_argument("--needle", default=None, help="label to look for, e.g. 'expense ratio:'")
    parser.add_argument("--no-filter", action="store_true", help="skip the scheme_name metadata filter")
    parser.add_argument("--text", action="store_true", help="print full chunk text")
    parser.add_argument("--suite", action="store_true", help="run the built-in retrieval suite")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.ERROR, format="%(levelname)s %(message)s")

    if args.suite:
        return run_suite(k=args.k)
    if not args.question:
        parser.error("provide -q QUESTION or --suite")

    question = args.question
    needle = args.needle
    hits, scheme_filter, used_fallback = retrieve(
        question, k=args.k, use_filter=not args.no_filter
    )

    print(f"question:      {question}")
    print(f"scheme filter: {scheme_filter or 'none (global top-k)'}"
          f"{'  [fallback used]' if used_fallback else ''}")
    print(f"hits ({len(hits)}):")
    _print_hits(hits, needle=needle, full=args.text)
    if needle and not any(needle.lower() in hit.text.lower() for hit in hits):
        print(f"\nNeedle {needle!r} is NOT in any of these chunks. Try -k 8, add the scheme name,")
        print("or check the label wording with: python -m ingest.embed --dump data/debug/embeddings.txt")
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
