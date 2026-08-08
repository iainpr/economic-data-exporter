"""Our World in Data Grapher Chart API adapter."""

from __future__ import annotations

from io import BytesIO
from typing import Any

import pandas as pd

from economic_data_exporter.exceptions import ParsingError
from economic_data_exporter.models import SeriesMetadata, SeriesRequest, SourceResult
from economic_data_exporter.sources.base import CancelCheck, DataSource, finish_result
from economic_data_exporter.utils.validation import validate_series_id


class OwidSource(DataSource):
    name = "Our World in Data"
    base_url = "https://ourworldindata.org/grapher"
    hosts = ("ourworldindata.org",)

    def _metadata(self, slug: str, *, ignore_cache: bool = False) -> tuple[dict[str, Any], object]:
        response = self.client.get(
            f"{self.base_url}/{slug}.metadata.json",
            trusted_hosts=self.hosts,
            expected_content_types=("json",),
            use_cache=not ignore_cache,
        )
        try:
            payload: dict[str, Any] = response.json()  # type: ignore[assignment]
        except (TypeError, ValueError) as exc:
            raise ParsingError("OWID chart metadata is malformed.") from exc
        return payload, response

    def search(
        self, query: str, *, options: dict[str, object] | None = None
    ) -> list[SeriesMetadata]:
        # Exact chart-slug lookup is stable and documented. Broad OWID search APIs are
        # marked active-development.
        slug = validate_series_id(query, source=self.name)
        payload, _ = self._metadata(slug, ignore_cache=bool((options or {}).get("ignore_cache")))
        chart = payload.get("chart") or {}
        columns = payload.get("columns") or {}
        results: list[SeriesMetadata] = []
        for column_id, item in columns.items():
            results.append(
                SeriesMetadata(
                    source=self.name,
                    series_id=slug,
                    name=str(
                        item.get("titleShort")
                        or item.get("title")
                        or chart.get("title")
                        or column_id
                    ),
                    frequency=str(item.get("timespan") or "Chart-defined"),
                    units=str(item.get("unit") or item.get("shortUnit") or ""),
                    notes=str(
                        item.get("descriptionShort")
                        or item.get("description")
                        or chart.get("subtitle")
                        or ""
                    ),
                    source_url=f"{self.base_url}/{slug}",
                    attribution=str(
                        item.get("citationFull")
                        or chart.get("citation")
                        or "Our World in Data and underlying provider"
                    ),
                    license_text="OWID-produced data is CC BY; third-party source "
                    "licenses shown in chart metadata also apply.",
                    extra={"column_id": column_id},
                )
            )
        if not results:
            results.append(
                SeriesMetadata(
                    source=self.name,
                    series_id=slug,
                    name=str(chart.get("title") or slug),
                    source_url=f"{self.base_url}/{slug}",
                    attribution=str(
                        chart.get("citation") or "Our World in Data and underlying provider"
                    ),
                    license_text="OWID-produced data is CC BY; third-party source "
                    "licenses shown in chart metadata also apply.",
                )
            )
        return results

    def fetch(self, request: SeriesRequest, *, cancel: CancelCheck) -> SourceResult:
        slug = validate_series_id(request.series_id, source=self.name)
        ignore_cache = bool(request.options.get("ignore_cache"))
        cancel()
        metadata_payload, metadata_response = self._metadata(slug, ignore_cache=ignore_cache)
        cancel()
        params: dict[str, object] = {"csvType": "full", "useColumnShortNames": "true"}
        response = self.client.get(
            f"{self.base_url}/{slug}.csv",
            trusted_hosts=self.hosts,
            params=params,
            expected_content_types=("csv", "text/plain", "application/octet-stream"),
            use_cache=not ignore_cache,
        )
        cancel()
        try:
            wide = pd.read_csv(BytesIO(response.content))
        except Exception as exc:  # pandas parser exceptions vary by version
            raise ParsingError("OWID chart CSV could not be parsed.") from exc
        time_column = "Year" if "Year" in wide.columns else "Day" if "Day" in wide.columns else None
        if time_column is None or "Entity" not in wide.columns:
            raise ParsingError("OWID chart CSV lacks Entity and Year/Day columns.")
        id_columns = [
            column for column in ("Entity", "Code", time_column) if column in wide.columns
        ]
        value_columns = [column for column in wide.columns if column not in id_columns]
        requested_column = str(request.options.get("column") or "")
        if requested_column:
            if requested_column not in value_columns:
                raise ParsingError(
                    f"OWID data column '{requested_column}' is not present in this chart."
                )
            value_columns = [requested_column]
        if not value_columns:
            raise ParsingError("OWID chart contains no data columns.")
        if len(value_columns) > 1:
            raise ParsingError(
                "OWID chart contains multiple data columns. Use Validate slug metadata "
                "and select one column explicitly."
            )
        long = wide.melt(
            id_vars=id_columns, value_vars=value_columns, var_name="column", value_name="value"
        )
        geography_filter = request.geography.strip()
        if geography_filter:
            code_match = (
                long.get("Code", pd.Series(index=long.index, dtype="object"))
                .astype(str)
                .str.upper()
                == geography_filter.upper()
            )
            name_match = long["Entity"].astype(str).str.casefold() == geography_filter.casefold()
            long = long[code_match | name_match]
        if time_column == "Year":
            long["date"] = pd.to_datetime(
                long[time_column].astype("Int64").astype(str) + "-01-01", errors="coerce"
            )
        else:
            long["date"] = pd.to_datetime(long[time_column], errors="coerce")
        start = pd.Timestamp(request.start_date)
        end = pd.Timestamp(request.end_date)
        long = long[(long["date"] >= start) & (long["date"] <= end)]
        chart = metadata_payload.get("chart") or {}
        columns_meta = metadata_payload.get("columns") or {}
        column_names = ", ".join(value_columns)
        units = sorted(
            {str((columns_meta.get(column) or {}).get("unit") or "") for column in value_columns}
            - {""}
        )
        citations = sorted(
            {
                str((columns_meta.get(column) or {}).get("citationFull") or "")
                for column in value_columns
            }
            - {""}
        )
        selected_meta = columns_meta.get(value_columns[0]) or {}
        metadata = SeriesMetadata(
            source=self.name,
            series_id=slug,
            name=str(
                selected_meta.get("titleShort")
                or selected_meta.get("title")
                or chart.get("title")
                or column_names
                or slug
            ),
            geography=geography_filter,
            frequency="Annual" if time_column == "Year" else "Daily/chart-defined",
            units="; ".join(units),
            notes=str(chart.get("subtitle") or "")
            + (f" Columns: {column_names}." if len(value_columns) > 1 else ""),
            source_url=f"{self.base_url}/{slug}",
            attribution="; ".join(citations)
            or str(chart.get("citation") or "Our World in Data and underlying provider"),
            license_text="OWID-produced data is CC BY; third-party source licenses "
            "shown in chart metadata also apply.",
        )
        return finish_result(
            request=request,
            metadata=metadata,
            dates=long["date"],
            values=long["value"],
            geographies=long["Entity"].astype(str),
            retrieved_at=response.retrieved_at,
            from_cache=response.from_cache and getattr(metadata_response, "from_cache", False),
        )
