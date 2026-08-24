"""Central configuration for the quant platform.

Loads settings from environment variables (populated from a local .env file
via python-dotenv) and exposes a single validated `settings` object. No
secrets are ever hard-coded here; only defaults for non-sensitive values.
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, Field

PROJECT_ROOT = Path(__file__).resolve().parent
load_dotenv(PROJECT_ROOT / ".env", override=False)


def _resolve_path(value: str, base: Path) -> Path:
    p = Path(value)
    return p if p.is_absolute() else (base / p)


class Settings(BaseModel):
    data_provider: str = Field(default="yfinance")
    data_dir: Path
    duckdb_path: Path
    log_level: str = "INFO"

    http_max_retries: int = 5
    http_backoff_base_seconds: float = 1.5
    http_request_timeout_seconds: float = 30.0
    http_min_interval_seconds: float = 0.6

    # Optional third live-quote source (free tier, requires a signup key).
    # Left unset, `data/providers/live_quotes.py` just skips it - NSE India
    # and yfinance alone already give full coverage with no key needed.
    twelve_data_api_key: str | None = None

    @property
    def parquet_dir(self) -> Path:
        return self.data_dir / "parquet"

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def logs_dir(self) -> Path:
        return PROJECT_ROOT / "logs"


def load_settings() -> Settings:
    data_dir = _resolve_path(os.getenv("DATA_DIR", "data_files"), PROJECT_ROOT)
    duckdb_path = _resolve_path(
        os.getenv("DUCKDB_PATH", "duckdb/quant_platform.duckdb"), data_dir
    )
    settings = Settings(
        data_provider=os.getenv("DATA_PROVIDER", "yfinance"),
        data_dir=data_dir,
        duckdb_path=duckdb_path,
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        http_max_retries=int(os.getenv("HTTP_MAX_RETRIES", "5")),
        http_backoff_base_seconds=float(os.getenv("HTTP_BACKOFF_BASE_SECONDS", "1.5")),
        http_request_timeout_seconds=float(
            os.getenv("HTTP_REQUEST_TIMEOUT_SECONDS", "30")
        ),
        http_min_interval_seconds=float(os.getenv("HTTP_MIN_INTERVAL_SECONDS", "0.6")),
        twelve_data_api_key=os.getenv("TWELVE_DATA_API_KEY") or None,
    )
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.parquet_dir.mkdir(parents=True, exist_ok=True)
    settings.raw_dir.mkdir(parents=True, exist_ok=True)
    settings.duckdb_path.parent.mkdir(parents=True, exist_ok=True)
    settings.logs_dir.mkdir(parents=True, exist_ok=True)
    return settings


settings = load_settings()
