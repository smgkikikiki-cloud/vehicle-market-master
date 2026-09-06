#!/usr/bin/env python3
"""Every nameplate whose powertrain the catalog asserts instead of knowing.

DLT never publishes a powertrain. The รุ่น cell says "TOYOTA COROLLA CROSS"
and nothing else, so the volume lands at model grain and inherits whatever the
model row says - and the model row is the consensus of the trims the catalog
happens to list. Where that list is complete the reading is right. Where it is
partial the reading is confidently wrong, and nothing in the data tells the two
apart.

This is the work list for closing that, biggest first. Each row carries what is
needed to decide without opening the warehouse: what is claimed now, what the
catalog lists, and what DLT actually wrote - because the raw labels are the
evidence, and they split the work in two.

    CONFLICT   DLT printed a powertrain word that disagrees with what the
               catalog claims, or two that disagree with each other. "HONDA
               JAZZ HYBRID" against a model listed as ICE; "BYD SEAL 5 DM-i",
               a plug-in, against a model listed BEV. Worth opening first,
               though not every one is an error: "MILD HYBRID" and "BLUETEC
               HYBRID" both read as HEV here and one of them is an MHEV, and a
               nameplate genuinely sold in two powertrains will show both words
               and should end up MIXED rather than either one.
    CONFIRMS   A powertrain word that agrees with the claim. Low risk.
    NO-SIGNAL  DLT sends a bare nameplate and no source can settle it. Check
               the lineup, add or remove variants if it says so, then mark the
               model powertrain_checked.

A model already marked ``powertrain_checked`` drops off the list, so it shrinks
as the work is done.

    python tools/powertrain_worklist.py
    python tools/powertrain_worklist.py --csv worklist.csv
    python tools/powertrain_worklist.py --brand NISSAN --limit 40
    python tools/powertrain_worklist.py --kind has-evidence
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from vehreg import coverage, review  # noqa: E402
from vehreg.db import connect  # noqa: E402
from vehreg.web_bootstrap import database_path  # noqa: E402

#: Words that name a powertrain when DLT prints them in the รุ่น cell. Counting
#: distinct labels was tried first and is worthless: the D-Max has five
#: spellings and 297,449 of its 297,464 units are the bare one, the Ranger's
#: extra labels are the Raptor, and the Dolphin's are battery sizes. None of
#: that is about powertrain. A word that names one is.
#:
#: "TURBO" is deliberately absent. A Taycan Turbo is a battery-electric car and
#: a Cayenne Turbo is not, so the word carries no powertrain at all - it flagged
#: the Taycan as combustion on the first run.
#: Order matters: a mild hybrid is a combustion car with a bigger starter and
#: DLT writes it "MILD HYBRID", so it has to be claimed before the plain HYBRID
#: pattern gets to it. Without that split this list called the BMW 430D
#: Mild-hybrid and the AMG GLE 53 electrified, which they are not, and two of
#: the ten "wrong" nameplates were the tool's own reading.
MARKERS: tuple[tuple[str, str], ...] = (
    ("MHEV", r"\bMILD[- ]?HYBRID\b|\bMHEV\b|\bEQ[- ]?BOOST\b"),
    ("PHEV", r"\bPHEV\b|\bPLUG[- ]?IN\b|\bDM-?I\b|\bE-HYBRID\b"),
    ("HEV",  r"\bE:?[ -]?HEV\b|\bHEV\b|\bHYBRID\b|\bHV\b"),
    ("BEV",  r"\bBEV\b|\bELECTRIC\b|\bEV\b"),
)

#: There is no marker for combustion. TFSI, TSI and TDI were tried and they are
#: injection systems, not powertrains - Audi puts TFSI on mild hybrids - so they
#: flagged the A5 and the TT as contradicting an MHEV catalog entry that was
#: right all along. Silence about electrification is not evidence against it.

#: What the labels say about the claim.
CONFLICT = "CONFLICT"      # they disagree with it, or with each other
CONFIRMS = "CONFIRMS"      # they agree with it
NO_SIGNAL = "NO-SIGNAL"    # they say nothing either way

COLUMNS = ("units", "disagreeing_units", "share", "brand", "model", "unit_id",
           "claims", "kind", "labels_say", "catalog_variants", "dlt_labels",
           "years", "evidence")


def labels_say(labels: Iterable[str]) -> set[str]:
    """Powertrains the raw labels name, if any.

    Each label yields at most one, the first marker in ``MARKERS`` that hits,
    so "MILD HYBRID" is read as MHEV and never also as HEV.
    """
    found: set[str] = set()
    for label in labels:
        upper = label.upper()
        for name, pattern in MARKERS:
            if re.search(pattern, upper):
                found.add(name)
                break
    return found


def classify(claim: str, found: set[str]) -> str:
    if not found:
        return NO_SIGNAL
    if len(found) > 1 or claim not in found:
        return CONFLICT
    return CONFIRMS


def raw_labels(conn, unit_id: str, limit: int = 6) -> list[tuple[str, float]]:
    return [(str(r["raw_label"]), float(r["units"] or 0.0)) for r in conn.execute(
        "SELECT raw_label, SUM(units) AS units FROM fact_registration "
        "WHERE unit_id = ? AND grain = 'MODEL' "
        "GROUP BY raw_label ORDER BY units DESC LIMIT ?", (unit_id, limit))]


def build(conn, catalogs) -> list[dict[str, object]]:
    rows = []
    for item in coverage.assumed_powertrain(conn, catalogs):
        unit_id = str(item["unit_id"])
        year = max((y for y in catalogs if unit_id in catalogs[y].models),
                   default=None)
        variants = catalogs[year].variants_of(unit_id) if year else []
        counted = [(str(r["raw_label"]), float(r["units"] or 0.0))
                   for r in conn.execute(
            "SELECT raw_label, SUM(units) AS units FROM fact_registration "
            "WHERE unit_id = ? AND grain = 'MODEL' GROUP BY raw_label",
            (unit_id,))]
        every = [label for label, _ in counted]
        found = labels_say(every)
        # How much volume actually wears the disagreeing label. Without this a
        # nameplate looks as wrong as its whole month: the Honda Jazz reads
        # "13,786 units claimed ICE, labels say hybrid" when exactly one unit
        # says hybrid, while the Xpander Cross reads the same and every one of
        # its 11,134 units says HEV. They are not the same finding.
        claim = str(item["powertrain"])
        disagreeing = sum(units for label, units in counted
                          if labels_say([label]) - {claim})
        kind = classify(claim, found)
        # Show the labels that carry the signal, not the biggest ones: on a
        # conflict the whole point is which label disagrees.
        shown = [(l, 0.0) for l in every if labels_say([l])][:4] \
            if found else raw_labels(conn, unit_id, 4)
        rows.append({
            "units": item["units"],
            "disagreeing_units": round(disagreeing),
            "share": (f"{disagreeing / float(item['units']):.0%}"
                      if item["units"] else "-"),
            "brand": item["brand"],
            "model": item["model"],
            "unit_id": unit_id,
            "claims": item["powertrain"],
            "kind": kind,
            "labels_say": "/".join(sorted(found)) or "-",
            "catalog_variants": " | ".join(
                f"{v.name} [{v.powertrain.value}]" for v in variants) or "-",
            "dlt_labels": item["labels"],
            "years": item["periods"],
            "evidence": " | ".join(
                name if not units else f"{name} ({units:,.0f})"
                for name, units in shown),
        })
    # Conflicts first and, inside them, by how much volume actually carries the
    # disagreeing label rather than by nameplate size.
    order = {CONFLICT: 0, NO_SIGNAL: 1, CONFIRMS: 2}
    rows.sort(key=lambda r: (order[str(r["kind"])],
                             -float(r["disagreeing_units"]),
                             -float(r["units"])))
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--csv", type=Path, help="write the full list here")
    parser.add_argument("--brand", help="only this brand, as DLT spells it")
    parser.add_argument("--kind",
                        choices=("conflict", "confirms", "no-signal"))
    parser.add_argument("--limit", type=int, default=30,
                        help="rows to print (the CSV is never truncated)")
    args = parser.parse_args(argv)

    conn = connect(database_path())
    catalogs = review.load_catalogs()
    rows = build(conn, catalogs)

    if args.brand:
        rows = [r for r in rows
                if str(r["brand"]).upper() == args.brand.upper()]
    if args.kind:
        rows = [r for r in rows if r["kind"] == args.kind.upper()]

    if args.csv:
        with open(args.csv, "w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=COLUMNS)
            writer.writeheader()
            writer.writerows(rows)
        print(f"wrote {len(rows)} rows to {args.csv}")

    total = sum(float(r["units"]) for r in rows)
    print(f"\n{len(rows)} nameplates, {total:,.0f} units carrying a powertrain "
          "the source never stated")
    blurb = {CONFLICT: "the labels disagree with the catalog - open first",
             NO_SIGNAL: "bare labels; only the lineup settles it",
             CONFIRMS: "the labels back the claim"}
    for kind in (CONFLICT, NO_SIGNAL, CONFIRMS):
        group = [r for r in rows if r["kind"] == kind]
        print(f"  {kind:<10} {len(group):>4}  "
              f"{sum(float(r['units']) for r in group):>10,.0f}   {blurb[kind]}")

    print(f"\n{'units':>9} {'disagree':>9} {'sh':>5}  {'brand':<13} "
          f"{'model':<22} {'now':<5} {'labels':<9} kind")
    print("-" * 100)
    for row in rows[:args.limit]:
        print(f"{float(row['units']):>9,.0f} "
              f"{float(row['disagreeing_units']):>9,.0f} "
              f"{str(row['share']):>5}  {str(row['brand'])[:13]:<13} "
              f"{str(row['model'])[:22]:<22} {str(row['claims']):<5} "
              f"{str(row['labels_say'])[:9]:<9} {row['kind']}")
    if len(rows) > args.limit:
        print(f"... and {len(rows) - args.limit} more (use --csv for all)")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
