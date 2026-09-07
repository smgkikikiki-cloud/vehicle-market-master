from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def patch_rules() -> None:
    path = ROOT / "vehreg" / "powertrain_rules.py"
    text = path.read_text(encoding="utf-8")
    if 'R("Kia", "Carnival"' in text:
        print("powertrain batch2 rules already present")
        return

    marker = '''    # Mazda: petrol/diesel/mild-hybrid all fold to ICE in this taxonomy.\n'''
    if marker not in text:
        raise SystemExit("powertrain insertion marker not found")

    block = '''    # Owner batch 2: high-impact worklist decisions reviewed against the\n    # DLT source through 2026-08. Explicit source labels beat generic defaults.\n    R("Deepal", "Deepal S07", "BEV"),\n    R("BYD", "Sealion 6 DM-i", "PHEV"),\n\n    # Kia Carnival: diesel-only historically; HEV appears in DLT from 2025-11\n    # while generic CARNIVAL continues, so the unsplit current nameplate is MIXED.\n    R("Kia", "Carnival", "HEV", raw_any=("HEV", "HYBRID")),\n    R("Kia", "Carnival", "ICE", end="2025-10"),\n    R("Kia", "Carnival", MIXED, start="2025-11"),\n\n    R("Hyundai", "Staria", "ICE"),\n\n    # Porsche: generic nameplates span ICE/PHEV; explicit E-Hybrid labels stay exact.\n    R("Porsche", "Cayenne", "PHEV", raw_any=("E-HYBRID", "PHEV", "PLUG-IN")),\n    R("Porsche", "Cayenne", MIXED),\n    R("Porsche", "Panamera", "PHEV", raw_any=("E-HYBRID", "PHEV", "PLUG-IN")),\n    R("Porsche", "Panamera", MIXED),\n\n    # JLR Sport/Velar are separate canonical models after the catalog repair below.\n    R("Land Rover", "Range Rover Sport", "PHEV", raw_any=("PHEV",)),\n    R("Land Rover", "Range Rover Sport", MIXED),\n    R("Land Rover", "Range Rover Velar", "PHEV", raw_any=("PHEV",)),\n    R("Land Rover", "Range Rover Velar", MIXED),\n\n    # Audi Q8 generic spans ICE/PHEV. Q8 e-tron remains a separate electric model.\n    R("Audi", "Q8", "PHEV", raw_any=("TFSI E", "TFSIE", "PHEV", "PLUG-IN")),\n    R("Audi", "Q8", MIXED),\n\n    # A8 source evidence proves a transition overlap: TFSI e appears in 2024-04,\n    # while a 55 TFSI ICE registration still appears in 2024-06. Keep explicit\n    # labels exact and make only the post-transition bare nameplate MIXED.\n    R("Audi", "A8", "PHEV", raw_any=("TFSI E", "TFSIE", "PHEV", "PLUG-IN")),\n    R("Audi", "A8", "ICE", raw_any=("55 TFSI",)),\n    R("Audi", "A8", "ICE", end="2024-03"),\n    R("Audi", "A8", MIXED, start="2024-04"),\n\n'''
    path.write_text(text.replace(marker, block + marker), encoding="utf-8")
    print("patched powertrain rules")


def incomplete_model(model_id: str, name: str, aliases: list[str], note: str) -> dict:
    return {
        "id": model_id,
        "name_en": name,
        "name_th": "",
        "nameplate": "",
        "body_type": "SUV",
        "cab_type": "NOT_APPLICABLE",
        "registration_type": "",
        "market_scope": "NICHE",
        "aliases": aliases,
        "incomplete": True,
        "notes": note,
        "generations": [
            {
                "code": "unresearched",
                "segment": "UNKNOWN",
                "seats": None,
                "launched": None,
                "ended": None,
                "variants": [
                    {
                        "name": "spec incomplete; powertrain handled at fact level",
                        "powertrain": "UNKNOWN",
                        "drivetrain": "UNKNOWN",
                        "engine_cc": None,
                        "battery_kwh": None,
                        "price_thb": None,
                        "price_min_thb": None,
                        "price_max_thb": None,
                        "import_type": "UNKNOWN",
                        "origin_country": "UNKNOWN",
                        "price_note": "spec incomplete; owner-reviewed fact-level powertrain",
                        "aliases": [],
                        "incomplete": True,
                    }
                ],
            }
        ],
    }


