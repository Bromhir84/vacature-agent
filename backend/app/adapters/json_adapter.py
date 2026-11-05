from __future__ import annotations

from typing import Any

from jsonpath_ng import parse as jsonpath_parse

from app.adapters.http_util import absolute_url, get_json
from app.models import Source
from app.schemas import ListingDraft


def _dig(data: Any, path: str | None) -> Any:
    if not path:
        return None
    if path == "$":
        return data
    if path.startswith("$") or "[" in path or "." in path:
        matches = jsonpath_parse(path if path.startswith("$") else f"$.{path}").find(data)
        if not matches:
            return None
        if len(matches) == 1:
            return matches[0].value
        return [m.value for m in matches]
    # simple dotted path
    cur: Any = data
    for part in path.split("."):
        if cur is None:
            return None
        if isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
    return cur


def _format_template(template: str, item: dict[str, Any]) -> str:
    class _Safe(dict):
        def __missing__(self, key: str) -> str:
            return ""

    return template.format_map(_Safe(**{k: ("" if v is None else v) for k, v in item.items()}))


def _extract_items(payload: Any, items_path: str | None) -> list[Any]:
    """Resolve list items; `$` / empty means the payload itself when it is a list."""
    if isinstance(payload, list) and (not items_path or items_path == "$"):
        return payload
    if items_path == "$":
        return [payload] if payload is not None else []
    if not items_path:
        return []
    items = _dig(payload, items_path) or []
    if not isinstance(items, list):
        return [items]
    return items


def _item_matches_filter(item: dict[str, Any], item_filter: dict[str, Any]) -> bool:
    for key, expected in item_filter.items():
        if item.get(key) != expected:
            return False
    return True


def _employment_from_item(
    item: dict[str, Any],
    item_map: dict[str, Any],
    employment_map: dict[str, Any] | None = None,
) -> str | None:
    expr = item_map.get("employment_type")
    if not expr:
        # Heuristic for Application-style option_values
        option_values = item.get("option_values") or []
        for ov in option_values:
            option = ov.get("option") or {}
            slug = (option.get("slug") or "").lower()
            title = (option.get("title") or "").lower()
            if "dienstverband" in slug or "dienstverband" in title or "employment" in slug:
                return ov.get("value")
        return None
    value = _dig(item, expr)
    if isinstance(value, list):
        return ", ".join(str(v) for v in value if v)
    if employment_map and value is not None:
        # Map booleans and stringified bools: true → Detachering, etc.
        candidates = [value, str(value).lower(), str(value)]
        for key in candidates:
            if isinstance(key, bool):
                mapped = employment_map.get(str(key).lower())
            else:
                mapped = employment_map.get(key)  # type: ignore[arg-type]
            if mapped is not None:
                return str(mapped)
    return str(value) if value is not None else None


class JsonAdapter:
    def discover(self, source: Source) -> list[ListingDraft]:
        config = source.config or {}
        list_url = config.get("list_url") or source.base_url
        query = dict(config.get("query") or {})
        pagination = config.get("pagination") or {}
        item_map = config.get("item_map") or {}
        employment_map = config.get("employment_map") or {}
        item_filter = config.get("filter") or {}
        # Empty / "$" → root array; default stays "vacancies" for ANWB-style APIs.
        if "items_path" in pagination:
            items_path = pagination.get("items_path")
        else:
            items_path = "vacancies"
        page_param = pagination.get("page_param") or "page"
        if "total_pages_path" in pagination:
            total_pages_path = pagination.get("total_pages_path")
        else:
            total_pages_path = "meta.totalPageCount"
        max_pages = int(pagination.get("max_pages") or 50)
        single_shot = bool(pagination.get("single_shot")) or items_path in {None, "", "$"}

        drafts: list[ListingDraft] = []
        page = 1
        total_pages = 1

        while page <= total_pages and page <= max_pages:
            params = dict(query)
            # Many career APIs 404 when page=1 is passed; only send from page 2+.
            if not single_shot and page > 1:
                params[page_param] = page
            payload = get_json(list_url, params=params or None)
            if single_shot and isinstance(payload, list):
                items = payload
            else:
                items = _extract_items(payload, items_path)

            for item in items:
                if not isinstance(item, dict):
                    continue
                if item_filter and not _item_matches_filter(item, item_filter):
                    continue
                draft = self._map_item(
                    item,
                    item_map,
                    source.base_url,
                    default_employment_type=config.get("default_employment_type"),
                    employment_map=employment_map,
                )
                if draft:
                    drafts.append(draft)

            if single_shot:
                break

            tp = _dig(payload, total_pages_path) if total_pages_path else None
            try:
                total_pages = int(tp) if tp is not None else 1
            except (TypeError, ValueError):
                total_pages = 1
            if not items:
                break
            page += 1

        return drafts

    def fetch_detail(self, source: Source, draft: ListingDraft) -> ListingDraft:
        config = source.config or {}
        detail_template = config.get("detail_url_template")
        if not detail_template:
            return draft
        url = detail_template.format(id=draft.external_id, url=draft.url)
        payload = get_json(url)
        item_map = config.get("detail_map") or config.get("item_map") or {}
        detailed = self._map_item(
            payload if isinstance(payload, dict) else {},
            item_map,
            source.base_url,
            default_employment_type=config.get("default_employment_type"),
            employment_map=config.get("employment_map") or {},
        )
        if not detailed:
            return draft
        return draft.model_copy(
            update={
                "description": detailed.description or draft.description,
                "employment_type": detailed.employment_type or draft.employment_type,
                "location": detailed.location or draft.location,
                "raw_snippet": detailed.raw_snippet or draft.raw_snippet,
            }
        )

    def _map_item(
        self,
        item: dict[str, Any],
        item_map: dict[str, Any],
        base_url: str,
        default_employment_type: str | None = None,
        employment_map: dict[str, Any] | None = None,
    ) -> ListingDraft | None:
        external_id = _dig(item, item_map.get("external_id") or "id")
        title = _dig(item, item_map.get("title") or "title")
        if external_id is None or not title:
            return None

        url_template = item_map.get("url_template")
        url_field = item_map.get("url")
        if url_template:
            url = _format_template(url_template, item)
        elif url_field:
            url = str(_dig(item, url_field) or "")
        else:
            url = str(item.get("url") or "")
        if url.startswith("//"):
            url = "https:" + url
        url = absolute_url(base_url, url)

        description_template = item_map.get("description_template")
        if description_template:
            text_desc = _format_template(description_template, item).strip() or None
        else:
            description = _dig(item, item_map.get("description") or "intro")
            if isinstance(description, str):
                text_desc = description
            elif description is not None:
                text_desc = str(description)
            else:
                text_desc = None

        location = _dig(item, item_map.get("location") or "city")
        employment_type = _employment_from_item(item, item_map, employment_map)
        if not employment_type:
            employment_type = default_employment_type or item_map.get("default_employment_type")

        return ListingDraft(
            external_id=str(external_id),
            title=str(title).strip(),
            url=url,
            employment_type=str(employment_type).strip() if employment_type else None,
            location=str(location).strip() if location else None,
            description=text_desc,
            raw_snippet=(text_desc or "")[:500] or None,
        )
