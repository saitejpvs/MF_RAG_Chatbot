# Product Requirements Document

**Product:** Mutual Fund FAQ RAG Chatbot  
**Scope:** HDFC AMC — 5 Direct–Growth schemes (Groww public pages)  
**Status:** Draft  
**Owner:** Product  
**Last updated:** 2026-09-27

---

## 1. Summary

Build a small, facts-only FAQ assistant that answers questions about five HDFC mutual fund schemes using Retrieval-Augmented Generation (RAG). The bot retrieves from a vector store built from five public Groww scheme pages and must cite a source link on every answer. It must not give investment advice, store PII, or compute/compare returns.

The architecture must implement both RAG stages as distinct steps:

| Stage | Pipeline |
| --- | --- |
| **Data ingestion** | Load → Chunk → Embed → Store in ChromaDB |
| **Data retrieval** | Query embed → Retrieve → Generate (facts-only) → Cite |

---

## 2. Problem

Retail investors and support/content teams repeatedly ask the same scheme facts: expense ratio, exit load, minimum SIP, ELSS lock-in, riskometer, benchmark, and how to download statements. Answers are scattered across public pages and are easy to mix with opinion.

Users need a narrow assistant that:

- Answers only from the allowed corpus
- Always shows where the fact came from
- Refuses “should I buy/sell?” style questions

---

## 3. Goals and non-goals

### Goals

- Ship a working RAG prototype for one AMC (HDFC) and five schemes.
- Answer factual queries in ≤3 sentences with one citation URL.
- Show a tiny chat UI: welcome line, 3 example questions, facts-only disclaimer.
- Keep ingestion and retrieval as separate, inspectable stages.

### Non-goals

- Portfolio advice, suitability, or “best fund” recommendations
- Return calculation, ranking, or performance comparison
- Login, KYC, transactions, or personal holdings
- Multi-AMC coverage, live market data, or production-scale crawl
- Using blogs, app backend screenshots, or unofficial write-ups as sources

---

## 4. Users

| User | Need |
| --- | --- |
| Retail investor comparing schemes | Fast, cited facts (fees, lock-in, SIP, riskometer) |
| Support / content | Same answers to repetitive FAQ traffic without advice |

---

## 5. In-scope corpus

**AMC:** HDFC  
**Distributor pages (public):** Groww (`https://groww.in/`)  
**Plan type:** Direct – Growth (all five)

| Category | Scheme (as listed on Groww) | Source URL |
| --- | --- | --- |
| Large Cap | HDFC Large Cap Fund – Direct Growth | https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth |
| Flexi Cap | HDFC Equity Fund – Direct Growth | https://groww.in/mutual-funds/hdfc-equity-fund-direct-growth |
| ELSS | HDFC ELSS Tax Saver Fund – Direct Plan Growth | https://groww.in/mutual-funds/hdfc-elss-tax-saver-fund-direct-plan-growth |
| Small Cap | HDFC Small Cap Fund – Direct Growth | https://groww.in/mutual-funds/hdfc-small-cap-fund-direct-growth |
| Balanced Advantage (Hybrid) | HDFC Balanced Advantage Fund – Direct Growth | https://groww.in/mutual-funds/hdfc-balanced-advantage-fund-direct-growth |

**Source rule:** Use only these five public pages for retrieval. Do not treat third-party blogs as sources. If a user asks for returns, link to the scheme page / factsheet-style section rather than computing numbers.

---

## 6. Product experience

### 6.1 UI (minimum)

- Welcome line explaining the bot is a facts-only HDFC scheme FAQ assistant
- Three clickable example questions
- Persistent note: **“Facts-only. No investment advice.”**
- Chat input + answer area
- Each answer shows:
  - Body (≤3 sentences)
  - One citation link
  - `Last updated from sources: <date>`

### 6.2 Example questions (UI)

1. What is the expense ratio of HDFC Large Cap Fund Direct Growth?
2. What is the lock-in for HDFC ELSS Tax Saver?
3. What is the minimum SIP amount for HDFC Small Cap Fund?

