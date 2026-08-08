# Economic Data Exporter

## 0.6.1 patch release

- Bank of Canada now supports both Valet series and series-group identifiers.
- Direct group IDs transparently fall back to the official `/observations/group/{groupName}/json` endpoint.
- Metadata search now searches both Bank of Canada series and groups.
- Empty successful responses are reported as explicit `NoData` outcomes instead of opening an unusable preview.
- GUI failure reporting now shows per-request failure details.
- Qt worker/thread cleanup was tightened to avoid lifetime-related UI instability.


A Python 3.11+ PySide6 desktop application with a modern research-workspace GUI for retrieving authoritative economic time-series data and exporting a validated local Excel workbook. The application isolates provider-specific logic in source adapters, preserves raw provider observations, supports partial failures, and keeps blocking network and export work off the GUI thread.

Verified against official provider documentation on **2026-08-07**. Provider interfaces and terms can change; review the linked official documentation before redistributing data.

## Source capability table

| Source | Official access method used | Authentication | Search / metadata | Geography | Date range | Important limitations |
|---|---|---|---|---|---|---|
| Bank of Canada | Valet API | None | Official series catalogue | Provider-defined | Start/end supported | Conservative bounded requests; no fixed numeric quota stated in guide |
| FRED | FRED API v1 | User API key | FRED series search/metadata | Provider-defined | Observation start/end | FRED terms/copyright vary by series |
| World Bank | Indicators API v2 | None | Indicator catalogue/metadata | Country/economy code | API date range | Indicators API only, not every World Bank database |
| Our World in Data | Grapher chart CSV + metadata | None | Exact chart-slug metadata | Entity/code columns | Local filtering | Uses stable documented Grapher endpoints rather than broader experimental APIs |
| Penn World Table 11.0 | Official Dataverse metadata + `pwt110.xlsx` | None | Official workbook variable/definition sheet | `countrycode` | Annual 1950–2023 in PWT 11.0 | No stable series API; imports the official workbook and filters locally |
| Statistics Canada | Official WDS JSON + SDMX services | None | Vector metadata; cube inventory can be added later | Vector/cube dimensions | Reference-period range | WDS is intended for discrete data; large updates have separate Delta File mechanisms |
| OECD | Official Data Explorer SDMX REST API | None | Dataflow/structure discovery; exact flow/key for direct retrieval | SDMX dimensions | `startPeriod`/`endPeriod` | OECD currently documents a 60-downloads/hour API limit and other query restrictions |
| IMF | Official IMF DataMapper API v2 | None | Official indicator catalogue | Country/region/group code | Annual periods | DataMapper covers the indicators exposed by DataMapper; broader IMF datasets use the IMF Data Portal/SDMX APIs |
| BIS | Official BIS SDMX REST API v2 | None | SDMX structure/dataflow endpoints | SDMX dimensions | Provider/SDMX query | BIS API returns SDMX 2.1; series IDs require provider-specific dataflow/key syntax |
| ILOSTAT | Official ILOSTAT indicator REST service / SDMX tools | None for public indicator access | Indicator IDs and labels | `ref_area` plus classifications | `timefrom`/`timeto` | Detailed multi-dimensional queries depend on ILOSTAT classifications; bulk downloads remain available |
| FAOSTAT | Official FAOSTAT API developer portal identified; live adapter intentionally gated | Not implemented in 0.6.0 | Domain-code placeholder only | Provider-defined | Provider-defined | Current indexed official documentation did not expose enough stable endpoint/authentication detail for a safe live implementation, so no guessed request is made |


Official references:

