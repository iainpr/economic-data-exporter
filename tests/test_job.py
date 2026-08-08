from datetime import date
from pathlib import Path

import pandas as pd

from economic_data_exporter.models import ExportJob, SeriesMetadata, SeriesRequest, SourceResult
from economic_data_exporter.services.job import JobRunner
from economic_data_exporter.sources.base import DataSource


class FakeSource(DataSource):
    name = "Fake"

    def search(self, query: str, *, options=None):
        return []

    def fetch(self, request: SeriesRequest, *, cancel):
        cancel()
        if request.series_id == "BAD":
            raise ValueError("bad series")
        metadata = SeriesMetadata(source="Fake", series_id=request.series_id, name=request.series_id)
        data = pd.DataFrame(
            {
                "date": pd.to_datetime(["2020-01-01"]),
                "value": [1.0],
                "source": ["Fake"],
                "series_id": [request.series_id],
                "series_name": [request.series_id],
                "geography": [""],
                "frequency": ["Annual"],
                "units": [""],
                "retrieved_at": ["2026-08-05T00:00:00+00:00"],
                "source_url": ["https://example.org"],
            }
        )
        return SourceResult(request=request, data=data, metadata=metadata)


def test_partial_failure_exports_success(tmp_path: Path) -> None:
    source = FakeSource(client=None)  # type: ignore[arg-type]
    runner = JobRunner({"Fake": source}, max_workers=2)
    requests = [
        SeriesRequest("Fake", "GOOD", date(2020, 1, 1), date(2020, 1, 1)),
        SeriesRequest("Fake", "BAD", date(2020, 1, 1), date(2020, 1, 1)),
    ]
    summary = runner.run(ExportJob(requests, tmp_path / "partial.xlsx"))
    assert summary.output_path is not None and summary.output_path.exists()
    assert len(summary.successful) == 1
    assert len(summary.failures) == 1
