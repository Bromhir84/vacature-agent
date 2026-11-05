from __future__ import annotations

import hashlib
import logging
import re
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup, Tag

from app.adapters.http_util import absolute_url, get_text
from app.models import Source
from app.schemas import ListingDraft

logger = logging.getLogger(__name__)

HIPPO_REF_RE = re.compile(
    r"[?&]_hn:type=component-rendering[^\"'\s]*[?&]_hn:ref=([a-z0-9_]+)"
    r"|[?&]_hn:ref=([a-z0-9_]+)[^\"'\s]*[?&]_hn:type=component-rendering",
    re.I,
)


def _select_one(root: Tag, selector: str | None) -> Tag | None:
    if not selector:
        return None
    return root.select_one(selector)


def _select_many(root: Tag, selector: str | None) -> list[Tag]:
    if not selector:
        return []
    return list(root.select(selector))


def _field_value(root: Tag, field_cfg: dict[str, Any] | str | None) -> str | list[str] | None:
    if field_cfg is None:
        return None
    if isinstance(field_cfg, str):
        field_cfg = {"selector": field_cfg, "attr": "text"}

    selector = field_cfg.get("selector")
    attr = field_cfg.get("attr", "text")
    many = bool(field_cfg.get("many"))

    if many:
        nodes = _select_many(root, selector) if selector else [root]
        values: list[str] = []
        for node in nodes:
            if attr == "text":
                values.append(node.get_text(" ", strip=True))
            else:
                values.append(str(node.get(attr) or "").strip())
        return [v for v in values if v]

    node: Tag | None
    if selector:
        node = _select_one(root, selector)
    else:
        node = root
    if node is None:
        return None
    if attr == "text":
        return node.get_text(" ", strip=True) or None
    return str(node.get(attr) or "").strip() or None


def _external_id_from_url(url: str) -> str:
    path = urlparse(url).path.rstrip("/")
    slug = path.split("/")[-1] if path else url
    if slug:
        return slug
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]


def _merge_query(url: str, extra: dict[str, Any]) -> str:
    parsed = urlparse(url)
    merged = dict(parse_qsl(parsed.query, keep_blank_values=True))
    for key, value in extra.items():
        if value is None:
            continue
        merged[str(key)] = str(value)
    return urlunparse(parsed._replace(query=urlencode(merged)))


def _hippo_fragment_url(shell_html: str, list_url: str, query: dict[str, Any]) -> str | None:
    """Build a Hippo CMS component-rendering URL that contains the vacancy list HTML."""
    match = HIPPO_REF_RE.search(shell_html)
    if not match:
        # Fallback: looser search for any _hn:ref= near component-rendering mentions.
        refs = re.findall(r"_hn:ref=([a-z0-9_]+)", shell_html, flags=re.I)
        if not refs or "component-rendering" not in shell_html:
            return None
        ref = refs[0]
    else:
        ref = match.group(1) or match.group(2)
    if not ref:
        return None
    parsed = urlparse(list_url)
    base = f"{parsed.scheme}://{parsed.netloc}{parsed.path or '/vacatures'}"
    params = {
        "_hn:type": "component-rendering",
        "_hn:ref": ref,
        **{str(k): str(v) for k, v in (query or {}).items()},
    }
    # Keep non-_hn query already on list_url (e.g. vakgebied).
    existing = dict(parse_qsl(parsed.query, keep_blank_values=True))
    for key, value in existing.items():
        params.setdefault(key, value)
    return f"{base}?{urlencode(params)}"


