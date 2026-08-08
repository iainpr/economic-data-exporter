"""Export-job orchestration with bounded concurrency and cancellation."""

from __future__ import annotations

import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from typing import Callable

from economic_data_exporter.config import LIMITS
from economic_data_exporter.exceptions import CancelledError, EconomicDataError
from economic_data_exporter.models import (
    ExportJob,
    ExportSummary,
    FailureRecord,
    FetchSummary,
    SeriesRequest,
    SourceResult,
)
from economic_data_exporter.services.exporter import export_workbook
from economic_data_exporter.services.ingestion import assert_requests_unique
from economic_data_exporter.sources.base import DataSource
from economic_data_exporter.utils.redaction import redact_text
from economic_data_exporter.utils.validation import (
    validate_date_range,
    validate_geography,
    validate_output_path,
    validate_series_id,
    GEOGRAPHY_REQUIRED_SOURCES,
)

ProgressCallback = Callable[[int, int, str], None]


class JobRunner:
    def __init__(self, sources: dict[str, DataSource], *, max_workers: int = LIMITS.max_concurrency) -> None:
        self.sources = sources
        self.max_workers = max(1, min(max_workers, LIMITS.max_concurrency))
        self._cancelled = threading.Event()

    def cancel(self) -> None:
        self._cancelled.set()

    def _check_cancelled(self) -> None:
        if self._cancelled.is_set():
            raise CancelledError("Job cancelled by user.")

    @staticmethod
    def _validate_request(request: SeriesRequest) -> None:
        validate_date_range(request.start_date, request.end_date)
        validate_series_id(request.series_id, source=request.source)
        if request.source in GEOGRAPHY_REQUIRED_SOURCES:
            validate_geography(request.geography, required=True)
        elif request.geography:
            validate_geography(request.geography)

    def _fetch_one(self, request: SeriesRequest) -> SourceResult:
        self._check_cancelled()
        self._validate_request(request)
        try:
            source = self.sources[request.source]
        except KeyError as exc:
            raise EconomicDataError(f"Unsupported source: {request.source}") from exc
        return source.fetch(request, cancel=self._check_cancelled)

    def fetch(
        self,
        requests: list[SeriesRequest],
        *,
        fail_fast: bool = False,
        progress: ProgressCallback | None = None,
    ) -> FetchSummary:
        started = time.perf_counter()
        self._cancelled.clear()
        total = len(requests)
        if total == 0:
            raise EconomicDataError("At least one series request is required.")
        assert_requests_unique(requests)

        results: list[SourceResult] = []
        failures: list[FailureRecord] = []
        completed = 0

        with ThreadPoolExecutor(max_workers=self.max_workers, thread_name_prefix="economic-data") as pool:
            futures: dict[Future[SourceResult], SeriesRequest] = {
                pool.submit(self._fetch_one, request): request for request in requests
            }
            for future in as_completed(futures):
                request = futures[future]
                try:
                    results.append(future.result())
                    message = f"Retrieved {request.source} {request.series_id}"
                except CancelledError:
                    self._cancelled.set()
                    for pending in futures:
                        pending.cancel()
                    return FetchSummary(
                        successful=results,
                        failures=failures,
                        cancelled=True,
                        elapsed_seconds=time.perf_counter() - started,
                    )
                except Exception as exc:
                    failures.append(
                        FailureRecord(
                            source=request.source,
                            series_id=request.series_id,
                            geography=request.geography,
                            error_type=exc.__class__.__name__,
                            message=redact_text(str(exc)),
                        )
                    )
                    message = f"Failed {request.source} {request.series_id}"
                    if fail_fast:
                        self._cancelled.set()
                        for pending in futures:
                            pending.cancel()
                        break
                completed += 1
                if progress:
                    progress(completed, total, message)

        self._check_cancelled()
        total_records = sum(len(result.data) for result in results)
        if total_records > LIMITS.max_records:
            raise EconomicDataError(
                f"Combined result contains {total_records:,} records, above the configured {LIMITS.max_records:,}-record limit."
            )
        return FetchSummary(
            successful=results,
            failures=failures,
            cancelled=False,
            elapsed_seconds=time.perf_counter() - started,
        )

    def run(self, job: ExportJob, *, progress: ProgressCallback | None = None) -> ExportSummary:
        started = time.perf_counter()
        output_path = validate_output_path(job.output_path)
        fetch_summary = self.fetch(job.requests, fail_fast=job.fail_fast, progress=progress)
        if fetch_summary.cancelled:
            return ExportSummary(
                output_path=None,
                successful=fetch_summary.successful,
                failures=fetch_summary.failures,
                cancelled=True,
                elapsed_seconds=time.perf_counter() - started,
            )
        if not fetch_summary.successful:
            return ExportSummary(
                output_path=None,
                successful=[],
                failures=fetch_summary.failures,
                elapsed_seconds=fetch_summary.elapsed_seconds,
            )
        if progress:
            progress(len(job.requests), len(job.requests) + 1, "Writing and validating Excel workbook")
        path = export_workbook(
            output_path,
            fetch_summary.successful,
            fetch_summary.failures,
            format_options=job.format_options,
            progress=None,
        )
        if progress:
            progress(len(job.requests) + 1, len(job.requests) + 1, "Export complete")
        return ExportSummary(
            output_path=path,
            successful=fetch_summary.successful,
            failures=fetch_summary.failures,
            elapsed_seconds=time.perf_counter() - started,
        )