- Bank of Canada Valet documentation: https://www.bankofcanada.ca/valet/docs
- Bank of Canada Valet guide: https://www.bankofcanada.ca/valet-api-how-to/
- FRED API: https://fred.stlouisfed.org/docs/api/fred/
- FRED API terms: https://fred.stlouisfed.org/docs/api/terms_of_use.html
- World Bank Indicators API: https://datahelpdesk.worldbank.org/knowledgebase/topics/125589-developer-information
- OWID APIs: https://docs.owid.io/projects/etl/api/
- OWID Grapher Chart API: https://docs.owid.io/projects/etl/api/chart-api/
- PWT 11.0 official release: https://doi.org/10.34894/FABVLR
- Statistics Canada WDS: https://www.statcan.gc.ca/en/developers/wds
- OECD API: https://www.oecd.org/en/data/insights/data-explainers/2024/09/api.html
- IMF API: https://data.imf.org/en/Resource-Pages/IMF-API
- IMF DataMapper API: https://www.imf.org/external/datamapper/api/
- BIS Stats API: https://stats.bis.org/api-doc/v2/
- ILOSTAT data/SDMX tools: https://ilostat.ilo.org/data/ and https://ilostat.ilo.org/resources/sdmx-tools/
- FAOSTAT: https://www.fao.org/faostat/en/


## 0.6.0 data-engineering guarantees

Version 0.6.0 establishes a strict ingestion boundary. Every provider result is standardized immediately after parsing and before it can enter the combined export dataset.

- Canonical column names are lowercase and deterministic. Human-readable text values (series names, units, frequency, notes) are only whitespace-trimmed, preserving the provider's original casing; controlled geography codes are normalized to uppercase.
- Common textual and statistical missing-value sentinels are converted to pandas nulls before numeric coercion.
- Every observation carries `data_source`, a stable lowercase provider slug, alongside the human-readable `source` field.
- The canonical observation primary key is `(date, source, series_id, geography)`. Duplicate keys fail closed rather than silently multiplying rows.
- Duplicate export requests are rejected before provider calls begin.
- Provider adapters remain modular; `JobRunner` is the master orchestrator and the shared ingestion service is the single standardization boundary.
- Workbook output is atomic and replacement-based. A stable run ID is recorded in the README sheet so repeated logical runs are traceable without appending to stale output.
- Preview/clean operations remain derived transformations and never mutate the canonical ingested observations.

The application intentionally preserves the original case of both identifiers and human-readable text: lowercasing identifiers would break some provider APIs, and lowercasing display text like series names would contradict the "raw provider observations are canonical" guarantee below. Only column names and geography codes are case-normalized.

## Architecture

```text
src/economic_data_exporter/
  gui/                PySide6 widgets and QThread workers
  sources/            One adapter per provider plus common DataSource contract
  services/           Job orchestration, atomic Excel export, optional analysis
  utils/              Validation, logging, redaction
  models.py           Immutable requests/metadata and normalized result models
  network.py          HTTPS allow-lists, timeouts, retries, caching, size limits
```

The GUI creates `SeriesRequest` objects only. `JobRunner` validates each request, retrieves independent series with bounded concurrency, and passes successful `SourceResult` objects to the exporter. Provider endpoint construction and parsing never occur in GUI code.

The canonical `Data` worksheet is produced only from normalized source results. Optional analysis functions always copy their inputs and return separate derived frames. They do not receive a workbook handle and cannot modify the raw worksheet.

## Installation

### Linux / CachyOS / Arch-family systems

Install the basic system prerequisites with `pacman`:

```bash
sudo pacman -Syu --needed python python-pip unzip
```

Create an isolated Python environment in the project directory:

```bash
python -m venv .venv
```

For **Fish shell** (the default on many CachyOS setups):

```fish
source .venv/bin/activate.fish
```

For Bash/Zsh:

```bash
source .venv/bin/activate
```

Install the application:

```bash
python -m pip install --upgrade pip
python -m pip install .
```

Launch:

```bash
economic-data-exporter
```

You do not need LibreOffice, Microsoft Excel, R, Docker, a database, a GPU, or QuantEcon for normal retrieval and Excel export. PySide6, pandas, NumPy, HTTPX, openpyxl, platformdirs, and keyring are installed as Python dependencies inside the virtual environment.

