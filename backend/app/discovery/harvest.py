from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from urllib.parse import parse_qs, unquote, urlparse

from bs4 import BeautifulSoup
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.http_util import get_text
from app.discovery.broker_gate import KindScore, is_blocked_name, is_blocked_url
from app.discovery.coverage import url_covered_by_sources
from app.discovery.resolve import normalize_url, origin_of
from app.models import Source

logger = logging.getLogger(__name__)

# Site-wide ICT on WerkenvoorNederland (CVG.08 = ICT). No werkgever = whole portal.
WVN_SITE_WIDE_ICT = "https://www.werkenvoornederland.nl/vacatures?vakgebied=CVG.08"
WBO_VACATURES = "https://www.werkenbijdeoverheid.nl/vacatures"

ORG_NAME_CLEAN_RE = re.compile(r"\s+")


@dataclass
class HarvestCandidate:
    name: str
    career_url: str
    base_url: str
    kind_score: KindScore
    raw_snippet: str | None
    blocked: bool


def _existing_org_keys(db: Session) -> set[str]:
    """Names and werkgever/org filter values already covered by sources."""
    keys: set[str] = set()
    for source in db.scalars(select(Source)).all():
        keys.add(_norm_key(source.name))
        list_url = ""
        if isinstance(source.config, dict):
            list_url = str(source.config.get("list_url") or "")
        if list_url:
            keys.add(_norm_key(list_url))
            parsed = urlparse(list_url)
            qs = parse_qs(parsed.query)
            for key in ("werkgever", "organisaties", "organisatie"):
                for org in qs.get(key, []):
                    keys.add(_norm_key(unquote(org)))
    return keys


def _norm_key(value: str) -> str:
    return ORG_NAME_CLEAN_RE.sub(" ", (value or "").strip().lower())


def _safe_fetch(url: str) -> str | None:
    try:
        return get_text(url)
    except Exception as exc:  # noqa: BLE001
        logger.info("harvest fetch failed for %s: %s", url, exc)
        return None


def _orgs_from_wbo(html: str) -> list[tuple[str, str]]:
    """Extract employer/org hints from WerkenbijdeOverheid vacatures page."""
    soup = BeautifulSoup(html, "html.parser")
    found: list[tuple[str, str]] = []
    seen: set[str] = set()
    for anchor in soup.find_all("a", href=True):
        href = str(anchor["href"])
        text = ORG_NAME_CLEAN_RE.sub(" ", anchor.get_text(" ", strip=True)).strip()
        if not text or len(text) < 3:
            continue
        if href.startswith("/"):
            abs_url = "https://www.werkenbijdeoverheid.nl" + href
        elif href.startswith("http"):
            abs_url = href
        else:
            continue
        parsed = urlparse(abs_url)
        if "werkenbijdeoverheid.nl" not in (parsed.hostname or ""):
            continue
        path = parsed.path or ""
        qs = parse_qs(parsed.query)
        org_keys = ("organisatie", "organisaties", "organization", "werkgever", "searchterm")
        org_val = None
        for key in org_keys:
            if key in qs and qs[key]:
                org_val = unquote(qs[key][0]).strip()
                break
        if org_val:
            name = org_val
            career = normalize_url(abs_url) or abs_url
        elif "/organisaties/" in path or "/werkgevers/" in path or "/organisatie/" in path:
            name = text
            career = abs_url
        else:
            continue
        key = _norm_key(name)
        if key in seen or len(name) > 120:
            continue
        seen.add(key)
        found.append((name, career))
    return found


def _candidate(
    name: str,
    career_url: str,
    *,
    blocked: bool = False,
    reason: str | None = None,
) -> HarvestCandidate:
    if blocked:
        score = KindScore("broker", 1.0, [reason or "denylist"])
    else:
        score = KindScore(
            kind="portal",
            broker_risk=0.05,
            reasons=["harvested from trusted public portal"],
        )
    return HarvestCandidate(
        name=name[:255],
        career_url=career_url,
        base_url=origin_of(career_url),
        kind_score=score,
        raw_snippet=None,
        blocked=blocked,
    )


def harvest_portal_candidates(db: Session) -> list[HarvestCandidate]:
    existing = _existing_org_keys(db)
    candidates: list[HarvestCandidate] = []
    seen_urls: set[str] = set()

    pairs: list[tuple[str, str]] = []

    # WvN: only the site-wide ICT list. Per-werkgever slices are redundant.
    if not url_covered_by_sources(db, WVN_SITE_WIDE_ICT):
        pairs.append(("WerkenvoorNederland ICT", WVN_SITE_WIDE_ICT))

    wbo_html = _safe_fetch(f"{WBO_VACATURES}?searchterm=ICT")
    if wbo_html:
        pairs.extend(_orgs_from_wbo(wbo_html))

    for name, career_url in pairs:
        career_url = normalize_url(career_url) or career_url
        if not career_url:
            continue
        if _norm_key(name) in existing or _norm_key(career_url) in existing:
            continue
        if url_covered_by_sources(db, career_url):
            continue
        if career_url in seen_urls:
            continue
        seen_urls.add(career_url)

        block_name = is_blocked_name(name)
        block_url = is_blocked_url(career_url)
        if block_name.blocked or block_url.blocked:
            reason = block_name.reason or block_url.reason or "denylist"
            candidates.append(_candidate(name, career_url, blocked=True, reason=reason))
            continue

        candidates.append(_candidate(name, career_url))

    return candidates
