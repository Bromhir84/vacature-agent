from __future__ import annotations

from typing import Protocol

from app.models import Source
from app.schemas import ListingDraft


class SiteAdapter(Protocol):
    def discover(self, source: Source) -> list[ListingDraft]: ...

    def fetch_detail(self, source: Source, draft: ListingDraft) -> ListingDraft: ...


def get_adapter(adapter_key: str) -> SiteAdapter:
    from app.adapters.agent_adapter import AgentAdapter
    from app.adapters.html_adapter import HtmlAdapter
    from app.adapters.json_adapter import JsonAdapter

    key = adapter_key.lower().strip()
    if key == "json":
        return JsonAdapter()
    if key == "html":
        return HtmlAdapter()
    if key == "agent":
        return AgentAdapter()
    if key == "crawl":
        raise ValueError(
            "adapter_key=crawl is the Open Web system source; run POST /api/crawl/run instead"
        )
    raise ValueError(f"Unknown adapter_key: {adapter_key}")
