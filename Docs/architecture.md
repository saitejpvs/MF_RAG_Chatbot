# Architecture

**Product:** Mutual Fund FAQ RAG Chatbot  
**Source of truth:** [prd.md](./prd.md)  
**Last updated:** 2026-09-27

This document describes how the prototype is built. Ingestion and retrieval stay as two pipelines. Stages are not collapsed into one opaque script.

---

## 1. Design principles

1. **Two pipelines.** Load → Chunk → Embed → Store is offline/batch. Query → Guard → Retrieve → Generate is online.
2. **Same embedding model on both sides.** `sentence-transformers/all-MiniLM-L6-v2` for documents and queries.
3. **Citations are data, not decoration.** Every chunk carries `url`; the generator may only cite a retrieved URL.
4. **Guardrails before retrieval.** PII, advice, and returns-comparison intents never reach generation as if they were FAQ facts.
5. **Facts only.** The LLM may use retrieved chunk text. It must not invent numbers, rank funds, or compute returns.

---

## 2. System context

```
┌──────────────┐     5 public URLs      ┌─────────────────────┐
│  Groww.in    │ ─────────────────────► │  Ingestion pipeline │
│  scheme pages│                        │  (batch)            │
└──────────────┘                        └──────────┬──────────┘
                                                   │ persist
                                                   ▼
                                        ┌─────────────────────┐
                                        │  ChromaDB           │
                                        │  collection:        │
                                        │  hdfc_mf_faqs       │
                                        └──────────▲──────────┘
                                                   │ query embed + top-k
┌──────────────┐     question           ┌──────────┴──────────┐
│  Chat UI     │ ─────────────────────► │  Retrieval pipeline │
│  (facts-only)│ ◄───────────────────── │  (online)           │
└──────────────┘     answer + 1 URL     │  + LLM generator    │
                                        └─────────────────────┘
```

**Actors:** retail user or support/content person in the tiny chat UI. No login, no personal holdings.

**External systems:**

| System | Role | When |
| --- | --- | --- |
| Groww public HTML | Corpus | Ingestion only |
| Hugging Face MiniLM | Embeddings | Ingest + query |
| LLM (local or API) | Answer wording | Query time only |
| ChromaDB (local disk) | Vector + metadata store | Both |

---

## 3. Logical architecture

Ingestion and retrieval share the embedding model and ChromaDB. They do not share the LLM.

```
┌─────────────────────────────────────────────────────────────────┐
│                         Chat UI (thin)                          │
│  welcome · 3 example questions · disclaimer · Q&A · citation    │
└───────────────────────────────┬─────────────────────────────────┘
                                │ HTTP / in-process call
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Query service (online)                     │
│  Guardrails → Query embed → Retrieve → Generate → Format        │
└───────────────────────────────┬─────────────────────────────────┘
                                │
          ┌─────────────────────┼─────────────────────┐
          ▼                     ▼                     ▼
   ┌─────────────┐      ┌─────────────┐       ┌─────────────┐
   │ MiniLM      │      │ ChromaDB    │       │ LLM         │
   │ embedder    │      │ hdfc_mf_faqs│       │ facts-only  │
   └──────▲──────┘      └──────▲──────┘       └─────────────┘
          │                    │
          │                    │ write-only from ingest
          │                    │
┌─────────┴────────────────────┴──────────────────────────────┐
│                   Ingestion service (batch)                   │
│         Load → Clean → Chunk → Embed → Upsert Chroma          │
└───────────────────────────────▲───────────────────────────────┘
                                │
                         sources.csv / sources.md
                         (5 Groww URLs + scheme metadata)
```

---

## 4. Suggested module layout

Keep each RAG stage in its own module so architecture matches the milestone.

```
app/
  ui/                 # welcome, examples, disclaimer, chat
  query/
    guardrails.py     # PII, advice, returns, out-of-scope
    retrieve.py       # embed query, Chroma top-k, optional scheme filter
    generate.py       # prompt + LLM + citation pick
    format.py         # ≤3 sentences, last-updated, one URL
ingest/
  load.py             # fetch 5 URLs, extract text
  chunk.py            # recursive, section-aware
  embed.py            # MiniLM encode
  store.py            # Chroma persist
shared/
  config.py           # paths, k, chunk sizes, model name
  schemas.py          # Document, Chunk, QueryResult
  embedder.py         # single MiniLM wrapper used by ingest + query
data/
  sources.csv         # 5 URLs
  chroma/             # persistent Chroma directory
  sample_qa.md
```

