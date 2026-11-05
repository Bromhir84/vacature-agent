from __future__ import annotations

import heapq
import json
import logging
import traceback
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.http_util import get_text, http_client, rate_limit
from app.config import get_settings
from app.crawl.extract import (
    ExtractedLink,
    classify_link,
    extract_ddg_result_urls,
    extract_links,
    registrable_hint,
)
from app.crawl.robots import RobotsCache
from app.crawl.score import RelevanceScore, score_url_relevance
from app.crawl.seeds import DDG_HTML_SEARCH, DEFAULT_SEARCH_QUERIES, DEFAULT_SEED_URLS
from app.crawl.judge import is_noise_host, judge_crawl_candidate
from app.crawl.rejudge import rejudge_open_web_listings
from app.crawl.service import (
    collapse_listings_to_one_per_domain,
    domain_key,
    domains_claimed_by_source,
    ensure_open_web_source,
    external_id_for_url,
    listing_url_exists,
    page_title_from_html,
)
from app.crawl.visits import load_recent_visits, record_visit
from app.discovery.broker_gate import is_blocked_url, score_source_kind
from app.discovery.coverage import url_covered_by_sources
from app.discovery.resolve import normalize_url, origin_of
from app.discovery.service import _upsert_proposal
from app.models import Listing, ScanRun, Source

logger = logging.getLogger(__name__)


@dataclass(order=True)
class FrontierItem:
    priority: float
    seq: int
    url: str = field(compare=False)
    title: str = field(compare=False, default="")
    allow_cross_domain: bool = field(compare=False, default=False)
    seed_host: str = field(compare=False, default="")


