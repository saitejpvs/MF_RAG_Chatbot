from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class SourceRow:
    doc_id: str
    scheme_name: str
    category: str
    url: str


@dataclass
class Document:
    doc_id: str
    url: str
    scheme_name: str
    category: str
    amc: str
    text: str
    fetched_at: datetime


@dataclass
class Chunk:
    chunk_id: str
    doc_id: str
    text: str
    url: str
    scheme_name: str
    category: str
    amc: str
    chunk_index: int
    fetched_at: datetime


@dataclass
class RetrievedChunk:
    """One hit from Chroma (architecture 6.3 step 4)."""

    chunk_id: str
    text: str
    url: str
    scheme_name: str
    category: str
    amc: str
    chunk_index: int
    fetched_at: str
    distance: float


@dataclass
class QueryResult:
    """Structured result of the query pipeline.

    Phase 5 fills intent, message, and hits. Phase 6 adds answer,
    citation_url, and last_updated_from_sources. Phase 8 adds the
    resolved_question actually used for retrieval, plus how conversation
    memory resolved it.
    """

    intent: str
    message: str
    should_retrieve: bool
    skip_generate: bool
    scheme_filter: str | None = None
    used_fallback: bool = False
    answer: str = ""
    citation_url: str = ""
    last_updated_from_sources: str = ""
    resolved_question: str = ""
    memory_used: bool = False
    memory_strategy: str = "no-memory"
    hits: list[RetrievedChunk] = field(default_factory=list)
