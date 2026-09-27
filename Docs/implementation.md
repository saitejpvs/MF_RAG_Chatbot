# Implementation guide (phase-wise)

**Product:** Mutual Fund FAQ RAG Chatbot  
**Follow:** [architecture.md](./architecture.md) and [prd.md](./prd.md)  
**How to use:** Run **one phase per Cursor chat** (or one prompt at a time). Paste the **Cursor prompt** at the end of that phase. Do not skip phases. Do not merge ingest and query into one script.

**Stack (v1, do not substitute without asking):**

- Python 3.11+
- Embedding: `sentence-transformers/all-MiniLM-L6-v2`
- Vector DB: ChromaDB (persistent, collection `hdfc_mf_faqs`)
- Chunking: recursive, section-aware (not semantic)
- UI: Streamlit (simplest for the tiny chat; swap only if already using FastAPI+HTML)

---

## Rules for every phase

1. Read `Docs/architecture.md` before writing code.
2. Keep stages in **separate modules** (`ingest/load.py`, `ingest/chunk.py`, etc.).
3. Use **one shared embedder** (`shared/embedder.py`) for ingest and query.
4. Public sources only: the five Groww URLs in `data/sources.csv`.
5. No PII storage. No returns math. No investment advice.
6. Stop at the phase **Definition of done**. Do not start the next phase unless asked.
7. After coding, show how to run the phase and what output to inspect.

---

## Target tree (end state)

```
Docs/                 # already exists (prd, architecture, this file)
data/
  sources.csv
  chroma/             # created in Phase 4
  sample_qa.md        # Phase 8
ingest/
  load.py
  chunk.py
  embed.py            # thin wrapper around shared embedder if needed
  store.py
  run.py              # CLI: python -m ingest.run
app/
  query/
    guardrails.py
    retrieve.py
    generate.py
    format.py
    service.py        # orchestrates query pipeline
  ui/
    app.py            # Streamlit
shared/
  config.py
  schemas.py
  embedder.py
requirements.txt
README.md             # Phase 8
.env.example          # LLM key placeholder only
```

---

## Phase 0 — Scaffold and source list

**Goal:** Empty project that Cursor can fill, plus the canonical 5 URLs.

**Create:**

- `requirements.txt` — placeholders: `sentence-transformers`, `chromadb`, `beautifulsoup4`, `requests`, `lxml`, `streamlit`, `python-dotenv` (add LLM client later in Phase 6).
- `shared/config.py` — paths, model name, `chunk_size=500`, `chunk_overlap=100`, `k=4`, collection name `hdfc_mf_faqs`.
- `shared/schemas.py` — dataclasses/TypedDicts for `SourceRow`, `Document`, `Chunk` matching architecture §5.2–5.3.
- `data/sources.csv` columns: `doc_id,scheme_name,category,url`

**CSV rows (exact URLs):**

| doc_id | category | url |
| --- | --- | --- |
| hdfc-large-cap-direct-growth | large_cap | https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth |
| hdfc-equity-direct-growth | flexi_cap | https://groww.in/mutual-funds/hdfc-equity-fund-direct-growth |
| hdfc-elss-tax-saver-direct-growth | elss | https://groww.in/mutual-funds/hdfc-elss-tax-saver-fund-direct-plan-growth |
| hdfc-small-cap-direct-growth | small_cap | https://groww.in/mutual-funds/hdfc-small-cap-fund-direct-growth |
| hdfc-balanced-advantage-direct-growth | hybrid_baf | https://groww.in/mutual-funds/hdfc-balanced-advantage-fund-direct-growth |

**Do not:** fetch pages, install nothing mandatory beyond listing deps, build UI.

**Definition of done:**

- [ ] Tree exists; `sources.csv` has exactly 5 rows
- [ ] Config matches architecture defaults
- [ ] README is **not** required yet (Phase 8)

### Cursor prompt — Phase 0

```
Implement Phase 0 only from Docs/implementation.md and Docs/architecture.md.
Create the project scaffold, shared/config.py, shared/schemas.py, requirements.txt, and data/sources.csv with the five HDFC Groww URLs.
Do not fetch pages, chunk, embed, or build UI.
Stop when Phase 0 definition of done is met. Summarize files created.
```

---

## Phase 1 — Load (ingestion stage 1)

**Goal:** Turn 5 URLs into cleaned `Document` objects. No chunking yet.

