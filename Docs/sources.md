# Sources

Public source list for the HDFC Mutual Fund FAQ assistant: five Groww scheme pages, all
Direct–Growth. This mirrors `data/sources.csv`, which is what the ingest pipeline reads.

| # | Scheme | Category | URL |
| --- | --- | --- | --- |
| 1 | HDFC Large Cap Fund – Direct Growth | large_cap | https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth |
| 2 | HDFC Equity Fund – Direct Growth | flexi_cap | https://groww.in/mutual-funds/hdfc-equity-fund-direct-growth |
| 3 | HDFC ELSS Tax Saver Fund – Direct Plan Growth | elss | https://groww.in/mutual-funds/hdfc-elss-tax-saver-fund-direct-plan-growth |
| 4 | HDFC Small Cap Fund – Direct Growth | small_cap | https://groww.in/mutual-funds/hdfc-small-cap-fund-direct-growth |
| 5 | HDFC Balanced Advantage Fund – Direct Growth | hybrid_baf | https://groww.in/mutual-funds/hdfc-balanced-advantage-fund-direct-growth |

Notes:

- These are public distributor pages, not the AMC's SID/KIM documents, so figures can lag
  official filings. Each answer carries the `fetched_at` date of the page it came from.
- Nothing else is in scope. Questions about other AMCs or other schemes get a coverage message.
- Raw HTML is written to `data/raw/` during ingest for debugging only and is git-ignored; it is
  never stored in the vector database.
