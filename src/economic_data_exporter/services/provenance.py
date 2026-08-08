"""Reproducibility and provenance helpers for export runs."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from typing import Iterable

from economic_data_exporter.models import ExportFormatOptions, SeriesRequest


def run_fingerprint(
    requests: Iterable[SeriesRequest], options: ExportFormatOptions
) -> str:
    """Return a stable identifier for the logical export request.

    The fingerprint intentionally excludes retrieval timestamps, cache state,
    and output path. Re-running the same logical job therefore produces the
    same run identifier even when the provider data are refreshed.
    """

    payload = {
        "requests": [
            {
                **asdict(request),
                "start_date": request.start_date.isoformat(),
                "end_date": request.end_date.isoformat(),
                "options": dict(sorted(request.options.items())),
            }
            for request in requests
        ],
        "format_options": asdict(options),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]
