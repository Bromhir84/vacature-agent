from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

from app.crawl.score import RelevanceScore, score_url_relevance
from app.discovery.broker_gate import (
    EMPLOYER_HOST_HINTS,
    PORTAL_HOST_SUFFIXES,
    is_blocked_url,
)

# Aggregators / boards / staffing marketplaces that often slip past soft scoring.
UNUSABLE_HOST_SUFFIXES: tuple[str, ...] = (
    # Job boards & aggregators
    "glassdoor.nl",
    "glassdoor.com",
    "jooble.org",
    "werkzoeken.nl",
    "ictergezocht.nl",
    "vacatures.com",
    "vdab.be",
    "techniekwerkt.nl",
    "engineering.jobs",
    "nl.engineering.jobs",
    "zzp-opdrachten.nl",
    "jobbird.com",
    "jobscout24.nl",
    "stepstone.nl",
    "totaljobs.com",
    "carriereverkenner.nl",
    "devopscarriere.nl",
    "talentvoorit.nl",
    "matchmatters.nl",
    "vacature.nl",
    "intermediair.nl",
    # Inhuur / DAS / MSP marketplaces & detacheerders
    "inhuurloket.nl",
    "inhuurbron.nl",
    "impactvandaag.nl",
    "detransparentebroker.nl",
    "1upply.nl",
    "redcarpet.careers",
    "magnitglobal.com",
    "inwork.nl",
    "greenpepper.nl",
    "acknowledge.nl",
    "t2.nl",
    "nordavo.nl",
    "passionned.nl",
    "iduet.nl",
    "esprit-ict.nl",
    "neomax.nl",
    "braincap.nl",
    "innspire.nl",
    # Social / video / non-career (including mobile/short hosts)
    "facebook.com",
    "fb.com",
    "fb.me",
    "instagram.com",
    "youtube.com",
    "youtu.be",
    "youtube-nocookie.com",
    "googlevideo.com",
    "twitter.com",
    "x.com",
    "t.co",
    "tiktok.com",
    "vm.tiktok.com",
    "linkedin.com",
    "lnkd.in",
    "pinterest.com",
    "pin.it",
    "reddit.com",
    "whatsapp.com",
    "wa.me",
    "threads.net",
    "snapchat.com",
    "vimeo.com",
)

UNUSABLE_PATH_RE = re.compile(
    r"/(favorieten|favorites|kaart|map|nieuws|news|blog|login|signin|register|"
    r"consent|cookie|privacy|voorwaarden|terms|cart|winkelwagen|checkout|"
    r"bewaarde-vacatures|sollicitaties)(/|$)",
    re.I,
)

# Titles that scream "search results / category listing", not one vacature.
LIST_TITLE_RE = re.compile(
    r"^\s*\d+\s+(vacatures?|jobs?|opdrachten)\b|"
    r"\b\d+\s+(vacatures?|jobs?)\s+(voor|gevonden|in)\b|"
    r"\b(vacatures?|jobs?)\s+(gevonden|overzicht|per functie)\b|"
    r"\balle\s+vacatures\b|"
    r"\bbekijk\s+opdrachten\b",
    re.I,
)

SINGLE_VACANCY_PATH_RE = re.compile(
    r"/(vacature|vacancy|opdracht|job)s?(/|$)|"
    r"/(vacatures|vacancies|jobs|opdrachten|careers)/[^/?#]+",
    re.I,
)

# Category hubs under /vacatures/<topic> — not a single job.
CATEGORY_SLUGS = frozenset(
    {
        "ict",
        "it",
        "inhuur",
        "detachering",
        "interim",
        "all",
        "alle",
        "zoeken",
        "search",
        "overzicht",
        "favorieten",
        "favorites",
        "kaart",
        "map",
    }
)

# Trusted hosts still need a concrete vacancy URL to count as a usable listing.
OVERVIEW_OK_AS_SEED = False

AGENCY_HOST_RE = re.compile(
    r"(detach|uitzend|staffing|interim[-]?bureau|freelancer|inhuur|"
    r"zzp[-]?opdracht|recruit|headhunt|detacheer)",
    re.I,
)

# Page/title self-identifies as a detacheerder / uitzend agency (not an employer).
DETACHEERDER_SELF_RE = re.compile(
    r"\bwij\s+zijn\s+(een\s+)?(ict[- ]?)?detacheerder\b|"
    r"\bals\s+(ict[- ]?)?detacheerder\b|"
    r"\b(ict[- ]?)?detacheerder\s+(van|voor|in)\b|"
    r"\b(jouw|uw|jullie)\s+(ict[- ]?)?detacheerder\b|"
    r"\bons\s+(ict[- ]?)?(detacherings?bureau|uitzendbureau)\b|"
    r"\bdetacheringbureau\b|"
    r"\buitzendbureau\b|"
    r"\bwij\s+detacheren\b|"
    r"\bprofessionals?\s+(detacheren|uitzenden|bemiddelen)\b|"
    r"\bspecialist\s+in\s+(ict[- ]?)?detachering\b|"
    r"\bdetacherings?partner\b|"
    r"\bdetacherings?organisatie\b|"
    r"\bwerving\s+en\s+selectie\b|"
    r"\bIT[- ]?detachering\b|"
    r"\bICT[- ]?detachering\b|"
    r"\bvacatures\s+ICT[- ]?detachering\b|"
    r"\bkom\s+jij\s+voor\s+ons\s+werken\b.*\bdetach|"
    r"\bdetach.*\bkom\s+jij\s+voor\s+ons\s+werken\b",
    re.I,
)


