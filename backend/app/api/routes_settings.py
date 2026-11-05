from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.pipeline.settings_store import get_runtime_settings, set_setting
from app.schemas import SettingsOut, SettingsUpdate

router = APIRouter(prefix="/api/settings", tags=["settings"])

# Keys that are safe to write as-is from the patch payload.
WRITABLE_KEYS = {
    "staffing_keywords",
    "employment_allowlist",
    "employment_blocklist",
    "confidence_candidate",
    "confidence_review",
    "scan_interval_hours",
    "agent_max_listings",
    "agent_max_pages",
    "llm_model",
    "llm_base_url",
}


@router.get("", response_model=SettingsOut)
def get_settings_api(db: Session = Depends(get_db)) -> SettingsOut:
    data = get_runtime_settings(db)
    return SettingsOut(**{k: data[k] for k in SettingsOut.model_fields})


@router.patch("", response_model=SettingsOut)
def update_settings_api(payload: SettingsUpdate, db: Session = Depends(get_db)) -> SettingsOut:
    data = payload.model_dump(exclude_unset=True)

    if data.pop("clear_llm_api_key", False):
        set_setting(db, "llm_api_key", "")

    api_key = data.pop("llm_api_key", None)
    if isinstance(api_key, str) and api_key.strip():
        # Ignore masked placeholder resubmits from the UI.
        if "…" not in api_key and not api_key.startswith("••••"):
            set_setting(db, "llm_api_key", api_key.strip())

    for key, value in data.items():
        if key in WRITABLE_KEYS:
            set_setting(db, key, value)

    db.commit()
    out = get_runtime_settings(db)
    return SettingsOut(**{k: out[k] for k in SettingsOut.model_fields})
