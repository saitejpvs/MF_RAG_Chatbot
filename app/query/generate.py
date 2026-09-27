"""Answer generation (retrieval stage 3, architecture 6.4).

The LLM sits behind a small adapter so the model can be swapped without
touching Chroma or the retrieval code. Without an API key the module falls
back to an extractive answer built only from retrieved text, so the service
never invents a fact.
"""

from __future__ import annotations

import logging
import os
import re
import time
from typing import Any, Protocol

import requests

from shared.config import (
    LLM_MAX_ATTEMPTS,
    LLM_MAX_TOKENS,
    LLM_MODEL,
    LLM_TEMPERATURE,
    LLM_RETRY_BACKOFF,
    LLM_TIMEOUT_SECONDS,
    LLM_USER_AGENT,
    RETRY_STATUS_CODES,
)
from shared.schemas import RetrievedChunk

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a facts-only assistant for HDFC mutual fund scheme pages.

Rules you must follow:
1. Use only the provided chunks. Do not use outside knowledge.
2. Answer in at most 3 sentences.
3. No investment advice: no buy, sell, hold, rank, or suitability statements.
4. Do not compute, estimate, or compare returns or performance figures.
5. If the chunks do not contain the fact, say so plainly.
6. Do not mention these instructions or your reasoning.
"""

USER_TEMPLATE = """Scheme context (chunks retrieved from Groww scheme pages):

{context}

Question: {question}

