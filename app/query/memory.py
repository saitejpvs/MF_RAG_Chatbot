"""Conversation memory for resolving follow-ups before retrieval.

Holds the last MEMORY_WINDOW_MESSAGES chat messages (5 user/assistant pairs) in
process only, and rewrites an elided follow-up into a standalone question so that
"what about the minimum SIP?" is answered about the scheme just discussed instead
of being searched across all five schemes.

Constraints that keep this facts-only:
- Guardrails run on the raw question first, so no rewrite can bypass PII,
  advice, returns, or out-of-scope refusals.
- Only answered factual turns are stored, so a refusal cannot bias later turns.
- Resolution may only re-attach a scheme name or paraphrase the question; the
  answer itself is still generated from retrieved chunks alone.
- answer_question(question) stays stateless unless a memory object is passed.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from app.query.guardrails import FACT_PATTERNS, INTENT_FACTUAL, GuardDecision, check
from app.query.retrieve import match_scheme
from shared.config import MEMORY_LLM_REWRITE, MEMORY_WINDOW_MESSAGES

logger = logging.getLogger(__name__)

FOLLOW_UP_MAX_WORDS = 9
MAX_REWRITE_CHARS = 300

ELISION_STARTS = (
    "what about",
    "how about",
    "and its",
    "and it",
    "and the",
    "also",
    "its",
    "it",
    "that",
    "this",
    "the same",
    "same",
    "there",
    "for it",
    "of it",
    "in it",
    "then",
)

REWRITE_SYSTEM = (
    "You rewrite a follow-up question into a standalone question using the conversation "
    "history. Reply with the rewritten question only, no quotes and no explanation. "
    "Never add a scheme name, number, or fact that is not already in the history or the "
    "question. If the question is already standalone, repeat it unchanged."
)


@dataclass(frozen=True)
class Resolution:
    """Outcome of follow-up resolution, for logging and the --detail view."""

    question: str
    original: str
    used_memory: bool
    strategy: str


@dataclass
class ConversationMemory:
    """Last N chat messages, newest at the end. Never persisted to disk."""

    window: int = MEMORY_WINDOW_MESSAGES
    _messages: list[dict[str, str]] = field(default_factory=list, repr=False)

    def add_message(self, role: str, text: str) -> None:
        text = (text or "").strip()
        if not text:
            return
        self._messages.append({"role": role, "text": text})
        overflow = len(self._messages) - self.window
        if overflow > 0:
            del self._messages[:overflow]

    def add_turn(self, question: str, answer: str) -> None:
        self.add_message("user", question)
        self.add_message("assistant", answer)

    def clear(self) -> None:
        self._messages.clear()

    @property
    def messages(self) -> list[dict[str, str]]:
        return [dict(message) for message in self._messages]

    @property
    def size(self) -> int:
        return len(self._messages)

    def turns(self) -> list[tuple[str, str]]:
        """(question, answer) pairs, oldest first."""
        pairs: list[tuple[str, str]] = []
        for index, message in enumerate(self._messages):
            if message["role"] != "user":
                continue
            answer = (
                self._messages[index + 1]["text"]
                if index + 1 < len(self._messages)
                and self._messages[index + 1]["role"] == "assistant"
                else ""
            )
            pairs.append((message["text"], answer))
        return pairs

    def last_scheme(self) -> str | None:
        """Most recently mentioned scheme in memory, else None."""
        for question, _ in reversed(self.turns()):
            scheme = match_scheme(question)
            if scheme:
                return scheme
        return None

    def history_block(self) -> str:
        lines = [
            f"{'User' if message['role'] == 'user' else 'Assistant'}: {message['text']}"
            for message in self._messages
        ]
        return "\n".join(lines)

    def __len__(self) -> int:
        return len(self._messages)


def _word_count(text: str) -> int:
    return len([token for token in re.split(r"\W+", text) if token])


def _fact_patterns_in(text: str) -> list[str]:
    return [
        pattern
        for pattern in FACT_PATTERNS
        if re.search(pattern, text, re.IGNORECASE)
    ]


def looks_elided(question: str) -> bool:
    """True when a question reads as a follow-up rather than a standalone ask."""
    lowered = question.strip().lower()
    if not lowered:
        return False
    if match_scheme(lowered):
        return False
    if _word_count(lowered) <= 2:
        return True
    if _word_count(lowered) <= FOLLOW_UP_MAX_WORDS and any(
        lowered.startswith(prefix) for prefix in ELISION_STARTS
    ):
        return True
    return bool(
        _word_count(lowered) <= FOLLOW_UP_MAX_WORDS
        and re.search(r"\b(that|this|same|it|its|there|those)\s+(one|fund|scheme|it)?\b", lowered)
    )


def looks_like_bare_attribute_question(question: str) -> bool:
    """A short, fact-shaped question that names no scheme, e.g. "what is the exit
    load?". Standalone as a first question, a follow-up once a fund is in play."""
    if match_scheme(question):
        return False
    if not _fact_patterns_in(question):
        return False
    return _word_count(question) <= FOLLOW_UP_MAX_WORDS


def _question_with_scheme(question: str, scheme: str) -> str:
    stem = question.strip().rstrip("?.! ")
    return f"{stem} for {scheme}?"


def _llm_rewrite(question: str, memory: ConversationMemory, client: Any) -> str | None:
    prompt = (
        "Conversation so far:\n"
        f"{memory.history_block()}\n\n"
        f"Follow-up question: {question}\n\n"
        "Standalone question:"
    )
    try:
        rewritten = client.complete(REWRITE_SYSTEM, prompt).strip().strip('"')
    except Exception as exc:  # noqa: BLE001 - any provider failure must not break the turn
        logger.warning("Memory rewrite failed (%s); using the original question", type(exc).__name__)
        return None
    rewritten = re.sub(r"\s+", " ", rewritten).strip()
    if not rewritten or len(rewritten) > MAX_REWRITE_CHARS:
        return None
    return rewritten


def _is_acceptable(question: str, original: str) -> bool:
    """The rewrite must stay in scope and keep the fact being asked about."""
    decision: GuardDecision = check(question)
    if decision.intent != INTENT_FACTUAL:
        return False
    wanted = _fact_patterns_in(original)
    return not wanted or any(re.search(pattern, question, re.IGNORECASE) for pattern in wanted)


def resolve_followup(
    question: str,
    memory: ConversationMemory | None,
    *,
    client: Any | None = None,
) -> Resolution:
    """Make an elided follow-up standalone. Returns the question to retrieve with."""
    original = (question or "").strip()
    if memory is None or memory.size == 0 or not original:
        return Resolution(original, original, False, "no-memory")

    if match_scheme(original):
        return Resolution(original, original, False, "self-contained")

    scheme = memory.last_scheme()
    if scheme and (looks_elided(original) or looks_like_bare_attribute_question(original)):
        candidate = _question_with_scheme(original, scheme)
        if match_scheme(candidate) == scheme and _is_acceptable(candidate, original):
            logger.info("Memory: carried scheme %r into follow-up", scheme)
            return Resolution(candidate, original, True, "scheme-carryover")

    if MEMORY_LLM_REWRITE and client is not None:
        rewritten = _llm_rewrite(original, memory, client)
        if rewritten and _is_acceptable(rewritten, original):
            logger.info("Memory: rewrote follow-up with the LLM")
            return Resolution(rewritten, original, True, "llm-rewrite")

    return Resolution(original, original, False, "unchanged")