The UI talks only to the query service. Re-ingest is a CLI/script, not a chat action.

---

## 5. Pipeline A — Data ingestion

Run once at setup and again when sources are refreshed. Output is a persistent Chroma collection.

### 5.1 Sequence

```
sources.csv
    │
    ▼
Load          GET each Groww URL
    │         extract main scheme text; drop nav/ads
    │         attach url, scheme_name, category, amc, fetched_at
    ▼
Chunk         recursive character split (section-aware)
    │         size 400–600 chars, overlap 80–100
    │         merge/drop < ~80 chars
    │         chunk_index
    ▼
Embed         all-MiniLM-L6-v2 (384-dim)
    ▼
Store         ChromaDB upsert collection hdfc_mf_faqs
```

### 5.2 Load

**Input:** the five URLs in [prd.md](./prd.md) §5.

**Work:**

1. Fetch HTML (user-agent appropriate for a small public crawl).
2. Extract visible scheme content: name, category, expense ratio, exit load, min SIP/lump sum, lock-in, riskometer, benchmark, and any statement/download notes.
3. Strip chrome (header, footer, related-fund widgets, ads).
4. Do not keep raw HTML in the vector store; keep cleaned text.

**Document record (pre-chunk):**

| Field | Type | Example |
| --- | --- | --- |
| `doc_id` | string | `hdfc-large-cap-direct-growth` |
| `url` | string | Groww scheme URL |
| `scheme_name` | string | HDFC Large Cap Fund – Direct Growth |
| `category` | string | large_cap \| flexi_cap \| elss \| small_cap \| hybrid_baf |
| `amc` | string | `HDFC` |
| `text` | string | cleaned page text |
| `fetched_at` | ISO datetime | ingest time |

### 5.3 Chunk

**Strategy (from PRD):** recursive character splitting, section-aware — not semantic chunking.

| Parameter | Value |
| --- | --- |
| Separators (in order) | headings, `\n\n`, `\n`, `. `, space |
| `chunk_size` | 400–600 characters |
| `chunk_overlap` | 80–100 characters |
| Discard/merge | fragments &lt; ~80 characters |

**Chunk record:**

| Field | Type |
| --- | --- |
| `chunk_id` | `{doc_id}::{chunk_index}` |
| `text` | chunk body |
| `url` | parent URL (citation) |
| `scheme_name` | string |
| `category` | string |
| `amc` | `HDFC` |
| `chunk_index` | int |
| `fetched_at` | ISO datetime |

### 5.4 Embed

- Model: `sentence-transformers/all-MiniLM-L6-v2`
- Dimension: 384
- Encode chunk `text` only (metadata is stored alongside, not embedded as a blob unless we later add a prefix like `scheme_name:`)
- Optional prefix: `{scheme_name}. {text}` so scheme identity is in the vector. If used, query embedding must use the same convention.

### 5.5 Store

- Engine: **ChromaDB**, persistent dir (e.g. `data/chroma`)
- Collection: `hdfc_mf_faqs`
- Distance: cosine (default for MiniLM)
- Upsert by `chunk_id` so re-ingest is idempotent
- After ingest, record a corpus-level `last_updated_from_sources` (max `fetched_at`) for the UI stamp

---

## 6. Pipeline B — Data retrieval

Online path for every chat turn.

### 6.1 Sequence

