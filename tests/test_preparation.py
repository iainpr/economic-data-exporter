from pathlib import Path

import pandas as pd
import pytest

from economic_data_exporter.exceptions import ExportError
from economic_data_exporter.models import ExportFormatOptions
from economic_data_exporter.services.preparation import prepare_export_data


def test_clean_research_profile_drops_missing_values_and_columns(sample_result) -> None:
    result = sample_result
    result.data.loc[0, "value"] = None
    options = ExportFormatOptions(
        columns=("date", "value", "source", "series_id", "series_name"),
        drop_missing_values=True,
        remove_duplicate_rows=True,
    )
    data, transformations = prepare_export_data([result], options)
    assert list(data.columns) == ["date", "value", "source", "series_id", "series_name"]
    assert data["value"].notna().all()
    assert any("Dropped" in item for item in transformations)


def test_wide_shape_creates_series_columns(sample_result) -> None:
    data = sample_result.data.copy()
    second = data.iloc[0].copy()
    second["series_id"] = "OTHER"
    result2 = type(sample_result)(
        request=sample_result.request,
        data=pd.DataFrame([second]),
        metadata=sample_result.metadata,
    )
    options = ExportFormatOptions(output_shape="wide")
    wide, _ = prepare_export_data([sample_result, result2], options)
    assert "date" in wide.columns
    assert any("Bank of Canada:" in str(column) for column in wide.columns if column != "date")


def test_wide_shape_rejects_duplicate_date_series_key(sample_result) -> None:
    duplicate = sample_result.data.iloc[[0]].copy()
    duplicate.loc[duplicate.index[0], "value"] = 999999.0
    options = ExportFormatOptions(output_shape="wide")
    duplicate_result = type(sample_result)(sample_result.request, duplicate, sample_result.metadata)
    with pytest.raises(ExportError):
        prepare_export_data([sample_result, duplicate_result], options)


def test_preview_missing_numeric_values_are_nan_not_string(sample_result):
    from economic_data_exporter.services.preparation import prepare_export_data, preview_frame
    from economic_data_exporter.models import ExportFormatOptions

    result = sample_result
    result.data.loc[0, "value"] = float("nan")
    options = ExportFormatOptions()
    data, _ = prepare_export_data([result], options)
    preview = preview_frame(data, max_rows=10)
    assert pd.isna(preview.loc[0, "value"])
