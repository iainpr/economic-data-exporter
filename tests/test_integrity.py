import pandas as pd
import pytest

from economic_data_exporter.exceptions import ValidationError
from economic_data_exporter.utils.validation import validate_observations


def test_duplicate_observations_rejected() -> None:
    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(["2020-01-01", "2020-01-01"]),
            "value": [1.0, 2.0],
            "series_id": ["X", "X"],
            "geography": ["CA", "CA"],
        }
    )
    with pytest.raises(ValidationError):
        validate_observations(frame, max_records=100)


def test_missing_observations_preserved_as_warning() -> None:
    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(["2020-01-01", "2020-01-02"]),
            "value": [1.0, None],
            "series_id": ["X", "X"],
            "geography": ["CA", "CA"],
        }
    )
    warnings = validate_observations(frame, max_records=100)
    assert any("missing" in item.lower() for item in warnings)
