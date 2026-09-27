"""Rules-based guardrails run before retrieval (retrieval stage 1, architecture 6.2).

No LLM. Detects PII, advice, returns/performance, and out-of-scope AMCs.
A refused PII message is never logged or echoed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

INTENT_FACTUAL = "factual"
INTENT_PII = "refused_pii"
INTENT_ADVICE = "refused_advice"
INTENT_RETURNS = "refused_returns"
INTENT_OUT_OF_SCOPE = "out_of_scope"

PII_MESSAGE = (
    "Do not share personal data. This assistant does not store PAN, Aadhaar, "
    "account numbers, OTPs, emails, or phones."
)
ADVICE_MESSAGE = (
    "I can't recommend, rank, or rate funds. I can share published facts about the "
    "five HDFC Direct-Growth schemes, such as expense ratio, exit load, lock-in, and "
    "minimum SIP."
)
RETURNS_MESSAGE = (
    "I don't calculate or compare returns or performance figures. For published "
    "figures, use the scheme's Groww page."
)
OUT_OF_SCOPE_MESSAGE = (
    "Coverage is limited to five HDFC Mutual Fund Direct-Growth schemes: Large Cap, "
    "Flexi Cap, ELSS Tax Saver, Small Cap, and Balanced Advantage."
)

PII_PATTERNS = (
    re.compile(r"\b[a-z]{5}\d{4}[a-z]\b", re.I),  # PAN
    re.compile(r"\b\d{4}\s?\d{4}\s?\d{4}\b"),  # Aadhaar
    re.compile(r"\b[\w.%+-]+@[\w.-]+\.[a-z]{2,}\b", re.I),  # email
    re.compile(r"\b(?:\+?91[\s-]?)?[6-9]\d{9}\b"),  # phone
)

PII_KEYWORDS = (
    "pan number",
    "pan card",
    "aadhaar",
    "aadhar",
    "account number",
    "bank account",
    "otp",
    "one time password",
    "password",
    "phone number",
    "mobile number",
    "email id",
    "credit card",
    "debit card",
    "demat",
    "folio number",
)

# Unambiguous requests for a judgement. Checked first so "should I buy" wins even
# when the question also contains fact words.
STRONG_ADVICE_PATTERNS = (
    r"\bshould i\b",
    r"\bshould we\b",
    r"\bshall i\b",
    r"\bcan i\b",
    r"\bwould you\b",
    r"\bwhich (?:one|fund|scheme|is better|should)\b",
    r"\bwhat should i\b",
    r"\b(?:best|top|safest|good|great|nice)\b[\w\s]{0,20}\b(?:fund|scheme|mutual fund|elss|option|choice)",
    r"\b(?:is|are)\s+(?:it|this|that|hdfc\w*)\s+(?:a\s+)?(?:good|great|best|safe|safer|worth)\b",
    r"\brecommend",
    r"\bsuggest",
    r"\bshortlist",
    r"\badvice\b",
    r"\bsuitable\b",
    r"\bworth investing\b",
    r"\bworth it\b",
    r"\bworth (?:buying|investing|purchasing)\b",
    r"\bgood choice\b",
    r"\branking\b",
    r"\b(?:want|plan|planning|thinking|looking) (?:to )?(?:buy|sell|invest|purchase|start investing)\b",
    r"\bhelp me choose\b",
)

# Verbs that mean "act on this", not "describe this". Kept out of
# STRONG_ADVICE so factual words like "exit load" and "hold period" still pass.
LOOSE_ADVICE_PATTERNS = (
    r"\bbuy\b",
    r"\bsell\b",
    r"\bpurchase\b",
    r"\binvest\b",
    r"\bput money\b",
)

# FAQ-shaped fact vocabulary. A comparison question about these stays factual.
FACT_PATTERNS = (
    r"\bexpense ratio\b",
    r"\bexit load\b",
    r"\bexit penalty\b",
    r"\block[\s-]?in\b",
    r"\bminimum sip\b",
    r"\bmin(?:imum)? (?:sip|lumpsum|investment|withdrawal)\b",
    r"\bsip amount\b",
    r"\blumpsum\b",
    r"\bnav\b",
    r"\baum\b",
    r"\bbenchmark\b",
    r"\briskometer\b",
    r"\bfund manager\b",
    r"\bstamp duty\b",
    r"\bisin\b",
    r"\blaunch date\b",
    r"\btax\b",
    r"\bdirect growth\b",
    r"\bplan type\b",
    r"\bminimum\b",
    r"\btell me about\b",
)

RETURNS_PATTERNS = (
    r"\breturns?\b",
    r"\bcagr\b",
    r"\bxirr\b",
    r"\birr\b",
    r"\boutperform\w*",
    r"\bunderperform\w*",
    r"\bperform\w*",
    r"\bperformance\b",
    r"\bcompare\b",
    r"\bversus\b",
    r"\bvs\.?\b",
    r"\bwhich (?:grew|performed)\b",
    r"\bhow much (?:did|has)\b.*\bgrow",
    r"\bprofit\b",
    r"\bgained\b",
)

OTHER_AMCS = (
    "icici",
    "axis",
    "kotak",
    "sbi",
    "nippon",
    "tata",
    "aditya birla",
    "birla",
    "mirae",
    "canara",
    "punjab",
    "bajaj",
    "idbi",
    "union",
    "dsp",
    "invesco",
    "quant",
    "pgim",
    "mahindra",
    "sundaram",
    "shriram",
    "baroda",
    "angel",
    "motilal",
    "parag parikh",
    "ppf",
    "sbi mf",
)


@dataclass(frozen=True)
class GuardDecision:
    intent: str
    message: str
    should_retrieve: bool
    skip_generate: bool
    matched_rule: str

    @property
    def refused(self) -> bool:
        return self.intent != INTENT_FACTUAL


def _matches(text: str, patterns: tuple[str, ...]) -> str | None:
    for pattern in patterns:
        if re.search(pattern, text, re.IGNORECASE):
            return pattern
    return None


def has_pii(question: str) -> str | None:
    """Return the matched rule name only. Never returns or logs the raw text."""
    lowered = question.lower()
    for keyword in PII_KEYWORDS:
        if keyword in lowered:
            return f"keyword:{keyword}"
    for pattern in PII_PATTERNS:
        if pattern.search(question):
            return f"pattern:{pattern.pattern}"
    return None


def check(question: str) -> GuardDecision:
    """Classify a question into one of the five contract intents."""
    question = question.strip()
    if not question:
        return GuardDecision(
            INTENT_OUT_OF_SCOPE,
            "Please ask a question about one of the five HDFC Direct-Growth schemes.",
            False,
            True,
            "empty",
        )

    if has_pii(question):
        return GuardDecision(INTENT_PII, PII_MESSAGE, False, True, "pii")

    strong_advice = _matches(question, STRONG_ADVICE_PATTERNS)
    if strong_advice:
        return GuardDecision(INTENT_ADVICE, ADVICE_MESSAGE, False, True, f"advice:{strong_advice}")

    is_fact_question = _matches(question, FACT_PATTERNS) is not None
    returns_hit = _matches(question, RETURNS_PATTERNS)
    if returns_hit and not is_fact_question:
        return GuardDecision(INTENT_RETURNS, RETURNS_MESSAGE, True, True, f"returns:{returns_hit}")

    loose_advice = _matches(question, LOOSE_ADVICE_PATTERNS)
    if loose_advice and not is_fact_question:
        return GuardDecision(INTENT_ADVICE, ADVICE_MESSAGE, False, True, f"advice:{loose_advice}")

    lowered = question.lower()
    if any(amc in lowered for amc in OTHER_AMCS):
        return GuardDecision(INTENT_OUT_OF_SCOPE, OUT_OF_SCOPE_MESSAGE, False, True, "other_amc")

    return GuardDecision(INTENT_FACTUAL, "", True, False, "in_scope")
