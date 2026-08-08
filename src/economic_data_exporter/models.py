"""Validated internal data models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pandas as pd

DATA_COLUMNS = [
    "date",
    "value",
    "source",
    "data_source",
    "series_id",
    "series_name",
    "geography",
    "frequency",
    "units",
    "retrieved_at",
    "source_url",
]


DEFAULT_EXPORT_COLUMNS = [
    "date",
    "value",
    "source",
    "data_source",
    "series_id",
    "series_name",
    "geography",
    "frequency",
    "units",
]


@dataclass(frozen=True, slots=True)
class SeriesMetadata:
    source: str
    series_id: str
    name: str
    geography: str = ""
    frequency: str = ""
    units: str = ""
    notes: str = ""
    source_url: str = ""
    attribution: str = ""
    license_text: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SeriesRequest:
    source: str
    series_id: str
    start_date: date
    end_date: date
    geography: str = ""
    frequency: str = ""
    options: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ExportFormatOptions:
    """User-selected derived-output rules; canonical provider data remain unchanged."""

    output_shape: str = "long"
    columns: tuple[str, ...] = tuple(DATA_COLUMNS)
    drop_missing_values: bool = False
    remove_duplicate_rows: bool = True
    sort_by_date: bool = True
    freeze_header: bool = True
    autofilter: bool = True
    auto_width: bool = True
    include_series_sheets: bool = False
    preview_rows: int = 500

    def __post_init__(self) -> None:
        if self.output_shape not in {"long", "wide"}:
            raise ValueError("output_shape must be 'long' or 'wide'.")
        invalid = set(self.columns) - set(DATA_COLUMNS)
        if invalid:
            raise ValueError(f"Unsupported export columns: {sorted(invalid)}")
        if "date" not in self.columns:
            raise ValueError("The date column is required for export.")
        if self.output_shape == "long" and "value" not in self.columns:
            raise ValueError("The value column is required for long-format export.")
        if self.preview_rows < 50:
            raise ValueError("preview_rows must be at least 50.")


PRIMARY_KEY_COLUMNS = ("date", "source", "series_id", "geography")


@dataclass(slots=True)
class SourceResult:
    request: SeriesRequest
    data: pd.DataFrame
    metadata: SeriesMetadata
    retrieved_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    warnings: list[str] = field(default_factory=list)
    from_cache: bool = False
    transformations: list[str] = field(default_factory=list)

    def normalized(self) -> pd.DataFrame:
        frame = self.data.copy()
        for column in DATA_COLUMNS:
            if column not in frame.columns:
                frame[column] = pd.NA
        return frame[DATA_COLUMNS]


@dataclass(frozen=True, slots=True)
class FailureRecord:
    source: str
    series_id: str
    geography: str
    error_type: str
    message: str


@dataclass(slots=True)
class ExportJob:
    requests: list[SeriesRequest]
    output_path: Path
    fail_fast: bool = False
    ignore_cache: bool = False
    include_series_sheets: bool = False
    format_options: ExportFormatOptions = field(default_factory=ExportFormatOptions)


@dataclass(slots=True)
class ExportSummary:
    output_path: Path | None
    successful: list[SourceResult]
    failures: list[FailureRecord]
    cancelled: bool = False
    elapsed_seconds: float = 0.0


@dataclass(slots=True)
class FetchSummary:
    successful: list[SourceResult]
    failures: list[FailureRecord]
    cancelled: bool = False
    elapsed_seconds: float = 0.0
