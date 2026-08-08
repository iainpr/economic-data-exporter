"""Derived export preparation used by the preview/clean workflow."""

from __future__ import annotations

import pandas as pd

from economic_data_exporter.exceptions import ExportError, ValidationError
from economic_data_exporter.models import DATA_COLUMNS, ExportFormatOptions, SourceResult
from economic_data_exporter.services.ingestion import assert_primary_key_unique


def _combined_raw_data(results: list[SourceResult]) -> pd.DataFrame:
    frames = [result.normalized() for result in results]
    if not frames:
        return pd.DataFrame(columns=DATA_COLUMNS)
    combined = pd.concat(frames, ignore_index=True, copy=False)
    combined["date"] = pd.to_datetime(combined["date"], errors="coerce")
    try:
        assert_primary_key_unique(combined, context="Combined ingestion dataset")
    except ValidationError as exc:
        raise ExportError(str(exc)) from exc
    return combined


def _series_key(frame: pd.DataFrame) -> pd.Series:
    geography = frame["geography"].fillna("").astype(str)
    return (
        frame["source"].fillna("").astype(str)
        + ":"
        + frame["series_id"].fillna("").astype(str)
        + geography.map(lambda value: f":{value}" if value else "")
    )


def clean_combined_data(
    results: list[SourceResult],
    *,
    remove_duplicate_rows: bool,
    drop_missing_values: bool,
    sort_by_date: bool,
) -> tuple[pd.DataFrame, list[str]]:
    """Combine and clean raw results, independent of output shape/column selection.

    This is the expensive half of export preparation (concat, dedupe, sort). It is
    split out from column/shape selection so callers that only change which
    columns or shape to display (e.g. the preview dialog) can reuse this result
    instead of recomputing it.
    """

    frame = _combined_raw_data(results)
    transformations: list[str] = []

    if frame.empty:
        raise ExportError("No successful observations are available for export.")

    if frame["date"].isna().any():
        raise ExportError("Export preparation found invalid observation dates.")

    if remove_duplicate_rows:
        before = len(frame)
        frame = frame.drop_duplicates(keep="first").reset_index(drop=True)
        removed = before - len(frame)
        transformations.append(
            f"Removed {removed:,} exact duplicate rows."
            if removed
            else "Checked for exact duplicate rows; none removed."
        )

    if drop_missing_values:
        before = len(frame)
        frame = frame.loc[frame["value"].notna()].copy()
        removed = before - len(frame)
        transformations.append(
            f"Dropped {removed:,} rows with missing values."
            if removed
            else "Dropped rows with missing values; none were present."
        )
    else:
        transformations.append("Missing values preserved explicitly.")

    if sort_by_date:
        frame.sort_values(["date", "source", "series_id", "geography"], inplace=True, kind="stable")
        frame.reset_index(drop=True, inplace=True)
        transformations.append("Sorted observations by date, source, series ID, and geography.")

    return frame, transformations


def shape_output(
    frame: pd.DataFrame,
    options: ExportFormatOptions,
    transformations: list[str],
) -> tuple[pd.DataFrame, list[str]]:
    """Select columns (long) or pivot (wide) a cleaned frame from clean_combined_data."""

    transformations = list(transformations)
    if options.output_shape == "long":
        export_columns = [column for column in options.columns if column in frame.columns]
        selected = frame[export_columns].copy()
        transformations.append(
            f"Exported tidy long format with columns: {', '.join(export_columns)}."
        )
        return selected, transformations

    keys = _series_key(frame)
    duplicate_keys = frame.assign(_series_key=keys).duplicated(
        subset=["date", "_series_key"], keep=False
    )
    if duplicate_keys.any():
        raise ExportError(
            "Wide output cannot represent multiple observations for the same date and "
            "source/series/geography key. Use long format or narrow the selection."
        )
    wide_source = frame.assign(_series_key=keys)
    wide = wide_source.pivot(index="date", columns="_series_key", values="value").reset_index()
    wide.columns.name = None
    transformations.append(
        "Pivoted observations to wide format with one value column per source/series/geography key."
    )
    return wide, transformations


def prepare_export_data(
    results: list[SourceResult],
    options: ExportFormatOptions,
) -> tuple[pd.DataFrame, list[str]]:
    """Return a derived export frame and an auditable list of transformations."""

    frame, transformations = clean_combined_data(
        results,
        remove_duplicate_rows=options.remove_duplicate_rows,
        drop_missing_values=options.drop_missing_values,
        sort_by_date=options.sort_by_date,
    )
    return shape_output(frame, options, transformations)


def preview_frame(data: pd.DataFrame, *, max_rows: int) -> pd.DataFrame:
    """Create a bounded, display-friendly preview without mutating the source frame."""

    return data.head(max_rows).copy(deep=True)
