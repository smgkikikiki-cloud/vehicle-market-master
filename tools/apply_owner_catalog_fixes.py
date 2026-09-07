#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
YEARS = range(2021, 2027)


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"anchor missing in {path}: {old!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


rules = ROOT / "vehreg" / "powertrain_rules.py"
replacements = {
    'R("Audi", "Q7", MIXED),': 'R("Audi", "Audi Q7", MIXED),',
    'R("Audi", "A6", MIXED),': 'R("Audi", "Audi A6", MIXED),',
}
for old, new in replacements.items():
    replace_once(rules, old, new)

# Remove defensive spellings that do not correspond to any canonical model.
# The SQL comparisons are already case-insensitive, so these only made the
# rulebook audit noisier and could hide a genuinely missing catalog entry.
text = rules.read_text(encoding="utf-8")
for line in (
    '    R("Nissan", "Kicks", "HEV"),\n',
    '    R("MG", "HS", "PHEV", raw_any=("PHEV",)),\n',
    '    R("MG", "HS", "ICE"),\n',
    '    R("MG", "MG 3", "ICE", end="2024-07"),\n',
    '    R("MG", "MG 3", "HEV", start="2024-08"),\n',
    '    R("Mazda", "Mazda 2", "ICE"),\n',
    '    R("Mazda", "Mazda 3", "ICE"),\n',
    '    R("Mercedes-Benz", "CLA-Class", "ICE", end="2026-02"),\n',
    '    R("Mercedes-Benz", "CLA-Class", "BEV", start="2026-03"),\n',
    '    R("Mitsubishi", "XFORCE", "HEV"),\n',
):
    text = text.replace(line, "")
rules.write_text(text, encoding="utf-8")


def incomplete_hev_model(*, model_id: str, name: str, body: str,
                         scope: str, aliases: list[str], note: str) -> dict:
    return {
        "id": model_id,
        "name_en": name,
        "name_th": "",
        "nameplate": "",
        "body_type": body,
        "cab_type": "NOT_APPLICABLE",
        "registration_type": "",
        "market_scope": scope,
        "aliases": aliases,
        "incomplete": True,
        "powertrain_checked": True,
        "notes": note,
        "generations": [{
            "code": "unresearched",
            "segment": "UNKNOWN",
            "seats": None,
            "launched": None,
            "ended": None,
            "variants": [{
                "name": "HEV (owner-reviewed; spec incomplete)",
                "powertrain": "HEV",
                "drivetrain": "UNKNOWN",
                "engine_cc": None,
                "battery_kwh": None,
                "price_thb": None,
                "price_min_thb": None,
                "price_max_thb": None,
                "import_type": "UNKNOWN",
                "origin_country": "UNKNOWN",
                "price_note": "spec incomplete; powertrain owner-reviewed",
                "aliases": [],
                "incomplete": True,
            }],
        }],
    }


IS = incomplete_hev_model(
    model_id="lexus_is", name="IS", body="SEDAN", scope="CORE",
    aliases=["IS300h", "IS300H", "IS300"],
    note=("Owner-reviewed HEV. Added because DLT IS300h was fuzzy-matching ES; "
          "specification deliberately left incomplete."),
)
LS = incomplete_hev_model(
    model_id="lexus_ls", name="LS", body="SEDAN", scope="CORE",
    aliases=["LS500h", "LS500H", "LS500", "LS350"],
    note=("Owner-reviewed HEV. Added because DLT LS500h was fuzzy-matching LM "
          "and other LS labels were stranded at brand grain; spec incomplete."),
)
PRIUS = incomplete_hev_model(
    model_id="prius", name="Prius", body="HATCHBACK", scope="GREY",
    aliases=[
        "PRIUS", "PRIUS Z", "PRIUS Z HYBRID", "PRIUS HYBRID Z 2WD",
        "PRIUS HYBRID X 2WD", "PRIUS 1.8L TOP OPT", "PRIUS 1.8L STD TRD",
    ],
    note=("Owner-reviewed HEV. DLT volume in this warehouse is low-volume import "
          "traffic, so it is kept GREY and excluded from the default core market; "
          "specification deliberately left incomplete."),
)


def add_model(path: Path, model: dict) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    names = {str(m.get("name_en", "")).upper() for m in payload.get("models", [])}
    ids = {str(m.get("id", "")).upper() for m in payload.get("models", [])}
    if model["name_en"].upper() in names or model["id"].upper() in ids:
        return
    payload.setdefault("models", []).append(model)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")


for year in YEARS:
    lexus = ROOT / "vehreg" / "data" / str(year) / "models" / "lexus.json"
    toyota = ROOT / "vehreg" / "data" / str(year) / "models" / "toyota.json"
    if not lexus.exists() or not toyota.exists():
        raise SystemExit(f"missing annual catalog for {year}")
    add_model(lexus, IS)
    add_model(lexus, LS)
    add_model(toyota, PRIUS)

# Regression tests at the index boundary: these were real misfiles, not merely
# wrong powertrain labels.  Exact surfaces must beat the old fuzzy neighbours.
test_path = ROOT / "tests" / "test_powertrain_catalog_fixes.py"
test_path.write_text(r'''import unittest

from vehreg.catalog import Catalog, DATA_DIR
from vehreg.powertrain_rules import effective_powertrain_sql


class OwnerCatalogFixTests(unittest.TestCase):
    def test_lexus_is_no_longer_matches_es(self):
        for year in range(2021, 2027):
            cat = Catalog.load(DATA_DIR, year)
            unit_id, _, _ = cat.model_index.lookup("LEXUS IS300h")
            self.assertEqual(unit_id, "lexus.lexus_is", year)
            self.assertEqual(
                {v.powertrain.value for v in cat.variants_of(unit_id)}, {"HEV"})

    def test_lexus_ls_no_longer_matches_lm(self):
        for year in range(2021, 2027):
            cat = Catalog.load(DATA_DIR, year)
            unit_id, _, _ = cat.model_index.lookup("LEXUS LS500H")
            self.assertEqual(unit_id, "lexus.lexus_ls", year)
            self.assertEqual(
                {v.powertrain.value for v in cat.variants_of(unit_id)}, {"HEV"})

    def test_prius_has_a_real_model_target(self):
        for year in range(2021, 2027):
            cat = Catalog.load(DATA_DIR, year)
            for label in ("TOYOTA PRIUS", "TOYOTA PRIUS Z HYBRID",
                          "TOYOTA PRIUS HYBRID Z 2WD"):
                unit_id, _, _ = cat.model_index.lookup(label)
                self.assertEqual(unit_id, "toyota.prius", (year, label))
            self.assertEqual(
                {v.powertrain.value for v in cat.variants_of("toyota.prius")},
                {"HEV"})

    def test_audi_rules_use_canonical_model_names(self):
        sql = effective_powertrain_sql("b")
        self.assertIn("AUDI Q7", sql)
        self.assertIn("AUDI A6", sql)


if __name__ == "__main__":
    unittest.main()
''', encoding="utf-8")

print("owner catalog fixes installed")
