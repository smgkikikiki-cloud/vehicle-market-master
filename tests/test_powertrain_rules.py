import unittest

from vehreg import db
from vehreg.cube import run
from vehreg.powertrain_rules import is_owner_reviewed


class OwnerPowertrainRuleTests(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")
        self.source = db.register_source(self.conn, "test")

    def add(self, period, brand, model, base, raw, units=1):
        year = int(period[:4])
        unit = f"x.{brand}.{model}".lower().replace(" ", "_") + str(len(list(self.conn.execute('select 1 from fact_registration'))))
        self.conn.execute(
            "INSERT INTO dim_unit (unit_id,catalog_year,grain,brand,model,powertrain,"
            "powertrain_group,market_powertrain,market_scope,is_electrified,is_plug_in) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (unit, year, "MODEL", brand, model, base,
             "HYBRID" if base in {"HEV","PHEV","REEV"} else "COMBUSTION",
             "HYBRID" if base == "HEV" else "PLUGIN" if base == "PHEV" else
             "REEV" if base == "REEV" else "ELECTRIC" if base == "BEV" else "FUEL",
             "CORE", 0 if base == "ICE" else 1, 1 if base in {"PHEV","REEV","BEV"} else 0)
        )
        self.conn.execute(
            "INSERT INTO fact_registration "
            "(period,registration_type,province,unit_id,grain,units,source_id,raw_label) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (period, "RY1", "ALL", unit, "MODEL", units, self.source, raw))

    def values(self, field="powertrain"):
        return {r[field]: r["units"] for r in run(self.conn, [field]).rows}

    def test_honda_crv_cutoff(self):
        self.add("2025-11", "Honda", "CR-V", "HEV", "CR-V")
        self.add("2025-12", "Honda", "CR-V", "MIXED", "CR-V")
        self.assertEqual(self.values(), {"HEV": 1, "MIXED": 1})

    def test_deepal_s05_uses_source_label(self):
        self.add("2026-08", "Deepal", "Deepal S05", "MIXED", "S05 MAX")
        self.add("2026-08", "Deepal", "Deepal S05", "MIXED", "S05 REEV MAX")
        self.assertEqual(self.values(), {"BEV": 1, "REEV": 1})

    def test_denza_bare_d9_defaults_bev_but_explicit_phev_wins(self):
        self.add("2026-08", "Denza", "Denza D9", "MIXED", "DENZA D9 AWD")
        self.add("2026-08", "Denza", "Denza D9", "MIXED", "D9 PHEV")
        self.assertEqual(self.values(), {"BEV": 1, "PHEV": 1})

    def test_camry_and_corolla_cross_cutoffs(self):
        self.add("2024-09", "Toyota", "Camry", "HEV", "Camry")
        self.add("2024-10", "Toyota", "Camry", "MIXED", "Camry")
        self.add("2025-12", "Toyota", "Corolla Cross", "HEV", "COROLLA CROSS")
        self.add("2026-01", "Toyota", "Corolla Cross", "MIXED", "COROLLA CROSS")
        self.assertEqual(self.values(), {"HEV": 2, "MIXED": 2})

    def test_bmw_family_can_be_deliberately_mixed(self):
        self.add("2026-08", "BMW", "5 Series", "PHEV", "5 SERIES")
        self.assertEqual(self.values(), {"MIXED": 1})

    def test_lexus_es_new_generation_fallback(self):
        self.add("2026-08", "Lexus", "ES", "HEV", "ES300h")
        self.add("2026-08", "Lexus", "ES", "HEV", "ES350e")
        self.add("2026-08", "Lexus", "ES", "HEV", "ES")
        self.assertEqual(self.values(), {"BEV": 1, "HEV": 1, "MIXED": 1})

    def test_reader_bucket_moves_with_override(self):
        self.add("2026-08", "Deepal", "Deepal S05", "MIXED", "S05 REEV MAX")
        self.assertEqual(self.values("market_powertrain"), {"REEV": 1})

    def test_reviewed_key_is_punctuation_insensitive_and_volvo_wildcard(self):
        self.assertTrue(is_owner_reviewed("HONDA", "CR V"))
        self.assertTrue(is_owner_reviewed("Volvo", "XC40"))
        self.assertFalse(is_owner_reviewed("Porsche", "Cayenne"))


if __name__ == "__main__":
    unittest.main()