@dataclass
class CrawlJudgement:
    usable: bool
    reasons: list[str] = field(default_factory=list)


def _hostname(url: str) -> str:
    try:
        host = urlparse(url).hostname or ""
    except Exception:  # noqa: BLE001
        return ""
    return host.lower().removeprefix("www.")


def _host_matches(host: str, suffix: str) -> bool:
    suffix = suffix.lower().removeprefix("www.")
    return host == suffix or host.endswith("." + suffix)


def is_noise_host(url: str) -> str | None:
    """Return reason if host is social/video/board noise; else None."""
    host = _hostname(url)
    if not host:
        return "empty host"
    if is_blocked_url(url).blocked:
        return "broker denylist"
    for suffix in UNUSABLE_HOST_SUFFIXES:
        if _host_matches(host, suffix):
            return f"unusable host: {host}"
    return None


def _is_trusted_employer_or_portal(host: str, url: str) -> bool:
    for suffix in PORTAL_HOST_SUFFIXES:
        if _host_matches(host, suffix):
            return True
    for hint in EMPLOYER_HOST_HINTS:
        if hint.search(host) or hint.search(url):
            return True
    return False


def judge_crawl_candidate(
    url: str,
    *,
    title: str | None = None,
    snippet: str | None = None,
    relevance: RelevanceScore | None = None,
) -> CrawlJudgement:
    """Deeper usability gate for crawl survivors (boards, junk paths, list pages)."""
    reasons: list[str] = []
    host = _hostname(url)
    path = urlparse(url).path or "/"
    title_text = (title or "").strip()
    hay = " ".join(
        part for part in (url.lower(), title_text.lower(), (snippet or "").lower()[:2000]) if part
    )

    noise = is_noise_host(url)
    if noise:
        return CrawlJudgement(False, [noise])

    if UNUSABLE_PATH_RE.search(path):
        return CrawlJudgement(False, [f"unusable path: {path}"])

    if title_text and LIST_TITLE_RE.search(title_text):
        return CrawlJudgement(False, [f"list/search title: {title_text[:80]}"])

    if title_text in {"0", "Kaart", "Map"} or title_text.lower() in {"favorieten", "favorites"}:
        return CrawlJudgement(False, [f"junk title: {title_text}"])

    if title_text.startswith("http://") or title_text.startswith("https://"):
        return CrawlJudgement(False, ["title is raw URL"])

    trusted = _is_trusted_employer_or_portal(host, url)
    if AGENCY_HOST_RE.search(host) and not trusted:
        return CrawlJudgement(False, [f"staffing/agency host: {host}"])

    # Agency self-marketing (detacheerder / uitzend) — never want these as "employer" hits.
    if not trusted and DETACHEERDER_SELF_RE.search(hay):
        return CrawlJudgement(False, ["page self-identifies as detacheerder/agency"])

    # /vacatures/ict style category hubs (even on portals)
    path_parts = [p for p in path.lower().split("/") if p]
    if len(path_parts) >= 2 and path_parts[-1] in CATEGORY_SLUGS:
        return CrawlJudgement(False, [f"category hub path: /{'/'.join(path_parts[-2:])}"])

    rel = relevance or score_url_relevance(
        url, title=title_text or None, snippet=snippet, page_kind="detail"
    )
    if rel.skip_broker:
        return CrawlJudgement(False, rel.reasons[:3] or ["broker signals"])

    looks_single = bool(SINGLE_VACANCY_PATH_RE.search(path))
    strong_detail = bool(
        re.search(r"/(vacature|vacancy|opdracht|job)(/|$)", path, re.I)
    ) or (
        looks_single
        and len(path_parts) >= 2
        and path_parts[-1] not in CATEGORY_SLUGS
        and len(path_parts[-1]) >= 8
    )

    if not trusted:
        if not strong_detail:
            return CrawlJudgement(False, ["not a single-vacancy URL on unknown host"])
        if rel.score < 0.55:
            return CrawlJudgement(
                False,
                [f"weak relevance {rel.score} on non-employer host"],
            )
        staffingish = bool(
            re.search(
                r"inhuur|detach|interim|zzp|inlener|extern",
                hay,
                re.I,
            )
        )
        techish = bool(
            re.search(
                r"\bict\b|devops|cloud|software|engineer|developer|architect|data\b",
                hay,
                re.I,
            )
        )
        if not (staffingish or techish):
            return CrawlJudgement(False, ["no staffing/ICT signal on non-employer host"])
        # Staffing signal on unknown host is a yellow flag when it's agency marketing.
        if staffingish and re.search(r"\bdetach(eer|ering)\b", hay, re.I) and not techish:
            # e.g. pure "detachering vacatures" agency pages without a concrete tech role
            if DETACHEERDER_SELF_RE.search(hay) or re.search(
                r"\b(voor\s+ons\s+werken|ons\s+team\s+van\s+professionals)\b", hay, re.I
            ):
                return CrawlJudgement(False, ["agency marketing page"])
        reasons.append("accepted unknown-host detail with signals")
    else:
        if path.rstrip("/").endswith(("favorieten", "favorites")):
            return CrawlJudgement(False, ["favorites page"])
        if not strong_detail and not OVERVIEW_OK_AS_SEED:
            return CrawlJudgement(False, ["trusted host but not a concrete vacancy URL"])
        reasons.append("trusted employer/portal vacancy")

    return CrawlJudgement(True, reasons)
