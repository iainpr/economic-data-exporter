# Test and build report

Date: 2026-08-06

## Completed checks

- `PYTHONPATH=src python -m pytest`: **28 tests passed**.
- `python -m compileall -q src tests`: completed successfully.
- New multi-source/multi-ID parsing tests passed.
- New preview/clean preparation tests passed for long and wide output, missing-value filtering, duplicate handling, and wide-format collision detection.
- Core analysis import and tests run without QuantEcon installed.
- Mocked HTTP tests made no live network calls.

## Covered behavior

The test suite covers the original provider-adapter, network, validation, security, integrity, and workbook behavior plus the new GUI-supporting preparation layer:

- date-range, series-ID, geography, and output-path validation;
- parsing multiple indicator IDs separated by commas, semicolons, and newlines;
- trusted HTTPS host enforcement and streamed response-size limits;
- bounded transient retries, timeouts, and rate-limit errors;
- cache secret redaction;
- Bank of Canada request construction and normalization;
- World Bank complete mocked pagination;
- OWID CSV normalization and malformed CSV handling;
- PWT official Dataverse metadata/datafile workflow and malformed workbook handling;
- duplicate-observation rejection and missing-value preservation;
- atomic workbook generation with README, Data, and Failures sheets;
- partial-series failure behavior;
- optional analysis isolation from raw data and QuantEcon absence;
- derived export profiles, long/tidy output, wide output, explicit missing-value dropping, exact-duplicate cleanup, and wide-key collision validation.

## Checks not performed in this build environment

- No live provider calls were made, by design. Provider value verification remains a manual QA step.
- The PySide6 GUI was syntax-compiled but not launched because PySide6 and an OS keyring backend were not installed in the build container. The GUI dependencies are declared in `pyproject.toml` and install with `pip install .` on the target desktop.
- Ruff, Black, and mypy were not available in the build container, so those commands were not executed here. Their configurations remain included in `pyproject.toml`.

These limitations are reported explicitly rather than inferred as successful checks.


## 0.5.0 provider verification notes

- PWT 11.0 was rechecked against the current Groningen Growth and Development Centre release page and Dataverse record. The current release is PWT 11.0, published 2025-10-07, covering 185 countries and 1950–2023. Dataverse exposes the canonical `pwt110.xlsx` plus separate `pwt110_capital_detail.xlsx` and `pwt110_na_data.xlsx`; the adapter now selects `pwt110.xlsx` explicitly instead of treating multiple spreadsheets as ambiguous.
- Statistics Canada WDS was implemented from the current official WDS documentation, including vector metadata and `getDataFromVectorByReferencePeriodRange`.
- OECD uses the documented SDMX REST service. The README records the current documented 60-download/hour limit.
- IMF uses the directly documented DataMapper API v2 for the 0.3.0 adapter; the broader IMF SDMX API remains a future extension.
- BIS uses the official SDMX REST v2 contract.
- ILOSTAT uses its documented public indicator REST service and retains the official bulk-download route as a fallback.
- FAOSTAT is intentionally gated: the official FAO announcement confirms the 2026 API developer portal, but this build did not have enough directly indexed official endpoint/authentication detail to implement a safe live query without guessing.

Automated tests: **33 passed**. No live network calls are made by the automated suite.


## 0.5.0 verification

- 33/33 automated tests pass after the 0.5.0 changes.
- Python source and tests compile successfully.
- The 0.5.0 benchmark fixture (100 series × 1,000 observations = 100,000 normalized rows) completed in 22.48 seconds on the build environment, with approximately 396 MiB sampled incremental peak RSS. This benchmark uses a mocked Bank of Canada-shaped provider and excludes live network latency.
- The 0.5.0 exporter styles worksheets in the same `ExcelWriter` pass and performs only a read-only validation reopen, eliminating the prior write/reopen/restyle/save cycle.
- The IMF geography requirement is centralized in `GEOGRAPHY_REQUIRED_SOURCES` and consumed by both GUI request construction and `JobRunner` validation.
- Preview cells use `pandas.isna()` so missing numeric values render as blank cells rather than `nan`.
- IMF metadata search is performed once per successful fetch.
- GUI worker state uses `_worker_thread` / `_worker` rather than shadowing Qt's inherited `thread()` method.
- Provider modules were consolidated into `sources/misc.py` for Statistics Canada, IMF, ILOSTAT, and FAOSTAT, and OECD/BIS remain represented through the shared SDMX layer.
- PySide6 GUI runtime could not be launched in the build environment because PySide6 is not installed there; therefore live visual testing on Windows remains a user-side verification step.


## 0.6.0 verification

- 39/39 automated tests pass after the 0.6.0 ingestion/provenance changes.
- Python source and tests compile successfully with Python 3.13.
- The canonical ingestion boundary standardizes provider frames before combination.
- Duplicate request validation runs before provider calls.
- Combined observation primary-key validation runs before cleaning or export.
- `data_source` provenance is added at ingestion and included in the canonical schema.
- Export run IDs are stable for the same logical request and are recorded in the workbook README.
- Workbook output remains atomic and replacement-based.
- A wheel was built successfully from the local setuptools build backend.
- Live provider/network verification was not performed in the build environment; provider tests remain fixture/mock based.

## 0.6.1 patch verification

- Bank of Canada group fallback regression test added.
- Bank of Canada series/group metadata search regression test added.
- Empty-result GUI handling changed to explicit NoData failure reporting.
- Qt worker/thread cleanup revised.
- 41/41 automated tests pass in the build environment.
