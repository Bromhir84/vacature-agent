from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

from app.discovery.broker_gate import (
    BROKER_PAGE_SIGNALS,
    EMPLOYER_HOST_HINTS,
    PORTAL_HOST_SUFFIXES,
    is_blocked_name,
    is_blocked_url,
)
from app.pipeline.rules import DEFAULT_BLOCKLIST, DEFAULT_STAFFING_KEYWORDS
DETAIL_PATH_RE = re.compile(
    r"/(vacatures?|vacancies|jobs?|opdrachten?|careers?)/[^/?#]+",
    re.I,
)
OVERVIEW_PATH_RE = re.compile(
    r"/(vacatures?|vacancies|jobs?|opdrachten?|careers?|werken-bij|carriere|carri[eè]re)/?$",
    re.I,
)
TECH_KEYWORDS = (
    "ict",
    " it ",
    "/it/",
    "software",
    "developer",
    "devops",
    "data",
    "cloud",
    "cyber",
    "security",
    "engineer",
    "architect",
    "analist",
    "analyst",
)


@dataclass
class RelevanceScore:
    score: float
    reasons: list[str] = field(default_factory=list)
    skip_broker: bool = False


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def _hostname(url: str) -> str:
    try:
        host = urlparse(url).hostname or ""
    except Exception:  # noqa: BLE001
        return ""
    return host.lower().removeprefix("www.")


def _host_matches_suffix(host: str, suffix: str) -> bool:
    suffix = suffix.lower().removeprefix("www.")
    return host == suffix or host.endswith("." + suffix)


def score_url_relevance(
    url: str,
    *,
    title: str | None = None,
    snippet: str | None = None,
    page_kind: str = "detail",
) -> RelevanceScore:
    """Cheap 0–1 score for how likely a URL yields appropriate vacatures."""
    reasons: list[str] = []
    block = is_blocked_url(url)
    if block.blocked:
        return RelevanceScore(0.0, [block.reason or "broker denylist"], skip_broker=True)
    name_block = is_blocked_name(title or "")
    if name_block.blocked:
        return RelevanceScore(0.0, [name_block.reason or "broker name"], skip_broker=True)

    parsed = urlparse(url)
    path = parsed.path or "/"
    host = _hostname(url)
    hay = " ".join(
        part for part in (url.lower(), (title or "").lower(), (snippet or "").lower()) if part
    )

    for pattern in BROKER_PAGE_SIGNALS:
        if pattern.search(hay):
            return RelevanceScore(
                0.0,
                [f"broker page signal: {pattern.pattern}"],
                skip_broker=True,
            )

    score = 0.2
    reasons.append("base")

    if page_kind == "detail":
        if DETAIL_PATH_RE.search(path):
            score += 0.28
            reasons.append("job detail path")
        elif OVERVIEW_PATH_RE.search(path.rstrip("/") + "/") or path.rstrip("/").endswith(
            ("vacatures", "vacancies", "jobs", "careers")
        ):
            score -= 0.15
            reasons.append("looks like overview not detail")
        else:
            # Soft credit if vacancy-ish tokens appear somewhere in path/query
            if re.search(r"vacature|vacancy|opdracht|/jobs?/|/careers?/", path + "?" + (parsed.query or ""), re.I):
                score += 0.12
                reasons.append("vacancy tokens in URL")
    else:
        if OVERVIEW_PATH_RE.search(path.rstrip("/") + "/") or any(
            token in path.lower() for token in ("vacatures", "werken-bij", "careers", "jobs")
        ):
            score += 0.18
            reasons.append("career overview path")
        if DETAIL_PATH_RE.search(path):
            score += 0.05
            reasons.append("nested vacancy path on overview")

    staffing_hits = [kw for kw in DEFAULT_STAFFING_KEYWORDS if kw.lower() in hay]
    if staffing_hits:
        score += min(0.08 * len(staffing_hits), 0.24)
        reasons.append(f"staffing keywords: {', '.join(staffing_hits[:3])}")

    tech_hits = []
    for kw in TECH_KEYWORDS:
        token = kw.strip().lower()
        if token and token in hay:
            tech_hits.append(token)
    # Word-boundary-ish IT match already covered via " it " / "/it/" patterns above.
    if re.search(r"\bict\b", hay, re.I):
        tech_hits.insert(0, "ict")
    tech_combined = list(dict.fromkeys(tech_hits))
    if tech_combined:
        score += min(0.06 * len(tech_combined), 0.18)
        reasons.append(f"ICT/tech keywords: {', '.join(tech_combined[:3])}")

    for hint in EMPLOYER_HOST_HINTS:
        if hint.search(host) or hint.search(url):
            score += 0.15
            reasons.append(f"employer career host: {host}")
            break

    for suffix in PORTAL_HOST_SUFFIXES:
        if _host_matches_suffix(host, suffix):
            score += 0.1 if page_kind == "overview" else 0.06
            reasons.append(f"public portal host: {host}")
            break

    block_hits = [b for b in DEFAULT_BLOCKLIST if b.lower() in hay]
    if block_hits:
        score -= min(0.12 * len(block_hits), 0.3)
        reasons.append(f"blocklist phrases: {', '.join(block_hits[:2])}")

    return RelevanceScore(score=round(_clamp(score), 3), reasons=reasons)
