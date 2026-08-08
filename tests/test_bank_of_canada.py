from datetime import date
from pathlib import Path

import httpx
import pytest

from economic_data_exporter.exceptions import ParsingError
from economic_data_exporter.models import SeriesRequest
from economic_data_exporter.network import HttpClient
from economic_data_exporter.sources.bank_of_canada import BankOfCanadaSource


def test_url_and_query_construction_and_normalization(tmp_path: Path) -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200,
            json={
                "seriesDetail": {
                    "FXUSDCAD": {
                        "label": "USD/CAD",
                        "description": "Exchange rate",
                        "dimension": {"name": "Daily"},
                    }
                },
                "observations": [
                    {"d": "2020-01-01", "FXUSDCAD": {"v": "1.30"}},
                    {"d": "2020-01-02", "FXUSDCAD": {"v": None}},
                ],
            },
            request=request,
        )

    source = BankOfCanadaSource(HttpClient(cache_dir=tmp_path, transport=httpx.MockTransport(handler)))
    request = SeriesRequest(
        source=source.name,
        series_id="FXUSDCAD",
        start_date=date(2020, 1, 1),
        end_date=date(2020, 1, 2),
        options={"ignore_cache": True},
    )
    result = source.fetch(request, cancel=lambda: None)
    assert captured[0].url.path.endswith("/observations/FXUSDCAD/json")
    assert captured[0].url.params["start_date"] == "2020-01-01"
    assert list(result.data["value"].astype(object)) == [1.3, pytest.approx(float("nan"), nan_ok=True)]
    assert "Provider missing values" in " ".join(result.warnings)


def test_malformed_json(tmp_path: Path) -> None:
    source = BankOfCanadaSource(
        HttpClient(
            cache_dir=tmp_path,
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, content=b"not json", headers={"content-type": "application/json"}, request=request)
            ),
        )
    )
    request = SeriesRequest(source=source.name, series_id="X", start_date=date(2020, 1, 1), end_date=date(2020, 1, 2))
    with pytest.raises(ParsingError):
        source.fetch(request, cancel=lambda: None)


def test_group_fallback_expands_multiple_series(tmp_path: Path) -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path.endswith("/observations/GROUP/json"):
            return httpx.Response(404, json={"message": "not a series"}, request=request)
        assert request.url.path.endswith("/observations/group/GROUP/json")
        return httpx.Response(
            200,
            json={
                "groupDetail": {"label": "Example Group", "description": "A group."},
                "seriesDetail": {
                    "SERIESA": {"label": "Series A", "dimension": {"name": "Monthly"}, "unit": "%"},
                    "SERIESB": {"label": "Series B", "dimension": {"name": "Monthly"}, "unit": "%"},
                },
                "observations": [
                    {"d": "2020-01-01", "SERIESA": {"v": "1.0"}, "SERIESB": {"v": "2.0"}},
                    {"d": "2020-02-01", "SERIESA": {"v": "1.1"}, "SERIESB": {"v": None}},
                ],
            },
            request=request,
        )

    source = BankOfCanadaSource(HttpClient(cache_dir=tmp_path, transport=httpx.MockTransport(handler)))
    request = SeriesRequest(
        source=source.name,
        series_id="GROUP",
        start_date=date(2020, 1, 1),
        end_date=date(2020, 2, 1),
        options={"ignore_cache": True},
    )
    result = source.fetch(request, cancel=lambda: None)
    assert calls == [
        "/valet/observations/GROUP/json",
        "/valet/observations/group/GROUP/json",
    ]
    assert set(result.data["series_id"]) == {"SERIESA", "SERIESB"}
    assert len(result.data) == 4
    assert result.metadata.extra["kind"] == "group"
    assert result.metadata.extra["series_count"] == 2


def test_search_includes_series_groups(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/lists/series/json"):
            return httpx.Response(200, json={"series": {"FXUSDCAD": {"label": "USD/CAD", "description": "Exchange rate"}}}, request=request)
        assert request.url.path.endswith("/lists/groups/json")
        return httpx.Response(200, json={"groups": {"MY_GROUP": {"label": "My group", "description": "Group description"}}}, request=request)

    source = BankOfCanadaSource(HttpClient(cache_dir=tmp_path, transport=httpx.MockTransport(handler)))
    results = source.search("MY_GROUP", options={"ignore_cache": True})
    assert len(results) == 1
    assert results[0].series_id == "MY_GROUP"
    assert results[0].extra["kind"] == "group"