class HtmlAdapter:
    def discover(self, source: Source) -> list[ListingDraft]:
        config = source.config or {}
        list_url = config.get("list_url") or source.base_url
        query = dict(config.get("query") or {})
        item_selector = config.get("list_item_selector") or "a.vacancy-item"
        fields = config.get("fields") or {}
        pagination = config.get("pagination") or {}
        max_pages = int(pagination.get("max_pages") or 10)
        next_selector = pagination.get("next_selector")
        page_param = pagination.get("page_param")

        by_url: dict[str, ListingDraft] = {}
        url = list_url
        params: dict[str, Any] | None = dict(query) if query else None
        page = 1

        # WerkenvoorNederland shell pages are empty; vacancy cards live in a Hippo fragment.
        if config.get("hippo_component"):
            shell = get_text(list_url, params=params)
            fragment = _hippo_fragment_url(shell, list_url, query)
            if fragment:
                logger.info("Using Hippo fragment list URL for %s", source.name)
                url = fragment
                params = None
            else:
                logger.warning(
                    "hippo_component set for %s but no _hn:ref found; scraping shell page",
                    source.name,
                )

        while url and page <= max_pages:
            if page_param:
                extra: dict[str, Any] = dict(params or {})
                extra[str(page_param)] = page
                page_url = _merge_query(url, extra)
                page_params = None
            else:
                page_url = url
                page_params = params

            html = get_text(page_url, params=page_params)
            soup = BeautifulSoup(html, "html.parser")
            items = soup.select(item_selector)
            new_on_page = 0
            for item in items:
                draft = self._map_card(item, fields, list_url or source.base_url, config)
                if not draft:
                    continue
                # Skip a11y/placeholder titles (common on Amsterdam career pages).
                if draft.title.lower().startswith("label voor"):
                    continue
                if draft.title.lower() in {"bekijk vacature", "bekijk bewaarde vacatures"}:
                    continue
                # Skip bare overview links mistaken for cards.
                path = urlparse(draft.url).path.rstrip("/").lower()
                if path.endswith("/vacatures") or path.endswith("/vacature") or path.endswith("/bewaard"):
                    continue
                existing = by_url.get(draft.url)
                if existing is None:
                    by_url[draft.url] = draft
                    new_on_page += 1
                elif len(draft.title) > len(existing.title):
                    by_url[draft.url] = draft

            if page_param:
                if new_on_page == 0:
                    break
                page += 1
                params = None
                continue

            params = None  # only first request uses query params for next-link mode
            next_url = None
            if next_selector:
                next_el = soup.select_one(next_selector)
                if next_el and next_el.get("href"):
                    next_url = absolute_url(url, str(next_el.get("href")))
            if not next_url or next_url == url:
                break
            url = next_url
            page += 1

        drafts = list(by_url.values())
        detail_cfg = config.get("detail") or {}
        if detail_cfg.get("enabled"):
            enriched: list[ListingDraft] = []
            for draft in drafts:
                enriched.append(self.fetch_detail(source, draft))
            return enriched
        return drafts

    def fetch_detail(self, source: Source, draft: ListingDraft) -> ListingDraft:
        config = source.config or {}
        detail_cfg = config.get("detail") or {}
        if not detail_cfg.get("enabled", True):
            return draft
        try:
            html = get_text(draft.url)
        except Exception:
            return draft
        soup = BeautifulSoup(html, "html.parser")
        text = self._detail_text(soup, detail_cfg)
        if text and len(text) > 50:
            # Keep a bounded description for storage/LLM
            clipped = text[:8000]
            return draft.model_copy(
                update={
                    "description": clipped,
                    "raw_snippet": clipped[:500],
                }
            )
        return draft

    def _detail_text(self, soup: BeautifulSoup, detail_cfg: dict[str, Any]) -> str | None:
        # NS-style vacancy pages: role content lives in accordion sections, not the shell.
        accordion_parts: list[str] = []
        for acc in soup.select(".vacancy-accordion"):
            heading = ""
            title_el = acc.select_one(".accordion-title, button, h2, h3")
            if title_el:
                heading = title_el.get_text(" ", strip=True)
            body_el = acc.select_one(".accordion-content") or acc
            body = body_el.get_text("\n", strip=True)
            if not body or len(body) < 40:
                continue
            # Prefer "Dit ga je doen" / role body over generic employer fluff later.
            prefix = f"{heading}\n" if heading and heading.lower() not in body.lower()[:80] else ""
            accordion_parts.append(f"{prefix}{body}".strip())
        if accordion_parts:
            # De-dupe identical accordion copies that appear twice in the DOM.
            seen: set[str] = set()
            unique: list[str] = []
            for part in accordion_parts:
                key = re.sub(r"\s+", " ", part).strip().lower()
                if key in seen:
                    continue
                seen.add(key)
                unique.append(part)
            return "\n\n".join(unique)

        desc_selector = detail_cfg.get("description_selector") or "main"
        node = soup.select_one(desc_selector) or soup.body
        return node.get_text("\n", strip=True) if node else None

    def _map_card(
        self,
        item: Tag,
        fields: dict[str, Any],
        base_url: str,
        config: dict[str, Any],
    ) -> ListingDraft | None:
        href_cfg = fields.get("url") or {"attr": "href"}
        href = _field_value(item, href_cfg if isinstance(href_cfg, dict) else {"attr": "href"})
        if isinstance(href, list):
            href = href[0] if href else None
        if not href:
            href = item.get("href")
        if not href:
            return None
        url = absolute_url(base_url, str(href))

        title = _field_value(item, fields.get("title") or {"attr": "text"})
        if isinstance(title, list):
            title = " ".join(title)
        if not title:
            title = item.get_text(" ", strip=True)
        title = re.sub(r"\s+", " ", str(title)).strip()
        # Strip leading Inhuur tag duplication from NS cards
        title = re.sub(r"^Inhuur\s+", "", title, flags=re.IGNORECASE).strip()
        if not title:
            return None

        location = _field_value(item, fields.get("location"))
        if isinstance(location, list):
            location = location[0] if location else None

        description = _field_value(item, fields.get("description"))
        if isinstance(description, list):
            description = " ".join(description)

        tags_val = _field_value(item, fields.get("tags"))
        tags: list[str] = []
        if isinstance(tags_val, list):
            tags = [str(t).strip() for t in tags_val if str(t).strip()]
        elif isinstance(tags_val, str) and tags_val.strip():
            tags = [tags_val.strip()]

        # NS: Inhuur appears as a tag/label near the card text
        card_text = item.get_text(" ", strip=True)
        if re.search(r"\bInhuur\b", card_text, re.IGNORECASE) and "Inhuur" not in tags:
            tags.append("Inhuur")

        employment_type = None
        if config.get("employment_from_tags") and tags:
            employment_type = tags[0]
        elif tags:
            for t in tags:
                if t.lower() in {"inhuur", "detachering", "interim", "zzp"}:
                    employment_type = t
                    break

        external_id = _external_id_from_url(url)
        return ListingDraft(
            external_id=external_id,
            title=title[:512],
            url=url,
            employment_type=employment_type,
            location=str(location).strip() if location else None,
            description=str(description).strip() if description else None,
            raw_snippet=(str(description).strip()[:500] if description else card_text[:500]),
            tags=tags,
        )
