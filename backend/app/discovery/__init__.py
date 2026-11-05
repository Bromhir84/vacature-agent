"""Career-page discovery: broker gate, URL resolve, portal harvest, proposals."""

from app.discovery.broker_gate import (
    BlockResult,
    KindScore,
    assert_source_allowed,
    is_blocked_name,
    is_blocked_url,
    score_source_kind,
)

__all__ = [
    "BlockResult",
    "KindScore",
    "assert_source_allowed",
    "is_blocked_name",
    "is_blocked_url",
    "score_source_kind",
]
