"""Reproducible mocked-provider benchmark for the core pipeline.

No live network calls are made. Use a large unprofiled run for capacity timing and a smaller
profiled run for CPU hot spots. A lightweight /proc RSS sampler provides peak-memory
measurement without the extreme allocation-tracing overhead of tracemalloc during openpyxl
workbook creation.
"""

from __future__ import annotations

import argparse
import cProfile
import io
import json
import os
import platform
import pstats
import resource
import threading
import time
from datetime import date, timedelta
from pathlib import Path

import httpx
import pandas as pd

from economic_data_exporter.models import SeriesRequest
from economic_data_exporter.network import HttpClient
from economic_data_exporter.services.exporter import export_workbook
from economic_data_exporter.sources.bank_of_canada import BankOfCanadaSource


def memory_total_bytes() -> int | None:
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            if line.startswith("MemTotal:"):
                return int(line.split()[1]) * 1024
    except OSError:
        return None
    return None


def current_rss_bytes() -> int | None:
    try:
        for line in Path("/proc/self/status").read_text(encoding="utf-8").splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) * 1024
    except OSError:
        return None
    return None


class MemorySampler:
    def __init__(self, interval_seconds: float = 0.05) -> None:
        self.interval_seconds = interval_seconds
        self.peak_bytes = current_rss_bytes() or 0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="rss-sampler", daemon=True)

    def _run(self) -> None:
        while not self._stop.wait(self.interval_seconds):
            self.peak_bytes = max(self.peak_bytes, current_rss_bytes() or 0)

    def __enter__(self) -> MemorySampler:
        self._thread.start()
        return self

    def __exit__(self, *_: object) -> None:
        self._stop.set()
        self._thread.join(timeout=1.0)
        self.peak_bytes = max(self.peak_bytes, current_rss_bytes() or 0)


def make_payload(series_id: str, observations_per_series: int) -> bytes:
    start = date(2020, 1, 1)
    observations = []
    for index in range(observations_per_series):
        current = start + timedelta(days=index)
        value = None if index % 97 == 0 else f"{100 + index * 0.01:.6f}"
        observations.append({"d": current.isoformat(), series_id: {"v": value}})
    return json.dumps(
        {
            "seriesDetail": {
                series_id: {
                    "label": f"Fixture {series_id}",
                    "description": "Synthetic benchmark fixture",
                    "dimension": {"name": "Daily"},
                    "unit": "index",
                }
            },
            "observations": observations,
        }
    ).encode("utf-8")


def run(
    output_dir: Path,
    *,
    series_count: int,
    observations_per_series: int,
    profile: bool,
) -> dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)
    payloads = {
        f"S{index:03d}": make_payload(f"S{index:03d}", observations_per_series)
        for index in range(series_count)
    }

    def handler(request: httpx.Request) -> httpx.Response:
        series_id = request.url.path.split("/")[-2]
        return httpx.Response(
            200,
            content=payloads[series_id],
            headers={"content-type": "application/json"},
            request=request,
        )

    run_label = f"{series_count}series_{series_count * observations_per_series}rows"
    cache_dir = output_dir / f"cache_{run_label}"
    cache_dir.mkdir(parents=True, exist_ok=True)
    client = HttpClient(cache_dir=cache_dir, transport=httpx.MockTransport(handler))
    source = BankOfCanadaSource(client)
    profiler = cProfile.Profile() if profile else None
    baseline_rss = current_rss_bytes() or 0

    with MemorySampler() as memory:
        if profiler:
            profiler.enable()

        retrieval_started = time.perf_counter()
        results = []
        for index in range(series_count):
            series_id = f"S{index:03d}"
            results.append(
                source.fetch(
                    SeriesRequest(
                        source=source.name,
                        series_id=series_id,
                        start_date=date(2020, 1, 1),
                        end_date=date(2035, 12, 31),
                        options={"ignore_cache": True},
                    ),
                    cancel=lambda: None,
                )
            )
        retrieval_seconds = time.perf_counter() - retrieval_started

        concat_started = time.perf_counter()
        combined = pd.concat(
            [result.normalized() for result in results], ignore_index=True, copy=False
        )
        normalization_concat_seconds = time.perf_counter() - concat_started

        workbook_path = output_dir / f"benchmark_{run_label}.xlsx"
        export_started = time.perf_counter()
        export_workbook(workbook_path, results, [])
        export_seconds = time.perf_counter() - export_started

        if profiler:
            profiler.disable()

    client.close()

    stats_name = ""
    if profiler:
        stats_path = output_dir / f"cpu_profile_{run_label}.txt"
        stream = io.StringIO()
        pstats.Stats(profiler, stream=stream).strip_dirs().sort_stats("cumulative").print_stats(50)
        stats_path.write_text(stream.getvalue(), encoding="utf-8")
        stats_name = stats_path.name

    max_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    max_rss_bytes = max_rss * (1024 if platform.system() != "Darwin" else 1)
    report = {
        "benchmark_kind": "mocked Bank of Canada-shaped provider; no live network latency",
        "profiled": profile,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "logical_cpu_count": os.cpu_count(),
        "system_memory_bytes": memory_total_bytes(),
        "series_count": series_count,
        "observations_per_series": observations_per_series,
        "normalized_rows": len(combined),
        "retrieval_and_per_series_normalization_seconds": round(retrieval_seconds, 4),
        "single_concat_seconds": round(normalization_concat_seconds, 4),
        "excel_export_and_validation_seconds": round(export_seconds, 4),
        "total_pipeline_seconds": round(
            retrieval_seconds + normalization_concat_seconds + export_seconds, 4
        ),
        "baseline_rss_bytes": baseline_rss,
        "sampled_peak_rss_bytes": memory.peak_bytes,
        "sampled_incremental_peak_bytes": max(0, memory.peak_bytes - baseline_rss),
        "process_max_rss_bytes": max_rss_bytes,
        "workbook_bytes": workbook_path.stat().st_size,
        "cpu_profile": stats_name or None,
        "workbook": workbook_path.name,
        "known_limits": [
            "Fixture excludes real provider latency, throttling, server-side pagination, "
            "and compression variability.",
            "openpyxl workbook generation is expected to dominate CPU and memory for large jobs.",
            "Configured application-wide normalized-row limit is 500,000 rows.",
            "Excel permits at most 1,048,576 rows per worksheet including the header.",
        ],
    }
    report_path = output_dir / f"results_{run_label}{'_profiled' if profile else ''}.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--series", type=int, default=100)
    parser.add_argument("--observations", type=int, default=1_000)
    parser.add_argument("--profile", action="store_true")
    parser.add_argument(
        "--output-dir", type=Path, default=Path(__file__).resolve().parent / "results"
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    print(
        json.dumps(
            run(
                args.output_dir,
                series_count=args.series,
                observations_per_series=args.observations,
                profile=args.profile,
            ),
            indent=2,
        )
    )
