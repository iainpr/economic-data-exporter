"""Provider adapters that use compact official APIs alongside the shared SDMX layer."""

from __future__ import annotations

import threading
from io import StringIO

import pandas as pd

from economic_data_exporter import __version__
from economic_data_exporter.exceptions import ParsingError
from economic_data_exporter.models import SeriesMetadata, SeriesRequest, SourceResult
from economic_data_exporter.network import HttpClient
from economic_data_exporter.sources.base import CancelCheck, DataSource, finish_result
from economic_data_exporter.sources.sdmx import SDMXSource
from economic_data_exporter.utils.validation import validate_series_id


class StatisticsCanadaSource(DataSource):
    name = "Statistics Canada"
    base_url = "https://www150.statcan.gc.ca/t1/wds/rest"
    hosts = ("www150.statcan.gc.ca",)
    source_url = "https://www.statcan.gc.ca/en/developers/wds"

    def search(
        self, query: str, *, options: dict[str, object] | None = None
    ) -> list[SeriesMetadata]:
        q = query.strip().lstrip("Vv")
        if not q.isdigit():
            return []
        response = self.client.post_json(
            f"{self.base_url}/getSeriesInfoFromVector",
            trusted_hosts=self.hosts,
            payload=[{"vectorId": int(q)}],
        )
        payload = response.json()
        obj = payload[0].get("object", {}) if isinstance(payload, list) and payload else {}
        title = str(obj.get("SeriesTitleEn", f"Vector {q}"))
        return [
            SeriesMetadata(
                source=self.name,
                series_id=f"V{q}",
                name=title,
                frequency=str(obj.get("frequencyCode", "")),
                source_url=self.source_url,
                attribution="Statistics Canada",
                license_text="Statistics Canada Open Licence Agreement.",
            )
        ]

    def fetch(self, request: SeriesRequest, *, cancel: CancelCheck) -> SourceResult:
        sid = validate_series_id(request.series_id, source=self.name)
        vector = sid.lstrip("Vv")
        if not vector.isdigit():
            raise ValueError("Statistics Canada identifiers must be vector IDs such as V123456789.")
        cancel()
        response = self.client.get(
            f"{self.base_url}/getDataFromVectorByReferencePeriodRange",
            trusted_hosts=self.hosts,
            params={
                "vectorIds": f'"{vector}"',
                "startRefPeriod": request.start_date.isoformat(),
                "endReferencePeriod": request.end_date.isoformat(),
            },
            expected_content_types=("json",),
        )
        payload = response.json()
        objects = payload.get("object", []) if isinstance(payload, dict) else []
        if not objects:
            raise ParsingError(
                "Statistics Canada returned no observations for the requested vector and period."
            )
        obj = objects[0] if isinstance(objects, list) else objects
        points = obj.get("vectorDataPoint", [])
        if not points:
            raise ParsingError("Statistics Canada returned an empty vector.")
        metadata_info = self.search(vector)
        metadata = (
            metadata_info[0]
            if metadata_info
            else SeriesMetadata(
                source=self.name,
                series_id=f"V{vector}",
                name=f"Statistics Canada vector V{vector}",
                source_url=self.source_url,
                attribution="Statistics Canada",
                license_text="See Statistics Canada data terms and conditions.",
            )
        )
        dates = pd.to_datetime([point.get("refPer") for point in points], errors="coerce")
        values = [point.get("value") for point in points]
        return finish_result(
            request=request,
            metadata=metadata,
            dates=pd.Series(dates),
            values=pd.Series(values),
            geographies=request.geography,
            retrieved_at=response.retrieved_at,
            from_cache=response.from_cache,
        )


