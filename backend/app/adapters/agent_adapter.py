from __future__ import annotations

import hashlib
import json
import re
from typing import Any
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

import httpx

from app.adapters.http_util import get_text
from app.config import get_settings
from app.llm import chat_completion, parse_json_content
from app.models import Source
from app.schemas import ListingDraft

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "http_get",
            "description": "Fetch a URL and return truncated HTML/text content.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "extract_links",
            "description": "Extract likely vacancy detail links from previously fetched HTML for a URL.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "The page URL whose cached HTML should be parsed"},
                    "limit": {"type": "integer", "default": 25},
                },
                "required": ["url"],
            },
        },
    },
]

VACANCY_LINK_RE = re.compile(
    r"vacature|vacancy|job[s]?|opdracht|carri[eè]re|career|/jobs/|/careers/|"
    r"werken-bij|vacatures/",
    re.I,
)

OVERVIEW_PATH_RE = re.compile(
    r"/(vacatures|vacancies|jobs|careers|opdrachten|carriere|carri[eè]re)/?$",
    re.I,
)


class AgentAdapter:
    def __init__(self) -> None:
        self._cache: dict[str, str] = {}

    def discover(self, source: Source) -> list[ListingDraft]:
        settings = get_settings()
        config = source.config or {}
        list_url = config.get("list_url") or source.base_url
        max_listings = int(config.get("max_listings") or settings.agent_max_listings)
        max_pages = int(config.get("max_pages") or settings.agent_max_pages)
        focus_keywords = config.get("focus_keywords") or [
            "inhuur",
            "detachering",
            "extern",
            "inlener",
            "interim",
            "zzp",
            "ICT",
        ]
        focus_text = ", ".join(str(k) for k in focus_keywords)

        start_host = urlparse(list_url).netloc.lower()
        system = (
            "You scan Dutch employer career websites for job vacancies. "
            "Prioritize external staffing roles (detachering, inhuur, inlener, extern, interim, zzp) "
            "and ICT/IT roles when relevant. "
            "Use tools to fetch pages and extract vacancy detail links (not overview hubs). "
            f"Stay on the same site host ({start_host}) — do not invent API paths like /api/vacatures. "
            "If a tool returns an error JSON, try extract_links on the start URL or another known vacancy list page. "
            "When done, respond with ONLY JSON: "
            '{"listings":[{"title":"...","url":"...","location":null,"employment_type":null,"description":null}]}'
        )
        user = (
            f"Start URL: {list_url}\n"
            f"Find up to {max_listings} vacancy detail URLs from this career overview. "
            f"You may open at most {max_pages} pages. "
            f"Strongly prefer vacancies matching these focus keywords: {focus_text}."
        )

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]

        for _ in range(max_pages + 4):
            response = chat_completion(
                messages,
                tools=TOOLS,
                temperature=0.1,
                max_tokens=3000,
            )
            message = response.choices[0].message
            tool_calls = message.tool_calls or []
            if tool_calls:
                messages.append(
                    {
                        "role": "assistant",
                        "content": message.content or "",
                        "tool_calls": [
                            {
                                "id": tc.id,
                                "type": "function",
                                "function": {
                                    "name": tc.function.name,
                                    "arguments": tc.function.arguments,
                                },
                            }
                            for tc in tool_calls
                        ],
                    }
                )
                for tc in tool_calls:
                    result = self._run_tool(tc.function.name, tc.function.arguments, list_url)
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": result[:12000],
                        }
                    )
                continue

            content = message.content or ""
            data = parse_json_content(content)
            listings = data.get("listings") if isinstance(data, dict) else None
            if not isinstance(listings, list):
                return self._fallback_from_cache(list_url, max_listings)
            drafts: list[ListingDraft] = []
            for item in listings[:max_listings]:
                if not isinstance(item, dict):
                    continue
                url = str(item.get("url") or "").strip()
                title = str(item.get("title") or "").strip()
                if not url or not title:
                    continue
                if not url.startswith("http"):
                    url = urljoin(list_url, url)
                drafts.append(
                    ListingDraft(
                        external_id=self._external_id(url),
                        title=title[:512],
                        url=url,
                        employment_type=(str(item["employment_type"]) if item.get("employment_type") else None),
                        location=(str(item["location"]) if item.get("location") else None),
                        description=(str(item["description"]) if item.get("description") else None),
                        raw_snippet=(str(item.get("description") or title)[:500]),
                    )
                )
            if not drafts:
                return self._fallback_from_cache(list_url, max_listings)
            enriched: list[ListingDraft] = []
            for draft in drafts[:max_listings]:
                enriched.append(self.fetch_detail(source, draft))
            return enriched

        return self._fallback_from_cache(list_url, max_listings)

    def fetch_detail(self, source: Source, draft: ListingDraft) -> ListingDraft:
        try:
            html = self._fetch(draft.url)
        except Exception:
            return draft
        soup = BeautifulSoup(html, "html.parser")
        text = soup.get_text("\n", strip=True)
        if len(text) < 80:
            return draft
        return draft.model_copy(
            update={
                "description": text[:8000],
                "raw_snippet": text[:500],
            }
        )

    def _run_tool(self, name: str, arguments: str, base_url: str) -> str:
        try:
            args = json.loads(arguments or "{}")
        except json.JSONDecodeError:
            args = {}
        start_host = urlparse(base_url).netloc.lower()
        if name == "http_get":
            url = str(args.get("url") or base_url)
            if not url.startswith("http"):
                url = urljoin(base_url, url)
            host = urlparse(url).netloc.lower()
            if host and start_host and host != start_host and not host.endswith("." + start_host):
                return json.dumps(
                    {
                        "error": "off_host",
                        "message": f"Refusing off-host URL {url}; stay on {start_host}",
                    }
                )
            try:
                html = self._fetch(url)
            except Exception as exc:  # noqa: BLE001
                return json.dumps({"error": "http_error", "url": url, "message": str(exc)[:500]})
            return html[:15000]
        if name == "extract_links":
            url = str(args.get("url") or base_url)
            limit = int(args.get("limit") or 25)
            try:
                html = self._cache.get(url) or self._fetch(url)
            except Exception as exc:  # noqa: BLE001
                return json.dumps({"error": "http_error", "url": url, "message": str(exc)[:500]})
            links = self._extract_vacancy_links(html, url, limit)
            return json.dumps({"links": links}, ensure_ascii=False)
        return json.dumps({"error": f"unknown tool {name}"})

    def _fetch(self, url: str) -> str:
        if url in self._cache:
            return self._cache[url]
        try:
            text = get_text(url)
        except httpx.HTTPError:
            raise
        self._cache[url] = text
        return text

    def _extract_vacancy_links(self, html: str, base_url: str, limit: int) -> list[dict[str, str]]:
        if "<feed" in html[:500].lower() or "<rss" in html[:500].lower() or "<entry" in html.lower():
            feed_links = self._extract_feed_links(html, limit)
            if feed_links:
                return feed_links

        soup = BeautifulSoup(html, "html.parser")
        results: list[dict[str, str]] = []
        seen: set[str] = set()
        for a in soup.find_all("a", href=True):
            href = str(a.get("href") or "")
            text = a.get_text(" ", strip=True)
            full = urljoin(base_url, href)
            parsed = urlparse(full)
            if parsed.scheme not in {"http", "https"}:
                continue
            path = parsed.path.lower()
            haystack = f"{path} {text.lower()}"
            if full in seen:
                continue
            if not VACANCY_LINK_RE.search(haystack):
                continue
            # Skip pure overview roots / filters
            if OVERVIEW_PATH_RE.search(path.rstrip("/") + "/") and path.count("/") <= 2:
                continue
            if path.rstrip("/").endswith("vacatures") and path.count("/") <= 2:
                continue
            seen.add(full)
            results.append({"url": full, "title": text[:200] or full})
            if len(results) >= limit:
                break
        return results

    def _extract_feed_links(self, xml_text: str, limit: int) -> list[dict[str, str]]:
        """Parse Atom/RSS vacancy feeds (e.g. Defensie /feed-vacancy)."""
        # Prefer regex over lxml so Atom feeds work without extra deps.
        results: list[dict[str, str]] = []
        seen: set[str] = set()
        entry_chunks = re.findall(
            r"<entry\b.*?</entry>|<item\b.*?</item>",
            xml_text,
            flags=re.I | re.S,
        )
        for chunk in entry_chunks:
            title_m = re.search(
                r"<title\b[^>]*>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>",
                chunk,
                flags=re.I | re.S,
            )
            title = re.sub(r"<[^>]+>", "", title_m.group(1)).strip() if title_m else ""
            link = ""
            for link_m in re.finditer(r"<link\b([^>]*)>", chunk, flags=re.I):
                attrs = link_m.group(1)
                href_m = re.search(r'href=["\']([^"\']+)["\']', attrs, flags=re.I)
                if not href_m:
                    continue
                rel_m = re.search(r'rel=["\']([^"\']+)["\']', attrs, flags=re.I)
                rel = (rel_m.group(1) if rel_m else "alternate").lower()
                if rel in {"alternate", ""} or not link:
                    link = href_m.group(1)
            if not link:
                id_m = re.search(r"<id\b[^>]*>(.*?)</id>", chunk, flags=re.I | re.S)
                if id_m:
                    maybe = re.sub(r"<[^>]+>", "", id_m.group(1)).strip()
                    if maybe.startswith("http"):
                        link = maybe
            if not link or link in seen:
                continue
            seen.add(link)
            results.append({"url": link, "title": (title or link)[:200]})
            if len(results) >= limit:
                break
        return results

    def _fallback_from_cache(self, list_url: str, limit: int) -> list[ListingDraft]:
        html = self._cache.get(list_url)
        if not html:
            try:
                html = self._fetch(list_url)
            except Exception:
                return []
        links = self._extract_vacancy_links(html, list_url, limit)
        return [
            ListingDraft(
                external_id=self._external_id(link["url"]),
                title=link["title"] or link["url"],
                url=link["url"],
                raw_snippet=link["title"],
            )
            for link in links
        ]

    def _external_id(self, url: str) -> str:
        path = urlparse(url).path.rstrip("/")
        slug = path.split("/")[-1] if path else ""
        return slug or hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
