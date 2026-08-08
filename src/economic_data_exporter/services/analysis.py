"""Explicit derived analysis that never mutates canonical raw observations."""

from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pandas as pd

from economic_data_exporter import __version__
from economic_data_exporter.exceptions import ValidationError


def descriptive_statistics(data: pd.DataFrame) -> pd.DataFrame:
    required = {"date", "value", "source", "series_id", "series_name", "geography"}
    if not required.issubset(data.columns):
        raise ValidationError("Data frame lacks required normalized columns.")
    frame = data.copy(deep=True)
    frame["value"] = pd.to_numeric(frame["value"], errors="coerce")
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    grouped = frame.groupby(["source", "series_id", "series_name", "geography"], dropna=False)
    rows: list[dict[str, object]] = []
    for keys, subset in grouped:
        values = subset["value"]
        rows.append(
            {
                "source": keys[0],
                "series_id": keys[1],
                "series_name": keys[2],
                "geography": keys[3],
                "observation_count": int(values.notna().sum()),
                "missing_value_count": int(values.isna().sum()),
                "minimum": values.min(),
                "maximum": values.max(),
                "mean": values.mean(),
                "median": values.median(),
                "standard_deviation": values.std(),
                "date_start": subset["date"].min(),
                "date_end": subset["date"].max(),
                "calculated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                "application_version": __version__,
            }
        )
    return pd.DataFrame(rows)


def growth_rate(data: pd.DataFrame, *, method: str, missing_policy: str = "preserve") -> pd.DataFrame:
    if method not in {"percent_change", "log_difference"}:
        raise ValidationError("Growth method must be percent_change or log_difference.")
    if missing_policy != "preserve":
        raise ValidationError("Only the preserve missing-data policy is supported.")
    frame = data.copy(deep=True)
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame["value"] = pd.to_numeric(frame["value"], errors="coerce")
    keys = ["source", "series_id", "geography"]
    frame.sort_values(keys + ["date"], inplace=True, kind="stable")
    grouped = frame.groupby(keys, dropna=False)["value"]
    if method == "percent_change":
        frame["derived_value"] = grouped.pct_change(fill_method=None) * 100.0
        formula = "100 * (x_t / x_(t-1) - 1)"
    else:
        if (frame["value"].dropna() <= 0).any():
            raise ValidationError("Log differences require strictly positive non-missing observations.")
        frame["derived_value"] = grouped.transform(lambda values: np.log(values).diff())
        formula = "ln(x_t) - ln(x_(t-1))"
    frame["transformation"] = formula
    frame["missing_data_policy"] = missing_policy
    frame["calculated_at"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    frame["application_version"] = __version__
    return frame


def correlation_matrix(data: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    frame = data.copy(deep=True)
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame["value"] = pd.to_numeric(frame["value"], errors="coerce")
    frame["key"] = frame["source"].astype(str) + ":" + frame["series_id"].astype(str) + ":" + frame["geography"].astype(str)
    wide = frame.pivot_table(index="date", columns="key", values="value", aggfunc="first")
    matrix = wide.corr(min_periods=2)
    overlap = wide.notna().astype(int).T.dot(wide.notna().astype(int))
    return matrix, overlap


def markov_regime_analysis(
    data: pd.DataFrame,
    *,
    bins: int = 3,
    series_key: tuple[str, str, str] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Explicit optional QuantEcon Markov-chain analysis on a copied derived series.

    The routine discretizes one selected series into empirical quantile regimes, estimates a
    transition matrix, and uses ``quantecon.MarkovChain`` only to calculate stationary
    distributions. It never writes to or mutates the raw input data.
    """
    if bins < 2 or bins > 10:
        raise ValidationError("Markov regime bins must be between 2 and 10.")
    try:
        from quantecon import MarkovChain
    except ImportError as exc:
        raise ValidationError(
            'QuantEcon is not installed. Install the optional analysis group with pip install -e ".[analysis]".'
        ) from exc

    required = {"source", "series_id", "geography", "date", "value"}
    if not required.issubset(data.columns):
        raise ValidationError("Data frame lacks required normalized columns.")
    frame = data.copy(deep=True)
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame["value"] = pd.to_numeric(frame["value"], errors="coerce")
    if series_key is None:
        unique = frame[["source", "series_id", "geography"]].drop_duplicates()
        if len(unique) != 1:
            raise ValidationError("Select exactly one source/series/geography for Markov analysis.")
        row = unique.iloc[0]
        series_key = (str(row["source"]), str(row["series_id"]), str(row["geography"]))
    source, series_id, geography = series_key
    selected = frame[
        (frame["source"].astype(str) == source)
        & (frame["series_id"].astype(str) == series_id)
        & (frame["geography"].astype(str) == geography)
    ].sort_values("date")
    values = selected["value"].dropna()
    if len(values) < max(10, bins * 3):
        raise ValidationError("Too few non-missing observations for stable regime estimation.")
    regimes = pd.qcut(values, q=bins, labels=False, duplicates="drop")
    actual_bins = int(regimes.max()) + 1
    if actual_bins < 2:
        raise ValidationError("Series has insufficient variation for multiple regimes.")
    counts = np.zeros((actual_bins, actual_bins), dtype="float64")
    regime_values = regimes.to_numpy(dtype="int64")
    for previous, current in zip(regime_values[:-1], regime_values[1:], strict=True):
        counts[previous, current] += 1.0
    row_totals = counts.sum(axis=1, keepdims=True)
    transition = np.divide(counts, row_totals, out=np.zeros_like(counts), where=row_totals != 0)
    for index in range(actual_bins):
        if row_totals[index, 0] == 0:
            transition[index, index] = 1.0
    chain = MarkovChain(transition)
    transition_frame = pd.DataFrame(
        transition,
        index=[f"regime_{index}" for index in range(actual_bins)],
        columns=[f"regime_{index}" for index in range(actual_bins)],
    )
    stationary = pd.DataFrame(
        chain.stationary_distributions,
        columns=[f"regime_{index}" for index in range(actual_bins)],
    )
    for output in (transition_frame, stationary):
        output.attrs.update(
            {
                "source_series": series_key,
                "method": "Empirical quantile discretization followed by quantecon.MarkovChain",
                "bins_requested": bins,
                "bins_realized": actual_bins,
                "missing_data_policy": "Drop missing values for optional derived analysis only",
                "calculated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                "application_version": __version__,
            }
        )
    return transition_frame, stationary
