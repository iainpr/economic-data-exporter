"""Canonical ingestion boundary for provider data.

Every provider response passes through this module before it becomes a
SourceResult. Provider-specific parsing belongs in the source adapter; shared
normalization, null handling, provenance, and primary-key validation belong
here.
"""

from __future__ import annotations

import re
from typing import Iterable

import pandas as pd

from economic_data_exporter.exceptions import ValidationError
from economic_data_exporter.models import PRIMARY_KEY_COLUMNS

# These are intentionally applied before numeric coercion. They cover common
# statistical-provider sentinels without treating zero as missing.
NULL_TOKENS = frozenset({"", "na", "n/a", "nan", "null", "none", "nil", "-99", "-999", "-9999", "..", "."})

# These columns are identifiers/control fields. Lowercasing them can change
# their meaning or make a provider request impossible (for example a
# case-sensitive series ID or URL), so their values are preserved.
IDENTIFIER_COLUMNS = frozenset({"source", "data_source", "series_id", "source_url", "retrieved_at"})
UPPERCASE_CODE_COLUMNS = frozenset({"geography"})


def canonical_column_name(value: object) -> str:
    text = str(value).strip().lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_")


def source_slug(source: str) -> str:
    text = canonical_column_name(source)
    return text or "unknown_source"


def standardize_nulls(frame: pd.DataFrame) -> pd.DataFrame:
    """Convert common textual missing-value sentinels to pd.NA."""

    out = frame.copy()
    for column in out.columns:
        if not (pd.api.types.is_object_dtype(out[column]) or pd.api.types.is_string_dtype(out[column])):
            continue
        values = out[column].astype("string")
        normalized = values.str.strip().str.casefold()
        out.loc[normalized.isin(NULL_TOKENS), column] = pd.NA
    return out


def standardize_strings(frame: pd.DataFrame) -> pd.DataFrame:
    """Normalize string values while preserving case-sensitive identifiers."""

    out = frame.copy()
    out.columns = [canonical_column_name(column) for column in out.columns]
    for column in out.columns:
        if column in IDENTIFIER_COLUMNS:
            continue
        if column in UPPERCASE_CODE_COLUMNS:
            out[column] = out[column].astype("string").str.strip().str.upper()
        elif pd.api.types.is_object_dtype(out[column]) or pd.api.types.is_string_dtype(out[column]):
            out[column] = out[column].astype("string").str.strip()
    return out


def standardize_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Apply deterministic schema, string, and null normalization at ingestion."""

    out = standardize_nulls(frame)
    out = standardize_strings(out)
    return out


def assert_primary_key_unique(frame: pd.DataFrame, *, context: str = "dataset") -> None:
    """Fail closed if the canonical observation key is not unique."""

    missing = [column for column in PRIMARY_KEY_COLUMNS if column not in frame.columns]
    if missing:
        raise ValidationError(f"{context} is missing primary-key columns: {', '.join(missing)}.")
    duplicate_mask = frame.duplicated(subset=list(PRIMARY_KEY_COLUMNS), keep=False)
    if duplicate_mask.any():
        duplicate_count = int(duplicate_mask.sum())
        sample = frame.loc[duplicate_mask, list(PRIMARY_KEY_COLUMNS)].head(3).to_dict("records")
        raise ValidationError(
            f"{context} violates the observation primary key {', '.join(PRIMARY_KEY_COLUMNS)}: "
            f"{duplicate_count:,} duplicate rows detected. Sample keys: {sample}"
        )


def canonicalize_observations(frame: pd.DataFrame, *, source: str) -> pd.DataFrame:
    """Canonicalize one provider's observation frame immediately after parsing."""

    out = standardize_frame(frame)
    out["source"] = source
    out["data_source"] = source_slug(source)
    if "geography" in out.columns:
        out["geography"] = out["geography"].fillna("").astype("string").str.strip().str.upper()
    if "date" in out.columns:
        out["date"] = pd.to_datetime(out["date"], errors="coerce")
    if "value" in out.columns:
        # Numeric conversion happens only after null-sentinel normalization.
        out["value"] = pd.to_numeric(out["value"], errors="coerce").astype("float64")
    return out


def assert_requests_unique(requests: Iterable[object]) -> None:
    """Prevent duplicate retrieval requests before any provider is called."""

    seen: set[tuple[object, ...]] = set()
    for request in requests:
        key = (
            getattr(request, "source", ""),
            getattr(request, "series_id", ""),
            getattr(request, "geography", ""),
            getattr(request, "frequency", ""),
            getattr(request, "start_date", None),
            getattr(request, "end_date", None),
        )
        if key in seen:
            raise ValidationError(
                "Duplicate export request detected for "
                f"{key[0]} / {key[1]} / {key[2] or 'no geography'} / "
                f"{key[4]} to {key[5]}. Remove the duplicate request before retrieval."
            )
        seen.add(key)