class IMFSource(DataSource):
    name = "IMF"
    base_url = "https://www.imf.org/external/datamapper/api/v2"
    hosts = ("www.imf.org",)
    source_url = "https://www.imf.org/external/datamapper/api/"

    def __init__(self, client: HttpClient) -> None:
        super().__init__(client)
        self._catalogue_lock = threading.Lock()
        self._catalogue: dict[str, object] | None = None

    def _indicator_catalogue(self, *, ignore_cache: bool) -> dict[str, object]:
        # The full indicator catalogue is fetched and JSON-decoded here at most
        # once per adapter instance (unless a refresh is explicitly requested);
        # search() and fetch() both look it up from memory afterward instead of
        # each re-fetching and re-parsing it independently.
        with self._catalogue_lock:
            if self._catalogue is not None and not ignore_cache:
                return self._catalogue
            response = self.client.get(
                f"{self.base_url}/indicators",
                trusted_hosts=self.hosts,
                expected_content_types=("json",),
                use_cache=not ignore_cache,
            )
            payload = response.json()
            indicators = payload.get("indicators", {}) if isinstance(payload, dict) else {}
            self._catalogue = indicators
            return indicators

    def search(
        self, query: str, *, options: dict[str, object] | None = None
    ) -> list[SeriesMetadata]:
        indicators = self._indicator_catalogue(
            ignore_cache=bool((options or {}).get("ignore_cache"))
        )
        q = query.casefold().strip()
        out: list[SeriesMetadata] = []
        for code, info in indicators.items():
            label = str(info.get("label", code)) if isinstance(info, dict) else str(info)
            if q in f"{code} {label}".casefold():
                out.append(
                    SeriesMetadata(
                        source=self.name,
                        series_id=code,
                        name=label,
                        frequency="Annual",
                        source_url=self.source_url,
                        attribution="International Monetary Fund, DataMapper",
                        license_text="See IMF data terms.",
                    )
                )
            if len(out) >= 100:
                break
        return out

    def fetch(self, request: SeriesRequest, *, cancel: CancelCheck) -> SourceResult:
        indicator = validate_series_id(request.series_id, source=self.name)
        geo = request.geography.strip().upper()
        if not geo:
            raise ValueError(
                "IMF DataMapper retrieval requires a country, region, or group code in Geography."
            )
        cancel()
        ignore_cache = bool(request.options.get("ignore_cache"))
        response = self.client.get(
            f"{self.base_url}/{indicator}/{geo}",
            trusted_hosts=self.hosts,
            params={
                "periods": ",".join(
                    str(year) for year in range(request.start_date.year, request.end_date.year + 1)
                )
            },
            expected_content_types=("json",),
            use_cache=not ignore_cache,
        )
        payload = response.json()
        values = payload.get("values", {}) if isinstance(payload, dict) else {}
        series = values.get(indicator, {}).get(geo, {}) if isinstance(values, dict) else {}
        if not series:
            raise ParsingError(f"IMF returned no observations for {indicator} / {geo}.")
        catalogue = self._indicator_catalogue(ignore_cache=ignore_cache)
        info = catalogue.get(indicator)
        label = str(info.get("label", indicator)) if isinstance(info, dict) else indicator
        metadata = SeriesMetadata(
            source=self.name,
            series_id=indicator,
            name=label,
            frequency="Annual",
            source_url=self.source_url,
            attribution="International Monetary Fund, DataMapper",
            license_text="See IMF data terms.",
        )
        dates = pd.to_datetime([f"{year}-01-01" for year in series], errors="coerce")
        vals = pd.Series(list(series.values()))
        return finish_result(
            request=request,
            metadata=metadata,
            dates=pd.Series(dates),
            values=vals,
            geographies=geo,
            retrieved_at=response.retrieved_at,
            from_cache=response.from_cache,
        )