def run_web_crawl(
    db: Session,
    *,
    max_pages: int | None = None,
    max_new_urls: int | None = None,
    min_relevance: float | None = None,
    queries: list[str] | None = None,
    seed_urls: list[str] | None = None,
) -> dict[str, Any]:
    settings = get_settings()
    max_pages = int(max_pages if max_pages is not None else settings.crawl_max_pages)
    max_new_urls = int(max_new_urls if max_new_urls is not None else settings.crawl_max_new_urls)
    min_relevance = float(
        min_relevance if min_relevance is not None else settings.crawl_min_relevance
    )

    source = ensure_open_web_source(db)
    run = ScanRun(source_id=source.id, status="running", started_at=datetime.utcnow())
    db.add(run)
    db.commit()
    db.refresh(run)

    stats: dict[str, Any] = {
        "pages_fetched": 0,
        "discovered": 0,
        "upserted": 0,
        "skipped_broker": 0,
        "skipped_low_score": 0,
        "skipped_dup": 0,
        "skipped_domain": 0,
        "skipped_unusable": 0,
        "skipped_recent": 0,
        "rejudged_discarded": 0,
        "proposals_created": 0,
        "avg_relevance": 0.0,
    }
    errors: list[str] = []
    relevance_scores: list[float] = []
    robots = RobotsCache()
    visited: set[str] = set()
    enqueued: set[str] = set()
    revisit_days = float(settings.crawl_revisit_days)
    recent_urls, recent_hosts = load_recent_visits(db, revisit_days=revisit_days)
    # Weed out obvious junk already stored, then one URL per hostname.
    rejudge_stats = rejudge_open_web_listings(db)
    stats["rejudged_discarded"] = int(rejudge_stats.get("discarded") or 0)
    removed = collapse_listings_to_one_per_domain(db, source.id)
    if removed:
        logger.info("Collapsed %s duplicate open-web listings (one per host)", removed)
    claimed_domains: set[str] = domains_claimed_by_source(db, source.id)
    # Block hosts we already cover with a listing OR fetched recently.
    reserved_hosts: set[str] = set(claimed_domains) | set(recent_hosts)
    claimed_proposal_hosts: set[str] = set()
    frontier: list[FrontierItem] = []
    seq = 0

    def push(
        url: str,
        *,
        title: str = "",
        page_kind: str = "overview",
        allow_cross_domain: bool = False,
        seed_host: str = "",
    ) -> None:
        nonlocal seq
        normalized = normalize_url(url)
        if not normalized or normalized in enqueued or normalized in visited:
            return
        if normalized in recent_urls:
            stats["skipped_recent"] += 1
            return
        host = domain_key(normalized)
        # At most one frontier fetch per hostname — stops jobs.ict.eu/a, /b, /c spam.
        if host and host in reserved_hosts:
            stats["skipped_domain"] += 1
            return
        # Skip career hubs already covered by a configured Source.
        if url_covered_by_sources(db, normalized):
            stats["skipped_dup"] += 1
            if host:
                reserved_hosts.add(host)
            return
        if is_blocked_url(normalized).blocked:
            stats["skipped_broker"] += 1
            return
        noise = is_noise_host(normalized)
        if noise:
            # Social/video/boards — never fetch or propose.
            stats["skipped_unusable"] += 1
            return
        scored = score_url_relevance(
            normalized, title=title or None, page_kind=page_kind
        )
        if scored.skip_broker:
            stats["skipped_broker"] += 1
            return
        # Reject obvious detacheerder/agency titles before spending a fetch.
        pre = judge_crawl_candidate(normalized, title=title or None, relevance=scored)
        if not pre.usable:
            reason_blob = " ".join(pre.reasons).lower()
            if any(
                key in reason_blob
                for key in (
                    "unusable host",
                    "broker",
                    "staffing/agency host",
                    "detacheerder",
                    "agency marketing",
                )
            ):
                stats["skipped_unusable"] += 1
                return
        # Higher score → lower priority number for min-heap
        seq += 1
        heapq.heappush(
            frontier,
            FrontierItem(
                priority=-scored.score,
                seq=seq,
                url=normalized,
                title=title,
                allow_cross_domain=allow_cross_domain,
                seed_host=seed_host or host or registrable_hint(normalized),
            ),
        )
        enqueued.add(normalized)
        if host:
            reserved_hosts.add(host)

    try:
        for url in seed_urls if seed_urls is not None else list(DEFAULT_SEED_URLS):
            push(url, page_kind="overview", allow_cross_domain=True)

        raw_queries = [
            q.strip()
            for q in (queries if queries is not None else DEFAULT_SEARCH_QUERIES)
            if q and q.strip()
        ]
        # Rotate default query order by day so successive runs explore differently.
        if queries is None and raw_queries:
            offset = datetime.utcnow().timetuple().tm_yday % len(raw_queries)
            search_queries = raw_queries[offset:] + raw_queries[:offset]
        else:
            search_queries = raw_queries
        for query in search_queries:
            for result_url, result_title in _search_ddg(query):
                kind = classify_link(result_url, result_title)
                if kind == "other":
                    kind = "overview"
                push(
                    result_url,
                    title=result_title,
                    page_kind=kind,
                    allow_cross_domain=True,
                )

        while frontier and stats["pages_fetched"] < max_pages and stats["upserted"] < max_new_urls:
            item = heapq.heappop(frontier)
            url = item.url
            if url in visited:
                continue
            visited.add(url)

            host = domain_key(url)
            # Listing already saved for this host from an earlier page — do not refetch.
            if host and host in claimed_domains:
                stats["skipped_domain"] += 1
                continue
            if url in recent_urls:
                stats["skipped_recent"] += 1
                continue

            if not robots.allowed(url):
                errors.append(f"robots disallow: {url}")
                record_visit(db, url, outcome="skipped")
                recent_urls.add(normalize_url(url) or url)
                if host:
                    recent_hosts.add(host)
                continue

            try:
                html = get_text(url)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"fetch {url}: {exc}")
                record_visit(db, url, outcome="error")
                recent_urls.add(normalize_url(url) or url)
                if host:
                    recent_hosts.add(host)
                continue

            record_visit(db, url, outcome="fetched")
            recent_urls.add(normalize_url(url) or url)
            if host:
                recent_hosts.add(host)
            stats["pages_fetched"] += 1
            page_title = item.title or page_title_from_html(html) or url
            page_kind = classify_link(url, page_title)
            if page_kind == "other":
                page_kind = "overview"

            page_score = score_url_relevance(
                url, title=page_title, snippet=html[:1500], page_kind=page_kind
            )
            if page_score.skip_broker:
                stats["skipped_broker"] += 1
                continue

            if page_kind == "overview" and page_score.score >= min_relevance:
                if host and host in claimed_proposal_hosts:
                    pass
                else:
                    created = _maybe_proposal(db, url, page_title, page_score, html[:800])
                    if created:
                        stats["proposals_created"] += 1
                        if host:
                            claimed_proposal_hosts.add(host)

            if page_kind == "detail":
                _ingest_detail(
                    db,
                    source,
                    url=url,
                    title=page_title,
                    snippet=html[:1200],
                    score=page_score,
                    min_relevance=min_relevance,
                    claimed_domains=claimed_domains,
                    reserved_hosts=reserved_hosts,
                    stats=stats,
                    relevance_scores=relevance_scores,
                )
                if stats["upserted"] >= max_new_urls:
                    break

            links = extract_links(html, url, limit=80)
            # Keep only the single best-scoring detail link per hostname from this page.
            best_detail: dict[str, tuple[float, ExtractedLink]] = {}
            overview_links: list[ExtractedLink] = []
            for link in links:
                if link.kind == "detail":
                    link_host = domain_key(link.url)
                    if not link_host or link_host in claimed_domains:
                        if link_host and link_host in claimed_domains:
                            stats["skipped_domain"] += 1
                        continue
                    scored = score_url_relevance(
                        link.url, title=link.title, page_kind="detail"
                    )
                    if scored.skip_broker:
                        stats["skipped_broker"] += 1
                        continue
                    prev = best_detail.get(link_host)
                    if prev is None or scored.score > prev[0]:
                        if prev is not None:
                            stats["skipped_domain"] += 1
                        best_detail[link_host] = (scored.score, link)
                    else:
                        stats["skipped_domain"] += 1
                elif link.kind == "overview":
                    overview_links.append(link)

            for _score, link in best_detail.values():
                _handle_extracted_link(
                    db,
                    source,
                    link=link,
                    parent=item,
                    min_relevance=min_relevance,
                    claimed_domains=claimed_domains,
                    reserved_hosts=reserved_hosts,
                    stats=stats,
                    relevance_scores=relevance_scores,
                    push=push,
                )
                if stats["upserted"] >= max_new_urls:
                    break

            for link in overview_links:
                _handle_extracted_link(
                    db,
                    source,
                    link=link,
                    parent=item,
                    min_relevance=min_relevance,
                    claimed_domains=claimed_domains,
                    reserved_hosts=reserved_hosts,
                    stats=stats,
                    relevance_scores=relevance_scores,
                    push=push,
                )
                if stats["upserted"] >= max_new_urls:
                    break

            db.commit()

        stats["discovered"] = (
            stats["upserted"]
            + stats["skipped_dup"]
            + stats["skipped_low_score"]
            + stats["skipped_domain"]
            + stats["skipped_recent"]
        )
        if relevance_scores:
            stats["avg_relevance"] = round(sum(relevance_scores) / len(relevance_scores), 3)

        source.last_scan_at = datetime.utcnow()
        run.status = "success"
        run.discovered = int(stats["discovered"])
        run.upserted = int(stats["upserted"])
        run.classified = 0
        run.candidates = 0
        summary = {
            "pages_fetched": stats["pages_fetched"],
            "skipped_broker": stats["skipped_broker"],
            "skipped_low_score": stats["skipped_low_score"],
            "skipped_dup": stats["skipped_dup"],
            "skipped_domain": stats["skipped_domain"],
            "skipped_unusable": stats["skipped_unusable"],
            "skipped_recent": stats["skipped_recent"],
            "rejudged_discarded": stats["rejudged_discarded"],
            "proposals_created": stats["proposals_created"],
            "avg_relevance": stats["avg_relevance"],
            "min_relevance": min_relevance,
            "revisit_days": revisit_days,
            "errors": errors[:20],
        }
        run.errors = json.dumps(summary, ensure_ascii=False)
        run.finished_at = datetime.utcnow()
        db.commit()
        db.refresh(run)
        return {
            "run": run,
            "source_id": source.id,
            **{k: stats[k] for k in (
                "pages_fetched",
                "discovered",
                "upserted",
                "skipped_broker",
                "skipped_low_score",
                "skipped_dup",
                "skipped_domain",
                "skipped_unusable",
                "skipped_recent",
                "rejudged_discarded",
                "proposals_created",
                "avg_relevance",
            )},
            "errors": errors[:20],
        }
    except Exception as exc:  # noqa: BLE001
        run.status = "error"
        run.discovered = int(stats.get("discovered") or 0)
        run.upserted = int(stats.get("upserted") or 0)
        run.errors = f"{exc}\n{traceback.format_exc()}"
        run.finished_at = datetime.utcnow()
        db.commit()
        db.refresh(run)
        logger.exception("web crawl failed")
        return {
            "run": run,
            "source_id": source.id,
            "pages_fetched": stats["pages_fetched"],
            "discovered": stats["discovered"],
            "upserted": stats["upserted"],
            "skipped_broker": stats["skipped_broker"],
            "skipped_low_score": stats["skipped_low_score"],
            "skipped_dup": stats["skipped_dup"],
            "skipped_domain": stats["skipped_domain"],
            "skipped_unusable": stats["skipped_unusable"],
            "skipped_recent": stats["skipped_recent"],
            "rejudged_discarded": stats["rejudged_discarded"],
            "proposals_created": stats["proposals_created"],
            "avg_relevance": stats["avg_relevance"],
            "errors": [str(exc)],
        }


