from datetime import date
from pathlib import Path

import httpx
import pytest

from economic_data_exporter.exceptions import ParsingError
from economic_data_exporter.models import SeriesRequest
from economic_data_exporter.network import HttpClient
from economic_data_exporter.sources.owid import OwidSource


def test_owid_csv_normalization(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith(".metadata.json"):
            return httpx.Response(
                200,
                json={
                    "chart": {"title": "Life expectancy"},
                    "columns": {"life_expectancy": {"unit": "years", "citationFull": "UN; OWID"}},
                },
                request=request,
            )
        return httpx.Response(
            200,
            text="Entity,Code,Year,life_expectancy\nCanada,CAN,2020,82\nCanada,CAN,2021,82.1\n",
            headers={"content-type": "text/csv"},
            request=request,
        )

    source = OwidSource(HttpClient(cache_dir=tmp_path, transport=httpx.MockTransport(handler)))
    result = source.fetch(
        SeriesRequest(
            source=source.name,
            series_id="life-expectancy",
            start_date=date(2020, 1, 1),
            end_date=date(2021, 12, 31),
            geography="CAN",
            options={"ignore_cache": True},
        ),
        cancel=lambda: None,
    )
    assert result.data["value"].tolist() == [82.0, 82.1]
    assert result.metadata.units == "years"


def test_malformed_owid_csv(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith(".metadata.json"):
            return httpx.Response(200, json={"chart": {}, "columns": {}}, request=request)
        return httpx.Response(
            200, text="a,b\n1,2\n", headers={"content-type": "text/csv"}, request=request
        )

    source = OwidSource(HttpClient(cache_dir=tmp_path, transport=httpx.MockTransport(handler)))
    request = SeriesRequest(
        source=source.name,
        series_id="bad-chart",
        start_date=date(2020, 1, 1),
        end_date=date(2021, 1, 1),
    )
    with pytest.raises(ParsingError):
        source.fetch(request, cancel=lambda: None)
