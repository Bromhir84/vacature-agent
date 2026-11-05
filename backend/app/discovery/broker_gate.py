from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from fastapi import HTTPException


# Hard denylist: broker / marketplace / aggregator hosts (suffix match on hostname).
BROKER_DOMAIN_SUFFIXES: tuple[str, ...] = (
    "freep.nl",
    "www.freep.nl",
    "temper.works",
    "www.temper.works",
    "youngones.com",
    "www.youngones.com",
    "youngones.nl",
    "www.youngones.nl",
    "indeed.com",
    "www.indeed.com",
    "nl.indeed.com",
    "linkedin.com",
    "www.linkedin.com",
    "monsterboard.nl",
    "www.monsterboard.nl",
    "nationalevacaturebank.nl",
    "www.nationalevacaturebank.nl",
    "jobbird.com",
    "www.jobbird.com",
    "werk.nl",
    "www.werk.nl",
    "uitzendbureau.nl",
    "www.uitzendbureau.nl",
    "unique.nl",
    "www.unique.nl",
    "randstad.nl",
    "www.randstad.nl",
    "tempo-team.nl",
    "www.tempo-team.nl",
    "manpower.nl",
    "www.manpower.nl",
    "startpeople.nl",
    "www.startpeople.nl",
    "otto-workforce.com",
    "www.otto-workforce.com",
    "undutchables.nl",
    "www.undutchables.nl",
    "yacht.nl",
    "www.yacht.nl",
    "hays.nl",
    "www.hays.nl",
    "robertwalters.nl",
    "www.robertwalters.nl",
    "michaelpage.nl",
    "www.michaelpage.nl",
    "experis.nl",
    "www.experis.nl",
    "brunel.net",
    "www.brunel.net",
    "brunel.nl",
    "www.brunel.nl",
    "detacheerders.nl",
    "www.detacheerders.nl",
    "freelance.nl",
    "www.freelance.nl",
    "hoppenbrouwers.nl",  # staffing-heavy; keep gated
    # Boards / aggregators commonly hit by open-web crawl
    "glassdoor.nl",
    "glassdoor.com",
    "jooble.org",
    "werkzoeken.nl",
    "ictergezocht.nl",
    "vacatures.com",
    "vdab.be",
    "techniekwerkt.nl",
    "engineering.jobs",
    "zzp-opdrachten.nl",
    "inhuurloket.nl",
    "inhuurbron.nl",
    "impactvandaag.nl",
    "detransparentebroker.nl",
    "1upply.nl",
    "redcarpet.careers",
    "magnitglobal.com",
    "matchmatters.nl",
    "talentvoorit.nl",
    "devopscarriere.nl",
    "carriereverkenner.nl",
    # Social / video noise frequently linked from career footers
    "youtube.com",
    "youtu.be",
    "tiktok.com",
    "facebook.com",
    "instagram.com",
    "twitter.com",
    "x.com",
)

BROKER_NAME_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bfreep\b", re.I),
    re.compile(r"\balliander\s+inhuur\b", re.I),
    re.compile(r"\buitzend(bureau|kracht)\b", re.I),
    re.compile(r"\bdetach(eer|erings)?bureau\b", re.I),
    re.compile(r"\bdetacheerder\b", re.I),
    re.compile(r"\bICT[- ]?detachering\b", re.I),
    re.compile(r"\bstaffing\s+(agency|markt|marketplace)\b", re.I),
    re.compile(r"\bmarktplaats\b", re.I),
    re.compile(r"\bjob\s*board\b", re.I),
)

PORTAL_HOST_SUFFIXES: tuple[str, ...] = (
    "werkenvoornederland.nl",
    "werkenbijdeoverheid.nl",
)

EMPLOYER_HOST_HINTS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^werkenbij[.\-]", re.I),
    re.compile(r"\bwerkenbij", re.I),
    re.compile(r"^werken-bij", re.I),
    re.compile(r"\bcareers?\.", re.I),
    re.compile(r"^jobs\.", re.I),
)

BROKER_PAGE_SIGNALS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bvia\s+(ons\s+)?(uitzend|detach|bureau)\b", re.I),
    re.compile(r"\buitzendbureau\b", re.I),
    re.compile(r"\bdetacheringbureau\b", re.I),
    re.compile(r"\bprofessionals?\s+bemiddelen\b", re.I),
    re.compile(r"\bopdrachtgevers?\s+en\s+opdrachtnemers?\b", re.I),
    re.compile(r"\bregistreer\s+als\s+(zzp|freelancer)\b", re.I),
    re.compile(r"\bmarketplace\b", re.I),
    re.compile(r"\bjob\s*board\b", re.I),
    re.compile(r"\bduizenden\s+opdrachten\b", re.I),
    re.compile(r"\bwij\s+zijn\s+(een\s+)?(ict[- ]?)?detacheerder\b", re.I),
    re.compile(r"\bals\s+(ict[- ]?)?detacheerder\b", re.I),
    re.compile(r"\bwij\s+detacheren\b", re.I),
    re.compile(r"\b(ict[- ]?)?detacheerder\s+(van|voor|in)\b", re.I),
    re.compile(r"\bspecialist\s+in\s+(ict[- ]?)?detachering\b", re.I),
)

EMPLOYER_PAGE_SIGNALS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bwerken\s+bij\b", re.I),
    re.compile(r"\bonze\s+vacatures\b", re.I),
    re.compile(r"\bcarri[eè]re\s+bij\b", re.I),
    re.compile(r"\bas\s+werkgever\b", re.I),
    re.compile(r"\bmedewerkers?\s+vertellen\b", re.I),
)


