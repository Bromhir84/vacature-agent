from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes_crawl import router as crawl_router
from app.api.routes_discovery import router as discovery_router
from app.api.routes_listings import router as listings_router
from app.api.routes_scans import router as scans_router
from app.api.routes_settings import router as settings_router
from app.api.routes_sources import router as sources_router
from app.config import get_settings
from app.db import SessionLocal, init_db
from app.scheduler import shutdown_scheduler, start_scheduler
from app.seed import seed_database

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _ensure_sqlite_dir() -> None:
    settings = get_settings()
    url = settings.database_url
    if url.startswith("sqlite:///"):
        raw = url.removeprefix("sqlite:///")
        # Absolute path forms: sqlite:////data/x.db -> /data/x.db
        if url.startswith("sqlite:////"):
            path = Path("/" + url.removeprefix("sqlite:////"))
        else:
            path = Path(raw)
        path.parent.mkdir(parents=True, exist_ok=True)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    _ensure_sqlite_dir()
    init_db()
    db = SessionLocal()
    try:
        seed_database(db)
    finally:
        db.close()
    if os.getenv("DISABLE_SCHEDULER", "").lower() not in {"1", "true", "yes"}:
        start_scheduler()
    yield
    shutdown_scheduler()


app = FastAPI(title="Vacature Agent", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(sources_router)
app.include_router(discovery_router)
app.include_router(crawl_router)
app.include_router(listings_router)
app.include_router(scans_router)
app.include_router(settings_router)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