def _search_ddg(query: str) -> list[tuple[str, str]]:
    try:
        rate_limit()
        with http_client() as client:
            response = client.post(DDG_HTML_SEARCH, data={"q": query})
            response.raise_for_status()
            html = response.text
    except Exception as exc:  # noqa: BLE001
        logger.info("DDG search failed for %r: %s", query, exc)
        return []
    return extract_ddg_result_urls(html, limit=20)


def _handle_extracted_link(
    db: Session,
    source: Source,
    *,
    link: ExtractedLink,
    parent: FrontierItem,
    min_relevance: float,
    claimed_domains: set[str],
    reserved_hosts: set[str],
    stats: dict[str, Any],
    relevance_scores: list[float],
    push,
) -> None:
    if is_blocked_url(link.url).blocked:
        stats["skipped_broker"] += 1
        return

    parent_host = parent.seed_host or domain_key(parent.url) or registrable_hint(parent.url)
    link_host = domain_key(link.url)
    parent_reg = registrable_hint(parent.url)
    link_reg = registrable_hint(link.url)
    same_site = bool(link_reg and parent_reg and link_reg == parent_reg) or (
        link_host and link_host == domain_key(parent.url)
    )
    if not same_site and not parent.allow_cross_domain:
        return

    scored = score_url_relevance(link.url, title=link.title, page_kind=link.kind)
    if scored.skip_broker:
        stats["skipped_broker"] += 1
        return

    if link.kind == "detail":
        if link_host and link_host in claimed_domains:
            stats["skipped_domain"] += 1
            return
        _ingest_detail(
            db,
            source,
            url=link.url,
            title=link.title,
            snippet=link.title,
            score=scored,
            min_relevance=min_relevance,
            claimed_domains=claimed_domains,
            reserved_hosts=reserved_hosts,
            stats=stats,
            relevance_scores=relevance_scores,
        )
        return

    if link.kind == "overview":
        push(
            link.url,
            title=link.title,
            page_kind="overview",
            allow_cross_domain=False,
            seed_host=parent_host if same_site else link_host,
        )


