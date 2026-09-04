from __future__ import annotations

import argparse
from pathlib import Path

from .catalog import DATA_DIR, Catalog, available_years
from .db import connect, rebuild_dimension
from .provincial import (
    available_periods,
    ensure_schema,
    ingest_provincial_xlsx,
    reconciliation_for_period,
)
from .web_bootstrap import database_path


def _catalogs(conn) -> dict[int, Catalog]:
    out: dict[int, Catalog] = {}
    for year in available_years(DATA_DIR):
        catalog = Catalog.load(DATA_DIR, year)
        rebuild_dimension(conn, catalog)
        out[year] = catalog
    return out


def cmd_ingest(args: argparse.Namespace) -> int:
    conn = connect(args.db or database_path())
    ensure_schema(conn)
    catalogs = _catalogs(conn)
    report = ingest_provincial_xlsx(
        conn,
        catalogs,
        Path(args.path),
        source_name=args.source_name,
    )
    print(report.render())
    if not report.unchanged:
        print("\nreconciliation:")
        for period in available_periods(conn):
            row = reconciliation_for_period(conn, period)
            if row["national_units"]:
                print(
                    f"{period}: provincial={row['provincial_units']:,.0f} "
                    f"national={row['national_units']:,.0f} "
                    f"diff={row['difference']:+,.0f} "
                    f"({row['difference_pct']:+.2%})"
                )
    conn.close()
    return 0


def cmd_qa(args: argparse.Namespace) -> int:
    conn = connect(args.db or database_path())
    ensure_schema(conn)
    periods = [args.period] if args.period else available_periods(conn)
    if not periods:
        print("no provincial facts")
        conn.close()
        return 0
    for period in periods:
        row = reconciliation_for_period(conn, period)
        print(
            f"{period}: provincial={row['provincial_units']:,.0f} "
            f"national={row['national_units']:,.0f} "
            f"diff={row['difference']:+,.0f} "
            f"({row['difference_pct']:+.2%})"
        )
    review = conn.execute(
        "SELECT COALESCE(SUM(units),0) AS units, COUNT(*) AS rows "
        "FROM provincial_review WHERE status='open'"
    ).fetchone()
    print(
        f"open review: {int(review['rows']):,} rows / "
        f"{float(review['units'] or 0):,.0f} registrations"
    )
    conn.close()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Admin utilities for TDR provincial registration data"
    )
    parser.add_argument("--db", help="SQLite DB path; defaults to VEHREG_DB/data/vehreg.sqlite3")
    sub = parser.add_subparsers(dest="command", required=True)

    ingest = sub.add_parser("ingest", help="ingest DLT brand-model-province XLSX")
    ingest.add_argument("path", help="path to the DLT provincial XLSX workbook")
    ingest.add_argument("--source-name", default=None)
    ingest.set_defaults(func=cmd_ingest)

    qa = sub.add_parser("qa", help="show provincial vs national reconciliation")
    qa.add_argument("--period", default=None, help="optional YYYY-MM")
    qa.set_defaults(func=cmd_qa)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
