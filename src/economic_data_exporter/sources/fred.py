"""FRED API v1 adapter."""

from __future__ import annotations

import os
from typing import Any

import keyring
import pandas as pd

from economic_data_exporter.exceptions import AuthenticationError, ParsingError
from economic_data_exporter.models import SeriesMetadata, SeriesRequest, SourceResult
from economic_data_exporter.sources.base import CancelCheck, DataSource, finish_result

KEYRING_SERVICE = "Economic Data Exporter"
KEYRING_USER = "FRED_API_KEY"


def load_fred_key() -> str:
    environment_key = os.environ.get("FRED_API_KEY", "").strip()
    try:
        stored_key = (keyring.get_password(KEYRING_SERVICE, KEYRING_USER) or "").strip()
    except keyring.errors.KeyringError:
        stored_key = ""
    key = environment_key or stored_key
    if len(key) != 32 or not key.isalnum() or key.lower() != key:
        raise AuthenticationError("A valid 32-character lowercase FRED API key is required.")
    return key


class FredSource(DataSource):
    name = "FRED"
    base_url = "https://api.stlouisfed.org/fred"
    hosts = ("api.stlouisfed.org",)

    def _key(self, options: dict[str, object] | None) -> str:
        supplied = str((options or {}).get("api_key") or "").strip()
        if supplied:
            if len(supplied) != 32 or not supplied.isalnum() or supplied.lower() != supplied:
                raise AuthenticationError("FRED API key format is invalid.")
            return supplied
        return load_fred_key()

    def search(
        self, query: str, *, options: dict[str, object] | None = None
    ) -> list[SeriesMetadata]:
        response = self.client.get(
            f"{self.base_url}/series/search",
            trusted_hosts=self.hosts,
            params={
                "api_key": self._key(options),
                "file_type": "json",
                "search_text": query,
                "limit": 100,
            },
            expected_content_types=("json",),
            use_cache=not bool((options or {}).get("ignore_cache")),
        )
        try:
            payload: dict[str, Any] = response.json()  # type: ignore[assignment]
            items = payload["seriess"]
        except (KeyError, TypeError, ValueError) as exc:
            raise ParsingError("FRED series-search response is malformed.") from exc
        return [
            SeriesMetadata(
                source=self.name,
                series_id=str(item["id"]),
                name=str(item.get("title") or item["id"]),
                frequency=str(item.get("frequency") or ""),
                units=str(item.get("units") or ""),
                notes=str(item.get("notes") or ""),
                source_url=f"https://fred.stlouisfed.org/series/{item['id']}",
                attribution="Federal Reserve Bank of St. Louis FRED API; underlying series "
                "may have separate rights.",
                license_text="FRED API Terms of Use; inspect series notes for "
                "third-party copyright restrictions.",
                extra={"seasonal_adjustment": item.get("seasonal_adjustment", "")},
            )
            for item in items
        ]

    def fetch(self, request: SeriesRequest, *, cancel: CancelCheck) -> SourceResult:
        cancel()
        api_key = self._key(request.options)
        common: dict[str, object] = {
            "api_key": api_key,
            "file_type": "json",
            "series_id": request.series_id,
        }
        meta_response = self.client.get(
            f"{self.base_url}/series",
            trusted_hosts=self.hosts,
            params=common,
            expected_content_types=("json",),
            use_cache=not bool(request.options.get("ignore_cache")),
        )
        cancel()
        params: dict[str, object] = {
            **common,
            "observation_start": request.start_date.isoformat(),
            "observation_end": request.end_date.isoformat(),
        }
        if request.frequency:
            params["frequency"] = request.frequency
        for name in ("realtime_start", "realtime_end", "vintage_dates"):
            if request.options.get(name):
                params[name] = request.options[name]
        obs_response = self.client.get(
            f"{self.base_url}/series/observations",
            trusted_hosts=self.hosts,
            params=params,
            expected_content_types=("json",),
            use_cache=not bool(request.options.get("ignore_cache")),
        )
        cancel()
        try:
            meta_payload: dict[str, Any] = meta_response.json()  # type: ignore[assignment]
            item = meta_payload["seriess"][0]
            obs_payload: dict[str, Any] = obs_response.json()  # type: ignore[assignment]
            observations = obs_payload["observations"]
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise ParsingError("FRED response is malformed or the series does not exist.") from exc
        metadata = SeriesMetadata(
            source=self.name,
            series_id=request.series_id,
            name=str(item.get("title") or request.series_id),
            frequency=str(item.get("frequency") or request.frequency or ""),
            units=str(item.get("units") or ""),
            notes=str(item.get("notes") or ""),
            source_url=f"https://fred.stlouisfed.org/series/{request.series_id}",
            attribution="Federal Reserve Bank of St. Louis FRED API; underlying series "
            "may have separate rights.",
            license_text="FRED API Terms of Use; inspect series notes for "
            "third-party copyright restrictions.",
        )
        warnings = []
        if "copyright" in metadata.notes.casefold():
            warnings.append(
                "FRED series notes indicate copyright restrictions; review provider "
                "terms before reuse."
            )
        return finish_result(
            request=request,
            metadata=metadata,
            dates=pd.Series([row.get("date") for row in observations], dtype="object"),
            values=pd.Series(
                [None if row.get("value") == "." else row.get("value") for row in observations],
                dtype="object",
            ),
            geographies=request.geography,
            retrieved_at=obs_response.retrieved_at,
            from_cache=meta_response.from_cache and obs_response.from_cache,
            warnings=warnings,
        )