def _ingest_detail(
    db: Session,
    source: Source,
    *,
    url: str,
    title: str,
    snippet: str,
    score: RelevanceScore,
    min_relevance: float,
    claimed_domains: set[str],
    reserved_hosts: set[str],
    stats: dict[str, Any],
    relevance_scores: list[float],
) -> None:
    if score.skip_broker:
        stats["skipped_broker"] += 1
        return
    if score.score < min_relevance:
        stats["skipped_low_score"] += 1
        return
    normalized = normalize_url(url) or url
    judgement = judge_crawl_candidate(
        normalized,
        title=title,
        snippet=snippet,
        relevance=score,
    )
    if not judgement.usable:
        stats["skipped_unusable"] += 1
        return
    host = domain_key(normalized)
    if host and host in claimed_domains:
        stats["skipped_domain"] += 1
        return
    if listing_url_exists(db, normalized):
        stats["skipped_dup"] += 1
        if host:
            claimed_domains.add(host)
            reserved_hosts.add(host)
        return

    reasons_line = "score_reasons: " + "; ".join(score.reasons[:6])
    judge_line = "judge: " + "; ".join(judgement.reasons[:4])
    raw = f"{reasons_line}\n{judge_line}\n{(snippet or '')[:1000]}".strip()
    external_id = external_id_for_url(normalized)
    existing = db.scalar(
        select(Listing).where(
            Listing.source_id == source.id,
            Listing.external_id == external_id,
        )
    )
    now = datetime.utcnow()
    if existing:
        existing.title = (title or existing.title)[:512]
        existing.url = normalized
        existing.raw_snippet = raw
        existing.relevance_score = score.score
        existing.last_seen_at = now
        existing.disappeared = False
        if existing.status in {"discarded", "removed"}:
            existing.status = "open" if existing.viewed_at else "new"
        if host:
            claimed_domains.add(host)
            reserved_hosts.add(host)
        relevance_scores.append(score.score)
        return

    listing = Listing(
        source_id=source.id,
        external_id=external_id,
        title=(title or normalized)[:512],
        url=normalized,
        raw_snippet=raw,
        relevance_score=score.score,
        status="new",
        first_seen_at=now,
        last_seen_at=now,
    )
    db.add(listing)
    db.flush()
    if host:
        claimed_domains.add(host)
        reserved_hosts.add(host)
    stats["upserted"] += 1
    relevance_scores.append(score.score)