```
User question
    │
    ▼
Guardrails
    │  PII detected?     → refuse, do not store, do not retrieve
    │  Advice/opinion?   → refuse + optional educational URL (no ranking)
    │  Returns compare?  → do not compute; return scheme URL(s) only
    │  Other AMC/scheme? → out-of-scope message
    ▼
Memory           if the question is an elided follow-up, resolve it against
    │            the last 10 messages ("what about the minimum SIP?" →
    │            "… for HDFC Large Cap Fund – Direct Growth?")
    ▼
Query embed     same MiniLM model
    ▼
Retrieve        Chroma top-k (k=4 default; range 3–5)
                if query names a scheme, filter or boost that scheme_name
    ▼
Generate        LLM sees only retrieved chunk texts + metadata
                system: facts-only, ≤3 sentences, no advice, no invented numbers
    ▼
Format          pick exactly one citation URL from retrieved set
                append Last updated from sources: <date>
                return to UI
```

### 6.2 Guardrails (before retrieve)

| Intent | Detection (v1) | Response |
| --- | --- | --- |
| PII | PAN / Aadhaar / account / OTP / email / phone patterns | “Do not share personal data. This assistant does not store PAN, Aadhaar, account numbers, OTPs, emails, or phones.” No logging of the raw message. |
| Advice | buy, sell, should I, which is better, best fund, recommend | Polite refusal; no ranking. Optional educational link from corpus (e.g. riskometer/lock-in page of a named scheme). |
| Performance | returns, CAGR, outperform, compare performance | Do not calculate. Point to the relevant Groww scheme URL. |
| Out of scope | other AMC names, schemes not in the five | State coverage: five HDFC Direct–Growth schemes only. |

Guardrails can be rules/keywords for v1. LLM classification is optional later; rules are enough for the milestone.

### 6.2.1 Conversation memory (before retrieve)

Multi-turn chat needs one extra step: a follow-up rarely names the fund it is about, so an
unresolved "what about the minimum SIP?" is searched across all five schemes and the wrong
scheme wins. `app/query/memory.py` resolves it first.

| Setting | Default | Meaning |
| --- | --- | --- |
| `MEMORY_WINDOW_MESSAGES` | 10 | Chat messages kept in process (5 user/assistant pairs). Older messages are dropped. |
| `MEMORY_LLM_REWRITE` | `0` | Off by default. `1` additionally paraphrases follow-ups with the LLM, one extra call per turn. |

Resolution order:

1. No memory, or the question names a scheme itself → use it unchanged (`self-contained`).
2. Elided follow-up (pronoun, “what about…”, or a short bare fact question with no fund) and the
   most recent stored question names a scheme → re-attach that scheme name
   (`scheme-carryover`). The resolved question is logged and shown in the UI as “Read as: …”.
3. Otherwise, and only if `MEMORY_LLM_REWRITE=1` → ask the LLM to rewrite the follow-up as a
   standalone question from the history (`llm-rewrite`).
4. Otherwise use the question unchanged (`unchanged`).

Rules that keep this facts-only:

- Guardrails run on the **raw** question, so no rewrite can bypass a PII, advice, returns, or
  out-of-scope refusal.
- Only answered factual turns are stored, so a refusal cannot bias later turns, and PII text is
  never kept in memory.
- A resolved question must still classify as factual and must keep the fact keyword the user
  asked about; otherwise it is discarded.
- Memory is opt-in per call: `answer_question(q)` is stateless, `answer_question(q, memory=m)`
  is stateful. The UI holds one `ConversationMemory` in Streamlit session state; nothing is
  written to disk, and a “Clear conversation” control resets it.

This is query resolution only. It stores no user profile and no portfolio data — see §11.

### 6.3 Retrieve

1. Embed the (non-PII) question with MiniLM.
2. `query_embeddings` against `hdfc_mf_faqs`, `n_results = 4`.
3. If a known `scheme_name` / alias is in the query, **metadata filter** `scheme_name == …` first; if too few hits, fall back to unfiltered top-k.
4. Return `{text, url, scheme_name, category, fetched_at, distance}` for each hit.

**Empty / weak retrieval:** if distances are poor (tune a threshold after first ingest), do not invent. Say the corpus does not contain that fact and still return the closest in-scope scheme URL.

### 6.4 Generate

**Inputs to the LLM:**

- User question
- Retrieved chunks (text + url + scheme_name + fetched_at)
- Hard system instructions

**System rules:**

- Use only the provided chunks.
- ≤3 sentences.
- No investment advice, no suitability, no buy/sell.
- No computed or compared returns.
- If the chunks disagree or lack the fact, say so.
- Do not mention internal chain-of-thought.

