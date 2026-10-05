"""Pull a fixed list of Bank of Canada Valet series/groups and export to Excel + CSV.

Usage:
    pip install requests pandas openpyxl
    python scripts/fetch_boc_valet.py [--start 2000-01-01] [--end 2026-12-31] [--out boc_valet_data]

Each identifier is tried as a Valet *series* first; if the API reports it is not
a series (404), it is retried as a *group*, and every series in the group is kept.
Outputs:
    <out>.xlsx  - sheets: "wide" (one column per series, outer-joined on date),
                  "long" (date, series, value), "metadata", "status"
    <out>.csv   - the "wide" table
"""

from __future__ import annotations

import argparse
import sys

import pandas as pd
import requests

BASE = "https://www.bankofcanada.ca/valet"

IDENTIFIERS = [
    "BOS_REGIONAL_ATLANTIC",
    "BOS_REGIONAL_QC",
    "BOS_REGIONAL_ON",
    "BOS_REGIONAL_PRAIRIES",
    "BOS_REGIONAL_BC",
    "BD.CDN.10YR.DQ.YLD",
    "BD.CDN.LONG.DQ.YLD",
    "BD.CDN.RRB.DQ.YLD",
    "V80691335",
    "V80691333",
    "BROKER_AVERAGE_5YR_VRM",
    "V39079",
    "M.BCPI",
    "CSCE_C7_AB",
    "CSCE_C7_AT",
    "CSCE_C7_BC",
    "CSCE_C7_QC",
    "CSCE_C7_MB",
    "CSCE_C7_SK",
    "CSCE_C7_ON",
]


def fetch(session: requests.Session, ident: str, params: dict) -> tuple[str, dict]:
    """Return (kind, payload) where kind is 'series' or 'group'."""
    r = session.get(f"{BASE}/observations/{ident}/json", params=params, timeout=60)
    if r.status_code == 404:
        r = session.get(f"{BASE}/observations/group/{ident}/json", params=params, timeout=60)
        r.raise_for_status()
        return "group", r.json()
    r.raise_for_status()
    return "series", r.json()


def to_long(ident: str, payload: dict) -> tuple[pd.DataFrame, list[dict]]:
    details = payload.get("seriesDetail", {}) or {}
    rows = []
    for obs in payload.get("observations", []):
        date = obs.get("d")
        for key, cell in obs.items():
            if key == "d" or not isinstance(cell, dict):
                continue
            rows.append({"date": date, "series": key, "value": cell.get("v")})
    meta = [
        {
            "requested_id": ident,
            "series": key,
            "label": d.get("label"),
            "description": d.get("description"),
            "dimension": (d.get("dimension") or {}).get("key"),
        }
        for key, d in details.items()
    ]
    df = pd.DataFrame(rows, columns=["date", "series", "value"])
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    return df, meta


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--start", help="start date YYYY-MM-DD (default: full history)")
    ap.add_argument("--end", help="end date YYYY-MM-DD")
    ap.add_argument("--out", default="boc_valet_data", help="output path without extension")
    args = ap.parse_args()

    params = {k: v for k, v in {"start_date": args.start, "end_date": args.end}.items() if v}
    session = requests.Session()
    session.headers["User-Agent"] = "economic-data-exporter/fetch_boc_valet"

    frames, metadata, status = [], [], []
    for ident in IDENTIFIERS:
        try:
            kind, payload = fetch(session, ident, params)
            df, meta = to_long(ident, payload)
            frames.append(df)
            metadata.extend(meta)
            status.append({"requested_id": ident, "kind": kind, "series_returned": len(meta),
                           "observations": len(df), "error": ""})
            print(f"OK   {ident:<24} {kind:<6} {len(meta)} series, {len(df)} obs")
        except Exception as exc:  # keep going; report at the end
            status.append({"requested_id": ident, "kind": "", "series_returned": 0,
                           "observations": 0, "error": str(exc)})
            print(f"FAIL {ident:<24} {exc}", file=sys.stderr)

    if not frames:
        print("No data retrieved.", file=sys.stderr)
        return 1

    long_df = pd.concat(frames, ignore_index=True).drop_duplicates(["date", "series"])
    long_df["date"] = pd.to_datetime(long_df["date"])
    long_df = long_df.sort_values(["series", "date"])
    wide_df = long_df.pivot(index="date", columns="series", values="value").sort_index()

    with pd.ExcelWriter(f"{args.out}.xlsx", engine="openpyxl") as xl:
        wide_df.to_excel(xl, sheet_name="wide")
        long_df.to_excel(xl, sheet_name="long", index=False)
        pd.DataFrame(metadata).to_excel(xl, sheet_name="metadata", index=False)
        pd.DataFrame(status).to_excel(xl, sheet_name="status", index=False)
    wide_df.to_csv(f"{args.out}.csv")
    print(f"Wrote {args.out}.xlsx and {args.out}.csv ({wide_df.shape[1]} series, {len(wide_df)} dates)")
    return 0 if all(not s["error"] for s in status) else 2


if __name__ == "__main__":
    sys.exit(main())