**Create:** `ingest/load.py`

**Behavior:**

1. Read `data/sources.csv`.
2. HTTP GET each URL (timeout, simple User-Agent).
3. Parse HTML; extract **main scheme content** (title + body facts). Strip nav, footer, ads, related-fund widgets.
4. Return `Document`: `doc_id`, `url`, `scheme_name`, `category`, `amc="HDFC"`, `text`, `fetched_at` (UTC ISO).
5. CLI or `if __name__` that prints: URL, character count, first 500 chars of `text` for each doc — so we can inspect quality.

**Resilience:** If a page fails, log the error and continue; do not crash the whole run silently. Save optional debug dumps under `data/raw/` only if useful (git-ignore raw HTML).

**Do not:** chunk, embed, Chroma, LLM, UI.

**Definition of done:**

- [ ] Running the loader prints 5 documents with non-empty `text`
- [ ] Expense ratio / SIP / exit load style labels appear in at least some extracted text (spot-check)
- [ ] Chrome/nav junk is mostly gone

### Cursor prompt — Phase 1

```
Implement Phase 1 only from Docs/implementation.md.
Follow Docs/architecture.md §5.2 Load.
Write ingest/load.py that fetches the five URLs in data/sources.csv, extracts cleaned scheme text, and returns Document objects with metadata.
Add a small inspect CLI that prints char counts and a text preview per page.
Do not chunk, embed, or use Chroma.
Stop at Phase 1 definition of done. Tell me how to run the inspect command.
```

---

## Phase 2 — Chunk (ingestion stage 2)

**Goal:** Recursive, section-aware chunks. **Not** semantic chunking.

**Create:** `ingest/chunk.py`

**Parameters (from architecture):**

- Separators in order: headings, `\n\n`, `\n`, `. `, space
- `chunk_size` 400–600 (use config `500`)
- `chunk_overlap` 80–100 (use config `100`)
- Merge/drop fragments under ~80 characters
- `chunk_id` = `{doc_id}::{chunk_index}`
- Copy parent metadata: `url`, `scheme_name`, `category`, `amc`, `fetched_at`

**Inspect:** CLI that writes `data/debug/chunks.jsonl` or prints chunk count per scheme and 2–3 sample chunks. Confirm field–value pairs (e.g. exit load) stay in the same chunk.

**Do not:** embed or store in Chroma.

**Definition of done:**

- [ ] Each of 5 docs produces multiple chunks (not 1 giant blob, not hundreds of tiny fragments)
- [ ] Every chunk has `url` and `scheme_name`
- [ ] Spot-check: a fact sentence is not obviously split mid-phrase

### Cursor prompt — Phase 2

```
Implement Phase 2 only from Docs/implementation.md.
Follow Docs/architecture.md §5.3 Chunking: recursive character splitting, section-aware, NOT semantic.
Use shared/config.py sizes. Preserve metadata on every chunk.
Add an inspect path that shows chunk counts and samples.
Do not embed or write to Chroma.
Stop at Phase 2 definition of done.
```

---

## Phase 3 — Embed (ingestion stage 3)

**Goal:** One MiniLM wrapper used later by query as well.

**Create:** `shared/embedder.py` (required), optionally `ingest/embed.py` as a thin call.

**Behavior:**

- Load `sentence-transformers/all-MiniLM-L6-v2` once
- `embed_texts(list[str]) -> ndarray` 384-dim
- Optional prefix from architecture: `{scheme_name}. {text}` — **if you add it, document it in config** (`USE_SCHEME_PREFIX: bool`) so query uses the same rule
- Batch encode chunks from Phase 2

**Do not:** persist to Chroma yet (that is Phase 4). A dry-run print of embedding shape is enough.

**Definition of done:**

- [ ] Embedding a list of chunk texts returns shape `(n, 384)`
- [ ] Model name is only defined in `shared/config.py`

### Cursor prompt — Phase 3

```
Implement Phase 3 only from Docs/implementation.md.
Follow Docs/architecture.md §5.4.
Create shared/embedder.py using sentence-transformers/all-MiniLM-L6-v2.
Ingest and query must both import this module later. Do not write Chroma yet.
Add a tiny dry-run that prints embedding shape for a few chunks.
Stop at Phase 3 definition of done.
```

---

## Phase 4 — Store (ingestion stage 4) + ingest CLI