**Citation rule:** choose **one** URL from the retrieved chunks (the chunk that actually supports the fact; if several, prefer the scheme named in the question). Never cite a URL that was not retrieved.

**Last updated:** `Last updated from sources: {max fetched_at among cited/retrieved chunks}` (ISO date is enough).

### 6.5 Response contract (UI)

```json
{
  "answer": "string, ≤3 sentences",
  "citation_url": "https://groww.in/mutual-funds/...",
  "last_updated_from_sources": "YYYY-MM-DD",
  "intent": "factual | refused_advice | refused_pii | refused_returns | out_of_scope",
  "disclaimer": "Facts-only. No investment advice."
}
```

---

## 7. Chat UI

Thin client. No vector logic in the browser.

| Element | Spec |
| --- | --- |
| Welcome | Facts-only HDFC scheme FAQ assistant |
| Examples | Three PRD questions (click fills the input / submits) |
| Disclaimer | Persistent: “Facts-only. No investment advice.” plus full snippet from PRD §6.4 |
| Thread | User question + assistant bubble |
| Assistant bubble | `answer`, clickable `citation_url`, `Last updated from sources:` |

No fields for PAN, email, or phone. Do not persist chat logs that could contain PII; in-memory session is enough for the prototype.

---

## 8. Data stores

| Store | Contents | Lifetime |
| --- | --- | --- |
| `data/sources.csv` | 5 URLs + scheme + category | Source of truth for ingest |
| `data/chroma/` | embeddings + chunk text + metadata | Until re-ingest |
| In-memory chat | current session messages | Process lifetime; no PII |

Chroma is the only retrieval index. There is no SQL requirement for v1.

---

## 9. Configuration (defaults)

| Key | Default | Notes |
| --- | --- | --- |
| Embedding model | `sentence-transformers/all-MiniLM-L6-v2` | Shared ingest/query |
| Vector DB | Chroma persistent | Collection `hdfc_mf_faqs` |
| `chunk_size` | 500 | Band 400–600 |
| `chunk_overlap` | 100 | Band 80–100 |
| `k` | 4 | Band 3–5 |
| LLM | Configurable env | Swap without re-embedding |
| `MEMORY_WINDOW_MESSAGES` | 10 | Chat messages kept for follow-up resolution (§6.2.1) |
| `MEMORY_LLM_REWRITE` | `0` | `1` adds an LLM paraphrase step per follow-up |
| Sources | Exactly 5 Groww URLs | No extra blogs |

---

## 10. Trust, privacy, and failure modes

| Risk | Mitigation in architecture |
| --- | --- |
| Hallucinated fees/lock-in | Grounding prompt + one retrieved URL + refuse when retrieval is weak |
| Advice leakage | Guardrail before retrieve; prompt ban; no ranking in generator |
| PII leak | Pattern block; no persistence of blocked messages |
| Stale Groww numbers | `fetched_at` on chunks; stamp on every answer |
| Wrong scheme citation | Scheme metadata filter when the query names a fund |
| Mixing MiniLM with another embedder | Single `shared/embedder.py` |

---

## 11. What is intentionally not in this architecture

- Multi-AMC crawl or scheduler
- SID/KIM PDF semantic chunking
- Auth, KYC, transactions
- Returns engine or NAV time series
- Multi-turn “my portfolio” memory

Those five remain future work per the PRD.

Conversation memory for query resolution (§6.2.1) is in scope: it remembers the last 10
messages only to rewrite a follow-up before retrieval. Storing a user profile, holdings, or any
portfolio state is not.

---

## 12. Implementation order

1. `sources.csv` + loader for five URLs (inspect cleaned text).
2. Chunker → print chunks to verify field–value pairs stay together.
3. MiniLM + Chroma persist; smoke-query “expense ratio large cap”.
4. Guardrails + retrieve + generate + response contract.
5. Tiny UI (welcome, 3 examples, disclaimer, citation).
6. `sample_qa.md` + README limits.

Each step maps to a visible RAG stage: load, chunk, embed, store, then retrieve and generate.