def _maybe_proposal(
    db: Session,
    url: str,
    title: str,
    score: RelevanceScore,
    snippet: str,
) -> bool:
    if is_noise_host(url):
        return False
    judgement = judge_crawl_candidate(
        url, title=title, snippet=snippet, relevance=score
    )
    # Don't propose social boards or agency self-marketing as career sources.
    if not judgement.usable:
        reason_blob = " ".join(judgement.reasons).lower()
        if any(
            key in reason_blob
            for key in (
                "unusable host",
                "broker",
                "staffing/agency",
                "detacheerder",
                "agency marketing",
            )
        ):
            return False
    kind_score = score_source_kind(title, url, snippet, use_llm=False)
    status = "blocked" if kind_score.kind == "broker" or kind_score.broker_risk >= 0.95 else "pending"
    if is_blocked_url(url).blocked:
        status = "blocked"
    host = urlparse(url).hostname or "career"
    name = (title or host).strip()[:255] or host
    reasons = list(kind_score.reasons)
    reasons.append(f"relevance={score.score}")
    reasons.extend(f"rel: {r}" for r in score.reasons[:4])
    proposal = _upsert_proposal(
        db,
        name=name,
        career_url=url,
        base_url=origin_of(url) or url,
        origin="crawl",
        kind=kind_score.kind,
        broker_risk=kind_score.broker_risk,
        reasons=reasons,
        status=status,
        raw_snippet=snippet[:800],
        query=None,
    )
    return proposal is not None
