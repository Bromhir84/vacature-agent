from __future__ import annotations

import logging
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

from app.adapters.http_util import get_text
from app.config import get_settings

logger = logging.getLogger(__name__)


class RobotsCache:
    def __init__(self) -> None:
        self._parsers: dict[str, RobotFileParser | None] = {}

    def allowed(self, url: str) -> bool:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return False
        origin = f"{parsed.scheme}://{parsed.netloc}"
        if origin not in self._parsers:
            self._parsers[origin] = self._load(origin)
        parser = self._parsers[origin]
        if parser is None:
            # Fail open if robots.txt missing/unreadable (common for career sites).
            return True
        ua = get_settings().http_user_agent
        try:
            return bool(parser.can_fetch(ua, url))
        except Exception:  # noqa: BLE001
            return True

    def _load(self, origin: str) -> RobotFileParser | None:
        robots_url = origin.rstrip("/") + "/robots.txt"
        try:
            text = get_text(robots_url)
        except Exception as exc:  # noqa: BLE001
            logger.debug("robots.txt unavailable for %s: %s", origin, exc)
            return None
        parser = RobotFileParser()
        parser.set_url(robots_url)
        try:
            parser.parse(text.splitlines())
        except Exception as exc:  # noqa: BLE001
            logger.debug("robots.txt parse failed for %s: %s", origin, exc)
            return None
        return parser