class ILOStatSource(DataSource):
    name = "ILOSTAT"
    base_url = "https://rplumber.ilo.org/data/indicator/"
    hosts = ("rplumber.ilo.org",)
    source_url = "https://ilostat.ilo.org/data/"

    def search(
        self, query: str, *, options: dict[str, object] | None = None
    ) -> list[SeriesMetadata]:
        code = query.strip()
        if not code:
            return []
        try:
            response = self.client.get(
                self.base_url,
                trusted_hosts=self.hosts,
                params={"id": code, "lang": "en", "type": "label", "format": ".csv"},
                expected_content_types=("csv", "text/plain"),
                use_cache=not bool((options or {}).get("ignore_cache")),
            )
            frame = pd.read_csv(StringIO(response.text))
            label = str(frame.iloc[0].get("indicator.label", code)) if not frame.empty else code
        except Exception:
            label = code
        return [
            SeriesMetadata(
                source=self.name,
                series_id=code,
                name=label,
                source_url=self.source_url,
                attribution="International Labour Organization, ILOSTAT",
                license_text="See ILOSTAT terms of use.",
            )
        ]

    def fetch(self, request: SeriesRequest, *, cancel: CancelCheck) -> SourceResult:
        code = validate_series_id(request.series_id, source=self.name)
        params: dict[str, object] = {
            "id": code,
            "lang": "en",
            "type": "label",
            "format": ".csv",
            "timefrom": str(request.start_date.year),
            "timeto": str(request.end_date.year),
        }
        if request.geography:
            params["ref_area"] = request.geography.upper()
        cancel()
        response = self.client.get(
            self.base_url,
            trusted_hosts=self.hosts,
            params=params,
            expected_content_types=("csv", "text/plain"),
            use_cache=not bool(request.options.get("ignore_cache")),
        )
        try:
            frame = pd.read_csv(StringIO(response.text))
        except Exception as exc:
            raise ParsingError("ILOSTAT response was not valid CSV.") from exc
        if frame.empty:
            raise ParsingError("ILOSTAT returned no observations.")
        if "time" not in frame or "obs_value" not in frame:
            raise ParsingError("ILOSTAT response lacks time/obs_value columns.")
        if request.geography and "ref_area" in frame:
            frame = frame.loc[
                frame["ref_area"].astype(str).str.upper() == request.geography.upper()
            ]
        metadata = SeriesMetadata(
            source=self.name,
            series_id=code,
            name=str(frame["indicator.label"].iloc[0]) if "indicator.label" in frame else code,
            geography=request.geography,
            source_url=self.source_url,
            attribution="International Labour Organization, ILOSTAT",
            license_text="See ILOSTAT terms and attribution guidance.",
        )
        return finish_result(
            request=request,
            metadata=metadata,
            dates=pd.to_datetime(frame["time"].astype(str), errors="coerce"),
            values=frame["obs_value"],
            geographies=frame.get("ref_area", request.geography),
            retrieved_at=response.retrieved_at,
            from_cache=response.from_cache,
        )


class FAOSTATSource(DataSource):
    name = "FAOSTAT"
    base_url = "https://faostatservices.fao.org/api/v1"
    hosts = ("faostatservices.fao.org",)
    source_url = "https://www.fao.org/faostat/en/"

    def search(
        self, query: str, *, options: dict[str, object] | None = None
    ) -> list[SeriesMetadata]:
        code = query.strip().upper()
        return (
            [
                SeriesMetadata(
                    source=self.name,
                    series_id=code,
                    name=f"FAOSTAT domain {code}",
                    source_url=self.source_url,
                    attribution="FAO, FAOSTAT",
                    license_text="See FAOSTAT terms and conditions.",
                )
            ]
            if code
            else []
        )

    def fetch(self, request: SeriesRequest, *, cancel: CancelCheck) -> SourceResult:
        raise ValueError(
            f"FAOSTAT retrieval is intentionally not enabled in {__version__} until the "
            "official API query/authentication contract is fully verified."
        )


class OECDSource(SDMXSource):
    name = "OECD"
    base_url = "https://sdmx.oecd.org/public/rest"
    hosts = ("sdmx.oecd.org",)
    source_url = "https://www.oecd.org/en/data/insights/data-explainers/2024/09/api.html"
    attribution = "OECD Data Explorer"
    license_text = "Use subject to OECD Data Explorer Terms and Conditions."


class BISSource(SDMXSource):
    name = "BIS"
    base_url = "https://stats.bis.org/api/v2"
    hosts = ("stats.bis.org",)
    source_url = "https://stats.bis.org/api-doc/v2/"
    attribution = "Bank for International Settlements (BIS) Statistics"
    license_text = "See BIS statistical data and API terms for reuse and attribution."

    def _parse_id(self, series_id: str) -> tuple[str, str]:
        if "|" not in series_id:
            raise ValueError("BIS IDs must use AGENCY,RESOURCE,VERSION|KEY syntax.")
        return super()._parse_id(series_id)