def patch_land_rover() -> None:
    for year in range(2021, 2027):
        path = ROOT / "vehreg" / "data" / str(year) / "models" / "land_rover.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        models = data["models"]
        range_rover = next((m for m in models if m.get("id") == "range_rover"), None)
        if range_rover is None:
            raise SystemExit(f"{year}: Range Rover catalog target missing")
        range_rover["aliases"] = [
            a for a in range_rover.get("aliases", [])
            if str(a).strip().lower() not in {"velar", "range rover sport"}
        ]

        ids = {m.get("id") for m in models}
        if "range_rover_sport" not in ids:
            models.append(incomplete_model(
                "range_rover_sport",
                "Range Rover Sport",
                ["range rover sport"],
                "Added because DLT Range Rover Sport labels were previously swallowed by the generic Range Rover alias. Specs deliberately left incomplete; generic fact-level powertrain is owner-reviewed MIXED.",
            ))
        if "range_rover_velar" not in ids:
            models.append(incomplete_model(
                "range_rover_velar",
                "Range Rover Velar",
                ["range rover velar", "velar"],
                "Added because DLT Range Rover Velar labels were previously swallowed by the generic Range Rover alias. Specs deliberately left incomplete; generic fact-level powertrain is owner-reviewed MIXED.",
            ))

        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("split Range Rover Sport / Velar from generic Range Rover in 2021-2026 catalogs")


