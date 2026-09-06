#!/usr/bin/env python3
"""Turn DLT's pivot workbook into monthly CSVs the ordinary ingest can read.

Run it once per new workbook. It writes ``data/raw_pivot/pivot_YYYY-MM.csv``
for the months asked for; ``bootstrap_database`` picks those up on the next
boot, after the API exports and only for periods the API exports do not cover.

The pivot is the weaker source where an API export exists, because it carries
no registration class: on January 2026 the same month loses its cab split and
12,925 units fall to review instead of classifying. So the default is
``--missing``, which writes only the months the warehouse has no export for.
Replacing a month the API already covers is possible but has to be asked for.

    python tools/import_dlt_pivot.py workbook.xlsx --missing
    python tools/import_dlt_pivot.py workbook.xlsx --periods 2026-03 2026-04
    python tools/import_dlt_pivot.py workbook.xlsx --list
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from vehreg import dlt_pivot  # noqa: E402
from vehreg.db import connect  # noqa: E402
from vehreg.web_bootstrap import database_path  # noqa: E402

PIVOT_DIR = ROOT / "data" / "raw_pivot"
RAW_DIR = ROOT / "data" / "raw"


def periods_on_disk(raw_dir: Path) -> set[str]:
    return {path.stem.removeprefix("dlt_") for path in raw_dir.glob("dlt_????-??.csv")}


def catalog_years() -> set[int]:
    from vehreg.catalog import DATA_DIR, available_years
    return set(available_years(DATA_DIR))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workbook", type=Path)
    parser.add_argument("--sheet", default=None)
    parser.add_argument("--periods", nargs="*", default=None,
                        help="explicit YYYY-MM list")
    parser.add_argument("--missing", action="store_true",
                        help="every period the API exports do not cover")
    parser.add_argument("--list", action="store_true",
                        help="report the workbook against the warehouse, write nothing")
    parser.add_argument("--out", type=Path, default=PIVOT_DIR)
    args = parser.parse_args(argv)

    rows = dlt_pivot.load_workbook_rows(args.workbook, args.sheet)
    totals = dlt_pivot.period_totals(rows)
    declared = dlt_pivot.declared_period_totals(rows)
    drift = {p: (totals[p], declared[p]) for p in declared
             if abs(totals.get(p, 0.0) - declared[p]) > 0.5}
    if drift:
        print("the model rows do not add up to the workbook's own subtotals; "
              "refusing to write", file=sys.stderr)
        for period, (got, want) in sorted(drift.items()):
            print(f"  {period}: rows {got:,.0f} vs subtotal {want:,.0f}", file=sys.stderr)
        return 1

    have_export = periods_on_disk(RAW_DIR)
    years = catalog_years()
    conn = connect(database_path())
    loaded = {str(row["period"]) for row in
              conn.execute("SELECT DISTINCT period FROM fact_registration")}
    conn.close()

    if args.list or not (args.periods or args.missing):
        print(f"{'period':9} {'workbook':>10} {'export?':>8} {'loaded?':>8}  note")
        for period in sorted(totals):
            year = int(period[:4])
            note = "" if year in years else "no catalog for this year"
            print(f"{period:9} {totals[period]:>10,.0f} "
                  f"{'yes' if period in have_export else '-':>8} "
                  f"{'yes' if period in loaded else '-':>8}  {note}")
        return 0

    if args.periods:
        wanted = [p for p in args.periods if p in totals]
        unknown = sorted(set(args.periods) - set(totals))
        if unknown:
            print(f"not in the workbook: {', '.join(unknown)}", file=sys.stderr)
            return 1
    else:
        wanted = [p for p in sorted(totals) if p not in have_export]

    skipped = [p for p in wanted if int(p[:4]) not in years]
    wanted = [p for p in wanted if int(p[:4]) in years]
    for period in skipped:
        print(f"skip {period}: no catalog for {period[:4]}, every row would "
              f"queue for review rather than classify")

    for period in wanted:
        target = args.out / f"pivot_{period}.csv"
        written = dlt_pivot.write_period_csv(rows, period, target)
        print(f"wrote {target.relative_to(ROOT)}  {written} rows  "
              f"{totals[period]:,.0f} units")
    if wanted:
        print("\nrun the app (or vehreg web-bootstrap) to load them")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
