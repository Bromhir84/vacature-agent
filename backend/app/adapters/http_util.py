from __future__ import annotations

import time
from typing import Any
from urllib.parse import urljoin

import httpx

from app.config import get_settings

_last_request_at = 0.0


def rate_limit() -> None:
    global _last_request_at
    settings = get_settings()
    elapsed = time.monotonic() - _last_request_at
    delay = settings.request_delay_seconds
    if elapsed < delay:
        time.sleep(delay - elapsed)
    _last_request_at = time.monotonic()


def http_client() -> httpx.Client:
    settings = get_settings()
    return httpx.Client(
        timeout=60.0,
        headers={"User-Agent": settings.http_user_agent},
        follow_redirects=True,
    )


def get_json(url: str, params: dict[str, Any] | None = None) -> Any:
    rate_limit()
    with http_client() as client:
        response = client.get(url, params=params)
        response.raise_for_status()
        return response.json()


def get_text(url: str, params: dict[str, Any] | None = None) -> str:
    rate_limit()
    with http_client() as client:
        response = client.get(url, params=params)
        response.raise_for_status()
        return response.text


def absolute_url(base: str, href: str) -> str:
    return urljoin(base, href)
