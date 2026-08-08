from __future__ import annotations

from datetime import date
from io import BytesIO
from pathlib import Path

import httpx
import pandas as pd
import pytest

from economic_data_exporter.exceptions import ParsingError
from economic_data_exporter.models import SeriesRequest
from economic_data_exporter.network import HttpClient
from economic_data_exporter.sources.penn_world_table import PennWorldTableSource


def workbook_bytes() -> bytes:
    buffer = BytesIO()
    data = pd.DataFrame(
        {
            "countrycode": ["CAN", "CAN", "USA"],
            "country": ["Canada", "Canada", "United States"],
            "currency_unit": ["Canadian Dollar", "Canadian Dollar", "US Dollar"],
            "year": [2020, 2021, 2020],
            "rgdpo": [50.0, 51.0, 100.0],
        }
    )
    legend = pd.DataFrame(
        {
            "Variable name": ["rgdpo"],
            "Variable definition": ["Output-side real GDP at chained PPPs"],
        }
    )
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        data.to_excel(writer, sheet_name="Data", index=False)
        legend.to_excel(writer, sheet_name="Legend", index=False)
    return buffer.getvalue()


def test_official_dataverse_download_and_filter(tmp_path: Path) -> None:
    content = workbook_bytes()
    requested_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_paths.append(request.url.path)
        if request.url.path.endswith("/:persistentId/"):
            return httpx.Response(
                200,
                json={
                    "data": {
                        "latestVersion": {
                            "files": [
                                {
                                    "label": "pwt110_capital_detail.xlsx",
                                    "dataFile": {
                                        "id": 111,
                                        "filename": "pwt110_capital_detail.xlsx",
                                    },
                                },
                                {
                                    "label": "pwt110_na_data.xlsx",
                                    "dataFile": {"id": 112, "filename": "pwt110_na_data.xlsx"},
                                },
                                {
                                    "label": "pwt110.xlsx",
                                    "dataFile": {"id": 123, "filename": "pwt110.xlsx"},
                                },
                            ]
                        }
                    }
                },
                request=request,
            )
        return httpx.Response(
            200,
            content=content,
            headers={
                "content-type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            },
            request=request,
        )

    source = PennWorldTableSource(
        HttpClient(cache_dir=tmp_path, transport=httpx.MockTransport(handler))
    )
    result = source.fetch(
        SeriesRequest(
            source=source.name,
            series_id="rgdpo",
            start_date=date(2020, 1, 1),
            end_date=date(2021, 12, 31),
            geography="CAN",
            options={"ignore_cache": True},
        ),
        cancel=lambda: None,
    )
    assert requested_paths == [
        "/api/datasets/:persistentId/",
        "/api/access/datafile/123",
    ]
    assert result.data["value"].tolist() == [50.0, 51.0]
    assert result.metadata.name == "Output-side real GDP at chained PPPs"
    assert result.metadata.source_url == "https://doi.org/10.34894/FABVLR"


def test_workbook_parsed_once_across_search_and_fetch_calls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    content = workbook_bytes()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/:persistentId/"):
            return httpx.Response(
                200,
                json={
                    "data": {
                        "latestVersion": {
                            "files": [
                                {
                                    "label": "pwt110.xlsx",
                                    "dataFile": {"id": 123, "filename": "pwt110.xlsx"},
                                }
                            ]
                        }
                    }
                },
                request=request,
            )
        return httpx.Response(
            200,
            content=content,
            headers={
                "content-type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            },
            request=request,
        )

    source = PennWorldTableSource(
        HttpClient(cache_dir=tmp_path, transport=httpx.MockTransport(handler))
    )

    parse_calls = 0
    original_read_sheets = PennWorldTableSource._read_sheets

    def counting_read_sheets(payload: bytes) -> tuple[pd.DataFrame, pd.DataFrame]:
        nonlocal parse_calls
        parse_calls += 1
        return original_read_sheets(payload)

    monkeypatch.setattr(PennWorldTableSource, "_read_sheets", staticmethod(counting_read_sheets))

    source.search("rgdpo")
    source.fetch(
        SeriesRequest(
            source=source.name,
            series_id="rgdpo",
            start_date=date(2020, 1, 1),
            end_date=date(2021, 12, 31),
            geography="CAN",
        ),
        cancel=lambda: None,
    )

    assert parse_calls == 1


def test_malformed_pwt_workbook(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/:persistentId/"):
            return httpx.Response(
                200,
                json={
                    "data": {
                        "latestVersion": {
                            "files": [
                                {
                                    "label": "pwt110.xlsx",
                                    "dataFile": {"id": 123, "filename": "pwt110.xlsx"},
                                }
                            ]
                        }
                    }
                },
                request=request,
            )
        return httpx.Response(
            200,
            content=b"not an xlsx file",
            headers={"content-type": "application/octet-stream"},
            request=request,
        )

    source = PennWorldTableSource(
        HttpClient(cache_dir=tmp_path, transport=httpx.MockTransport(handler))
    )
    request = SeriesRequest(
        source=source.name,
        series_id="rgdpo",
        start_date=date(2020, 1, 1),
        end_date=date(2021, 12, 31),
        geography="CAN",
        options={"ignore_cache": True},
    )
    with pytest.raises(ParsingError):
        source.fetch(request, cancel=lambda: None)
