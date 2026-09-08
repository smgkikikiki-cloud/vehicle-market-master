#!/usr/bin/env python3
"""Turn reviewed ECO Sticker records into MarketTrim proposals for one model.

Phase 2 harvested 1,640 detail records and attached three of them.  This closes
that gap for a named model: every ECO record that matched the model and carries
a declared powertrain becomes one proposed trim, with its own source UUID.

Nothing is invented.  Dimensions, seats, wheel size and powertrain are copied
from the ECO record; anything the record leaves blank stays blank.  The ECO
price is *not* copied -- it is a declared tax figure and belongs in the ledger
as ``ECO_STICKER_PRICE`` if anywhere.

Output is an ``import_trims`` payload.  Writing it is a separate, reviewed step.

    python tools/eco_trim_proposals.py --model toyota.alphard --out payload.json
"""

from __future__ import annotations

import argparse
import gzip
import json
import re
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vehreg.catalog import Catalog, DATA_DIR, DEFAULT_YEAR  # noqa: E402
from vehreg.ecosticker_ingest import snapshot_dir  # noqa: E402
from vehreg.normalize import slug  # noqa: E402
from vehreg.taxonomy import Drivetrain  # noqa: E402

# Drivetrain is stated in the grade name, not in a field of its own.
DRIVETRAIN_WORDS = (
    (("4WD", "AWD", "4X4", "4MATIC", "QUATTRO", "XDRIVE"), Drivetrain.AWD.value),
    (("2WD", "4X2", "FWD"), Drivetrain.FWD.value),
    (("RWD",), Drivetrain.RWD.value),
)


def load_snapshot(data_dir: Path, year: int, snapshot_date: str) -> list[dict]:
    path = snapshot_dir(data_dir, year, snapshot_date) / "normalized.jsonl.gz"
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle]


def drivetrain_of(name: str) -> str:
    upper = " " + name.upper().replace("-", " ") + " "
    for words, value in DRIVETRAIN_WORDS:
        if any(f" {word} " in upper for word in words):
            return value
    return Drivetrain.UNKNOWN.value


def tidy(name: str, model_name: str) -> str:
    """Drop the nameplate and the registration-class noise from a grade name."""
    text = re.sub(r"\s+", " ", name).strip()
    for prefix in (model_name, model_name.replace("-", ""), model_name.upper()):
        if prefix and text.upper().startswith(prefix.upper()):
            text = text[len(prefix):].strip(" -")
    text = re.sub(r"\b(CAR|CBU|CKD)\b", "", text, flags=re.I)
    return re.sub(r"\s+", " ", text).strip(" -") or name.strip()


def wheel(raw: Optional[str]) -> str:
    """ECO writes one fitment; a differing rear is not published, so leave it."""
    return (raw or "").strip()


def propose(rows: list[dict], catalog: Catalog, model_id: str) -> dict:
    model = catalog.models.get(model_id)
    if model is None:
        raise SystemExit(f"unknown model_id {model_id!r}")
    generations = catalog.generations_of(model_id)
    if len(generations) != 1:
        raise SystemExit(
            f"{model_id} has {len(generations)} generations; name one explicitly")
    generation = generations[0]

    trims: list[dict] = []
    seen: set[str] = set()
    for row in rows:
        if row.get("matched_model_id") != model_id:
            continue
        if not row.get("powertrain_candidate"):
            continue
        name = tidy(row["model_raw"], model.name_en)
        local_id = slug(name)[:60]
        if not local_id or local_id in seen:
            continue
        seen.add(local_id)
        trim = {
            "id": local_id,
            "name": name,
            "powertrain": row["powertrain_candidate"],
            "drivetrain": drivetrain_of(row["model_raw"]),
            "source_refs": {"ecosticker": [row["source_id"]]},
            "notes": "Proposed from the 2026-09-08 ECO Sticker snapshot. "
                     "Specification is the manufacturer's homologation record.",
        }
        for field, key in (("seats", "seats"), ("length_mm", "length_mm"),
                           ("width_mm", "width_mm"), ("height_mm", "height_mm")):
            if row.get(key):
                trim[field] = row[key]
        fitment = wheel(row.get("wheel_size"))
        if fitment:
            trim["tire_front"] = fitment
            trim["tire_rear"] = fitment
        trims.append(trim)

    trims.sort(key=lambda t: t["id"])
    return {"generation_id": generation.id, "trims": trims}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--model", required=True, help="catalog model_id")
    parser.add_argument("--snapshot-date", default="2026-09-08")
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--year", type=int, default=DEFAULT_YEAR)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)

    catalog = Catalog.load(args.data_dir, args.year)
    rows = load_snapshot(args.data_dir, args.year, args.snapshot_date)
    payload = propose(rows, catalog, args.model)
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        args.out.write_text(text, encoding="utf-8")
        print(json.dumps({"model": args.model, "trims": len(payload["trims"]),
                          "out": str(args.out)}, ensure_ascii=False))
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
