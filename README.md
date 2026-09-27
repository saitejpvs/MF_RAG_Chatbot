# HDFC Mutual Fund FAQ — facts-only RAG chatbot

A narrow retrieval-augmented assistant for **five HDFC Direct–Growth schemes**. It answers
published scheme facts (expense ratio, exit load, lock-in, minimum SIP, riskometer, benchmark,
NAV) from public Groww pages, always with one source link, and refuses advice, returns maths,
and personal data.

> **Facts-only. No investment advice.** Answers are retrieved from public Groww scheme pages
> for five HDFC Direct–Growth funds. Mutual fund investments are subject to market risks. Read
> all scheme-related documents carefully. This assistant does not collect PAN, Aadhaar,
> account numbers, OTPs, emails, or phone numbers.

## Scope

AMC: **HDFC Mutual Fund**. Five Direct–Growth schemes, all from `data/sources.csv`
(see [Docs/sources.md](Docs/sources.md)):

| Scheme | Groww category |
| --- | --- |
| HDFC Large Cap Fund – Direct Growth | large_cap |
| HDFC Equity Fund – Direct Growth | flexi_cap |
| HDFC ELSS Tax Saver Fund – Direct Plan Growth | elss |
| HDFC Small Cap Fund – Direct Growth | small_cap |
| HDFC Balanced Advantage Fund – Direct Growth | hybrid_baf |

## Setup

Requires Python 3.9+ (developed on 3.9; 3.11+ recommended).

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

The embedding model (`sentence-transformers/all-MiniLM-L6-v2`, ~90 MB) downloads on first run.
It runs on **ONNX Runtime** rather than sentence-transformers: same weights, same 384-dim vectors
(cosine 1.0000 against the torch build), no torch. Torch's 339 MB of shared libraries were enough
to get the container OOM-killed on Render's 512 MB free tier; see `render.yaml`.

### Optional: LLM for prose answers

```bash
cp .env.example .env      # then set LLM_API_KEY
```

Any OpenAI-compatible endpoint works (OpenAI, Groq, Ollama, LM Studio, vLLM) via `LLM_BASE_URL`
and `LLM_MODEL`. **With no key the app still runs**: answers are assembled extractively from the
retrieved chunk text, so they stay facts-only but read like field labels rather than sentences.

Groq example (check `https://api.groq.com/openai/v1/models` for a model your key can reach):

```bash
LLM_API_KEY=gsk_...
LLM_BASE_URL=https://api.groq.com/openai/v1
LLM_MODEL=openai/gpt-oss-120b
```

Tunable in `.env` (with defaults in `shared/config.py`): `LLM_TIMEOUT_SECONDS` (30),
`LLM_MAX_ATTEMPTS` (3), `LLM_RETRY_BACKOFF` (2.0). Rate-limit and transient 5xx replies are
retried up to `LLM_MAX_ATTEMPTS` using the server's `Retry-After` before the extractive
fallback takes over, so a 429 degrades quality instead of breaking the answer.

## Ingest (once, and whenever sources change)

```bash
.venv/bin/python -m ingest.run
```

Fetches the five Groww pages, cleans them, chunks them recursively (500 chars, 100 overlap),
embeds with MiniLM, and upserts into Chroma at `data/chroma` (collection `hdfc_mf_faqs`).
Re-running is idempotent: chunks are upserted by `chunk_id`, so the count stays at 24.

Useful variants:

```bash
.venv/bin/python -m ingest.run --no-raw          # skip writing data/raw/*.html
.venv/bin/python -m ingest.store --query "..."   # inspect the store, no ingest
```

## Run the UI

```bash
.venv/bin/python -m streamlit run app/ui/app.py
```

Three clickable example questions, a persistent disclaimer, one citation link per answer, and a
`Last updated from sources:` line. Chat history is session-only; nothing is written to disk.

## Follow-up questions

The UI remembers the last 10 messages (5 exchanges) so a follow-up is answered about the fund you
just asked about:

```
You: What is the exit load for HDFC Equity Fund Direct Growth?
Bot: The scheme imposes an exit load of 1% if the units are redeemed within one year…
You: what about the minimum SIP?
Bot: The minimum SIP amount for the HDFC Equity Fund – Direct Growth is ₹100.
     Read as: what about the minimum SIP for HDFC Equity Fund – Direct Growth?
```

The resolved question is shown as `Read as:` so you can see the interpretation. A question that
already names a fund is never rewritten, guardrails always run on your raw words first, and
refused turns are not remembered. Tune or disable it:

| `.env` key | Default | Effect |
| --- | --- | --- |
| `MEMORY_WINDOW_MESSAGES` | `10` | Messages kept in process |
| `MEMORY_LLM_REWRITE` | `0` | `1` also paraphrases follow-ups with the LLM (slower, one extra call) |

Try it without the UI:

```bash
.venv/bin/python -m app.query.service --followups
```

## Query without the UI

```bash
.venv/bin/python -m app.query.service --q "What is the lock-in for HDFC ELSS Tax Saver?"
.venv/bin/python -m app.query.service --q "..." --detail    # + intent and retrieved chunks
.venv/bin/python -m app.query.service                        # 8-question battery as JSON
```

Response contract (architecture §6.5):

```json
{
  "answer": "…",
  "citation_url": "https://groww.in/mutual-funds/…",
  "last_updated_from_sources": "2026-09-27",
  "intent": "factual",
  "disclaimer": "Facts only. No investment advice."
}
```

## How it works

Offline pipeline (`python -m ingest.run`), one module per stage:

```
data/sources.csv
  → ingest/load.py    fetch + clean the 5 Groww pages  → Document
  → ingest/chunk.py   recursive section-aware split    → Chunk (24 total)
  → ingest/embed.py   shared/embedder.py, MiniLM 384d
  → ingest/store.py   Chroma upsert by chunk_id, cosine
```

Online pipeline (per chat turn, `app/query/`):

```
question
  → guardrails.py   rules: PII, advice, returns, out-of-scope
  → memory.py       optional: resolve an elided follow-up from the last 10 messages
  → retrieve.py     shared/embedder.py + Chroma top-k=4, scheme filter first
  → generate.py     facts-only LLM behind a swappable adapter (or extractive fallback)
  → format.py       one citation from the retrieved set, ≤3 sentences, last-updated stamp
  → service.py      returns the response contract; Streamlit UI just renders it
```

Both sides import the same `shared/embedder.py`, so documents and queries are always encoded
with the same model, the same prefix rule, and the same normalization.

## Deliverables

| Artifact | Path |
| --- | --- |
| Source list | `data/sources.csv`, [Docs/sources.md](Docs/sources.md) |
| Sample Q&A (real outputs) | [data/sample_qa.md](data/sample_qa.md) |
| Product spec / design | [Docs/prd.md](Docs/prd.md), [Docs/architecture.md](Docs/architecture.md) |
| Build guide | [Docs/implementation.md](Docs/implementation.md) |
| Disclaimer used in the UI | `app/ui/app.py` and `app/query/format.py` |

## Known limits

From [Docs/prd.md](Docs/prd.md) §12:

- The corpus is **five** Groww pages for HDFC Direct–Growth schemes only. Any other AMC or
  scheme is answered with a coverage message, not a guess.
- Groww is a public distributor page, not the AMC SID/KIM PDF, so figures can lag official filings.
- No live NAV or returns engine; every fact is point-in-time at `fetched_at`, and the UI shows
  that date.
- MiniLM is English-centric and small. It is weak for very long, multilingual, or heavily
  paraphrased questions.
- The generator can still hallucinate when retrieval is weak. Mitigations: every answer is
  restricted to retrieved chunks, capped at 3 sentences, cited with a URL that must appear in
  the retrieved set, and a weak-retrieval distance gate returns "could not find that fact"
  instead of an invented answer.
- Re-ingest is a CLI step, not a chat action, so the corpus is only as fresh as the last run.

## Out of scope for v1

More AMCs or schemes, official HDFC/SEBI/AMFI PDF ingest, auth or personalization, transaction
flows, and multi-turn portfolio context.
