from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler

from app.config import get_settings
from app.crawl.runner import run_web_crawl
from app.db import SessionLocal
from app.discovery.service import run_portal_harvest
from app.pipeline.runner import scan_all_enabled
from app.pipeline.settings_store import get_runtime_settings

logger = logging.getLogger(__name__)
scheduler = BackgroundScheduler()


def _scheduled_scan() -> None:
    db = SessionLocal()
    try:
        logger.info("Starting scheduled scan")
        scan_all_enabled(db, classify=True)
    except Exception:  # noqa: BLE001
        logger.exception("Scheduled scan failed")
    finally:
        db.close()


def _scheduled_harvest() -> None:
    db = SessionLocal()
    try:
        logger.info("Starting scheduled portal harvest")
        result = run_portal_harvest(db)
        logger.info(
            "Portal harvest finished: created=%s updated=%s blocked=%s",
            len(result["created"]),
            len(result["updated"]),
            result["blocked"],
        )
    except Exception:  # noqa: BLE001
        logger.exception("Scheduled portal harvest failed")
    finally:
        db.close()


def _scheduled_crawl() -> None:
    db = SessionLocal()
    try:
        logger.info("Starting scheduled open-web crawl")
        result = run_web_crawl(db)
        logger.info(
            "Open-web crawl finished: upserted=%s proposals=%s skipped_low=%s avg_relevance=%s",
            result.get("upserted"),
            result.get("proposals_created"),
            result.get("skipped_low_score"),
            result.get("avg_relevance"),
        )
    except Exception:  # noqa: BLE001
        logger.exception("Scheduled open-web crawl failed")
    finally:
        db.close()


def start_scheduler() -> None:
    db = SessionLocal()
    try:
        hours = float(get_runtime_settings(db)["scan_interval_hours"])
    finally:
        db.close()
    crawl_hours = max(float(get_settings().crawl_interval_hours), 1.0)
    if scheduler.running:
        return
    scheduler.add_job(
        _scheduled_scan,
        "interval",
        hours=max(hours, 0.25),
        id="vacature_scan",
        replace_existing=True,
    )
    scheduler.add_job(
        _scheduled_harvest,
        "interval",
        hours=24,
        id="portal_harvest",
        replace_existing=True,
    )
    scheduler.add_job(
        _scheduled_crawl,
        "interval",
        hours=crawl_hours,
        id="open_web_crawl",
        replace_existing=True,
    )
    scheduler.start()
    logger.info(
        "Scheduler started (scan every %s hours; harvest every 24h; crawl every %s hours)",
        hours,
        crawl_hours,
    )


def shutdown_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
