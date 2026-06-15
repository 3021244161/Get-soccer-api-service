import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[2]


def _split_csv(raw_value):
    return [item.strip() for item in (raw_value or "").split(",") if item.strip()]


@dataclass(frozen=True)
class Settings:
    app_name: str
    app_env: str
    app_host: str
    app_port: int
    log_level: str
    redis_url: str
    api_keys: tuple[str, ...]
    fast_refresh_interval_seconds: int
    slow_refresh_interval_seconds: int
    refresh_lock_ttl_seconds: int
    cache_keep_versions: int
    redis_key_prefix: str
    playwright_headless: bool
    source_url: str
    station_user_id: str
    station_uuid: str
    run_scheduler_in_api: bool
    scheduler_run_on_startup: bool

    @property
    def output_dir(self) -> Path:
        return BASE_DIR / "output"

    @property
    def active_version_key(self) -> str:
        return f"{self.redis_key_prefix}:active_version"

    @property
    def refresh_latest_key(self) -> str:
        return f"{self.redis_key_prefix}:refresh:latest"

    @property
    def refresh_lock_key(self) -> str:
        return f"{self.redis_key_prefix}:refresh:lock"

    @property
    def cache_backend(self) -> str:
        if self.redis_url.lower().startswith("memory://"):
            return "memory"
        return "redis"

    @property
    def refresh_interval_seconds(self) -> int:
        return self.fast_refresh_interval_seconds


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings(
        app_name=os.getenv("APP_NAME", "Football Lottery API"),
        app_env=os.getenv("APP_ENV", "development"),
        app_host=os.getenv("APP_HOST", "0.0.0.0"),
        app_port=int(os.getenv("APP_PORT", "8000")),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        redis_url=os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0"),
        api_keys=tuple(_split_csv(os.getenv("API_KEYS", "dev-key"))),
        fast_refresh_interval_seconds=int(
            os.getenv("FAST_REFRESH_INTERVAL_SECONDS", os.getenv("REFRESH_INTERVAL_SECONDS", "720"))
        ),
        slow_refresh_interval_seconds=int(os.getenv("SLOW_REFRESH_INTERVAL_SECONDS", "7200")),
        refresh_lock_ttl_seconds=int(os.getenv("REFRESH_LOCK_TTL_SECONDS", "1800")),
        cache_keep_versions=int(os.getenv("CACHE_KEEP_VERSIONS", "3")),
        redis_key_prefix=os.getenv("REDIS_KEY_PREFIX", "lottery"),
        playwright_headless=os.getenv("PLAYWRIGHT_HEADLESS", "true").lower() != "false",
        source_url=os.getenv("SOURCE_URL", ""),
        station_user_id=os.getenv("STATION_USER_ID", ""),
        station_uuid=os.getenv("STATION_UUID", ""),
        run_scheduler_in_api=os.getenv("RUN_SCHEDULER_IN_API", "false").lower() == "true",
        scheduler_run_on_startup=os.getenv("SCHEDULER_RUN_ON_STARTUP", "true").lower() != "false",
    )
