"""Application configuration and capacity limits."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from platformdirs import user_cache_path, user_log_path

from economic_data_exporter import __version__

APP_NAME = "Economic Data Exporter"
USER_AGENT = f"EconomicDataExporter/{__version__} (+desktop research tool)"


@dataclass(frozen=True, slots=True)
class Limits:
    max_concurrency: int = 3
    max_records: int = 500_000
    max_response_bytes: int = 100 * 1024 * 1024
    max_pages: int = 2_000
    cache_ttl_seconds: int = 24 * 60 * 60
    max_cache_bytes: int = 500 * 1024 * 1024
    connect_timeout_seconds: float = 10.0
    read_timeout_seconds: float = 60.0
    max_retries: int = 3


LIMITS = Limits()
CACHE_DIR: Path = user_cache_path(APP_NAME, ensure_exists=True)
LOG_DIR: Path = user_log_path(APP_NAME, ensure_exists=True)
