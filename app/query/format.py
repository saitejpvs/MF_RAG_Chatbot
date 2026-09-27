"""Response formatting (retrieval stage 4, architecture 6.4-6.5).

Picks exactly one citation URL from the retrieved set, stamps the last-updated
date, and returns the response contract the UI consumes.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Iterable

from shared.config import MAX_ANSWER_SENTENCES, WEAK_RETRIEVAL_DISTANCE
from shared.schemas import QueryResult, RetrievedChunk

DISCLAIMER = "Facts only. No investment advice."

MISSING_FACT_ANSWER = (
    "I could not find that fact on the HDFC scheme pages I have. "
    "Please check the linked scheme page for the latest published details."
)


def split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", (text or "").strip())
    return [part.strip() for part in parts if part.strip()]


def strip_markup(text: str) -> str:
    """Drop the markdown emphasis/bullet wrappers some models add, so the answer
    field is plain text in the response contract and in sample_qa.md."""
    cleaned = re.sub(r"\*\*(.+?)\*\*", r"\1", text or "")
    cleaned = re.sub(r"(?<!\w)\*(?!\s)|(?<!\s)\*(?!\w)", "", cleaned)
    cleaned = re.sub(r"^[\-\u2022]\s*", "", cleaned, flags=re.MULTILINE)
    return re.sub(r"\s{2,}", " ", cleaned).strip()


def limit_sentences(answer: str, max_sentences: int = MAX_ANSWER_SENTENCES) -> str:
    """Hard cap on sentence count, in case the model ignored the instruction."""
    answer = strip_markup(answer)
    sentences = split_sentences(answer)[:max_sentences]
    if not sentences:
        return ""
    if not sentences[-1].endswith((".", "!", "?")):
        sentences[-1] = sentences[-1].rstrip(" ,;:")
        # A model cut off mid-clause (token budget) leaves a dangling opener such as
        # "is a hybrid (". Drop the fragment rather than show a broken sentence.
        if re.search(r"[\(\[\u2013\u2014-]\s*$", sentences[-1]):
            sentences = sentences[:-1]
        else:
            sentences[-1] = f"{sentences[-1]}."
    return " ".join(part for part in sentences if part)


def retrieved_urls(hits: Iterable[RetrievedChunk]) -> set[str]:
    return {hit.url for hit in hits if hit.url}


def pick_citation_url(
    hits: list[RetrievedChunk],
    *,
    scheme_name: str | None = None,
    proposed: str | None = None,
) -> str:
    """Exactly one URL, always from the retrieved set (architecture 6.4)."""
    if not hits:
        return ""
    allowed = retrieved_urls(hits)
    if proposed and proposed in allowed:
        return proposed
    if scheme_name:
        for hit in hits:
            if hit.scheme_name == scheme_name and hit.url in allowed:
                return hit.url
    return hits[0].url


def citation_from_answer(answer: str, hits: list[RetrievedChunk]) -> str | None:
    """Use a URL the model mentioned, but only if it was actually retrieved."""
    allowed = retrieved_urls(hits)
    for url in re.findall(r"https?://[^\s)\]]+", answer or ""):
        cleaned = url.rstrip(".,;")
        if cleaned in allowed:
            return cleaned
    return None


def is_weak_retrieval(hits: list[RetrievedChunk], threshold: float = WEAK_RETRIEVAL_DISTANCE) -> bool:
    return bool(hits) and min(hit.distance for hit in hits) > threshold


def last_updated_from_sources(
    hits: list[RetrievedChunk],
    *,
    corpus_stamp: str | None = None,
) -> str:
    """ISO date of the newest source behind this answer."""
    stamps = [hit.fetched_at for hit in hits if hit.fetched_at]
    if not stamps and corpus_stamp:
        stamps = [corpus_stamp]
    if not stamps:
        return ""
    newest = max(stamps)
    try:
        return datetime.fromisoformat(newest).date().isoformat()
    except ValueError:
        return newest[:10]


def build_response(
    result: QueryResult,
    answer: str,
    *,
    citation_url: str = "",
    corpus_stamp: str | None = None,
) -> dict[str, Any]:
    """Architecture 6.5 response contract."""
    return {
        "answer": answer,
        "citation_url": citation_url,
        "last_updated_from_sources": last_updated_from_sources(result.hits, corpus_stamp=corpus_stamp),
        "intent": result.intent,
        "disclaimer": DISCLAIMER,
    }