def patch_tests() -> None:
    existing = ROOT / "tests" / "test_powertrain_rules.py"
    text = existing.read_text(encoding="utf-8")
    text = text.replace(
        '        self.assertFalse(is_owner_reviewed("Porsche", "Cayenne"))',
        '        self.assertTrue(is_owner_reviewed("Porsche", "Cayenne"))',
    )
    existing.write_text(text, encoding="utf-8")

    new_test = ROOT / "tests" / "test_owner_powertrain_batch2.py"
    new_test.write_text('''import unittest\n\nfrom vehreg import db\nfrom vehreg.catalog import Catalog, DATA_DIR\nfrom vehreg.cube import run\nfrom vehreg.powertrain_rules import is_owner_reviewed\n\n\nclass OwnerPowertrainBatch2Tests(unittest.TestCase):\n    def setUp(self):\n        self.conn = db.connect(":memory:")\n        self.source = db.register_source(self.conn, "test-batch2")\n\n    def add(self, period, brand, model, base, raw, units=1):\n        year = int(period[:4])\n        n = self.conn.execute("select count(*) n from fact_registration").fetchone()["n"]\n        unit = f"batch2.{brand}.{model}.{n}".lower().replace(" ", "_")\n        group = (\n            "HYBRID" if base in {"HEV", "PHEV", "REEV"}\n            else "ZERO_EMISSION" if base in {"BEV", "FCEV"}\n            else "COMBUSTION"\n        )\n        market = (\n            "HYBRID" if base == "HEV" else "PLUGIN" if base == "PHEV" else\n            "REEV" if base == "REEV" else "ELECTRIC" if base in {"BEV", "FCEV"}\n            else "FUEL"\n        )\n        self.conn.execute(\n            "INSERT INTO dim_unit (unit_id,catalog_year,grain,brand,model,powertrain,"\n            "powertrain_group,market_powertrain,market_scope,is_electrified,is_plug_in) "\n            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",\n            (unit, year, "MODEL", brand, model, base, group, market, "CORE",\n             0 if base == "ICE" else 1, 1 if base in {"PHEV", "REEV", "BEV"} else 0),\n        )\n        self.conn.execute(\n            "INSERT INTO fact_registration "\n            "(period,registration_type,province,unit_id,grain,units,source_id,raw_label) "\n            "VALUES (?,?,?,?,?,?,?,?)",\n            (period, "RY1", "ALL", unit, "MODEL", units, self.source, raw),\n        )\n\n    def values(self):\n        return {r["powertrain"]: r["units"] for r in run(self.conn, ["powertrain"]).rows}\n\n    def test_carnival_changes_from_ice_to_mixed_but_explicit_hev_wins(self):\n        self.add("2025-10", "Kia", "Carnival", "ICE", "CARNIVAL")\n        self.add("2025-11", "Kia", "Carnival", "ICE", "CARNIVAL")\n        self.add("2026-08", "Kia", "Carnival", "ICE", "CARNIVAL HEV 7P LUXURY")\n        self.assertEqual(self.values(), {"HEV": 1, "ICE": 1, "MIXED": 1})\n\n    def test_s07_sealion6_and_staria_owner_defaults(self):\n        self.add("2026-08", "Deepal", "Deepal S07", "MIXED", "S07")\n        self.add("2026-08", "BYD", "Sealion 6 DM-i", "MIXED", "BYD SEALION 6")\n        self.add("2026-08", "Hyundai", "Staria", "MIXED", "STARIA")\n        self.assertEqual(self.values(), {"BEV": 1, "ICE": 1, "PHEV": 1})\n\n    def test_porsche_generic_is_mixed_and_explicit_ehybrid_is_phev(self):\n        self.add("2026-08", "Porsche", "Cayenne", "PHEV", "CAYENNE")\n        self.add("2026-08", "Porsche", "Cayenne", "PHEV", "CAYENNE E-HYBRID COUPE")\n        self.add("2026-08", "Porsche", "Panamera", "PHEV", "PANAMERA")\n        self.assertEqual(self.values(), {"MIXED": 2, "PHEV": 1})\n\n    def test_audi_q8_and_a8_rules_preserve_explicit_transition_labels(self):\n        self.add("2024-02", "Audi", "A8", "ICE", "A8")\n        self.add("2024-04", "Audi", "A8", "ICE", "A8 L TFSI E QUATTRO")\n        self.add("2024-06", "Audi", "A8", "PHEV", "A8 L 55 TFSI q Premium")\n        self.add("2024-06", "Audi", "A8", "ICE", "A8")\n        self.add("2026-08", "Audi", "Q8", "ICE", "Q8")\n        self.add("2026-08", "Audi", "Q8", "ICE", "Q8 60 TFSI e q S line BE")\n        self.assertEqual(self.values(), {"ICE": 2, "MIXED": 2, "PHEV": 2})\n\n    def test_range_rover_sport_and_velar_are_real_catalog_targets(self):\n        for year in range(2021, 2027):\n            cat = Catalog.load(DATA_DIR, year)\n            sport, _, _ = cat.model_index.lookup("LAND ROVER RANGE ROVER SPORT 3.0 LITRE")\n            velar, _, _ = cat.model_index.lookup("LAND ROVER RANGE ROVER VELAR 2.0 LITRE")\n            base, _, _ = cat.model_index.lookup("LAND ROVER RANGE ROVER 3.0 LITRE")\n            self.assertEqual(sport, "land_rover.range_rover_sport", year)\n            self.assertEqual(velar, "land_rover.range_rover_velar", year)\n            self.assertEqual(base, "land_rover.range_rover", year)\n\n    def test_range_rover_sport_velar_powertrain_rules(self):\n        self.add("2026-08", "Land Rover", "Range Rover Sport", "UNKNOWN", "RANGE ROVER SPORT")\n        self.add("2026-08", "Land Rover", "Range Rover Sport", "UNKNOWN", "RANGE ROVER SPORT 3.0 L PHEV")\n        self.add("2026-08", "Land Rover", "Range Rover Velar", "UNKNOWN", "RANGE ROVER VELAR")\n        self.assertEqual(self.values(), {"MIXED": 2, "PHEV": 1})\n\n    def test_batch2_models_are_owner_reviewed(self):\n        for brand, model in (\n            ("Kia", "Carnival"), ("Deepal", "Deepal S07"),\n            ("BYD", "Sealion 6 DM-i"), ("Hyundai", "Staria"),\n            ("Porsche", "Cayenne"), ("Porsche", "Panamera"),\n            ("Land Rover", "Range Rover Sport"), ("Land Rover", "Range Rover Velar"),\n            ("Audi", "Q8"), ("Audi", "A8"),\n        ):\n            with self.subTest(brand=brand, model=model):\n                self.assertTrue(is_owner_reviewed(brand, model))\n\n\nif __name__ == "__main__":\n    unittest.main()\n''', encoding="utf-8")
    print("patched tests")


def main() -> None:
    patch_rules()
    patch_land_rover()
    patch_tests()


if __name__ == "__main__":
    main()
