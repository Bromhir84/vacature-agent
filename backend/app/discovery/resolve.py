from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from app.adapters.http_util import get_text
from app.discovery.broker_gate import KindScore, is_blocked_url, score_source_kind

logger = logging.getLogger(__name__)

VACANCY_PATH_HINTS = (
    "/vacatures",
    "/vacancies",
    "/jobs",
    "/careers",
    "/werken-bij",
    "/werkenbij",
    "/carriere",
    "/opdrachten",
)

VACANCY_LINK_RE = re.compile(
    r"vacature|vacancy|job[s]?|opdracht|carri[eè]re|career|/jobs/|/careers/|"
    r"werken-bij|werkenbij|vacatures",
    re.I,
)

OVERVIEW_PATH_RE = re.compile(
    r"/(vacatures|vacancies|jobs|careers|opdrachten|carriere|carri[eè]re|werken-bij)/?",
    re.I,
)


@dataclass
class ResolvedCareer:
    name: str
    career_url: str
    base_url: str
    query: str
    kind_score: KindScore
    raw_snippet: str | None
    blocked: bool
    error: str | None = None


def normalize_url(value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""
    if "://" not in raw:
        raw = "https://" + raw
    parsed = urlparse(raw)
    if not parsed.netloc:
        return ""
    # Drop fragment; keep query (portals use org filters).
    path = parsed.path or "/"
    query = f"?{parsed.query}" if parsed.query else ""
    return f"{parsed.scheme}://{parsed.netloc}{path}{query}"


def origin_of(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"


def _slugify_company(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "", name.lower())
    return slug


def _looks_like_url(value: str) -> bool:
    text = value.strip()
    if "://" in text:
        return True
    if "." in text and " " not in text and not text.endswith("."):
        return True
    return False


def _safe_fetch(url: str) -> str | None:
    try:
        return get_text(url)
    except Exception as exc:  # noqa: BLE001
        logger.info("discovery fetch failed for %s: %s", url, exc)
        return None


def _extract_vacancy_links(base_url: str, html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    found: list[str] = []
    seen: set[str] = set()
    for anchor in soup.find_all("a", href=True):
        href = str(anchor.get("href") or "").strip()
        if not href or href.startswith("#") or href.lower().startswith("mailto:"):
            continue
        abs_url = urljoin(base_url, href)
        parsed = urlparse(abs_url)
        if parsed.scheme not in {"http", "https"}:
            continue
        text = f"{href} {anchor.get_text(' ', strip=True)}"
        if not VACANCY_LINK_RE.search(text):
            continue
        key = abs_url.split("#", 1)[0]
        if key in seen:
            continue
        seen.add(key)
        found.append(key)
    return found


def _pick_best_career_url(candidates: list[str], fallback: str) -> str:
    if not candidates:
        return fallback
    # Prefer overview-style paths over deep vacancy detail URLs.
    overviews = [u for u in candidates if OVERVIEW_PATH_RE.search(urlparse(u).path or "")]
    pool = overviews or candidates
    # Prefer shorter paths (list hubs).
    pool.sort(key=lambda u: (len(urlparse(u).path or ""), len(u)))
    return pool[0]


def _title_from_html(html: str | None, fallback: str) -> str:
    if not html:
        return fallback
    soup = BeautifulSoup(html, "html.parser")
    if soup.title and soup.title.string:
        title = re.sub(r"\s+", " ", soup.title.string).strip()
        title = re.split(r"[|\-–—]", title)[0].strip()
        if title:
            return title[:255]
    return fallback


def resolve_query(query: str, *, use_llm: bool = False) -> ResolvedCareer:
    """Resolve a company name, domain, or URL into a scored career proposal candidate."""
    q = (query or "").strip()
    if not q:
        return ResolvedCareer(
            name="",
            career_url="",
            base_url="",
            query=q,
            kind_score=KindScore("unknown", 0.5, ["empty query"]),
            raw_snippet=None,
            blocked=False,
            error="empty query",
        )

    career_url = ""
    page_html: str | None = None
    display_name = q

    if _looks_like_url(q):
        career_url = normalize_url(q)
        if not career_url:
            return ResolvedCareer(
                name=q,
                career_url="",
                base_url="",
                query=q,
                kind_score=KindScore("unknown", 0.5, ["invalid URL"]),
                raw_snippet=None,
                blocked=False,
                error="invalid URL",
            )
        block = is_blocked_url(career_url)
        if block.blocked:
            return ResolvedCareer(
                name=q,
                career_url=career_url,
                base_url=origin_of(career_url),
                query=q,
                kind_score=KindScore("broker", 1.0, [block.reason or "denylist"]),
                raw_snippet=None,
                blocked=True,
                error=block.reason,
            )

        page_html = _safe_fetch(career_url)
        # If pasted URL is a homepage, try vacancy path hints / extracted links.
        path = urlparse(career_url).path or "/"
        if page_html and (path in {"", "/"} or not VACANCY_LINK_RE.search(career_url)):
            links = _extract_vacancy_links(career_url, page_html)
            hinted: list[str] = []
            for suffix in VACANCY_PATH_HINTS:
                candidate = origin_of(career_url).rstrip("/") + suffix
                hinted.append(candidate)
            for candidate in hinted:
                html = _safe_fetch(candidate)
                if html and len(html) > 500:
                    career_url = candidate
                    page_html = html
                    break
            else:
                if links:
                    career_url = _pick_best_career_url(links, career_url)
                    page_html = _safe_fetch(career_url) or page_html
        display_name = _title_from_html(page_html, origin_of(career_url).replace("https://", "").replace("http://", ""))
    else:
        # Company name → try common NL career hosts + homepage patterns.
        slug = _slugify_company(q)
        candidates = []
        if slug:
            candidates.extend(
                [
                    f"https://werkenbij{slug}.nl/vacatures",
                    f"https://werkenbij{slug}.nl",
                    f"https://www.werkenbij{slug}.nl/vacatures",
                    f"https://werkenbij.{slug}.nl/vacatures",
                    f"https://www.{slug}.nl/vacatures",
                    f"https://www.{slug}.nl/werken-bij",
                    f"https://careers.{slug}.nl",
                    f"https://www.{slug}.nl",
                ]
            )
        for candidate in candidates:
            html = _safe_fetch(candidate)
            if not html or len(html) < 400:
                continue
            block = is_blocked_url(candidate)
            if block.blocked:
                continue
            links = _extract_vacancy_links(candidate, html)
            career_url = _pick_best_career_url(links, candidate) if links else candidate
            page_html = _safe_fetch(career_url) if career_url != candidate else html
            if career_url != candidate and not page_html:
                page_html = html
                career_url = candidate
            display_name = _title_from_html(page_html, q)
            break
        if not career_url:
            return ResolvedCareer(
                name=q,
                career_url="",
                base_url="",
                query=q,
                kind_score=KindScore("unknown", 0.5, ["could not resolve career URL"]),
                raw_snippet=None,
                blocked=False,
                error="could not resolve career URL",
            )

    block = is_blocked_url(career_url)
    snippet = None
    if page_html:
        text = BeautifulSoup(page_html, "html.parser").get_text(" ", strip=True)
        snippet = re.sub(r"\s+", " ", text)[:1500]

    if block.blocked:
        score = KindScore("broker", 1.0, [block.reason or "denylist"])
    else:
        score = score_source_kind(
            display_name or q,
            career_url,
            snippet,
            use_llm=use_llm,
        )

    return ResolvedCareer(
        name=(display_name or q)[:255],
        career_url=career_url,
        base_url=origin_of(career_url),
        query=q,
        kind_score=score,
        raw_snippet=snippet,
        blocked=block.blocked,
        error=block.reason if block.blocked else None,
    )
