from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import AppSetting
from app.pipeline.rules import DEFAULT_ALLOWLIST, DEFAULT_BLOCKLIST, DEFAULT_STAFFING_KEYWORDS


DEFAULTS: dict[str, Any] = {
    "staffing_keywords": DEFAULT_STAFFING_KEYWORDS,
    "employment_allowlist": DEFAULT_ALLOWLIST,
    "employment_blocklist": DEFAULT_BLOCKLIST,
}

SECRET_KEYS = {"llm_api_key"}


def get_setting(db: Session, key: str, default: Any = None) -> Any:
    row = db.get(AppSetting, key)
    if row is None:
        return DEFAULTS.get(key, default)
    return row.value


def set_setting(db: Session, key: str, value: Any) -> None:
    row = db.get(AppSetting, key)
    if row is None:
        row = AppSetting(key=key, value=value)
        db.add(row)
    else:
        row.value = value


def mask_secret(value: str | None) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "••••••••"
    return f"{value[:4]}…{value[-4:]}"


def resolve_llm_config(db: Session | None = None) -> dict[str, str]:
    """DB overrides win over environment defaults."""
    env = get_settings()
    if db is None:
        from app.db import SessionLocal

        session = SessionLocal()
        try:
            return resolve_llm_config(session)
        finally:
            session.close()

    stored_key = get_setting(db, "llm_api_key", None)
    stored_base = get_setting(db, "llm_base_url", None)
    stored_model = get_setting(db, "llm_model", None)

    api_key = str(stored_key).strip() if stored_key else env.llm_api_key
    base_url = str(stored_base).strip() if stored_base else env.llm_base_url
    model = str(stored_model).strip() if stored_model else env.llm_model
    return {
        "llm_api_key": api_key or "",
        "llm_base_url": base_url or env.llm_base_url,
        "llm_model": model or env.llm_model,
    }


def get_runtime_settings(db: Session, *, include_secrets: bool = False) -> dict[str, Any]:
    env = get_settings()
    llm = resolve_llm_config(db)
    api_key = llm["llm_api_key"]
    return {
        "staffing_keywords": get_setting(db, "staffing_keywords", DEFAULT_STAFFING_KEYWORDS),
        "employment_allowlist": get_setting(db, "employment_allowlist", DEFAULT_ALLOWLIST),
        "employment_blocklist": get_setting(db, "employment_blocklist", DEFAULT_BLOCKLIST),
        "confidence_candidate": float(
            get_setting(db, "confidence_candidate", env.confidence_candidate)
        ),
        "confidence_review": float(get_setting(db, "confidence_review", env.confidence_review)),
        "scan_interval_hours": float(get_setting(db, "scan_interval_hours", env.scan_interval_hours)),
        "agent_max_listings": int(get_setting(db, "agent_max_listings", env.agent_max_listings)),
        "agent_max_pages": int(get_setting(db, "agent_max_pages", env.agent_max_pages)),
        "llm_model": llm["llm_model"],
        "llm_base_url": llm["llm_base_url"],
        "llm_api_key_set": bool(api_key),
        "llm_api_key_masked": mask_secret(api_key) if api_key else "",
        "llm_api_key": api_key if include_secrets else None,
        "llm_source": "database" if get_setting(db, "llm_api_key", None) else ("environment" if env.llm_api_key else "none"),
    }


def ensure_default_settings(db: Session) -> None:
    env = get_settings()
    defaults = {
        **DEFAULTS,
        "confidence_candidate": env.confidence_candidate,
        "confidence_review": env.confidence_review,
        "scan_interval_hours": env.scan_interval_hours,
        "agent_max_listings": env.agent_max_listings,
        "agent_max_pages": env.agent_max_pages,
        "llm_model": env.llm_model,
        "llm_base_url": env.llm_base_url,
    }
    for key, value in defaults.items():
        if db.get(AppSetting, key) is None:
            db.add(AppSetting(key=key, value=value))
    db.commit()
