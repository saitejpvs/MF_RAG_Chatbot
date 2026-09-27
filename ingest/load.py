"""Load Groww scheme pages into cleaned Document objects (ingestion stage 1).

Does not chunk, embed, or write to Chroma.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from bs4 import BeautifulSoup

from shared.config import (
    AMC,
    FETCH_TIMEOUT_SECONDS,
    FETCH_USER_AGENT,
    PREVIEW_CHARS,
    RAW_HTML_DIR,
    SOURCES_CSV,
)
from shared.schemas import Document, SourceRow

logger = logging.getLogger(__name__)

DROP_HTML_TAGS = (
    "script",
    "style",
    "noscript",
    "nav",
    "footer",
    "header",
    "iframe",
    "svg",
    "form",
)

CHROME_TEXT_PATTERNS = (
    r"^login$",
    r"^sign up$",
    r"^download app$",
    r"^related funds$",
    r"^popular funds$",
    r"^watchlist$",
)

PII_PATTERNS = (
    re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I),
    re.compile(r"\b(?:\+91[\s-]?)?[6-9]\d{9}\b"),
)


def read_sources(path: Path | None = None) -> list[SourceRow]:
    csv_path = path or SOURCES_CSV
    rows: list[SourceRow] = []
    with csv_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for raw in reader:
            rows.append(
                SourceRow(
                    doc_id=raw["doc_id"].strip(),
                    scheme_name=raw["scheme_name"].strip(),
                    category=raw["category"].strip(),
                    url=raw["url"].strip(),
                )
            )
    return rows


def fetch_html(url: str) -> str:
    response = requests.get(
        url,
        timeout=FETCH_TIMEOUT_SECONDS,
        headers={
            "User-Agent": FETCH_USER_AGENT,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-IN,en;q=0.9",
        },
    )
    response.raise_for_status()
    response.encoding = response.apparent_encoding or "utf-8"
    return response.text


def _next_data(html: str) -> dict[str, Any] | None:
    marker = 'id="__NEXT_DATA__"'
    start = html.find(marker)
    if start < 0:
        return None
    gt = html.find(">", start)
    end = html.find("</script>", gt)
    if gt < 0 or end < 0:
        return None
    try:
        return json.loads(html[gt + 1 : end])
    except json.JSONDecodeError:
        logger.warning("Failed to parse __NEXT_DATA__ JSON")
        return None


def _mf_payload(html: str) -> dict[str, Any] | None:
    data = _next_data(html)
    if not data:
        return None
    mf = (
        data.get("props", {})
        .get("pageProps", {})
        .get("mfServerSideData")
    )
    return mf if isinstance(mf, dict) else None


def _fmt(value: Any) -> str | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else f"{value:.4f}".rstrip("0").rstrip(".")
    return str(value).strip()


def _lock_in_text(lock: Any) -> str:
    if not isinstance(lock, dict):
        return "not specified on this page"
    parts: list[str] = []
    for key, label in (("years", "year(s)"), ("months", "month(s)"), ("days", "day(s)")):
        val = lock.get(key)
        if val not in (None, "", 0, "0"):
            parts.append(f"{val} {label}")
    return ", ".join(parts) if parts else "not specified on this page"


def _strip_pii(text: str) -> str:
    cleaned = text
    for pattern in PII_PATTERNS:
        cleaned = pattern.sub("[redacted]", cleaned)
    return cleaned


def text_from_mf_data(mf: dict[str, Any], source: SourceRow) -> str:
    """Turn Groww Next.js scheme payload into labeled factual text.

    Omits holdings, return series, peer ranks, and contact PII so the corpus
    stays FAQ-shaped and facts-only.
    """
    category_info = mf.get("category_info") if isinstance(mf.get("category_info"), dict) else {}
    rta = mf.get("rta_details") if isinstance(mf.get("rta_details"), dict) else {}

    def line(label: str, value: Any, suffix: str = "") -> str | None:
        formatted = _fmt(value)
        if formatted is None:
            return None
        return f"{label}: {formatted}{suffix}"

    lines: list[str | None] = [
        line("Scheme name", mf.get("scheme_name") or source.scheme_name),
        line("Fund name", mf.get("fund_name")),
        line("AMC", mf.get("amc") or AMC),
        line("Fund house", mf.get("fund_house")),
        line("Groww category", source.category),
        line("Category", mf.get("category")),
        line("Sub category", mf.get("sub_category")),
        line("Plan type", mf.get("plan_type")),
        line("Scheme type", mf.get("scheme_type")),
        line("Riskometer", mf.get("nfo_risk")),
        line("Benchmark", mf.get("benchmark")),
        line("Benchmark name", mf.get("benchmark_name")),
        line("Expense ratio", mf.get("expense_ratio"), "%"),
        line("Base expense ratio", mf.get("base_expense_ratio"), "%"),
        line("Exit load", mf.get("exit_load")),
        line("Lock-in", _lock_in_text(mf.get("lock_in"))),
        line("Minimum SIP", mf.get("min_sip_investment")),
        line("SIP allowed", mf.get("sip_allowed")),
        line("Minimum lumpsum (1st investment)", mf.get("min_investment_amount")),
        line("Minimum additional lumpsum", mf.get("mini_additional_investment")),
        line("Lumpsum allowed", mf.get("lumpsum_allowed")),
        line("Minimum withdrawal", mf.get("min_withdrawal")),
        line("AUM (₹ Cr)", mf.get("aum")),
        line("NAV", f"{_fmt(mf.get('nav'))} as of {_fmt(mf.get('nav_date'))}" if mf.get("nav") is not None else None),
        line("Launch date", mf.get("launch_date")),
        line("Allotment date", mf.get("allotment_date")),
        line("ISIN", mf.get("isin")),
        line("Stamp duty", mf.get("stamp_duty")),
        line("Investment objective", mf.get("description")),
        line("Category tax impact", category_info.get("tax_impact")),
        line("Category notes", category_info.get("description")),
        line("SID / AMC site", mf.get("sid_url")),
        line("AMC page", mf.get("amc_page_url")),
        line("RTA", rta.get("rta_name")),
        line("Source URL", source.url),
    ]

    historic = mf.get("historic_exit_loads") or []
    if isinstance(historic, list) and historic:
        lines.append("Historic exit load notes:")
        for row in historic:
            if not isinstance(row, dict):
                continue
            note = _fmt(row.get("note"))
            as_on = _fmt(row.get("as_on_date"))
            if note:
                lines.append(f"- {note} (as on {as_on})" if as_on else f"- {note}")

    managers = mf.get("fund_manager_details") or []
    if isinstance(managers, list) and managers:
        lines.append("Fund managers:")
        for row in managers:
            if not isinstance(row, dict):
                continue
            name = _fmt(row.get("person_name"))
            if name:
                lines.append(f"- {name}")

    cleaned = [item for item in lines if item]
    return _strip_pii("\n".join(cleaned))


def text_from_html_fallback(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(DROP_HTML_TAGS):
        tag.decompose()
    main = soup.find("main") or soup.find("article") or soup.body or soup
    text = main.get_text("\n", strip=True)
    kept: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if any(re.search(pat, line, re.I) for pat in CHROME_TEXT_PATTERNS):
            continue
        kept.append(line)
    return _strip_pii(re.sub(r"\n{3,}", "\n\n", "\n".join(kept)))


def extract_text(html: str, source: SourceRow) -> str:
    mf = _mf_payload(html)
    if mf:
        return text_from_mf_data(mf, source)
    logger.warning("No mfServerSideData for %s; falling back to HTML text", source.url)
    return text_from_html_fallback(html)


def save_raw_html(doc_id: str, html: str) -> None:
    RAW_HTML_DIR.mkdir(parents=True, exist_ok=True)
    (RAW_HTML_DIR / f"{doc_id}.html").write_text(html, encoding="utf-8")


def load_documents(
    sources: list[SourceRow] | None = None,
    *,
    save_raw: bool = True,
) -> list[Document]:
    sources = sources if sources is not None else read_sources()
    documents: list[Document] = []
    for source in sources:
        fetched_at = datetime.now(timezone.utc)
        try:
            html = fetch_html(source.url)
            if save_raw:
                save_raw_html(source.doc_id, html)
            text = extract_text(html, source)
            if not text.strip():
                raise ValueError("extracted text is empty")
            documents.append(
                Document(
                    doc_id=source.doc_id,
                    url=source.url,
                    scheme_name=source.scheme_name,
                    category=source.category,
                    amc=AMC,
                    text=text,
                    fetched_at=fetched_at,
                )
            )
            logger.info("Loaded %s (%s chars)", source.doc_id, len(text))
        except Exception as exc:  # noqa: BLE001 — continue across URLs
            logger.error("Failed to load %s (%s): %s", source.doc_id, source.url, exc)
    return documents


def inspect_documents(documents: list[Document], failed_count: int) -> None:
    fact_needles = ("expense ratio", "exit load", "minimum sip", "lock-in", "riskometer", "benchmark")
    print(f"Loaded {len(documents)} document(s); {failed_count} failure(s)\n")
    for doc in documents:
        preview = doc.text[:PREVIEW_CHARS].replace("\n", " | ")
        lowered = doc.text.lower()
        hits = [n for n in fact_needles if n in lowered]
        print("=" * 80)
        print(f"doc_id:     {doc.doc_id}")
        print(f"url:        {doc.url}")
        print(f"scheme:     {doc.scheme_name}")
        print(f"category:   {doc.category}")
        print(f"amc:        {doc.amc}")
        print(f"fetched_at: {doc.fetched_at.isoformat()}")
        print(f"chars:      {len(doc.text)}")
        print(f"fact labels:{', '.join(hits) if hits else ' none spotted'}")
        print(f"preview:    {preview}")
        print()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inspect Groww scheme page loading (Phase 1).")
    parser.add_argument("--no-raw", action="store_true", help="Do not write data/raw/*.html")
    parser.add_argument("--sources", type=Path, default=None, help="Override sources.csv path")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    sources = read_sources(args.sources) if args.sources else read_sources()
    documents = load_documents(sources, save_raw=not args.no_raw)
    inspect_documents(documents, failed_count=len(sources) - len(documents))
    if len(documents) != len(sources):
        return 1
    if any(not doc.text.strip() for doc in documents):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