For optional secure FRED-key storage on Linux, configure an OS Secret Service/keyring backend such as GNOME Keyring or an existing KWallet/KeePassXC Secret Service provider. The application can also use `FRED_API_KEY` without a keyring.

### Windows, macOS, or Linux

The same project can be installed with a normal Python 3.11+ virtual environment:

```bash
python -m venv .venv
python -m pip install --upgrade pip
pip install .
economic-data-exporter
```

PySide6 is a declared core dependency. On a headless server, the GUI cannot display; run it in a normal desktop session.

## Using the GUI

The current UI is designed for batch-style research workflows rather than one-series-at-a-time exports. The workflow is:

1. **Select multiple sources.** Check any combination of Bank of Canada, FRED, World Bank, Our World in Data, Penn World Table, Statistics Canada, OECD, IMF, BIS, ILOSTAT, and FAOSTAT. Use **Select all sources** when required.
2. **Enter multiple IDs at once.** Paste one ID per line or separate IDs with commas or semicolons. For example:

   ```text
   FSR2018JUNEC10AS2
   bcpien
   FXUSDCAD
   SP.POP.TOTL
   ```

   The application creates one request for each selected source × ID combination. Duplicate request rows are ignored. This is intentionally a Cartesian selection mechanism: selecting all five sources with a set of IDs that only exist at one provider will produce expected partial failures for IDs that do not exist at other providers.
3. **Search metadata across selected sources.** Enter a keyword or exact identifier and select multiple returned metadata rows in one dialog. Adding selected metadata results places them directly into the request table with human-readable names.
4. **Set shared request options.** Choose dates, a shared geography code where relevant, and FRED frequency when applicable. World Bank and PWT require geography.
5. **Configure FRED credentials.** The dedicated Credentials section masks the key and provides **Load saved**, **Save to OS keyring**, and **Delete saved** actions. The key is never exported.
6. **Review the request table.** Every requested source/ID pair appears before retrieval.
7. **Retrieve data.** Network retrieval remains off the GUI main thread. Independent series use bounded concurrency and partial failures are retained.
8. **Preview and clean.** After retrieval, a preview window shows the actual retrieved data before any workbook is written. Choose:
   - `Clean research`: observation fields without retrieval/provenance columns by default;
   - `Full provenance`: all canonical normalized columns;
   - `Minimal observations`: a compact research table;
   - `Custom`: choose long-format columns yourself.

   You can also choose **Long / tidy** or **Wide / one column per series**, drop missing values explicitly, remove exact duplicate rows, sort by date/series, freeze the header, enable Excel filters, auto-size columns, and optionally create one worksheet per series.
9. **Export the derived view.** The preview/clean operations do not mutate or overwrite the canonical raw observations. The workbook README records the selected shape, columns, cleaning choices, and transformations.

The preview is intentionally bounded to the first 500 rows for display. The full derived dataset is still written to Excel after confirmation.

## FRED API key

FRED requires a user-owned API key. The application uses the following precedence when a request needs FRED authentication:

1. A key entered in the GUI for the current request.
2. `FRED_API_KEY` in the process environment.
3. The OS keyring.

Example environment configuration:

```bash
# Fish
set -x FRED_API_KEY your_32_character_lowercase_key

# Bash / Zsh
export FRED_API_KEY="your_32_character_lowercase_key"

# PowerShell
$env:FRED_API_KEY="your_32_character_lowercase_key"
```

The GUI saves a key to the OS keyring only after the user explicitly chooses **Save to OS keyring**. Keys are never written to the Excel workbook, README, diagnostic logs, or cache metadata. `.env.example` contains only placeholder names; the application does not automatically load arbitrary `.env` files.

Linux desktop environments may require a configured Secret Service/keyring backend. The environment-variable method remains available when no keyring backend exists.

## Excel workbook

