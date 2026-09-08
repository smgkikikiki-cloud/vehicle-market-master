#!/usr/bin/env python3
"""CI brake for an automated price PR: what a harvester is allowed to change.

A run that wants to rewrite fifty prices has a broken extractor, not fifty
announcements.  This refuses the PR instead of merging it.

Checks, in order:

1. every changed file is under ``market/`` -- no code, no catalog, no warehouse;
2. the ledger and campaigns still validate against the catalog;
3. no more than ``--max-offers`` price rows changed in one PR;
4. every trim that already had a current list price still has one, and any
   change to an existing price is inside ``--max-move`` percent.

Run it against the base revision:

    python tools/pricefeed_guard.py --base origin/main
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vehreg.catalog import Catalog, DATA_DIR, DEFAULT_YEAR  # noqa: E402
from vehreg.pricing import PriceLedger  # noqa: E402

ALLOWED_PREFIX = "vehreg/data/{year}/market/"


def changed_files(base: str) -> list[str]:
    out = subprocess.run(["git", "diff", "--name-only", f"{base}...HEAD"],
                         capture_output=True, text=True, check=True)
    return [line for line in out.stdout.splitlines() if line.strip()]


def ledger_at(revision: str, year: int) -> dict[str, int]:
    """trim_id -> current list price, as of today, at one git revision."""
    prices = subprocess.run(
        ["git", "show", f"{revision}:vehreg/data/{year}/market/prices"],
        capture_output=True, text=True)
    if prices.returncode != 0:
        return {}
    amounts: dict[str, int] = {}
    for name in prices.stdout.splitlines()[2:]:
        name = name.strip()
        if not name.endswith(".json"):
            continue
        blob = subprocess.run(
            ["git", "show", f"{revision}:vehreg/data/{year}/market/prices/{name}"],
            capture_output=True, text=True)
        if blob.returncode != 0:
            continue
        for row in json.loads(blob.stdout).get("prices", []):
            if row.get("price_type") == "LIST_PRICE":
                amounts.setdefault(row["trim_id"], row["amount_thb"])
    return amounts


def check(base: str, *, year: int, data_dir: Path,
          max_offers: int, max_move: float) -> list[str]:
    problems: list[str] = []
    allowed = ALLOWED_PREFIX.format(year=year)
    for path in changed_files(base):
        if not path.startswith(allowed):
            problems.append(f"{path}: outside {allowed}; a price PR changes data only")

    catalog = Catalog.load(data_dir, year)
    ledger = PriceLedger.load(data_dir, year=year, catalog=catalog)
    problems.extend(ledger.validate())

    before = ledger_at(base, year)
    after = {trim_id: row.amount_thb for trim_id in {r.trim_id for r in ledger.records}
             for row in [ledger.current_list_price(trim_id, as_of=date.today())]
             if row is not None}

    moved = {trim_id for trim_id in set(before) | set(after)
             if before.get(trim_id) != after.get(trim_id)}
    if len(moved) > max_offers:
        problems.append(
            f"{len(moved)} list prices change in one PR (limit {max_offers}); "
            "this is an extractor fault, not that many announcements")
    for trim_id in sorted(moved):
        old, new = before.get(trim_id), after.get(trim_id)
        if old is not None and new is None:
            problems.append(f"{trim_id}: had a current list price, now has none")
        elif old and new and abs(new - old) / old * 100 > max_move:
            problems.append(
                f"{trim_id}: list price moves {old:,} -> {new:,} "
                f"({abs(new - old) / old * 100:.1f}% > {max_move}%); needs a person")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", default="origin/main")
    parser.add_argument("--year", type=int, default=DEFAULT_YEAR)
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--max-offers", type=int, default=25)
    parser.add_argument("--max-move", type=float, default=25.0,
                        help="percent a single list price may move unattended")
    args = parser.parse_args(argv)
    problems = check(args.base, year=args.year, data_dir=args.data_dir,
                     max_offers=args.max_offers, max_move=args.max_move)
    if problems:
        print("price PR refused:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    print("price PR is within limits")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
