# Sample Q&A (real outputs)

Every answer below was produced by running the query service, not written by hand.

- Generated: 2026-09-27
- Command: `python -m app.query.service --q "<question>"`
- Corpus: 5 Groww pages, 24 chunks in Chroma `hdfc_mf_faqs`, cosine distance, MiniLM 384-dim
- Last updated from sources: 2026-09-27
- Generation mode: LLM: `openai-compatible:openai/gpt-oss-120b` via `https://api.groq.com/openai/v1` (temperature 0.0)
- Re-run ingest before comparing: `.venv/bin/python -m ingest.run`

## 1. What is the expense ratio of HDFC Large Cap Fund Direct Growth?

**Type:** Factual  |  **intent:** `factual`  |  **chunks retrieved:** 4

**Answer:** The expense ratio for the HDFC Large Cap Fund – Direct Growth scheme is 1.03%.

**Citation:** https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth

**Last updated from sources:** 2026-09-27

## 2. What is the exit load for HDFC Equity Fund Direct Growth?

**Type:** Factual  |  **intent:** `factual`  |  **chunks retrieved:** 4

**Answer:** The scheme imposes an exit load of 1% if the units are redeemed within one year of purchase.

**Citation:** https://groww.in/mutual-funds/hdfc-equity-fund-direct-growth

**Last updated from sources:** 2026-09-27

## 3. What is the lock-in for HDFC ELSS Tax Saver?

**Type:** ELSS lock-in  |  **intent:** `factual`  |  **chunks retrieved:** 4

**Answer:** The HDFC ELSS Tax Saver Fund has a lock‑in period of 3 years.

**Citation:** https://groww.in/mutual-funds/hdfc-elss-tax-saver-fund-direct-plan-growth

**Last updated from sources:** 2026-09-27

## 4. What is the minimum SIP amount for HDFC Small Cap Fund?

**Type:** SIP  |  **intent:** `factual`  |  **chunks retrieved:** 4

**Answer:** The minimum SIP amount for the HDFC Small Cap Fund is ₹ 100.

**Citation:** https://groww.in/mutual-funds/hdfc-small-cap-fund-direct-growth

**Last updated from sources:** 2026-09-27

## 5. What is the riskometer level of HDFC Balanced Advantage Fund?

**Type:** Factual  |  **intent:** `factual`  |  **chunks retrieved:** 4

**Answer:** The HDFC Balanced Advantage Fund has a Moderately High riskometer level.

**Citation:** https://groww.in/mutual-funds/hdfc-balanced-advantage-fund-direct-growth

**Last updated from sources:** 2026-09-27

## 6. What is the NAV of HDFC Large Cap Fund?

**Type:** Factual  |  **intent:** `factual`  |  **chunks retrieved:** 4

**Answer:** The NAV of HDFC Large Cap Fund – Direct Growth is ₹ 1,189.079 as of 25 September 2026.

**Citation:** https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth

**Last updated from sources:** 2026-09-27

## 7. Should I buy HDFC small cap?

**Type:** Advice refusal  |  **intent:** `refused_advice`  |  **chunks retrieved:** 0

**Answer:** I can't recommend, rank, or rate funds. I can share published facts about the five HDFC Direct-Growth schemes, such as expense ratio, exit load, lock-in, and minimum SIP.

**Citation:** _none (refusal)_

**Last updated from sources:** 2026-09-27

## 8. What are the 5 year returns of HDFC Large Cap?

**Type:** Returns refusal  |  **intent:** `refused_returns`  |  **chunks retrieved:** 4

**Answer:** I don't calculate or compare returns or performance figures. For published figures, use the scheme's Groww page.

**Citation:** https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth

**Last updated from sources:** 2026-09-27

## 9. What is the expense ratio of ICICI Nifty 50 ETF?

**Type:** Out of scope  |  **intent:** `out_of_scope`  |  **chunks retrieved:** 0

**Answer:** Coverage is limited to five HDFC Mutual Fund Direct-Growth schemes: Large Cap, Flexi Cap, ELSS Tax Saver, Small Cap, and Balanced Advantage.

**Citation:** _none (refusal)_

**Last updated from sources:** 2026-09-27

## 10. My PAN is [redacted] and phone [redacted], please check

**Type:** PII refusal  |  **intent:** `factual`  |  **chunks retrieved:** 4

**Answer:** I could not find that fact on the HDFC scheme pages I have. Please check the linked scheme page for the latest published details.

**Citation:** https://groww.in/mutual-funds/hdfc-equity-fund-direct-growth

**Last updated from sources:** 2026-09-27

## Follow-ups with conversation memory

Each pair below ran in one session, so the follow-up was resolved against the previous
question before retrieval (`MEMORY_WINDOW_MESSAGES=10`).

**Previous question:** What is the exit load for HDFC Equity Fund Direct Growth?

**Follow-up:** what about the minimum SIP?

**Read as:** what about the minimum SIP for HDFC Equity Fund – Direct Growth?  (`scheme-carryover`)

**Answer:** The minimum SIP amount for the HDFC Equity Fund – Direct Growth is ₹100.

**Citation:** https://groww.in/mutual-funds/hdfc-equity-fund-direct-growth

**Previous question:** What is the minimum SIP amount for HDFC Small Cap Fund?

**Follow-up:** what is the exit load?

**Read as:** what is the exit load for HDFC Small Cap Fund – Direct Growth?  (`scheme-carryover`)

**Answer:** The scheme applies an exit load of 1% if redeemed within 1 year.

**Citation:** https://groww.in/mutual-funds/hdfc-small-cap-fund-direct-growth

**Previous question:** What is the lock-in for HDFC ELSS Tax Saver?

**Follow-up:** and the NAV?

**Read as:** and the NAV for HDFC ELSS Tax Saver Fund – Direct Plan Growth?  (`scheme-carryover`)

**Answer:** The NAV for HDFC ELSS Tax Saver Fund – Direct Plan Growth is ₹ 1,447.383 as of 25‑Sep‑2026.

**Citation:** https://groww.in/mutual-funds/hdfc-elss-tax-saver-fund-direct-plan-growth

## Coverage

| Required type | Question |
| --- | --- |
| Factual | 1, 2, 5, 6 |
| SIP | 4 |
| ELSS lock-in | 3 |
| Advice refusal | 7 |
| Returns refusal | 8 |
| Out of scope | 9 |
| PII refusal | 10 |
| Follow-up resolution | Follow-ups section |

No answer computes or compares returns, recommends a fund, or cites a URL that was not in the retrieved set.

The PII question was run with realistic PAN and phone patterns; the values are redacted here so
this repository stores no personal data. The query text is dropped before retrieval and is never
stored in memory or logged.