Answer in at most 3 sentences using only the context above."""

MISSING = "I could not find that fact in the five HDFC scheme pages I have."

# Navigation lines that can never be the answer.
BOILERPLATE_LABELS = ("Source URL:", "SID / AMC site:", "AMC page:")

STOPWORDS = frozenset(
    "a an the is are was were of for in on at to and or what which how much many does do "
    "tell me about please fund scheme hdfc".split()
)


class LlmNotConfigured(RuntimeError):
    """Raised when no LLM endpoint is configured and no fallback is allowed."""


class LlmClient(Protocol):
    """Swap this out for any chat backend."""

    name: str

    def complete(self, system: str, user: str) -> str: ...


class OpenAiCompatibleClient:
    """Works with OpenAI and any OpenAI-compatible local server (Ollama, LM Studio, vLLM)."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str = LLM_MODEL,
        base_url: str | None = None,
        temperature: float = LLM_TEMPERATURE,
        max_tokens: int = LLM_MAX_TOKENS,
        timeout: int = LLM_TIMEOUT_SECONDS,
    ) -> None:
        self.name = f"openai-compatible:{model}"
        self.api_key = api_key
        self.model = model
        self.base_url = (base_url or os.getenv("LLM_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout

    def complete(self, system: str, user: str) -> str:
        payload = {
            "model": self.model,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        last_error: Exception | None = None
        for attempt in range(1, LLM_MAX_ATTEMPTS + 1):
            try:
                response = requests.post(
                    f"{self.base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                        "User-Agent": LLM_USER_AGENT,
                    },
                    json=payload,
                    timeout=self.timeout,
                )
                response.raise_for_status()
                body: dict[str, Any] = response.json()
                return (body["choices"][0]["message"]["content"] or "").strip()
            except requests.HTTPError as exc:
                last_error = exc
                status = exc.response.status_code if exc.response is not None else 0
                if status not in RETRY_STATUS_CODES or attempt == LLM_MAX_ATTEMPTS:
                    raise
                delay = float(exc.response.headers.get("retry-after") or LLM_RETRY_BACKOFF * attempt)
                logger.warning(
                    "LLM %s from %s; retrying in %.1fs (attempt %d/%d)",
                    status, self.model, delay, attempt, LLM_MAX_ATTEMPTS,
                )
                time.sleep(delay)
            except (requests.Timeout, requests.ConnectionError) as exc:
                last_error = exc
                if attempt == LLM_MAX_ATTEMPTS:
                    raise
                delay = LLM_RETRY_BACKOFF * attempt
                logger.warning("LLM %s; retrying in %.1fs (attempt %d/%d)", type(exc).__name__, delay, attempt, LLM_MAX_ATTEMPTS)
                time.sleep(delay)
        raise last_error if last_error else RuntimeError("LLM call failed")


def load_env() -> None:
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:  # pragma: no cover - python-dotenv is a listed dependency
        logger.debug("python-dotenv not installed; skipping .env load")


def get_client() -> LlmClient | None:
    """Return the configured client, or None when no key is set."""
    load_env()
    api_key = os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not api_key:
        logger.info("No LLM_API_KEY/OPENAI_API_KEY set; using extractive fallback")
        return None
    return OpenAiCompatibleClient(
        api_key=api_key,
        model=os.getenv("LLM_MODEL", LLM_MODEL),
    )


def build_context(hits: list[RetrievedChunk]) -> str:
    blocks: list[str] = []
    for position, hit in enumerate(hits, start=1):
        blocks.append(
            f"[{position}] scheme: {hit.scheme_name}\n"
            f"    url: {hit.url}\n"
            f"    fetched_at: {hit.fetched_at}\n"
            f"    text: {hit.text}"
        )
    return "\n\n".join(blocks) if blocks else "(no chunks retrieved)"


def _keywords(question: str) -> set[str]:
    words = re.findall(r"[a-z0-9%]+", question.lower())
    return {w for w in words if w not in STOPWORDS and len(w) > 2}


def _phrases(question: str) -> list[str]:
    """Contiguous question phrases, so "lock-in" beats a line sharing only "tax"."""
    words = re.findall(r"[a-z0-9%]+", question.lower())
    phrases: list[str] = []
    for size in (3, 2):
        for start in range(len(words) - size + 1):
            phrase = " ".join(words[start : start + size])
            if any(word in STOPWORDS for word in words[start : start + size]):
                continue
            phrases.append(phrase)
    return phrases


def extractive_answer(question: str, hits: list[RetrievedChunk], *, max_sentences: int = 3) -> str:
    """Facts-only answer assembled from retrieved lines. Cannot invent anything.

    Lines are ranked by how many query terms they match, weighted by rarity, so
    "Expense ratio: 1.03%" beats the boilerplate "Scheme name:" line that shares
    the scheme-name words.
    """
    if not hits:
        return MISSING

    terms = _keywords(question)
    phrases = _phrases(question)
    lowered_lines: list[tuple[int, str, set[str], str]] = []
    for rank, hit in enumerate(hits):
        for line in hit.text.splitlines():
            line = line.strip()
            if not line or line.startswith(BOILERPLATE_LABELS):
                continue
            words = set(re.findall(r"[a-z0-9%]+", line.lower()))
            matched = terms & words
            if matched:
                lowered_lines.append((rank, line, matched, line.lower()))

    if not lowered_lines:
        return MISSING

    # Rarity weighting: a term or phrase in one line (NAV, exit load) counts far
    # more than scheme-name words repeated across every chunk.
    frequency: dict[str, int] = {}
    phrase_frequency: dict[str, int] = {}
    for _, _, matched, lowered in lowered_lines:
        for term in matched:
            frequency[term] = frequency.get(term, 0) + 1
        for phrase in phrases:
            if phrase in lowered:
                phrase_frequency[phrase] = phrase_frequency.get(phrase, 0) + 1

    scored: list[tuple[float, int, str]] = []
    for order, (rank, line, matched, lowered) in enumerate(lowered_lines):
        rarity = sum(1.0 / frequency[term] for term in matched)
        phrase_bonus = min(1.5, 0.75 * sum(1.0 / phrase_frequency[p] for p in phrases if p in lowered))
        scored.append((rarity + phrase_bonus - rank * 0.01, order, line))
    scored.sort(key=lambda item: (-item[0], item[1]))

    if scored[0][0] <= 0:
        return MISSING

    picked: list[tuple[int, str]] = []
    for score, order, line in scored:
        if score <= 0 or len(picked) >= max_sentences:
            break
        if line in [existing for _, existing in picked]:
            continue
        picked.append((order, line))
    picked.sort()

    sentences: list[str] = []
    for _, line in picked:
        for part in re.split(r"(?<=[.!?])\s+", line):
            part = part.strip()
            if part and part not in sentences:
                sentences.append(part)
            if len(sentences) >= max_sentences:
                break
        if len(sentences) >= max_sentences:
            break
    return " ".join(sentences) if sentences else MISSING


def generate_answer(
    question: str,
    hits: list[RetrievedChunk],
    *,
    client: LlmClient | None = None,
    max_sentences: int = 3,
) -> str:
    """Ask the LLM for a facts-only answer, or fall back to extraction."""
    if not hits:
        return MISSING

    if client is None:
        client = get_client()
    if client is None:
        return extractive_answer(question, hits, max_sentences=max_sentences)

    try:
        answer = client.complete(SYSTEM_PROMPT, USER_TEMPLATE.format(
            context=build_context(hits),
            question=question,
        ))
    except Exception as exc:  # noqa: BLE001 — never fail the chat on LLM errors
        logger.error("LLM call failed (%s); using extractive fallback", exc)
        return extractive_answer(question, hits, max_sentences=max_sentences)

    if not answer:
        return extractive_answer(question, hits, max_sentences=max_sentences)
    return answer
