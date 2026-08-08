from __future__ import annotations

from datetime import UTC, date, datetime

import pandas as pd
import pytest

from economic_data_exporter.models import SeriesMetadata, SeriesRequest, SourceResult


@pytest.fixture
def sample_request() -> SeriesRequest:
    return SeriesRequest(
        source="Bank of Canada",
        series_id="FXUSDCAD",
        start_date=date(2020, 1, 1),
        end_date=date(2020, 1, 3),
    )


@pytest.fixture
def sample_result(sample_request: SeriesRequest) -> SourceResult:
    retrieved = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)
    metadata = SeriesMetadata(
        source="Bank of Canada",
        series_id="FXUSDCAD",
        name="USD/CAD",
        geography="Canada",
        frequency="Daily",
        units="CAD per USD",
        source_url="https://www.bankofcanada.ca/valet/observations/FXUSDCAD/json",
        attribution="Bank of Canada",
        license_text="Bank terms",
    )
    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(["2020-01-01", "2020-01-02", "2020-01-03"]),
            "value": [1.3, None, 1.31],
            "source": metadata.source,
            "series_id": metadata.series_id,
            "series_name": metadata.name,
            "geography": metadata.geography,
            "frequency": metadata.frequency,
            "units": metadata.units,
            "retrieved_at": retrieved.isoformat(),
            "source_url": metadata.source_url,
        }
    )
    return SourceResult(
        request=sample_request,
        data=frame,
        metadata=metadata,
        retrieved_at=retrieved,
        warnings=["Provider missing values were preserved explicitly."],
    )
