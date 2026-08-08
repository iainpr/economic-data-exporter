from datetime import date

import pandas as pd
import pytest

from economic_data_exporter.exceptions import ValidationError
from economic_data_exporter.models import ExportFormatOptions, SeriesRequest
from economic_data_exporter.services.ingestion import (
    assert_primary_key_unique,
    assert_requests_unique,
    canonicalize_observations,
)
from economic_data_exporter.services.provenance import run_fingerprint


def test_ingestion_standardizes_columns_strings_and_nulls() -> None:
    frame = pd.DataFrame(
        {
            "Series Name": ["  Some Indicator  "],
            "VALUE": ["-99"],
            "Geography": [" ca "],
            "Series_ID": ["FXUSDCAD"],
        }
    )
    out = canonicalize_observations(frame, source="Bank of Canada")
    assert list(out.columns) == ["series_name", "value", "geography", "series_id", "source", "data_source"]
    assert pd.isna(out.loc[0, "value"])
    assert out.loc[0, "series_name"] == "Some Indicator"
    assert out.loc[0, "geography"] == "CA"
    assert out.loc[0, "series_id"] == "FXUSDCAD"
    assert out.loc[0, "data_source"] == "bank_of_canada"


def test_primary_key_rejects_duplicates() -> None:
    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(["2020-01-01", "2020-01-01"]),
            "source": ["FRED", "FRED"],
            "series_id": ["GDP", "GDP"],
            "geography": ["US", "US"],
        }
    )
    with pytest.raises(ValidationError, match="primary key"):
        assert_primary_key_unique(frame)


def test_duplicate_requests_are_rejected() -> None:
    request = SeriesRequest("FRED", "GDP", date(2020, 1, 1), date(2020, 1, 2), geography="US")
    with pytest.raises(ValidationError, match="Duplicate export request"):
        assert_requests_unique([request, request])


def test_run_fingerprint_is_stable() -> None:
    request = SeriesRequest("FRED", "GDP", date(2020, 1, 1), date(2020, 1, 2), geography="US")
    options = ExportFormatOptions()
    assert run_fingerprint([request], options) == run_fingerprint([request], options)
