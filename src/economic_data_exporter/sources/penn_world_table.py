"""Penn World Table official Dataverse download/import adapter."""

from __future__ import annotations

import re
from io import BytesIO
from typing import Any

import pandas as pd

from economic_data_exporter.exceptions import ParsingError
from economic_data_exporter.models import SeriesMetadata, SeriesRequest, SourceResult
from economic_data_exporter.sources.base import CancelCheck, DataSource, finish_result
from economic_data_exporter.utils.validation import validate_geography, validate_series_id


class PennWorldTableSource(DataSource):
    name = "Penn World Table"
    dataverse_base = "https://dataverse.nl"
    hosts = ("dataverse.nl",)
    persistent_id = "doi:10.34894/FABVLR"  # PWT 11.0, published by GGDC in 2025.
    dataset_page = "https://doi.org/10.34894/FABVLR"
    workbook_pattern = re.compile(r"^pwt\d+\.xlsx$", re.IGNORECASE)
    canonical_workbook = "pwt110.xlsx"

    def _official_workbook(self, *, ignore_cache: bool) -> tuple[bytes, str, bool, object]:
        metadata_response = self.client.get(
            f"{self.dataverse_base}/api/datasets/:persistentId/",
            trusted_hosts=self.hosts,
            params={"persistentId": self.persistent_id},
            expected_content_types=("json",),
            use_cache=not ignore_cache,
        )
        try:
            payload: dict[str, Any] = metadata_response.json()  # type: ignore[assignment]
            files = payload["data"]["latestVersion"]["files"]
            candidates = [
                entry["dataFile"]
                for entry in files
                if self.workbook_pattern.fullmatch(str(entry.get("label") or entry.get("dataFile", {}).get("filename", "")))
            ]
            canonical = [entry for entry in candidates if str(entry.get("filename", "")).casefold() == self.canonical_workbook]
            if len(canonical) == 1:
                file_info = canonical[0]
            elif len(candidates) == 1:
                file_info = candidates[0]
            else:
                raise ParsingError("Official PWT release does not expose one unambiguous main workbook; pwt110.xlsx was not uniquely found.")
            file_id = int(file_info["id"])
            filename = str(file_info["filename"])
        except (KeyError, TypeError, ValueError) as exc:
            if isinstance(exc, ParsingError):
                raise
            raise ParsingError("Penn World Table Dataverse metadata is malformed.") from exc
        download = self.client.get(
            f"{self.dataverse_base}/api/access/datafile/{file_id}",
            trusted_hosts=self.hosts,
            expected_content_types=(
                "spreadsheetml",
                "application/vnd.ms-excel",
                "application/octet-stream",
            ),
            use_cache=not ignore_cache,
        )
        return download.content, filename, metadata_response.from_cache and download.from_cache, download

    @staticmethod
    def _read_sheets(content: bytes) -> tuple[pd.DataFrame, pd.DataFrame]:
        try:
            excel = pd.ExcelFile(BytesIO(content), engine="openpyxl")
            data_name = next((name for name in excel.sheet_names if name.casefold() == "data"), excel.sheet_names[0])
            legend_name = next((name for name in excel.sheet_names if "legend" in name.casefold()), "")
            data = pd.read_excel(excel, sheet_name=data_name)
            legend = pd.read_excel(excel, sheet_name=legend_name) if legend_name else pd.DataFrame()
        except Exception as exc:
            raise ParsingError("Official PWT workbook could not be parsed.") from exc
        return data, legend

    @staticmethod
    def _legend_map(legend: pd.DataFrame) -> dict[str, str]:
        if legend.empty:
            return {}
        columns = {str(column).casefold(): str(column) for column in legend.columns}
        variable_column = next(
            (original for folded, original in columns.items() if "variable" in folded and "name" in folded),
            str(legend.columns[0]),
        )
        description_column = next(
            (original for folded, original in columns.items() if "definition" in folded or "description" in folded),
            str(legend.columns[min(1, len(legend.columns) - 1)]),
        )
        mapping: dict[str, str] = {}
        for _, row in legend.iterrows():
            key = str(row.get(variable_column, "")).strip()
            value = str(row.get(description_column, "")).strip()
            if key and key.lower() != "nan":
                mapping[key] = "" if value.lower() == "nan" else value
        return mapping

    def search(self, query: str, *, options: dict[str, object] | None = None) -> list[SeriesMetadata]:
        content, filename, _, _ = self._official_workbook(
            ignore_cache=bool((options or {}).get("ignore_cache"))
        )
        data, legend = self._read_sheets(content)
        definitions = self._legend_map(legend)
        excluded = {"countrycode", "country", "currency_unit", "year"}
        needle = query.casefold().strip()
        results: list[SeriesMetadata] = []
        for column in data.columns:
            variable = str(column)
            if variable.casefold() in excluded:
                continue
            description = definitions.get(variable, "")
            if needle and needle not in f"{variable} {description}".casefold():
                continue
            results.append(
                SeriesMetadata(
                    source=self.name,
                    series_id=variable,
                    name=description or variable,
                    frequency="Annual",
                    notes=f"Imported from official {filename} release workbook.",
                    source_url=self.dataset_page,
                    attribution="Groningen Growth and Development Centre, Penn World Table 11.0.",
                    license_text="CC BY 4.0; cite the PWT 11.0 dataset as instructed by GGDC/Dataverse.",
                )
            )
            if len(results) >= 100:
                break
        return results

    def fetch(self, request: SeriesRequest, *, cancel: CancelCheck) -> SourceResult:
        variable = validate_series_id(request.series_id, source=self.name)
        geography = validate_geography(request.geography, required=True)
        cancel()
        content, filename, from_cache, download = self._official_workbook(
            ignore_cache=bool(request.options.get("ignore_cache"))
        )
        cancel()
        data, legend = self._read_sheets(content)
        required = {"countrycode", "year", variable}
        missing = required - {str(column) for column in data.columns}
        if missing:
            raise ParsingError(f"PWT workbook does not contain required columns: {', '.join(sorted(missing))}.")
        selected = data[
            (data["countrycode"].astype(str).str.upper() == geography)
            & (pd.to_numeric(data["year"], errors="coerce") >= request.start_date.year)
            & (pd.to_numeric(data["year"], errors="coerce") <= request.end_date.year)
        ].copy()
        definitions = self._legend_map(legend)
        country_name = ""
        if not selected.empty and "country" in selected.columns:
            country_name = str(selected.iloc[0]["country"])
        metadata = SeriesMetadata(
            source=self.name,
            series_id=variable,
            name=definitions.get(variable, variable),
            geography=country_name or geography,
            frequency="Annual",
            units="See PWT variable definition",
            notes=f"Raw observations imported from official {filename}; no transformation or resampling applied.",
            source_url=self.dataset_page,
            attribution="Groningen Growth and Development Centre, Penn World Table 11.0.",
            license_text="CC BY 4.0; cite the PWT 11.0 dataset as instructed by GGDC/Dataverse.",
        )
        return finish_result(
            request=request,
            metadata=metadata,
            dates=pd.to_datetime(selected["year"].astype("Int64").astype(str) + "-01-01", errors="coerce"),
            values=selected[variable],
            geographies=country_name or geography,
            retrieved_at=download.retrieved_at,
            from_cache=from_cache,
        )
