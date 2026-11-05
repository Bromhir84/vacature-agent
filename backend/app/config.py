from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "sqlite:///./data/vacature.db"
    llm_base_url: str = "https://api.openai-compat.model-serving.eu01.onstackit.cloud/v1"
    llm_api_key: str = ""
    llm_model: str = "Qwen/Qwen3.8-27B"
    scan_interval_hours: float = 6.0
    confidence_candidate: float = 0.7
    confidence_review: float = 0.4
    agent_max_listings: int = 25
    agent_max_pages: int = 5
    crawl_max_pages: int = 40
    crawl_max_new_urls: int = 100
    crawl_min_relevance: float = 0.35
    crawl_interval_hours: float = 24.0
    # Don't re-fetch the same URL/host within this many days.
    crawl_revisit_days: float = 7.0
    request_delay_seconds: float = 1.0
    http_user_agent: str = (
        "VacatureAgent/1.0 (+https://github.com/vacature-agent; respectful job scanner)"
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
