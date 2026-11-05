from __future__ import annotations

import re
from dataclasses import dataclass

from app.schemas import ListingDraft

DEFAULT_STAFFING_KEYWORDS = [
    "detachering",
    "detacheerder",
    "gedetacheerd",
    "inlener",
    "inhuur",
    "inhuren",
    "interim",
    "zzp",
    "freelance",
]

DEFAULT_ALLOWLIST = [
    "inhuur",
    "detachering",
    "interim",
    "zzp",
    "freelance",
    "extern",
]

DEFAULT_BLOCKLIST = [
    "vast dienstverband",
    "tijdelijk dienstverband met uitzicht op vast",
    "stage",
    "traineeship",
]

# "extern" only counts inside staffing-ish phrases
EXTERN_PHRASES = [
    r"externe\s+inhuur",
    r"externe\s+professional",
    r"externe\s+kracht",
    r"via\s+extern",
    r"\bextern\b.*\b(inhuur|detach|interim|zzp)\b",
    r"\b(inhuur|detach|interim|zzp)\b.*\bextern\b",
]


@dataclass
class RuleResult:
    passed: bool
    reasons: list[str]


def _norm(text: str | None) -> str:
    return (text or "").lower()


def evaluate_listing(
    draft: ListingDraft,
    *,
    staffing_keywords: list[str] | None = None,
    employment_allowlist: list[str] | None = None,
    employment_blocklist: list[str] | None = None,
) -> RuleResult:
    keywords = staffing_keywords or DEFAULT_STAFFING_KEYWORDS
    allowlist = [a.lower() for a in (employment_allowlist or DEFAULT_ALLOWLIST)]
    blocklist = [b.lower() for b in (employment_blocklist or DEFAULT_BLOCKLIST)]

    haystack = " ".join(
        filter(
            None,
            [
                draft.title,
                draft.employment_type,
                draft.description,
                draft.raw_snippet,
                " ".join(draft.tags or []),
            ],
        )
    )
    text = _norm(haystack)
    employment = _norm(draft.employment_type)
    tags = [_norm(t) for t in (draft.tags or [])]
    reasons: list[str] = []

    # Allowlist via employment type or tags
    for allowed in allowlist:
        if allowed and (allowed in employment or any(allowed in t for t in tags)):
            reasons.append(f"employment_allowlist:{allowed}")
            break

    # Keyword hits (word-ish)
    for kw in keywords:
        kw_l = kw.lower()
        if kw_l == "extern":
            continue
        if re.search(rf"\b{re.escape(kw_l)}\b", text):
            reasons.append(f"keyword:{kw}")

    for pattern in EXTERN_PHRASES:
        if re.search(pattern, text, flags=re.IGNORECASE):
            reasons.append("keyword_phrase:extern_staffing")
            break

    blocked = False
    for blocked_term in blocklist:
        if blocked_term and blocked_term in employment:
            blocked = True
            reasons.append(f"employment_blocklist:{blocked_term}")
            break

    if reasons and any(r.startswith(("employment_allowlist:", "keyword:", "keyword_phrase:")) for r in reasons):
        # Allowlist/keyword wins even if also blocked (e.g. odd dual labels)
        return RuleResult(passed=True, reasons=reasons)

    if blocked:
        return RuleResult(passed=False, reasons=reasons or ["blocked_employment_type"])

    return RuleResult(passed=False, reasons=reasons or ["no_staffing_signal"])
