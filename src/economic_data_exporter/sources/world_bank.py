"""World Bank Indicators API v2 adapter."""

from __future__ import annotations

from typing import Any

import pandas as pd

from economic_data_exporter.config import LIMITS
from economic_data_exporter.exceptions import ParsingError, ValidationError
from economic_data_exporter.models import SeriesMetadata, SeriesRequest, SourceResult
from economic_data_exporter.sources.base import CancelCheck, DataSource, finish_result
from economic_data_exporter.utils.validation import validate_geography


class WorldBankSource(DataSource):
    name = "World Bank"
    base_url = "https://api.worldbank.org/v2"
    hosts = ("api.worldbank.org",)

    def search(
        self, query: str, *, options: dict[str, object] | None = None
    ) -> list[SeriesMetadata]:
        needle = query.casefold().strip()
        results: list[SeriesMetadata] = []
        page = 1
        while page <= 20 and len(results) < 100:
            response = self.client.get(
                f"{self.base_url}/indicator",
                trusted_hosts=self.hosts,
                params={"format": "json", "per_page": 1000, "page": page},
                expected_content_types=("json",),
                use_cache=not bool((options or {}).get("ignore_cache")),
            )
            try:
                payload: list[Any] = response.json()  # type: ignore[assignment]
                page_meta, items = payload[0], payload[1]
            except (IndexError, TypeError, ValueError) as exc:
                raise ParsingError("World Bank indicator response is malformed.") from exc
            for item in items or []:
                indicator_id = str(item.get("id", ""))
                name = str(item.get("name", indicator_id))
                notes = str(item.get("sourceNote", ""))
                if needle and needle not in f"{indicator_id} {name} {notes}".casefold():
                    continue
                results.append(
                    SeriesMetadata(
                        source=self.name,
                        series_id=indicator_id,
                        name=name,
                        units=str(item.get("unit") or ""),
                        notes=notes,
                        source_url=f"https://data.worldbank.org/indicator/{indicator_id}",
                        attribution="World Bank Indicators API; cite the named source "
                        "organization where provided.",
                        license_text="World Bank Data terms and any dataset-specific terms apply.",
                        extra={"source": (item.get("source") or {}).get("value", "")},
                    )
                )
                if len(results) >= 100:
                    break
            total_pages = int(page_meta.get("pages", page))
            if page >= total_pages:
                break
            page += 1
        return results

    def fetch(self, request: SeriesRequest, *, cancel: CancelCheck) -> SourceResult:
        geography = validate_geography(request.geography, required=True)
        all_items: list[dict[str, Any]] = []
        page = 1
        metadata_item: dict[str, Any] | None = None
        source_url = f"{self.base_url}/country/{geography}/indicator/{request.series_id}"
        while True:
            cancel()
            response = self.client.get(
                source_url,
                trusted_hosts=self.hosts,
                params={
                    "format": "json",
                    "date": f"{request.start_date.year}:{request.end_date.year}",
                    "per_page": 1000,
                    "page": page,
                },
                expected_content_types=("json",),
                use_cache=not bool(request.options.get("ignore_cache")),
            )
            try:
                payload: list[Any] = response.json()  # type: ignore[assignment]
                page_meta, items = payload[0], payload[1]
            except (IndexError, TypeError, ValueError) as exc:
                raise ParsingError("World Bank observations response is malformed.") from exc
            if items:
                all_items.extend(items)
                metadata_item = metadata_item or items[0]
            pages = int(page_meta.get("pages", 1))
            if pages > LIMITS.max_pages:
                raise ValidationError("World Bank pagination exceeds the configured safety limit.")
            if page >= pages:
                break
            page += 1
        if len(all_items) > LIMITS.max_records:
            raise ValidationError("World Bank result exceeds the configured record limit.")
        meta = metadata_item or {}
        indicator = meta.get("indicator") or {}
        country = meta.get("country") or {}
        metadata = SeriesMetadata(
            source=self.name,
            series_id=request.series_id,
            name=str(indicator.get("value") or request.series_id),
            geography=str(country.get("value") or geography),
            frequency=str(meta.get("unit") or "Annual/indicator-defined"),
            units=str(meta.get("unit") or ""),
            source_url=response.url if "response" in locals() else source_url,
            attribution="World Bank Indicators API; cite the named source "
            "organization where provided.",
            license_text="World Bank Data terms and any dataset-specific terms apply.",
        )
        dates: list[object] = []
        values: list[object] = []
        geos: list[str] = []
        for item in all_items:
            period = str(item.get("date", ""))
            if period.isdigit() and len(period) == 4:
                parsed_date: object = f"{period}-01-01"
            elif "M" in period and len(period) >= 7:
                year, month = period.split("M", 1)
                parsed_date = f"{year}-{month.zfill(2)}-01"
            elif "Q" in period and len(period) >= 6:
                year, quarter = period.split("Q", 1)
                parsed_date = f"{year}-{(int(quarter) - 1) * 3 + 1:02d}-01"
            else:
                parsed_date = period
            dates.append(parsed_date)
            values.append(item.get("value"))
            geos.append(str((item.get("country") or {}).get("value") or geography))
        return finish_result(
            request=request,
            metadata=metadata,
            dates=pd.Series(dates, dtype="object"),
            values=pd.Series(values, dtype="object"),
            geographies=pd.Series(geos, dtype="object"),
            retrieved_at=response.retrieved_at,
            from_cache=response.from_cache,
        )
