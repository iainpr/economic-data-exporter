# 0.6.0 ingestion and reproducibility contract

## Ingestion boundary

All provider adapters terminate in `sources/base.py::finish_result`. That function constructs the provider-independent observation frame and immediately calls `services/ingestion.py::canonicalize_observations`.

The ingestion layer:

1. canonicalizes column names to lowercase `snake_case`;
2. converts common textual/statistical null sentinels to `pd.NA` before numeric coercion;
3. lowercases ordinary string values;
4. preserves case-sensitive identifiers (`series_id`, URLs, provider/source names) so API semantics are not corrupted;
5. normalizes geography codes to uppercase;
6. adds `data_source` as a stable lowercase provider slug;
7. parses dates and numeric values deterministically.

## Primary key

The canonical observation key is:

```text
(date, source, series_id, geography)
```

A duplicate key is a hard validation error. The combined export dataset is checked again before any cleaning, sorting, pivoting, or Excel output occurs.

## Request idempotency

Duplicate requests are rejected before retrieval. Workbook writes use a temporary file followed by atomic replacement, so rerunning an export replaces the target instead of appending to it. Each logical run receives a stable SHA-256-derived `run_id`, recorded in the workbook README.

The local HTTP cache is intentionally retained: it is a retrieval optimization, not part of the canonical output state. `Refresh / ignore cache` remains available when fresh provider data are required.

## Provenance

Each observation contains both:

- `source`: human-readable provider name;
- `data_source`: stable provider slug.

The workbook README additionally records provider metadata, URLs, attribution, licenses, request dates, cache/live status, warnings, and transformations.

## Modular architecture

Provider-specific parsing stays in individual adapters. `JobRunner` is the master execution layer. Shared ingestion, validation, preparation, and export services are deliberately centralized so provider changes do not duplicate pipeline logic.
