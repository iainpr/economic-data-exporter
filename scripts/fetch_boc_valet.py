"""Pull a fixed list of Bank of Canada Valet series/groups and export to Excel + CSV.

Usage:
    pip install requests pandas openpyxl
    python scripts/fetch_boc_valet.py [--start 2000-01-01] [--end 2026-12-31] [--out boc_valet_data]

Each identifier is tried as a Valet *series* first; if the API reports it is not
a series (404), it is retried as a *group*, and every series in the group is kept.
Outputs:
    <out>.xlsx  - sheets: "master" (date column + one column per series, in request
                  order; blank where a series has no observation for that date),
                  "metadata", "status"
    <out>.csv   - the "master" table
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


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--start", help="start date YYYY-MM-DD (default: full history)")
    ap.add_argument("--end", help="end date YYYY-MM-DD")
    ap.add_argument("--out", default="boc_valet_data", help="output path without extension")
    args = ap.parse_args()

    params = {k: v for k, v in {"start_date": args.start, "end_date": args.end}.items() if v}
    session = requests.Session()

    columns: dict[str, dict[str, str]] = {}  # series -> {date: value}, in request order
    metadata, status = [], []
    for ident in IDENTIFIERS:
        try:
            kind, payload = fetch(session, ident, params)
        except Exception as exc:  # keep going; failures are listed in the status sheet
            status.append({"requested_id": ident, "kind": "", "series": 0, "error": str(exc)})
            print(f"FAIL {ident:<24} {exc}", file=sys.stderr)
            continue
        details = payload.get("seriesDetail") or {}
        for obs in payload.get("observations", []):
            for key, cell in obs.items():
                if key != "d":
                    columns.setdefault(key, {})[obs["d"]] = cell.get("v")
        metadata += [
            {
                "requested_id": ident,
                "series": k,
                "label": d.get("label"),
                "description": d.get("description"),
            }
            for k, d in details.items()
        ]
        status.append({"requested_id": ident, "kind": kind, "series": len(details), "error": ""})
        print(f"OK   {ident:<24} {kind:<6} {len(details)} series")

    if not columns:
        print("No data retrieved.", file=sys.stderr)
        return 1

    master = pd.DataFrame(columns).apply(pd.to_numeric, errors="coerce")
    master.index = pd.to_datetime(master.index).date  # plain dates: no time part in Excel
    master = master.sort_index().rename_axis("date")

    with pd.ExcelWriter(f"{args.out}.xlsx", engine="openpyxl", date_format="YYYY-MM-DD") as xl:
        master.to_excel(xl, sheet_name="master")
        pd.DataFrame(metadata).to_excel(xl, sheet_name="metadata", index=False)
        pd.DataFrame(status).to_excel(xl, sheet_name="status", index=False)
    master.to_csv(f"{args.out}.csv")
    print(
        f"Wrote {args.out}.xlsx and {args.out}.csv ({master.shape[1]} series x {len(master)} dates)"
    )
    return 0 if all(not s["error"] for s in status) else 2


if __name__ == "__main__":
    sys.exit(main())