@dataclass
class BlockResult:
    blocked: bool
    reason: str | None = None


@dataclass
class KindScore:
    kind: str  # employer | portal | broker | unknown
    broker_risk: float
    reasons: list[str] = field(default_factory=list)


def _hostname(url: str) -> str:
    raw = (url or "").strip()
    if not raw:
        return ""
    if "://" not in raw:
        raw = "https://" + raw
    try:
        host = urlparse(raw).hostname or ""
    except Exception:  # noqa: BLE001
        return ""
    return host.lower().removeprefix("www.")


def _host_matches_suffix(host: str, suffix: str) -> bool:
    suffix = suffix.lower().removeprefix("www.")
    return host == suffix or host.endswith("." + suffix)


def is_blocked_url(url: str) -> BlockResult:
    host = _hostname(url)
    if not host:
        return BlockResult(False)
    for suffix in BROKER_DOMAIN_SUFFIXES:
        clean = suffix.lower().removeprefix("www.")
        if _host_matches_suffix(host, clean):
            return BlockResult(True, f"denylisted broker/marketplace domain: {host}")
    return BlockResult(False)


def is_blocked_name(name: str) -> BlockResult:
    text = (name or "").strip()
    if not text:
        return BlockResult(False)
    for pattern in BROKER_NAME_PATTERNS:
        if pattern.search(text):
            return BlockResult(True, f"denylisted broker name pattern: {pattern.pattern}")
    return BlockResult(False)


def assert_source_allowed(*, name: str, base_url: str, list_url: str | None = None) -> None:
    """Raise HTTP 400 if name or URLs hit the hard denylist."""
    for check in (
        is_blocked_name(name),
        is_blocked_url(base_url),
        is_blocked_url(list_url or ""),
    ):
        if check.blocked:
            raise HTTPException(status_code=400, detail=check.reason or "Blocked broker source")


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def score_source_kind(
    name: str,
    url: str,
    page_text: str | None = None,
    *,
    use_llm: bool = False,
) -> KindScore:
    reasons: list[str] = []
    risk = 0.15
    kind = "unknown"

    block = is_blocked_url(url) or is_blocked_name(name)
    if block.blocked:
        return KindScore("broker", 1.0, [block.reason or "hard denylist"])

    host = _hostname(url)
    for suffix in PORTAL_HOST_SUFFIXES:
        if _host_matches_suffix(host, suffix):
            kind = "portal"
            risk = 0.05
            reasons.append(f"trusted public portal host: {host}")
            break

    if kind != "portal":
        for hint in EMPLOYER_HOST_HINTS:
            if hint.search(host) or hint.search(url):
                kind = "employer"
                risk = 0.1
                reasons.append(f"employer career host hint: {host}")
                break

    hay = " ".join(part for part in (name, url, (page_text or "")[:4000]) if part)
    broker_hits = [p.pattern for p in BROKER_PAGE_SIGNALS if p.search(hay)]
    employer_hits = [p.pattern for p in EMPLOYER_PAGE_SIGNALS if p.search(hay)]

    if broker_hits:
        risk = _clamp(risk + 0.25 * len(broker_hits))
        reasons.append(f"broker page signals: {', '.join(broker_hits[:3])}")
        if risk >= 0.7:
            kind = "broker"

    if employer_hits and kind != "broker":
        risk = _clamp(risk - 0.1 * min(len(employer_hits), 3))
        reasons.append(f"employer page signals: {', '.join(employer_hits[:3])}")
        if kind == "unknown":
            kind = "employer"

    if use_llm and page_text:
        llm_score = _llm_kind_score(name, url, page_text)
        if llm_score is not None:
            # Blend: trust LLM kind when confident; keep max risk.
            if llm_score.reasons:
                reasons.extend(llm_score.reasons[:2])
            risk = _clamp(max(risk, llm_score.broker_risk))
            if llm_score.kind in {"employer", "portal", "broker"} and (
                kind == "unknown" or llm_score.broker_risk >= 0.6
            ):
                kind = llm_score.kind

    if not reasons:
        reasons.append("no strong employer/broker signals")

    return KindScore(kind=kind, broker_risk=round(risk, 3), reasons=reasons)


def _llm_kind_score(name: str, url: str, page_text: str) -> KindScore | None:
    try:
        from app.llm import chat_completion, parse_json_content
        from app.pipeline.settings_store import resolve_llm_config

        llm = resolve_llm_config()
        if not llm.get("llm_api_key"):
            return None

        snippet = re.sub(r"\s+", " ", page_text)[:2500]
        response = chat_completion(
            [
                {
                    "role": "system",
                    "content": (
                        "Classify a Dutch career/vacancy page. "
                        'Return JSON only: {"kind":"employer|portal|broker|unknown",'
                        '"broker_risk":0.0-1.0,"reason":"short"} . '
                        "employer = company careers site; portal = government/public job portal; "
                        "broker = uitzend/detach marketplace or staffing agency board."
                    ),
                },
                {
                    "role": "user",
                    "content": f"Name: {name}\nURL: {url}\nPage text:\n{snippet}",
                },
            ],
            json_mode=True,
            temperature=0.0,
            max_tokens=200,
        )
        data: dict[str, Any] = parse_json_content(response.choices[0].message.content) or {}
        kind = str(data.get("kind") or "unknown")
        if kind not in {"employer", "portal", "broker", "unknown"}:
            kind = "unknown"
        risk = float(data.get("broker_risk") or 0.5)
        reason = str(data.get("reason") or "llm classification")
        return KindScore(kind=kind, broker_risk=_clamp(risk), reasons=[f"llm: {reason}"])
    except Exception:  # noqa: BLE001
        return None
