"""Streamlit chat UI (retrieval stage 5, architecture 7).

Thin client: it calls app.query.service and does no vector logic. Chat history
lives in the Streamlit session only, so nothing is written to disk.

    streamlit run app/ui/app.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.query.memory import ConversationMemory  # noqa: E402
from app.query.service import answer_question, to_response  # noqa: E402
from shared.config import CHROMA_DIR, MEMORY_WINDOW_MESSAGES  # noqa: E402

WELCOME = "Facts-only HDFC scheme FAQ assistant. Ask about expense ratio, exit load, lock-in, minimum SIP, or other published facts for five HDFC Direct–Growth funds."

SHORT_NOTE = "Facts-only. No investment advice."

MEMORY_NOTE = (
    f"Follow-ups are remembered for the last {MEMORY_WINDOW_MESSAGES} messages, so "
    "“what about the minimum SIP?” is answered about the fund you just asked about. "
    "Nothing is stored on disk."
)

FULL_DISCLAIMER = (
    "Facts-only. No investment advice. Answers are retrieved from public Groww scheme pages "
    "for five HDFC Direct–Growth funds. Mutual fund investments are subject to market risks. "
    "Read all scheme-related documents carefully. This assistant does not collect PAN, "
    "Aadhaar, account numbers, OTPs, emails, or phone numbers."
)

EXAMPLE_QUESTIONS = [
    "What is the expense ratio of HDFC Large Cap Fund Direct Growth?",
    "What is the lock-in for HDFC ELSS Tax Saver?",
    "What is the minimum SIP amount for HDFC Small Cap Fund?",
]

NO_STORE_PATH = (
    "The vector store is missing. Run `python -m ingest.run` once, then reload this page."
)


def init_state() -> None:
    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "pending_question" not in st.session_state:
        st.session_state.pending_question = ""
    if "memory" not in st.session_state:
        st.session_state.memory = ConversationMemory()


def clear_chat() -> None:
    st.session_state.messages = []
    st.session_state.memory = ConversationMemory()
    st.rerun()


def ask(question: str) -> None:
    """Send one question to the query service and append both bubbles."""
    question = question.strip()
    if not question:
        return
    st.session_state.messages.append({"role": "user", "text": question})
    with st.spinner("Looking it up in the scheme pages…"):
        result = answer_question(question, memory=st.session_state.memory)
    st.session_state.messages.append(
        {
            "role": "assistant",
            "response": to_response(result),
            "resolved": result.resolved_question,
            "memory_used": result.memory_used,
        }
    )


def render_assistant(response: dict, resolved: str = "", memory_used: bool = False) -> None:
    st.markdown(response["answer"])
    if memory_used and resolved:
        st.caption(f"Read as: {resolved}")
    if response.get("citation_url"):
        st.markdown(f"[Source: {response['citation_url']}]({response['citation_url']})")
    if response.get("last_updated_from_sources"):
        st.caption(f"Last updated from sources: {response['last_updated_from_sources']}")
    st.caption(f"Intent: {response['intent']}  •  {response['disclaimer']}")


def main() -> None:
    st.set_page_config(page_title="HDFC MF FAQ (facts only)", layout="centered")
    init_state()

    st.title("HDFC Mutual Fund FAQ")
    st.markdown(WELCOME)
    st.info(SHORT_NOTE)

    with st.sidebar:
        st.caption(MEMORY_NOTE)
        if st.button("Clear conversation", width="stretch"):
            clear_chat()

    if not CHROMA_DIR.exists():
        st.warning(NO_STORE_PATH)
        st.caption(FULL_DISCLAIMER)
        return

    st.markdown("**Try one of these**")
    columns = st.columns(len(EXAMPLE_QUESTIONS))
    for column, example in zip(columns, EXAMPLE_QUESTIONS):
        if column.button(example, key=f"example-{example}"):
            st.session_state.pending_question = example

    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            if message["role"] == "user":
                st.markdown(message["text"])
            else:
                render_assistant(
                    message["response"],
                    message.get("resolved", ""),
                    message.get("memory_used", False),
                )

    typed = st.chat_input("Ask a factual question about the five HDFC Direct-Growth schemes")
    pending = st.session_state.pop("pending_question", "")
    question = typed or pending
    if question:
        ask(question)
        st.rerun()

    st.divider()
    st.caption(SHORT_NOTE)
    st.caption(FULL_DISCLAIMER)


if __name__ == "__main__":
    main()
