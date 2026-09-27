"""Shared configuration for ingest and query.

Single source of truth for paths, the embedding model name, and chunk/retrieve
sizes. Ingest and query both read it; nothing else may hardcode the model name.
Env vars (LLM_*, OPENAI_API_KEY) are read at query time only.
"""

import os
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
SOURCES_CSV = DATA_DIR / "sources.csv"
RAW_HTML_DIR = DATA_DIR / "raw"
DEBUG_DIR = DATA_DIR / "debug"
CHROMA_DIR = DATA_DIR / "chroma"

AMC = "HDFC"
EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
COLLECTION_NAME = "hdfc_mf_faqs"

CHUNK_SIZE = 500
CHUNK_OVERLAP = 100
MIN_CHUNK_SIZE = 80
RETRIEVE_K = 4

# Phase 3 embed settings. The model name lives here only (architecture 5.4).
EMBEDDING_DIM = 384
EMBED_BATCH_SIZE = 32
EMBED_NORMALIZE = True
# Optional prefix "{scheme_name}. {text}" so scheme identity is in the vector.
# Off for v1: queries have no canonical scheme name to prefix with, and the
# asymmetry buried fact chunks (expense-ratio chunk fell to rank 8/24). Turn on
# only together with the same rule on the query side.
USE_SCHEME_PREFIX = False

FETCH_TIMEOUT_SECONDS = 30
FETCH_USER_AGENT = (
    "Mozilla/5.0 (compatible; HDFC-MF-FAQ-RAG/0.1; +https://groww.in/) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
PREVIEW_CHARS = 500

# Phase 6 generation. LLM_API_KEY (or OPENAI_API_KEY) is read in app/query/generate.py.
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")
LLM_TEMPERATURE = 0.0
# Reasoning-style models (gpt-oss) spend part of this budget on hidden reasoning,
# so a low cap truncates the visible answer mid-clause.
LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "300"))
LLM_TIMEOUT_SECONDS = int(os.getenv("LLM_TIMEOUT_SECONDS", "30"))
# Some OpenAI-compatible gateways (Groq) reject the default python-requests agent
# with a Cloudflare 1010 challenge.
LLM_USER_AGENT = os.getenv("LLM_USER_AGENT", "openai-python/1.0")
# Free-tier gateways return 429 under bursty chat traffic; retry before falling back.
LLM_MAX_ATTEMPTS = int(os.getenv("LLM_MAX_ATTEMPTS", "3"))
LLM_RETRY_BACKOFF = float(os.getenv("LLM_RETRY_BACKOFF", "2.0"))
RETRY_STATUS_CODES = frozenset({408, 409, 425, 429, 500, 502, 503, 504})
MAX_ANSWER_SENTENCES = 3
# Cosine distance above which retrieval is treated as weak (architecture 6.3).
WEAK_RETRIEVAL_DISTANCE = 0.75
# Conversation memory: chat messages kept in process for follow-up resolution.
MEMORY_WINDOW_MESSAGES = int(os.getenv("MEMORY_WINDOW_MESSAGES", "10"))
# Off by default: the cheap scheme carry-over rule handles most follow-ups. Set to
# 1 to additionally paraphrase follow-ups with the LLM (one extra call per turn).
MEMORY_LLM_REWRITE = os.getenv("MEMORY_LLM_REWRITE", "0").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
