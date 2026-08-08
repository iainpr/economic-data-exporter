from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from economic_data_exporter.exceptions import ValidationError
from economic_data_exporter.utils.validation import (
    validate_date_range,
    validate_observations,
    validate_output_path,
    validate_series_id,
)


def test_date_range_validation() -> None:
    validate_date_range(date(2020, 1, 1), date(2020, 1, 1))
    with pytest.raises(ValidationError):
        validate_date_range(date(2020, 2, 1), date(2020, 1, 1))


def test_series_validation_by_source() -> None:
    assert validate_series_id("SP.POP.TOTL", source="World Bank") == "SP.POP.TOTL"
    assert validate_series_id("life-expectancy", source="Our World in Data") == "life-expectancy"
    assert validate_series_id("rgdpo", source="Penn World Table") == "rgdpo"
    with pytest.raises(ValidationError):
        validate_series_id("https://evil.example/x", source="Our World in Data")
    with pytest.raises(ValidationError):
        validate_series_id("../secret", source="Penn World Table")


def test_safe_output_path(tmp_path: Path) -> None:
    assert validate_output_path(tmp_path / "out.xlsx").suffix == ".xlsx"
    with pytest.raises(ValidationError):
        validate_output_path(tmp_path / "out.csv")


def test_validate_observations_warns_when_input_is_unsorted() -> None:
    unsorted = pd.DataFrame(
        {
            "date": pd.to_datetime(["2020-01-02", "2020-01-01"]),
            "value": [1.0, 2.0],
            "series_id": ["A", "A"],
            "geography": ["", ""],
        }
    )
    warnings = validate_observations(unsorted, max_records=100)
    assert "Observations were sorted by date during normalization." in warnings

    sorted_frame = unsorted.sort_values("date").reset_index(drop=True)
    assert "Observations were sorted by date during normalization." not in validate_observations(
        sorted_frame, max_records=100
    )


def test_imf_geography_is_required_in_job_runner():
    from datetime import date

    from economic_data_exporter.models import SeriesRequest
    from economic_data_exporter.services.job import JobRunner
    from economic_data_exporter.sources.base import DataSource

    class IMFStub(DataSource):
        name = "IMF"

        def search(self, query: str, *, options=None):
            return []

        def fetch(self, request, *, cancel):
            raise AssertionError("fetch should not run when required geography is missing")

    request = SeriesRequest("IMF", "NGDP_RPCH", date(2020, 1, 1), date(2020, 12, 31), "")
    runner = JobRunner({"IMF": IMFStub(client=None)}, max_workers=1)  # type: ignore[arg-type]
    try:
        runner._validate_request(request)
    except Exception as exc:
        assert "geography code is required" in str(exc)
    else:
        raise AssertionError("Expected IMF geography validation failure")
