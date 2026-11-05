from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import parse_qs, unquote, urlparse

from sqlalchemy.orm import Session

from app.discovery.broker_gate import PORTAL_HOST_SUFFIXES
from app.discovery.resolve import normalize_url
from app.models import Source


@dataclass(frozen=True)
class CoverageHit:
    source_id: int
    source_name: str
    reason: str


def _host(url: str) -> str:
    try:
        host = urlparse(url).hostname or ""
    except Exception:  # noqa: BLE001
        return ""
    return host.lower().removeprefix("www.")


def _origin(url: str) -> str:
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return ""
    host = (parsed.hostname or "").lower().removeprefix("www.")
    return f"{parsed.scheme.lower()}://{host}"


def is_portal_host(host_or_url: str) -> bool:
    host = _host(host_or_url) if "://" in host_or_url or "/" in host_or_url else host_or_url.lower().removeprefix("www.")
    for suffix in PORTAL_HOST_SUFFIXES:
        clean = suffix.lower().removeprefix("www.")
        if host == clean or host.endswith("." + clean):
            return True
    return False


def _norm_path(path: str) -> str:
    path = (path or "/").rstrip("/")
    return path if path else "/"


def _org_filters(url: str) -> set[str]:
    """Employer/org filter values. WvN uses werkgever= codes; organisaties= is invalid there."""
    qs = parse_qs(urlparse(url).query)
    values: set[str] = set()
    for key in ("werkgever", "organisaties", "organisatie", "organization"):
        for raw in qs.get(key, []):
            val = unquote(raw).strip().lower()
            if val:
                values.add(val)
    return values


def _is_site_wide_portal_list(url: str) -> bool:
    """True when a portal list URL has no employer/werkgever filter (searches the whole site)."""
    if not is_portal_host(url):
        return False
    path = _norm_path(urlparse(url).path)
    if path not in {"/vacatures", "/vacancies", "/jobs"}:
        return False
    return not _org_filters(url)


def _source_roots(source: Source) -> list[str]:
    roots: list[str] = []
    if source.base_url:
        roots.append(normalize_url(source.base_url) or source.base_url)
    if isinstance(source.config, dict) and source.config.get("list_url"):
        list_url = str(source.config["list_url"])
        roots.append(normalize_url(list_url) or list_url)
    # Dedupe while preserving order
    seen: set[str] = set()
    out: list[str] = []
    for root in roots:
        key = root.rstrip("/")
        if key in seen:
            continue
        seen.add(key)
        out.append(root)
    return out


def is_subpage_of(candidate: str, root: str) -> bool:
    """True if candidate is the same page or a deeper path under root (same host)."""
    cand = normalize_url(candidate) or candidate
    base = normalize_url(root) or root
    if not cand or not base:
        return False

    c = urlparse(cand)
    r = urlparse(base)
    c_host = (c.hostname or "").lower().removeprefix("www.")
    r_host = (r.hostname or "").lower().removeprefix("www.")
    if not c_host or c_host != r_host:
        return False

    c_path = _norm_path(c.path)
    r_path = _norm_path(r.path)

    if c_path == r_path:
        return True
    # A bare site root ("/") is not a path prefix for subpage detection —
    # employer whole-site coverage uses same-origin instead.
    if r_path == "/":
        return False
    return c_path.startswith(r_path + "/")


def source_covers_url(source: Source, url: str) -> CoverageHit | None:
    """Return a hit if this source already covers the candidate career URL."""
    cand = normalize_url(url) or url
    if not cand:
        return None

    cand_host = _host(cand)
    portal = is_portal_host(cand_host)
    cand_orgs = _org_filters(cand)

    for root in _source_roots(source):
        root_host = _host(root)
        if not root_host:
            continue

        # Exact match (ignore trailing slash differences via normalize).
        if (normalize_url(root) or root).rstrip("/") == cand.rstrip("/"):
            return CoverageHit(source.id, source.name, f"exact match of {root}")

        if portal:
            # Site-wide portal list (no werkgever) covers the entire portal host.
            if _is_site_wide_portal_list(root) and _host(root) == cand_host:
                return CoverageHit(
                    source.id,
                    source.name,
                    f"site-wide portal list covers host ({root})",
                )
            root_orgs = _org_filters(root)
            if root_orgs and cand_orgs and root_orgs & cand_orgs:
                return CoverageHit(
                    source.id,
                    source.name,
                    f"same portal werkgever/org filter as {root}",
                )
            # Deeper vacancy path under the same list path, only when org filters compatible.
            if is_subpage_of(cand, root):
                if not root_orgs or not cand_orgs or root_orgs & cand_orgs:
                    if not root_orgs and cand_orgs:
                        continue
                    if urlparse(cand).path.rstrip("/") == urlparse(root).path.rstrip("/"):
                        if root_orgs != cand_orgs:
                            continue
                    return CoverageHit(source.id, source.name, f"subpage of portal list {root}")
            continue

        # Dedicated employer career host: whole origin is already covered.
        if _origin(cand) and _origin(cand) == _origin(root):
            return CoverageHit(source.id, source.name, f"same career site as {root}")

        if is_subpage_of(cand, root):
            return CoverageHit(source.id, source.name, f"subpage of {root}")

    return None


def url_covered_by_sources(db: Session, url: str) -> CoverageHit | None:
    from sqlalchemy import select

    for source in db.scalars(select(Source)).all():
        hit = source_covers_url(source, url)
        if hit:
            return hit
    return None


def _primary_career_url(source: Source) -> str:
    """Prefer list_url; fall back to base_url. Used for duplicate audits."""
    if isinstance(source.config, dict) and source.config.get("list_url"):
        return normalize_url(str(source.config["list_url"])) or str(source.config["list_url"])
    return normalize_url(source.base_url) or source.base_url


def find_duplicate_sources(db: Session) -> list[dict]:
    """Find source pairs where career list URLs truly overlap (not shared portal hosts)."""
    from sqlalchemy import select

    sources = list(db.scalars(select(Source).order_by(Source.id)).all())
    doubles: list[dict] = []
    seen_pairs: set[tuple[int, int]] = set()

    for i, left in enumerate(sources):
        left_url = _primary_career_url(left)
        for right in sources[i + 1 :]:
            pair = (left.id, right.id)
            if pair in seen_pairs:
                continue

            right_url = _primary_career_url(right)
            reasons: list[str] = []

            # Compare career list pages only — shared portal base_url is intentional.
            hit = source_covers_url(left, right_url)
            if hit:
                reasons.append(f"{left.name} covers {right.name}: {hit.reason}")
            hit = source_covers_url(right, left_url)
            if hit:
                reasons.append(f"{right.name} covers {left.name}: {hit.reason}")

            # Same non-portal origin is always a double.
            if not is_portal_host(left.base_url) and not is_portal_host(right.base_url):
                if _origin(left.base_url) and _origin(left.base_url) == _origin(right.base_url):
                    reasons.append(f"same employer origin {_origin(left.base_url)}")

            if reasons:
                seen_pairs.add(pair)
                doubles.append(
                    {
                        "left_id": left.id,
                        "left_name": left.name,
                        "left_url": left_url,
                        "right_id": right.id,
                        "right_name": right.name,
                        "right_url": right_url,
                        "reasons": sorted(set(reasons)),
                    }
                )
    return doubles
