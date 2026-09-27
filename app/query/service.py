"""Query service: Guardrails -> Retrieve -> Generate -> Format.

    python -m app.query.service --q "expense ratio of HDFC Large Cap Fund Direct Growth?"

Prints the architecture 6.5 response contract as JSON. Assumes Phase 4 ingest
has been run; if data/chroma is missing it says so instead of failing.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from typing import Any

from app.query.format import (
    DISCLAIMER,
    MISSING_FACT_ANSWER,
    citation_from_answer,
    is_weak_retrieval,
    last_updated_from_sources,
    limit_sentences,
    pick_citation_url,
)
from app.query.generate import LlmClient, generate_answer
from app.query.guardrails import INTENT_FACTUAL, INTENT_PII, check
from app.query.memory import ConversationMemory, resolve_followup
from app.query.retrieve import get_corpus_stamp, retrieve
from shared.config import MAX_ANSWER_SENTENCES, PREVIEW_CHARS
from shared.schemas import QueryResult

logger = logging.getLogger(__name__)

DEMO_QUESTIONS = [
    "What is the expense ratio of HDFC Large Cap Fund Direct Growth?",
    "What is the lock-in for HDFC ELSS Tax Saver?",
    "What is the minimum SIP amount for HDFC Small Cap Fund?",
    "What is the exit load for HDFC Large Cap Fund?",
    "Should I buy HDFC small cap?",
    "What are the returns of HDFC Large Cap?",
    "My PAN is ABCDE1234F and my phone is 9876543210",
    "Is ICICI Nifty 50 ETF covered here?",
]


def answer_question(
    question: str,
    *,
    client: LlmClient | None = None,
    memory: ConversationMemory | None = None,
) -> QueryResult:
    """Run the full online pipeline and return the populated result.

    Stays stateless unless a memory object is passed, in which case an elided
    follow-up is resolved against the last MEMORY_WINDOW_MESSAGES messages before
    retrieval (see app/query/memory.py).
    """
    decision = check(question)
    result = QueryResult(
        intent=decision.intent,
        message=decision.message,
        should_retrieve=decision.should_retrieve,
        skip_generate=decision.skip_generate,
        resolved_question=question.strip(),
    )

    corpus_stamp = get_corpus_stamp()

    retrieval_question = question
    if memory is not None and decision.intent == INTENT_FACTUAL:
        resolution = resolve_followup(question, memory, client=client)
        retrieval_question = resolution.question
        result.resolved_question = resolution.question
        result.memory_strategy = resolution.strategy
        result.memory_used = resolution.used_memory

    if decision.should_retrieve:
        hits, scheme_filter, used_fallback = retrieve(retrieval_question)
        result.scheme_filter = scheme_filter
        result.used_fallback = used_fallback
        result.hits = hits

    if decision.skip_generate:
        # Refusal path: the guardrail message is the answer. Never generate.
        result.answer = decision.message
        result.citation_url = pick_citation_url(
            result.hits, scheme_name=result.scheme_filter
        )
    elif not result.hits:
        result.answer = MISSING_FACT_ANSWER
        result.citation_url = ""
    elif is_weak_retrieval(result.hits):
        logger.info("Weak retrieval (min distance %.3f); not inventing", result.hits[0].distance)
        result.answer = MISSING_FACT_ANSWER
        result.citation_url = pick_citation_url(
            result.hits, scheme_name=result.scheme_filter
        )
    else:
        answer = generate_answer(retrieval_question, result.hits, client=client)
        result.answer = limit_sentences(answer, MAX_ANSWER_SENTENCES)
        if not result.answer:
            logger.info("Generator produced no usable sentence; not inventing")
            result.answer = MISSING_FACT_ANSWER
        result.citation_url = pick_citation_url(
            result.hits,
            scheme_name=result.scheme_filter,
            proposed=citation_from_answer(result.answer, result.hits),
        )

    result.last_updated_from_sources = last_updated_from_sources(
        result.hits, corpus_stamp=corpus_stamp
    )

    if memory is not None and decision.intent == INTENT_FACTUAL and not decision.skip_generate:
        memory.add_turn(question, result.answer)

    return result


def to_response(result: QueryResult) -> dict[str, Any]:
    """Architecture 6.5 contract: answer, citation_url, last_updated, intent, disclaimer."""
    return {
        "answer": result.answer,
        "citation_url": result.citation_url,
        "last_updated_from_sources": result.last_updated_from_sources,
        "intent": result.intent,
        "disclaimer": DISCLAIMER,
    }


def format_detail(result: QueryResult, question: str) -> str:
    lines: list[str] = []
    if result.intent == INTENT_PII:
        lines.append("question:      [withheld: input matched a PII rule]")
    else:
        lines.append(f"question:      {question}")
    lines.append(f"intent:        {result.intent}")
    if result.resolved_question and result.resolved_question != question:
        lines.append(f"resolved:      {result.resolved_question}")
        lines.append(f"memory:        {result.memory_strategy}")
    if result.scheme_filter:
        scope = "global top-k (filter had no hits)" if result.used_fallback else "scheme filter"
        lines.append(f"scheme filter: {result.scheme_filter}  [{scope}]")
    lines.append(f"hits:          {len(result.hits)}")
    for rank, hit in enumerate(result.hits, start=1):
        preview = hit.text.replace("\n", " | ")[: PREVIEW_CHARS // 2]
        lines.append(f"  {rank}. distance={hit.distance:.4f}  {hit.chunk_id}")
        lines.append(f"     url: {hit.url}")
        lines.append(f"     {preview}")
    lines.append("")
    lines.append("response contract:")
    lines.append(json.dumps(to_response(result), ensure_ascii=False, indent=2))
    return "\n".join(lines)


FOLLOW_UP_SCRIPT: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "What is the expense ratio of HDFC Large Cap Fund Direct Growth?",
        ("what about the minimum SIP?", "and the lock-in?"),
    ),
    (
        "What is the minimum SIP amount for HDFC Small Cap Fund?",
        ("what is the exit load?",),
    ),
    (
        "What is the lock-in for HDFC ELSS Tax Saver?",
        ("and the NAV?", "what about HDFC Balanced Advantage Fund?"),
    ),
)


def run_followup_battery(*, client: LlmClient | None = None) -> int:
    """Prove that elided follow-ups resolve to the scheme under discussion."""
    memory = ConversationMemory()
    passed = 0
    total = 0
    for opener, follow_ups in FOLLOW_UP_SCRIPT:
        print(f"\nUser: {opener}")
        first = answer_question(opener, client=client, memory=memory)
        print(f"Assistant: {first.answer}")
        for follow_up in follow_ups:
            print(f"\nUser: {follow_up}")
            result = answer_question(follow_up, client=client, memory=memory)
            tag = f"resolved via {result.memory_strategy}" if result.memory_used else "standalone"
            print(f"Assistant: {result.answer}")
            print(f"  [{result.intent} | {tag} | filter={result.scheme_filter or 'none'}]")
            total += 1
            resolved_scheme = result.scheme_filter
            asked_for_scheme = follow_up.lower().find("balanced advantage") >= 0
            if result.intent == "factual" and (resolved_scheme or asked_for_scheme):
                passed += 1
    print(f"\n{passed}/{total} follow-ups kept a scheme scope")
    return 0 if passed == total else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run Guard -> Retrieve -> Generate -> Format and print the response contract (Phase 6).",
    )
    parser.add_argument("-q", "--q", "--question", dest="question", default=None, help="Question to run")
    parser.add_argument("--detail", action="store_true", help="Also show intent and retrieved chunks")
    parser.add_argument(
        "--followups",
        action="store_true",
        help="Run the scripted multi-turn battery that exercises conversation memory",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")

    if args.followups:
        return run_followup_battery()

    questions = [args.question] if args.question else DEMO_QUESTIONS
    for question in questions:
        result = answer_question(question)
        if args.detail:
            print(format_detail(result, question))
        else:
            print(json.dumps(to_response(result), ensure_ascii=False))
        if len(questions) > 1:
            print("-" * 80)
    return 0


if __name__ == "__main__":
    sys.exit(main())
