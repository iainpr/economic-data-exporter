"""Shared SDMX 2.1 retrieval for providers with documented REST services.

Provider adapters supply their official SDMX base URL and the provider-specific
flow/key syntax. No provider web pages are scraped.
"""

from __future__ import annotations

from io import StringIO
from xml.etree import ElementTree as ET

import pandas as pd

from economic_data_exporter.exceptions import ParsingError
from economic_data_exporter.models import SeriesMetadata, SeriesRequest, SourceResult
from economic_data_exporter.sources.base import CancelCheck, DataSource, finish_result
from economic_data_exporter.utils.validation import validate_series_id

_DOCTYPE_MARKER = b"<!DOCTYPE"


class SDMXSource(DataSource):
    base_url: str
    hosts: tuple[str, ...]
    source_url: str
    attribution: str
    license_text: str
    id_help: str = "Use the provider's dataflow reference followed by | and an SDMX key."

    def _parse_id(self, series_id: str) -> tuple[str, str]:
        if "|" not in series_id:
            raise ValueError(f"{self.name} series IDs must use DATAFLOW|KEY syntax. {self.id_help}")
        flow, key = series_id.split("|", 1)
        if not flow.strip() or not key.strip():
            raise ValueError("SDMX dataflow and key must both be supplied.")
        return flow.strip(), key.strip()

    def search(
        self, query: str, *, options: dict[str, object] | None = None
    ) -> list[SeriesMetadata]:
        q = query.casefold().strip()
        if "|" in query:
            flow, key = self._parse_id(query.strip())
            return [
                SeriesMetadata(
                    source=self.name,
                    series_id=f"{flow}|{key}",
                    name=query.strip(),
                    source_url=self.source_url,
                    attribution=self.attribution,
                    license_text=self.license_text,
                )
            ]
        response = self.client.get(
            f"{self.base_url}/dataflow/all/all/latest",
            trusted_hosts=self.hosts,
            params={"format": "csvfilewithlabels"},
            expected_content_types=("csv", "text/plain", "octet-stream"),
            use_cache=not bool((options or {}).get("ignore_cache")),
        )
        try:
            frame = pd.read_csv(StringIO(response.text))
        except Exception as exc:
            raise ParsingError(
                f"{self.name} dataflow catalogue was not a readable CSV response."
            ) from exc
        if frame.empty:
            return []
        text = frame.fillna("").astype(str)
        mask = (
            text.apply(lambda row: q in " ".join(row.tolist()).casefold(), axis=1)
            if q
            else pd.Series(True, index=frame.index)
        )
        results: list[SeriesMetadata] = []
        for _, row in frame.loc[mask].head(100).iterrows():
            agency = str(row.get("AGENCY_ID", row.get("agencyID", ""))).strip()
            flow = str(row.get("ID", row.get("id", row.get("DATAFLOW_ID", "")))).strip()
            version = str(row.get("VERSION", row.get("version", "latest"))).strip() or "latest"
            label = str(row.get("NAME", row.get("name", flow))).strip()
            if not flow:
                continue
            flow_ref = f"{agency},{flow},{version}"
            results.append(
                SeriesMetadata(
                    source=self.name,
                    series_id=f"{flow_ref}|",
                    name=label,
                    notes=self.id_help,
                    source_url=self.source_url,
                    attribution=self.attribution,
                    license_text=self.license_text,
                    extra={"selectable": False},
                )
            )
        return results

    def _csv_data(self, response_text: str) -> pd.DataFrame:
        try:
            frame = pd.read_csv(StringIO(response_text))
        except Exception as exc:
            raise ParsingError(f"{self.name} SDMX CSV response could not be parsed.") from exc
        if frame.empty:
            return frame
        value_col = next(
            (
                c
                for c in frame.columns
                if str(c).upper() in {"OBS_VALUE", "OBS_VALUE_LABEL", "VALUE"}
            ),
            None,
        )
        time_col = next(
            (c for c in frame.columns if str(c).upper() in {"TIME_PERIOD", "TIME"}), None
        )
        if value_col is None or time_col is None:
            raise ParsingError(f"{self.name} SDMX response lacks TIME_PERIOD/OBS_VALUE columns.")
        geography_col = next(
            (
                c
                for c in frame.columns
                if str(c).upper() in {"REF_AREA", "REF_AREA_LABEL", "GEO", "GEO_LABEL"}
            ),
            None,
        )
        out = pd.DataFrame(
            {
                "date": pd.to_datetime(frame[time_col], errors="coerce"),
                "value": pd.to_numeric(frame[value_col], errors="coerce"),
            }
        )
        out["geography"] = frame[geography_col].astype(str) if geography_col else ""
        return out

    def _xml_data(self, content: bytes) -> pd.DataFrame:
        if _DOCTYPE_MARKER in content[:1024].lstrip().upper():
            raise ParsingError(
                f"{self.name} SDMX XML response was rejected because it declares a DOCTYPE."
            )
        try:
            root = ET.fromstring(content)
        except ET.ParseError as exc:
            raise ParsingError(f"{self.name} SDMX XML response is malformed.") from exc
        rows: list[dict[str, object]] = []
        for series in root.iter():
            if not series.tag.endswith("Series"):
                continue
            geo = ""
            for child in series:
                if child.tag.endswith("SeriesKey"):
                    for dimension in child:
                        if dimension.attrib.get("id", "").upper() in {"REF_AREA", "GEO"}:
                            geo = dimension.attrib.get("value", "")
                if child.tag.endswith("Obs"):
                    obs_time = obs_value = None
                    for attr, attr_value in child.attrib.items():
                        if attr.endswith("TIME_PERIOD"):
                            obs_time = attr_value
                        elif attr.endswith("OBS_VALUE"):
                            obs_value = attr_value
                    if obs_time is not None:
                        rows.append({"date": obs_time, "value": obs_value, "geography": geo})
        if not rows:
            raise ParsingError(f"{self.name} SDMX XML response contained no observations.")
        out = pd.DataFrame(rows)
        out["date"] = pd.to_datetime(out["date"], errors="coerce")
        out["value"] = pd.to_numeric(out["value"], errors="coerce")
        return out

    def fetch(self, request: SeriesRequest, *, cancel: CancelCheck) -> SourceResult:
        series_id = validate_series_id(request.series_id, source=self.name)
        flow, key = self._parse_id(series_id)
        cancel()
        response = self.client.get(
            f"{self.base_url}/data/{flow}/{key}",
            trusted_hosts=self.hosts,
            params={
                "startPeriod": request.start_date.isoformat(),
                "endPeriod": request.end_date.isoformat(),
                "dimensionAtObservation": "AllDimensions",
                "format": "csvfilewithlabels",
            },
            expected_content_types=("csv", "xml", "text/plain", "octet-stream"),
            use_cache=not bool(request.options.get("ignore_cache")),
        )
        try:
            if "xml" in response.headers.get(
                "Content-Type", ""
            ).lower() or response.text.lstrip().startswith("<"):
                frame = self._xml_data(response.content)
            else:
                frame = self._csv_data(response.text)
        except ParsingError:
            raise
        if frame.empty:
            raise ParsingError(f"{self.name} returned no observations for {series_id}.")
        metadata = SeriesMetadata(
            source=self.name,
            series_id=series_id,
            name=series_id,
            geography=request.geography,
            frequency=request.frequency,
            source_url=self.source_url,
            attribution=self.attribution,
            license_text=self.license_text,
            notes="Retrieved through the provider's documented SDMX REST service; no "
            "resampling or unit conversion applied.",
        )
        return finish_result(
            request=request,
            metadata=metadata,
            dates=frame["date"],
            values=frame["value"],
            geographies=frame["geography"],
            retrieved_at=response.retrieved_at,
            from_cache=response.from_cache,
        )
