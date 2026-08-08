"""Bank of Canada Valet API adapter."""

from __future__ import annotations

from typing import Any

import pandas as pd

from economic_data_exporter.config import LIMITS
from economic_data_exporter.exceptions import ParsingError, SourceNotFoundError
from economic_data_exporter.models import SeriesMetadata, SeriesRequest, SourceResult
from economic_data_exporter.services.ingestion import canonicalize_observations
from economic_data_exporter.utils.validation import validate_observations
from economic_data_exporter.sources.base import CancelCheck, DataSource, finish_result


class BankOfCanadaSource(DataSource):
    name = "Bank of Canada"
    base_url = "https://www.bankofcanada.ca/valet"
    hosts = ("www.bankofcanada.ca",)

    def search(self, query: str, *, options: dict[str, object] | None = None) -> list[SeriesMetadata]:
        """Search both Valet series and series groups."""
        options = options or {}
        needle = query.casefold().strip()
        results: list[SeriesMetadata] = []

        series_response = self.client.get(
            f"{self.base_url}/lists/series/json",
            trusted_hosts=self.hosts,
            expected_content_types=("json",),
            use_cache=not bool(options.get("ignore_cache")),
        )
        try:
            series = series_response.json()["series"]  # type: ignore[index]
        except (KeyError, TypeError, ValueError) as exc:
            raise ParsingError("Bank of Canada series list is malformed.") from exc

        for series_id, item in series.items():
            label = str(item.get("label", series_id))
            description = str(item.get("description", ""))
            if needle and needle not in f"{series_id} {label} {description}".casefold():
                continue
            results.append(
                SeriesMetadata(
                    source=self.name,
                    series_id=str(series_id),
                    name=label,
                    notes=description,
                    source_url=f"{self.base_url}/observations/{series_id}/json",
                    attribution="Bank of Canada Valet API",
                    license_text="Subject to Bank of Canada terms of use and disclaimers.",
                    extra={"kind": "series"},
                )
            )
            if len(results) >= 100:
                return results

        groups_response = self.client.get(
            f"{self.base_url}/lists/groups/json",
            trusted_hosts=self.hosts,
            expected_content_types=("json",),
            use_cache=not bool(options.get("ignore_cache")),
        )
        try:
            groups = groups_response.json()["groups"]  # type: ignore[index]
        except (KeyError, TypeError, ValueError) as exc:
            raise ParsingError("Bank of Canada group list is malformed.") from exc

        for group_id, item in groups.items():
            label = str(item.get("label", group_id))
            description = str(item.get("description", ""))
            if needle and needle not in f"{group_id} {label} {description}".casefold():
                continue
            results.append(
                SeriesMetadata(
                    source=self.name,
                    series_id=str(group_id),
                    name=f"[Group] {label}",
                    notes=description,
                    source_url=f"{self.base_url}/observations/group/{group_id}/json",
                    attribution="Bank of Canada Valet API",
                    license_text="Subject to Bank of Canada terms of use and disclaimers.",
                    extra={"kind": "group"},
                )
            )
            if len(results) >= 100:
                break
        return results

    def fetch(self, request: SeriesRequest, *, cancel: CancelCheck) -> SourceResult:
        """Fetch one Valet series, or transparently expand a Valet series group."""
        cancel()
        try:
            return self._fetch_series(request, cancel=cancel)
        except SourceNotFoundError:
            # Valet has separate endpoints for individual series and groups.
            # A direct user-entered ID may therefore be either kind.
            return self._fetch_group(request, cancel=cancel)

    def _fetch_series(self, request: SeriesRequest, *, cancel: CancelCheck) -> SourceResult:
        url = f"{self.base_url}/observations/{request.series_id}/json"
        response = self.client.get(
            url,
            trusted_hosts=self.hosts,
            params={
                "start_date": request.start_date.isoformat(),
                "end_date": request.end_date.isoformat(),
            },
            expected_content_types=("json",),
            use_cache=not bool(request.options.get("ignore_cache")),
        )
        cancel()
        try:
            payload: dict[str, Any] = response.json()  # type: ignore[assignment]
            detail = payload.get("seriesDetail", {}).get(request.series_id, {})
            observations = payload["observations"]
            rows = [
                (item.get("d"), (item.get(request.series_id) or {}).get("v"))
                for item in observations
            ]
        except (KeyError, TypeError, ValueError) as exc:
            raise ParsingError("Bank of Canada observation response is malformed.") from exc
        metadata = SeriesMetadata(
            source=self.name,
            series_id=request.series_id,
            name=str(detail.get("label") or request.series_id),
            frequency=str(detail.get("dimension", {}).get("name") or "Provider frequency"),
            units=str(detail.get("unit") or ""),
            notes=str(detail.get("description") or ""),
            source_url=response.url,
            attribution="Bank of Canada Valet API",
            license_text="Subject to Bank of Canada terms of use and disclaimers.",
        )
        return finish_result(
            request=request,
            metadata=metadata,
            dates=pd.Series([row[0] for row in rows], dtype="object"),
            values=pd.Series([row[1] for row in rows], dtype="object"),
            geographies="Canada",
            retrieved_at=response.retrieved_at,
            from_cache=response.from_cache,
        )

    def _fetch_group(self, request: SeriesRequest, *, cancel: CancelCheck) -> SourceResult:
        url = f"{self.base_url}/observations/group/{request.series_id}/json"
        response = self.client.get(
            url,
            trusted_hosts=self.hosts,
            params={
                "start_date": request.start_date.isoformat(),
                "end_date": request.end_date.isoformat(),
            },
            expected_content_types=("json",),
            use_cache=not bool(request.options.get("ignore_cache")),
        )
        cancel()
        try:
            payload: dict[str, Any] = response.json()  # type: ignore[assignment]
            observations = payload["observations"]
            details = payload.get("seriesDetail", {})
            group_detail = payload.get("groupDetail", {})
        except (KeyError, TypeError, ValueError) as exc:
            raise ParsingError("Bank of Canada group observation response is malformed.") from exc

        rows: list[dict[str, object]] = []
        for observation in observations:
            raw_date = observation.get("d") or observation.get("q")
            if not raw_date:
                continue
            parsed_date = self._parse_observation_date(str(raw_date))
            for series_id, series_value in observation.items():
                if series_id in {"d", "q"} or not isinstance(series_value, dict):
                    continue
                detail = details.get(series_id, {}) if isinstance(details, dict) else {}
                rows.append(
                    {
                        "date": parsed_date,
                        "value": series_value.get("v"),
                        "source": self.name,
                        "series_id": str(series_id),
                        "series_name": str(detail.get("label") or series_id),
                        "geography": "Canada",
                        "frequency": str(detail.get("dimension", {}).get("name") or "Provider frequency"),
                        "units": str(detail.get("unit") or ""),
                        "retrieved_at": response.retrieved_at.replace(microsecond=0).isoformat(),
                        "source_url": response.url,
                    }
                )

        group_name = str(group_detail.get("label") or request.series_id)
        metadata = SeriesMetadata(
            source=self.name,
            series_id=request.series_id,
            name=f"[Group] {group_name}",
            notes=str(group_detail.get("description") or "Valet series group."),
            source_url=response.url,
            attribution="Bank of Canada Valet API",
            license_text="Subject to Bank of Canada terms of use and disclaimers.",
            extra={"kind": "group", "series_count": len({row["series_id"] for row in rows})},
        )
        frame = pd.DataFrame(rows)
        if frame.empty:
            frame = pd.DataFrame(columns=["date", "value", "source", "series_id", "series_name", "geography", "frequency", "units", "retrieved_at", "source_url"])
        frame = canonicalize_observations(frame, source=self.name)
        frame.sort_values(["date", "series_id", "geography"], inplace=True, kind="stable")
        frame.reset_index(drop=True, inplace=True)
        warnings = validate_observations(frame, max_records=LIMITS.max_records)
        warnings.append(f"Expanded Bank of Canada series group {request.series_id!r} into {metadata.extra['series_count']:,} series.")
        return SourceResult(
            request=request,
            data=frame,
            metadata=metadata,
            retrieved_at=response.retrieved_at,
            warnings=warnings,
            from_cache=response.from_cache,
        )

    @staticmethod
    def _parse_observation_date(value: str) -> str:
        if "Q" in value.upper():
            year, quarter = value.upper().split("Q", 1)
            return f"{int(year)}-{(int(quarter) - 1) * 3 + 1:02d}-01"
        return value