### 6.3 Answer types

| Query type | Behavior |
| --- | --- |
| Factual (expense ratio, exit load, min SIP, lock-in, riskometer, benchmark, statement download) | Retrieve + answer from corpus; one source URL |
| Opinion / advice (“Should I buy/sell?”, “Which is better?”) | Refuse politely; no ranking; optional educational link from corpus if relevant |
| Returns / performance comparison | Do not compute or compare; point to the official scheme page |
| PII (PAN, Aadhaar, account, OTP, email, phone) | Do not accept or store; tell the user not to share personal data |
| Out of corpus (other AMCs, other schemes) | Say the bot only covers the five HDFC schemes in scope |

### 6.4 Disclaimer (required in UI)

> Facts-only. No investment advice. Answers are retrieved from public Groww scheme pages for five HDFC Direct–Growth funds. Mutual fund investments are subject to market risks. Read all scheme-related documents carefully. This assistant does not collect PAN, Aadhaar, account numbers, OTPs, emails, or phone numbers.

---

## 7. Functional requirements

| ID | Requirement | Priority |
| --- | --- | --- |
| FR-1 | Ingest exactly the five Groww URLs into a local/offline-capable pipeline | P0 |
| FR-2 | Chunk, embed, and persist vectors in ChromaDB with source metadata (URL, scheme, category) | P0 |
| FR-3 | On each user query, embed the query, retrieve top-k chunks, generate a facts-only answer | P0 |
| FR-4 | Every answer includes exactly one citation URL from the retrieved set | P0 |
| FR-5 | Answers are ≤3 sentences and include `Last updated from sources:` | P0 |
| FR-6 | Advice/opinion intents are refused with a polite facts-only message | P0 |
| FR-7 | No PII is logged or stored | P0 |
| FR-8 | Tiny UI with welcome, 3 examples, and disclaimer | P0 |
| FR-9 | Ingestion and retrieval are implemented as separate modules/stages | P0 |
| FR-10 | README documents setup, scope, and known limits | P0 |
| FR-11 | Source list (CSV or MD) of the 5 URLs | P0 |
| FR-12 | Sample Q&A file (5–10 queries with answers + links) | P0 |

---

## 8. RAG architecture

Keep **ingestion** and **retrieval** as two pipelines. Do not collapse them into a single script that hides stages.

```
INGESTION
  Load (5 Groww HTML pages)
    → Chunk (recursive, section-aware — see §8.2)
      → Embed (sentence-transformers/all-MiniLM-L6-v2)
        → Store (ChromaDB + metadata)

RETRIEVAL
  User query
    → Guardrails (PII / advice / out-of-scope)
      → Embed query (same model)
        → Similarity search (ChromaDB, top-k)
          → Prompt LLM with retrieved chunks only
            → Answer + 1 citation + last-updated stamp
```

### 8.1 Loading

- Fetch the five public URLs.
- Extract visible text (scheme name, category, expense ratio, exit load, min investment/SIP, lock-in, riskometer, benchmark, AMC notes, statement/download guidance if present).
- Drop chrome (nav, ads, unrelated widgets) so chunks stay factual.
- Attach metadata: `url`, `scheme_name`, `category`, `amc=HDFC`, `fetched_at`.

### 8.2 Chunking strategy (decision)

**Decision: recursive character splitting, section-aware — not semantic chunking.**

**Why this data:** Groww scheme pages are short and structured (labeled fields + a few narrative blocks), not long unstructured SID/KIM PDFs. Facts users ask for (expense ratio, exit load, SIP, lock-in) sit in compact labeled sections. Recursive splits on headings/`\n\n`/`\n` keep a field and its value in the same chunk. Semantic chunking adds cost and variance without a clear gain on five pages.

**Suggested parameters (tune after first ingest):**

