"""Qt workers for metadata lookup, data retrieval, and export jobs."""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal, Slot

from economic_data_exporter.models import ExportFormatOptions, ExportSummary, FetchSummary, SeriesMetadata
from economic_data_exporter.services.exporter import export_workbook
from economic_data_exporter.services.job import JobRunner
from economic_data_exporter.sources.base import DataSource


class SearchWorker(QObject):
    finished = Signal(list)
    failed = Signal(str)

    def __init__(self, sources: dict[str, DataSource], query: str, options: dict[str, object]) -> None:
        super().__init__()
        self.sources = sources
        self.query = query
        self.options = options

    @Slot()
    def run(self) -> None:
        try:
            results: list[SeriesMetadata] = []
            errors: list[str] = []
            for name, source in self.sources.items():
                try:
                    results.extend(source.search(self.query, options=self.options))
                except Exception as exc:
                    errors.append(f"{name}: {exc}")
            if not results and errors:
                raise RuntimeError("Metadata search failed for all selected sources. " + " | ".join(errors))
            self.finished.emit(results)
        except Exception as exc:
            self.failed.emit(str(exc))


class FetchWorker(QObject):
    progress = Signal(int, int, str)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, runner: JobRunner, requests, *, fail_fast: bool) -> None:
        super().__init__()
        self.runner = runner
        self.requests = requests
        self.fail_fast = fail_fast

    @Slot()
    def run(self) -> None:
        try:
            summary: FetchSummary = self.runner.fetch(
                self.requests,
                fail_fast=self.fail_fast,
                progress=lambda done, total, text: self.progress.emit(done, total + 1, text),
            )
            self.finished.emit(summary)
        except Exception as exc:
            self.failed.emit(str(exc))


class ExportWorker(QObject):
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, output_path, successful, failures, options: ExportFormatOptions) -> None:
        super().__init__()
        self.output_path = output_path
        self.successful = successful
        self.failures = failures
        self.options = options

    @Slot()
    def run(self) -> None:
        try:
            path = export_workbook(
                self.output_path,
                self.successful,
                self.failures,
                format_options=self.options,
            )
            summary = ExportSummary(
                output_path=path,
                successful=self.successful,
                failures=self.failures,
            )
            self.finished.emit(summary)
        except Exception as exc:
            self.failed.emit(str(exc))