**Goal:** Persistent Chroma collection. Full ingest pipeline runnable as one command that still calls **separate** load/chunk/embed/store functions.

**Create:** `ingest/store.py`, `ingest/run.py`

**Behavior:**

- Persistent path e.g. `data/chroma`
- Collection `hdfc_mf_faqs`
- Cosine / default MiniLM-friendly metric
- Upsert by `chunk_id`
- Store document text + metadata fields from architecture
- After run, print: number of chunks upserted, persist path, max `fetched_at`

**CLI:** `python -m ingest.run` (or `python ingest/run.py`)  
Idempotent: running twice updates the same ids.

**Do not:** build chat UI or LLM answers.

**Definition of done:**

- [ ] `data/chroma` exists after ingest
- [ ] Re-running ingest does not duplicate ids
- [ ] A one-line smoke query **inside ingest/store or a tiny script** (not full query service) can retrieve a neighbor for `"expense ratio HDFC large cap"` and print `scheme_name` + `url`

### Cursor prompt — Phase 4

```
Implement Phase 4 only from Docs/implementation.md.
Follow Docs/architecture.md §5.5 and the ingest sequence in §5.1.
Write ingest/store.py (Chroma persistent, collection hdfc_mf_faqs, upsert by chunk_id) and ingest/run.py that runs Load → Chunk → Embed → Store as separate function calls.
Add a smoke similarity query printout after ingest.
Do not build guardrails, LLM, or UI.
Stop at Phase 4 definition of done. Tell me the exact ingest command.
```

---

## Phase 5 — Guardrails + retrieve (retrieval stage 1–2)

**Goal:** Online path up to retrieved chunks. No LLM yet.

**Create:**

- `app/query/guardrails.py`
- `app/query/retrieve.py`
- `app/query/service.py` (partial: guard → retrieve; return structured result)

**Guardrails (architecture §6.2) — rules/keywords, not an LLM:**

| Intent | Action |
| --- | --- |
| PII | Refuse; do not log raw text; skip retrieve |
| Advice | Refuse; no ranking; skip generate |
| Returns / compare performance | Do not compute; skip generate; caller will attach scheme URL in Phase 6 |
| Out of scope (other AMC) | Message; skip generate |

**Retrieve:**

- Embed query with **same** `shared/embedder.py`
- `k=4`
- If query matches a known scheme alias, metadata-filter that `scheme_name` first; fall back to global top-k
- Return list of hits: text, url, scheme_name, category, fetched_at, distance

**Inspect:** CLI `python -m app.query.service --q "..."` that prints intent + top chunks (no LLM).

**Do not:** call an LLM.

**Definition of done:**

- [ ] PII-like input is refused without Chroma write/logging
- [ ] “Should I buy HDFC small cap?” is `refused_advice`
- [ ] “Expense ratio of HDFC Large Cap Fund Direct Growth?” returns chunks whose `url` is the large-cap Groww page

### Cursor prompt — Phase 5

```
Implement Phase 5 only from Docs/implementation.md.
Follow Docs/architecture.md §6.1–6.3.
Add guardrails.py (rules-based) and retrieve.py using shared/embedder.py and existing Chroma collection.
Partial service: Guardrails → Retrieve only. CLI to print intent and chunks.
Do not add LLM generation or UI.
Assume Phase 4 ingest has been run (data/chroma exists). If missing, tell me to run ingest.
Stop at Phase 5 definition of done.
```

---

## Phase 6 — Generate + format (retrieval stage 3–4)

**Goal:** Facts-only answers with **exactly one citation URL** and last-updated stamp.

**Create:** `app/query/generate.py`, `app/query/format.py`; finish `app/query/service.py`.

**LLM:** Use env var (e.g. `OPENAI_API_KEY` or local endpoint). Put the client behind a small adapter so the model can be swapped without touching Chroma. `.env.example` with empty key.

**System prompt (must include):**

- Use only provided chunks
- ≤3 sentences
- No advice, no buy/sell, no suitability
- No computed or compared returns
- If chunks lack the fact, say so
- Citation URL must be one of the retrieved URLs

**Response contract (architecture §6.5):**  
`answer`, `citation_url`, `last_updated_from_sources`, `intent`, `disclaimer`

**Weak retrieval:** if distances are all poor, do not invent; still return closest in-scope URL.

**Definition of done:**