Every successful export contains:

- `README`: application and retrieval timestamps, request dates, IDs, names, units, source URLs, cache/live status, warnings, attribution, license notes, transformations, and capacity estimates.
- `Data`: deterministic tidy columns: `date`, `value`, `source`, `series_id`, `series_name`, `geography`, `frequency`, `units`, `retrieved_at`, `source_url`.
- `Failures`: included only when independent requests fail while others succeed.
- Optional per-series sheets with collision-safe worksheet names.

Missing provider values remain blank/NA. The application does not interpolate, resample, seasonally adjust, convert units, revise dates, or fill values. Text beginning with Excel formula prefixes is escaped to prevent formula injection; this behavior is disclosed in the workbook README.

Workbook creation is atomic: the exporter writes a same-directory temporary `.xlsx`, loads it with `openpyxl`, verifies the required sheets and schema, closes it, then uses `os.replace` for the final path.

## Network, cache, and capacity policy

Defaults are intentionally conservative:

- 3 simultaneous requests total.
- 10-second connect timeout and 60-second read timeout.
- Up to 3 bounded retries for transient network errors, `408`, `429`, and selected `5xx` statuses, using exponential backoff and jitter.
- HTTPS only, TLS verification enabled, provider-specific host allow-lists, and redirects refused.
- 100 MiB maximum response body.
- 500,000 combined normalized records per job.
- 24-hour safe-GET cache TTL and 500 MiB cache cap with oldest-file pruning.
- 2,000-page pagination safety bound.
- Excel row-limit check before writing.

The cache stores response bodies and redacted metadata only. Refresh/ignore-cache is available in the GUI. Logs record timing, byte counts, cache hits, retries, and source/job stages without query strings or API keys.

## Optional analysis and QuantEcon

The core application does not import or require QuantEcon. Install the optional group only for an explicit Markov-regime workflow:

```bash
pip install -e ".[analysis]"
```

Available service functions in `services/analysis.py`:

- Descriptive statistics.
- Explicit percent change or log difference.
- Correlation matrix with overlap counts.
- Optional empirical-regime transition analysis using `quantecon.MarkovChain` stationary distributions.

Derived outputs retain method parameters and provenance in DataFrame attributes. The QuantEcon workflow follows the documented `MarkovChain` API and the discrete-state Markov-chain concepts in the QuantEcon lectures: https://quantecon.org/lectures/

No analysis runs automatically, and no analysis function can overwrite provider observations.

## Tests and quality checks

Install development dependencies:

```bash
pip install -e ".[dev]"
```

Run:

```bash
pytest
coverage run -m pytest
coverage report -m
ruff check .
black --check .
mypy src/economic_data_exporter
```

Automated tests use mocked HTTP transports and make no live network calls. They cover date and identifier validation, URL parameters, pagination, retries, timeouts, rate limiting, malformed provider data, duplicate/missing observations, secret redaction, normalization, workbook sheets, partial failures, output paths, and raw-data isolation from optional analysis.

## Benchmarks

See [docs/BENCHMARKS.md](docs/BENCHMARKS.md) and `benchmarks/results/` for measured output and the CPU profile. Re-run with:

```bash
PYTHONPATH=src python benchmarks/benchmark_pipeline.py --series 100 --observations 1000
PYTHONPATH=src python benchmarks/benchmark_pipeline.py --series 25 --observations 1000 --profile
```

The benchmark uses a mocked Bank of Canada-shaped response fixture. It measures client parsing, normalization, one-time concatenation, workbook writing, workbook validation, and peak resident memory. It intentionally excludes real network latency.

## Manual QA checklist

### General

- Confirm the requested ID, geography, and date range in the workbook `README`.
- Confirm missing values match the provider and were not filled.
- Compare at least three dates: first, middle, and last observation.
- Confirm units, frequency, and source URL.
- Test one partial-failure job and verify successful data plus a `Failures` sheet.
- Cancel during retrieval and during export; verify no target workbook is falsely reported as complete and no `.tmp.xlsx` remains.