| Parameter | Value | Rationale |
| --- | --- | --- |
| Splitters | Headings, double newline, newline, sentence | Preserve field–value pairs |
| Target chunk size | 400–600 characters (~100–150 tokens) | MiniLM context is small; FAQ facts are short |
| Overlap | 80–100 characters | Avoid splitting “exit load 1% if redeemed within 1 year” across chunks |
| Min chunk size | Drop / merge fragments under ~80 characters | Reduce noise |

**Metadata on every chunk:** `url`, `scheme_name`, `category`, `chunk_index`, `fetched_at`.

Revisit semantic chunking only if later sources are long PDFs (KIM/SID) where section boundaries are weak.

### 8.3 Embedding

- **Model:** `sentence-transformers/all-MiniLM-L6-v2` (Hugging Face)
- Use the **same model** for documents and queries
- Store embeddings in ChromaDB; do not mix models across ingest and query

### 8.4 Vector store

- **DB:** ChromaDB (local persistent directory is fine for the prototype)
- Collection per corpus (e.g. `hdfc_mf_faqs`)
- Persist `text` + `embedding` + metadata listed above

### 8.5 Retrieval and generation

- Embed the user question; retrieve **top-k = 3–5** chunks
- Prefer same-scheme chunks when the query names a scheme
- Generator may only use retrieved text; if nothing relevant, say so and still point to the closest scheme URL
- Prompt rules: facts only; ≤3 sentences; one source URL; no advice; no invented numbers

---

## 9. Constraints and compliance

| Constraint | Rule |
| --- | --- |
| Public sources only | The five Groww URLs; no app-backend screenshots; no blogs |
| No PII | Do not accept or store PAN, Aadhaar, account numbers, OTPs, emails, phones |
| No performance claims | Do not compute or compare returns; link to the scheme page if asked |
| Clarity | ≤3 sentences; `Last updated from sources:` on every answer |
| No advice | Refuse buy/sell/suitability; educational redirect only |

---

## 10. Success criteria

The milestone is done when:

1. Ingestion runs end-to-end: 5 pages → chunks → MiniLM embeddings → ChromaDB.
2. A user can ask the example questions and get cited, ≤3-sentence answers.
3. Advice questions are refused.
4. Returns questions do not produce computed comparisons.
5. Deliverables in §11 are present.

**Quality bar (manual):** 8/10 sample questions in the Q&A file are factually consistent with the source page and include the correct URL.

---

## 11. Deliverables

| Deliverable | Description |
| --- | --- |
| Working prototype | App (preferred) or notebook; if hosting is not possible, ≤3-minute demo video |
| Source list | CSV or Markdown of the 5 URLs |
| README | Setup, AMC + scheme scope, known limits |
| Sample Q&A | 5–10 queries with assistant answers + links |
| Disclaimer snippet | Facts-only, no-advice text used in the UI |
| RAG chatbot | End product: chat UI backed by the two-stage RAG pipeline |

---

## 12. Known limits (to document in README)

- Corpus is five Groww pages for HDFC Direct–Growth schemes only.
- Groww is a public distributor page, not the AMC SID/KIM PDF; figures can lag official filings.
- No live NAV/returns engine; pages are point-in-time at `fetched_at`.
- MiniLM is English-centric and small; poor for very long or multilingual queries.
- Generator can still hallucinate if retrieval is weak — citation + refusal rules are the mitigation.

---

## 13. Out of scope (later)

- Additional AMCs or schemes
- Official HDFC/SEBI/AMFI PDF ingest (KIM, SID, factsheets) as a second corpus
- Auth, personalization, transaction flows
- Multi-turn portfolio context

---

## 14. Open decisions

| Topic | Default for v1 | Can change later |
| --- | --- | --- |
| LLM for generation | Any local or API chat model instructed as facts-only | Swap without changing embeddings |
| Hosting | Local app is enough | Hosted demo if easy |
| Chunk size | 400–600 chars, overlap 80–100 | Tune after inspecting chunks |
| k | 4 | Tune on the sample Q&A set |
