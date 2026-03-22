from functools import lru_cache
from urllib.parse import urlparse

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "development"
    log_level: str = "INFO"
    database_url: str = "sqlite:///./data/supply_chain_risk.db"
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    frontend_port: int = 8501
    frontend_api_base_url: str = "http://127.0.0.1:8000"
    ingestion_enabled: bool = True
    ingestion_interval_seconds: int = 900
    ingestion_request_timeout_seconds: float = 10.0
    ingestion_max_retries: int = 3
    ingestion_retry_backoff_seconds: float = 1.5
    rss_feed_urls: str = (
        "https://www.freightwaves.com/news/feed,"
        "https://www.supplychaindive.com/feeds/news/"
    )
    relevance_threshold: float = 0.35
    processing_enabled: bool = True
    risk_scoring_enabled: bool = True
    risk_article_flag_threshold: float = 0.6
    risk_spike_delta_threshold: float = 0.2
    risk_spike_ratio_threshold: float = 1.35
    risk_spike_baseline_points: int = 3
    watchlist_seed_items: str = (
        "Intel|company|intel corporation,"
        "TSMC|company|taiwan semiconductor,"
        "Panama Canal|region|panama canal,"
        "Copper|commodity|copper,"
        "Semiconductors|commodity|chips"
    )

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    @field_validator("app_env")
    @classmethod
    def validate_app_env(cls, value: str) -> str:
        normalized = value.strip().lower()
        allowed = {"development", "test", "staging", "production"}
        if normalized not in allowed:
            raise ValueError(f"APP_ENV must be one of: {', '.join(sorted(allowed))}")
        return normalized

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, value: str) -> str:
        normalized = value.strip().upper()
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if normalized not in allowed:
            raise ValueError(f"LOG_LEVEL must be one of: {', '.join(sorted(allowed))}")
        return normalized

    @field_validator("database_url", "frontend_api_base_url")
    @classmethod
    def validate_required_urls(cls, value: str) -> str:
        normalized = value.strip()
        parsed = urlparse(normalized)
        if normalized.startswith("sqlite:///"):
            return normalized
        if not parsed.scheme or not parsed.netloc:
            raise ValueError("must be a valid URL")
        return normalized

    @field_validator("rss_feed_urls")
    @classmethod
    def validate_rss_feed_urls(cls, value: str) -> str:
        urls = [item.strip() for item in value.split(",") if item.strip()]
        if not urls:
            raise ValueError("RSS_FEED_URLS must include at least one feed URL")
        for url in urls:
            parsed = urlparse(url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ValueError(f"invalid RSS feed URL: {url}")
        return ",".join(urls)

    @field_validator("watchlist_seed_items")
    @classmethod
    def validate_watchlist_seed_items(cls, value: str) -> str:
        allowed_entity_types = {"company", "region", "commodity"}
        items = [item.strip() for item in value.split(",") if item.strip()]
        for item in items:
            parts = [part.strip() for part in item.split("|")]
            if len(parts) < 2 or not parts[0] or not parts[1]:
                raise ValueError(
                    "WATCHLIST_SEED_ITEMS entries must use display_name|entity_type|query_hint format"
                )
            if parts[1] not in allowed_entity_types:
                raise ValueError(
                    "WATCHLIST_SEED_ITEMS entity_type must be one of: company, commodity, region"
                )
        return ",".join(items)

    @model_validator(mode="after")
    def validate_numeric_ranges(self) -> "Settings":
        if self.api_port <= 0 or self.frontend_port <= 0:
            raise ValueError("API_PORT and FRONTEND_PORT must be positive integers")
        if self.ingestion_interval_seconds <= 0:
            raise ValueError("INGESTION_INTERVAL_SECONDS must be greater than 0")
        if self.ingestion_request_timeout_seconds <= 0:
            raise ValueError("INGESTION_REQUEST_TIMEOUT_SECONDS must be greater than 0")
        if self.ingestion_max_retries <= 0:
            raise ValueError("INGESTION_MAX_RETRIES must be greater than 0")
        if self.ingestion_retry_backoff_seconds < 0:
            raise ValueError("INGESTION_RETRY_BACKOFF_SECONDS must be 0 or greater")

        threshold_fields = {
            "relevance_threshold": self.relevance_threshold,
            "risk_article_flag_threshold": self.risk_article_flag_threshold,
            "risk_spike_delta_threshold": self.risk_spike_delta_threshold,
            "risk_spike_ratio_threshold": self.risk_spike_ratio_threshold,
        }
        for field_name, value in threshold_fields.items():
            if value < 0:
                raise ValueError(f"{field_name} must be 0 or greater")

        if self.relevance_threshold > 1 or self.risk_article_flag_threshold > 1:
            raise ValueError("RELEVANCE_THRESHOLD and RISK_ARTICLE_FLAG_THRESHOLD must be between 0 and 1")
        if self.risk_spike_baseline_points <= 0:
            raise ValueError("RISK_SPIKE_BASELINE_POINTS must be greater than 0")

        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