### Bank of Canada

- Retrieve a known series such as `FXUSDCAD`.
- Compare values and dates with the Valet JSON response and Bank of Canada data page.
- Confirm no API key was requested.

### FRED

- Search for a known series such as `GDP`, select it, and compare observations with the FRED series page/API.
- Confirm the key is masked, absent from logs/cache metadata/workbook, and the non-endorsement notice appears in `README`.
- Test a series whose notes contain “Copyright” and verify the warning.

### World Bank

- Retrieve `SP.POP.TOTL` for `CAN` across multiple years.
- Compare with the Indicators API and data.worldbank.org indicator page.
- Use a mocked multi-page response in tests or a sufficiently broad query and verify page completion.

### Our World in Data

- Validate a slug such as `life-expectancy`, select its exact data column, and compare entity/year values with the chart CSV.
- Verify chart citation and underlying-source attribution from metadata.
- Confirm a multi-column chart requires an explicit column selection.

### Penn World Table

- Search for `rgdpo` or another variable from the official PWT 11.0 variable-definition sheet.
- Verify that the Dataverse release contains the canonical `pwt110.xlsx` workbook; the adapter deliberately ignores separate `pwt110_capital_detail.xlsx` and `pwt110_na_data.xlsx` files.
- Retrieve one country and compare several year/value pairs against the official PWT 11.0 workbook.
- Confirm the workbook source is the Dataverse DOI release and no fabricated API endpoint is used.

## SDMX provider conventions

OECD and BIS use the shared SDMX adapter. A direct series request is represented as:

```text
DATAFLOW_REFERENCE|SDMX_KEY
```

For OECD, `DATAFLOW_REFERENCE` follows the documented `{agency},{dataset},{version}` form. For BIS, use the provider's documented agency/resource/version dataflow reference. The application does not invent dimension order or codes; use the provider Data Explorer/API to obtain the exact key.

The SDMX layer is deliberately small: provider adapters still own their official host, endpoint family, rate-limit policy, attribution, and provider-specific conventions.

## Statistics Canada

Statistics Canada WDS exposes vector metadata and reference-period data through documented REST methods. Vector identifiers look like `V123456789`. The application preserves the provider's values and reference dates; it does not apply scalar factors, seasonal adjustment, interpolation, or frequency conversion.

## IMF

The IMF adapter currently targets the official DataMapper API v2 because that API has a directly documented public time-series contract. Enter an IMF indicator ID and put the country/region/group code in the Geography field. The broader IMF Data Portal also exposes SDMX 2.1/3.0 APIs, but those datasets require more provider-specific structure selection and are not guessed by this adapter.

## ILOSTAT

ILOSTAT's official indicator service accepts indicator IDs and supports reference-area and time filters. The application keeps the returned classifications and observation-status fields available in the normalized source result; the clean Excel profile can omit them.

## FAOSTAT

FAO announced a new API developer portal in April 2026. Because the official indexed documentation available during this build did not expose a sufficiently stable public endpoint/authentication contract, version 0.6.0 deliberately does **not** issue guessed FAOSTAT API calls. The GUI lists FAOSTAT so the source architecture is ready, but retrieval reports an explicit limitation. This is intentional rather than a fake implementation.

## Known limitations

- No provider offers identical metadata, geography, frequency, or revision semantics; the application does not pretend otherwise.
- OWID broad search interfaces are under active development, so stable exact chart-slug metadata lookup is used.
- PWT imports the complete official workbook before filtering; caching mitigates repeat cost.
- Excel export is CPU/memory intensive. The measured 100,000-row job remained well below the 8 GiB target, but large jobs are dominated by `openpyxl` cell creation and ZIP serialization.
- Live provider behavior cannot be validated by the offline automated test suite. Use the manual QA checklist after installation.