- [ ] Factual question → ≤3 sentences + correct scheme URL + date
- [ ] Advice question → refusal, `intent=refused_advice`, no ranking
- [ ] Returns question → no numbers computed; points at scheme URL
- [ ] Citation is never a URL that was not in the retrieved set

### Cursor prompt — Phase 6

```
Implement Phase 6 only from Docs/implementation.md.
Follow Docs/architecture.md §6.4–6.5.
Add generate.py and format.py. Complete query service: Guard → Retrieve → Generate → Format.
Facts-only LLM, ≤3 sentences, exactly one citation from retrieved chunks, Last updated from sources.
Adapter for LLM via env var. Do not build Streamlit UI yet.
Add a CLI that prints the JSON response contract for a question.
Stop at Phase 6 definition of done.
```

---

## Phase 7 — Tiny chat UI

**Goal:** Streamlit (or equivalent) thin client. No vector logic in the UI.

**Create:** `app/ui/app.py`

**Must have (PRD §6 / architecture §7):**

- Welcome line (facts-only HDFC FAQ assistant)
- Three example questions (clickable) from PRD:
  1. What is the expense ratio of HDFC Large Cap Fund Direct Growth?
  2. What is the lock-in for HDFC ELSS Tax Saver?
  3. What is the minimum SIP amount for HDFC Small Cap Fund?
- Persistent: **Facts-only. No investment advice.**
- Full disclaimer snippet from PRD §6.4
- Input + answers showing body, clickable citation, `Last updated from sources:`
- No PAN/email/phone fields
- Session-only chat; do not write PII to disk

**Definition of done:**

- [ ] `streamlit run app/ui/app.py` (or documented command) works locally
- [ ] Example clicks submit those questions
- [ ] Answers show one link and the last-updated line
- [ ] Disclaimer always visible

### Cursor prompt — Phase 7

```
Implement Phase 7 only from Docs/implementation.md.
Follow Docs/architecture.md §7 and PRD UI requirements in Docs/prd.md §6.
Build a tiny Streamlit chat UI that calls the existing query service only.
Welcome, 3 example questions, facts-only disclaimer, citation link, last-updated stamp.
No new RAG logic in the UI. No PII fields.
Stop at Phase 7 definition of done. Give the run command.
```

---

## Phase 8 — Deliverables and polish

**Goal:** Submission artifacts from the PRD. No new architecture.

**Create/update:**

- `README.md` — setup, ingest command, UI command, AMC + 5 schemes, known limits (PRD §12)
- `data/sources.csv` already exists; also `Docs/sources.md` if useful (same 5 URLs)
- `data/sample_qa.md` — 5–10 queries with **actual** assistant answers + links (run the service; do not invent)
- Disclaimer snippet copied into README
- `.gitignore` — `data/chroma/`, `.env`, `__pycache__`, `data/raw/`

**Sample Q&A should include:** at least one factual, one advice refusal, one returns refusal, one ELSS lock-in, one SIP/expense.

**Definition of done:**

- [ ] Fresh clone path: install → ingest → run UI documented
- [ ] Sample Q&A has 5–10 real outputs
- [ ] Known limits documented (Groww lag, five schemes only, MiniLM, hallucination mitigation)

### Cursor prompt — Phase 8

```
Implement Phase 8 only from Docs/implementation.md.
Write README.md, .gitignore, and data/sample_qa.md using real outputs from the query service (run it).
Include setup, scope (HDFC + five schemes), disclaimer, and known limits from Docs/prd.md §12.
Do not change RAG architecture. Stop at Phase 8 definition of done.
```

---

## Suggested Cursor workflow

| Session | Phase | Depends on |
| --- | --- | --- |
| 1 | 0 Scaffold | — |
| 2 | 1 Load | 0 |
| 3 | 2 Chunk | 1 (inspect text first) |
| 4 | 3 Embed | 2 |
| 5 | 4 Store + ingest CLI | 3 |
| 6 | 5 Guard + retrieve | 4 (Chroma must exist) |
| 7 | 6 Generate | 5 |
| 8 | 7 UI | 6 |
| 9 | 8 Docs | 7 |

If something fails, **re-run the same phase prompt** and paste the error. Do not jump to UI before Chroma ingest works.

---

## Phase complete checklist (copy into chat when verifying)

```
Phase __ :
- [ ] Matches architecture.md (named stages, separate modules)
- [ ] Did not start the next phase
- [ ] How to run: _______________
- [ ] What I inspected: _______________
```
