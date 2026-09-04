from __future__ import annotations

import argparse
from pathlib import Path

from vehreg.catalog import DATA_DIR, Catalog, available_years
from vehreg.db import connect, rebuild_dimension
from vehreg.state_seed import load_seed_csv

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "data" / "vehreg.sqlite3"
DEFAULT_SEED = ROOT / "data" / "research" / "monthly_production_state.csv"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Apply committed production-country/import-type history to the local vehicle DB"
    )
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--seed", type=Path, default=DEFAULT_SEED)
    args = parser.parse_args()

    args.db.parent.mkdir(parents=True, exist_ok=True)
    conn = connect(args.db)
    try:
        for year in available_years(DATA_DIR):
            rebuild_dimension(conn, Catalog.load(DATA_DIR, year))
        report = load_seed_csv(conn, args.seed)
    finally:
        conn.close()

    print(f"seed rows: {report['rows']}")
    print(f"applied: {report['applied']}")
    print(f"unchanged: {report['unchanged']}")
    if report["errors"]:
        print("errors:")
        for error in report["errors"]:
            print(f"- {error}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
