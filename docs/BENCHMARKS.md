# Benchmark and profiling report

Measured on **2026-08-05** in the build environment.

## Environment

- Python: 3.13.5 (the project supports Python 3.11+)
- OS/kernel: Linux 6.18.35 x86_64, glibc 2.41
- Logical CPUs available: 3
- Memory visible to the environment: 6,368,813,056 bytes (about 5.93 GiB)
- GPU: not used
- Fixture transport: `httpx.MockTransport`; no live network calls

## Capacity run: 100 series / 100,000 rows

| Stage | Measured time |
|---|---:|
| Mock retrieval, JSON parsing, and per-series normalization | 0.3716 s |
| Single concatenation | 0.0465 s |
| Excel writing and post-write validation | 11.6172 s |
| Total core pipeline | 12.0353 s |

Memory and output:

- Baseline RSS: 133,648,384 bytes
- Sampled peak RSS: 549,371,904 bytes
- Incremental sampled peak: 415,723,520 bytes
- Process maximum RSS: 550,572,032 bytes
- Workbook size: 4,009,903 bytes

The core completed the stated 100-series/100,000-observation acceptance workload without unbounded growth and without QuantEcon installed. Excel generation accounted for about 96.5% of elapsed pipeline time.

## Profiled run: 25 series / 25,000 rows

| Stage | Measured time |
|---|---:|
| Mock retrieval, JSON parsing, and per-series normalization | 0.1773 s |
| Single concatenation | 0.0204 s |
| Excel writing and post-write validation | 5.5330 s |
| Total profiled pipeline | 5.7308 s |

Memory and output:

- Baseline RSS: 130,015,232 bytes
- Sampled peak RSS: 236,544,000 bytes
- Incremental sampled peak: 106,528,768 bytes
- Process maximum RSS: 237,760,512 bytes
- Workbook size: 1,008,847 bytes

The CPU profile contains 12,356,068 function calls. `export_workbook` consumed 5.533 seconds cumulatively. The principal hot path was pandas/openpyxl cell generation and worksheet ZIP serialization; provider parsing and normalization were comparatively small. See `benchmarks/results/cpu_profile_25series_25000rows.txt`.

## Measurement method

- CPU: `cProfile`, sorted by cumulative time, on the 25,000-row fixture.
- Memory: a 50 ms `/proc/self/status` RSS sampler plus `resource.getrusage().ru_maxrss`.
- Workbook validation: load with `openpyxl` in read-only mode and verify required sheet/schema before atomic replacement.

The first attempt to combine Python allocation tracing with a fully profiled 100,000-row openpyxl run exceeded the execution ceiling because allocation tracing greatly magnified per-cell overhead. It was discarded rather than reported. The final methodology separates the unprofiled capacity run from the moderately large profiled run.

## Known limits

- Real provider latency, throttling, compression, and server-side pagination are excluded.
- Hardware differs from the nominal 4-core/8 GiB target, but it is lower in both visible CPU count and memory.
- Excel writing is the bottleneck and scales with cell count, not merely row count.
- The configured application-wide limit is 500,000 normalized rows; Excel has a hard limit of 1,048,576 rows per worksheet including the header.
