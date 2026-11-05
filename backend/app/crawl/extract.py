from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qs, unquote, urljoin, urlparse

from bs4 import BeautifulSoup

from app.discovery.resolve import normalize_url

VACANCY_LINK_RE = re.compile(
    r"vacature|vacancy|job[s]?|opdracht|carri[eè]re|career|/jobs/|/careers/|"
    r"werken-bij|werkenbij|vacatures",
    re.I,
)

OVERVIEW_PATH_RE = re.compile(
    r"/(vacatures|vacancies|jobs|careers|opdrachten|carriere|carri[eè]re|werken-bij)/?$",
    re.I,
)

DETAIL_PATH_RE = re.compile(
    r"/(vacatures?|vacancies|jobs?|opdrachten?|careers?)/[^/?#]+",
    re.I,
)


@dataclass
class ExtractedLink:
    url: str
    title: str
    kind: str  # detail | overview | other


def classify_link(url: str, title: str = "") -> str:
    parsed = urlparse(url)
    path = parsed.path or "/"
    hay = f"{path} {title}".lower()
    if not VACANCY_LINK_RE.search(hay) and not DETAIL_PATH_RE.search(path):
        return "other"
    # Bare overview roots
    if OVERVIEW_PATH_RE.search(path.rstrip("/") + "/") and path.count("/") <= 2:
        return "overview"
    if path.rstrip("/").endswith(("vacatures", "vacancies", "jobs", "careers", "werken-bij")) and path.count("/") <= 2:
        return "overview"
    if DETAIL_PATH_RE.search(path):
        return "detail"
    # Query-only list pages (portals)
    qs = parse_qs(parsed.query)
    if any(k in qs for k in ("vakgebied", "searchterm", "keywords", "werkgever", "organisatie")):
        if path.count("/") <= 2:
            return "overview"
    if VACANCY_LINK_RE.search(hay):
        # Deeper vacancy-ish paths → treat as detail candidates
        if path.count("/") >= 3 or re.search(r"vacature[-_/]|/vacatures?/[^/]+", path, re.I):
            return "detail"
        return "overview"
    return "other"


def extract_links(html: str, base_url: str, *, limit: int = 80) -> list[ExtractedLink]:
    soup = BeautifulSoup(html, "html.parser")
    results: list[ExtractedLink] = []
    seen: set[str] = set()
    for anchor in soup.find_all("a", href=True):
        href = str(anchor.get("href") or "").strip()
        if not href or href.startswith(("#", "mailto:", "javascript:")):
            continue
        full = normalize_url(urljoin(base_url, href))
        if not full or full in seen:
            continue
        parsed = urlparse(full)
        if parsed.scheme not in {"http", "https"}:
            continue
        title = anchor.get_text(" ", strip=True)[:200]
        kind = classify_link(full, title)
        if kind == "other":
            continue
        seen.add(full)
        results.append(ExtractedLink(url=full, title=title or full, kind=kind))
        if len(results) >= limit:
            break
    return results


def extract_ddg_result_urls(html: str, *, limit: int = 25) -> list[tuple[str, str]]:
    """Parse DuckDuckGo HTML search result links → (url, title)."""
    soup = BeautifulSoup(html, "html.parser")
    results: list[tuple[str, str]] = []
    seen: set[str] = set()
    for result in soup.select("a.result__a, a.result__url"):
        href = str(result.get("href") or "").strip()
        title = result.get_text(" ", strip=True)[:200]
        # DDG wraps redirects as //duckduckgo.com/l/?uddg=<encoded>
        if "uddg=" in href:
            qs = parse_qs(urlparse(href).query)
            encoded = (qs.get("uddg") or [None])[0]
            if encoded:
                href = unquote(encoded)
        if href.startswith("//"):
            href = "https:" + href
        full = normalize_url(href)
        if not full or full in seen:
            continue
        host = (urlparse(full).hostname or "").lower()
        if "duckduckgo.com" in host:
            continue
        seen.add(full)
        results.append((full, title or full))
        if len(results) >= limit:
            break
    return results


def registrable_hint(url: str) -> str:
    """Cheap host key for same-site BFS (not a full public-suffix parse)."""
    host = (urlparse(url).hostname or "").lower().removeprefix("www.")
    parts = host.split(".")
    if len(parts) >= 2:
        return ".".join(parts[-2:])
    return host
