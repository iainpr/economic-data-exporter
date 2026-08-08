"""Input and normalized-data validation."""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import pandas as pd

from economic_data_exporter.exceptions import ValidationError

SAFE_ID = re.compile(r"^[A-Za-z0-9_.:/#?=&%+~-]{1,250}$")
COUNTRY_CODE = re.compile(r"^[A-Za-z0-9]{2,5}$")
OWID_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,199}$")
PWT_VARIABLE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")
GEOGRAPHY_REQUIRED_SOURCES = frozenset({"World Bank", "Penn World Table", "IMF"})


def validate_date_range(start_date: date, end_date: date) -> None:
    if start_date > end_date:
        raise ValidationError("Start date must be on or before end date.")
    if start_date.year < 1600 or end_date.year > 2200:
        raise ValidationError("Date range is outside the supported validation bounds.")


def split_series_ids(value: str) -> list[str]:
    """Parse comma-, semicolon-, or newline-separated IDs while preserving order."""

    parts = re.split(r"[,;\n]+", value)
    result: list[str] = []
    seen: set[str] = set()
    for part in parts:
        cleaned = part.strip()
        if cleaned and cleaned not in seen:
            result.append(cleaned)
            seen.add(cleaned)
    if not result:
        raise ValidationError("Enter at least one series or indicator ID.")
    return result


def validate_series_id(value: str, *, source: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValidationError("Series or indicator ID is required.")
    if source == "Our World in Data":
        if not OWID_SLUG.fullmatch(cleaned):
            raise ValidationError("OWID identifiers must be chart slugs containing lowercase letters, numbers, and hyphens.")
    elif source == "Penn World Table":
        if not PWT_VARIABLE.fullmatch(cleaned):
            raise ValidationError("PWT variable names may contain letters, numbers, and underscores.")
    elif not SAFE_ID.fullmatch(cleaned):
        raise ValidationError("Series ID contains unsupported characters.")
    return cleaned


def validate_geography(value: str, *, required: bool = False) -> str:
    cleaned = value.strip().upper()
    if required and not cleaned:
        raise ValidationError("A country or geography code is required for this source.")
    if cleaned and not COUNTRY_CODE.fullmatch(cleaned):
        raise ValidationError("Geography must be a 2- to 5-character code.")
    return cleaned


def validate_output_path(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    if resolved.suffix.lower() != ".xlsx":
        raise ValidationError("Output file must use the .xlsx extension.")
    if not resolved.parent.exists() or not resolved.parent.is_dir():
        raise ValidationError("Output directory does not exist.")
    if resolved.exists() and resolved.is_dir():
        raise ValidationError("Output path points to a directory.")
    return resolved


def validate_observations(frame: pd.DataFrame, *, max_records: int) -> list[str]:
    warnings: list[str] = []
    required = {"date", "value"}
    if not required.issubset(frame.columns):
        raise ValidationError("Normalized observations are missing date or value columns.")
    if len(frame) > max_records:
        raise ValidationError(f"Job exceeds the configured {max_records:,}-record limit.")
    if frame.empty:
        warnings.append("No observations exist for the requested range.")
        return warnings
    if frame["date"].isna().any():
        raise ValidationError("One or more observation dates could not be parsed.")
    duplicates = frame.duplicated(subset=["date", "series_id", "geography"], keep=False)
    if duplicates.any():
        raise ValidationError("Provider response contains duplicate observations for the same date and series.")
    ordered = frame.sort_values("date")["date"]
    if not ordered.is_monotonic_increasing:
        warnings.append("Observations were sorted by date during normalization.")
    if frame["value"].isna().any():
        warnings.append("Provider missing values were preserved explicitly.")
    return warnings
