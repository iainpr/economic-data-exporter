"""Common source-adapter contract and normalization helpers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Callable

import pandas as pd

from economic_data_exporter.config import LIMITS
from economic_data_exporter.models import SeriesMetadata, SeriesRequest, SourceResult
from economic_data_exporter.network import HttpClient
from economic_data_exporter.services.ingestion import canonicalize_observations
from economic_data_exporter.utils.validation import validate_observations

CancelCheck = Callable[[], None]


class DataSource(ABC):
    name: str

    def __init__(self, client: HttpClient) -> None:
        self.client = client

    @abstractmethod
    def search(self, query: str, *, options: dict[str, object] | None = None) -> list[SeriesMetadata]:
        """Search or validate provider metadata without downloading observations."""

    @abstractmethod
    def fetch(self, request: SeriesRequest, *, cancel: CancelCheck) -> SourceResult:
        """Retrieve and normalize one independent series request."""


def finish_result(
    *,
    request: SeriesRequest,
    metadata: SeriesMetadata,
    dates: pd.Series,
    values: pd.Series,
    geographies: pd.Series | str,
    retrieved_at: datetime | None = None,
    from_cache: bool = False,
    warnings: list[str] | None = None,
) -> SourceResult:
    timestamp = retrieved_at or datetime.now(timezone.utc)
    frame = pd.DataFrame({"date": dates, "value": values})
    frame["source"] = metadata.source
    frame["series_id"] = metadata.series_id
    frame["series_name"] = metadata.name
    frame["geography"] = geographies
    frame["frequency"] = metadata.frequency
    frame["units"] = metadata.units
    frame["retrieved_at"] = timestamp.replace(microsecond=0).isoformat()
    frame["source_url"] = metadata.source_url
    frame = canonicalize_observations(frame, source=metadata.source)
    frame.sort_values(["date", "geography"], inplace=True, kind="stable")
    frame.reset_index(drop=True, inplace=True)
    integrity_warnings = validate_observations(frame, max_records=LIMITS.max_records)
    return SourceResult(
        request=request,
        data=frame,
        metadata=metadata,
        retrieved_at=timestamp,
        warnings=[*(warnings or []), *integrity_warnings],
        from_cache=from_cache,
    )
