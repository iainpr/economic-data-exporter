from datetime import date
from pathlib import Path

import httpx

from economic_data_exporter.models import SeriesRequest
from economic_data_exporter.network import HttpClient
from economic_data_exporter.sources.world_bank import WorldBankSource


def test_complete_bounded_pagination(tmp_path: Path) -> None:
    pages: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params.get("page", "1"))
        pages.append(page)
        item = {
            "indicator": {"id": "SP.POP.TOTL", "value": "Population"},
            "country": {"id": "CA", "value": "Canada"},
            "date": str(2019 + page),
            "value": 10 + page,
            "unit": "people",
        }
        return httpx.Response(200, json=[{"page": page, "pages": 2, "total": 2}, [item]], request=request)

    source = WorldBankSource(HttpClient(cache_dir=tmp_path, transport=httpx.MockTransport(handler)))
    request = SeriesRequest(
        source=source.name,
        series_id="SP.POP.TOTL",
        start_date=date(2020, 1, 1),
        end_date=date(2021, 12, 31),
        geography="CAN",
        options={"ignore_cache": True},
    )
    result = source.fetch(request, cancel=lambda: None)
    assert pages == [1, 2]
    assert len(result.data) == 2
    assert result.data["date"].dt.year.tolist() == [2020, 2021]
