import unittest

from vehreg import db
from vehreg.catalog import Catalog, DATA_DIR
from vehreg.cube import run
from vehreg.powertrain_rules import is_owner_reviewed


class OwnerPowertrainBatch2Tests(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")
        self.source = db.register_source(self.conn, "test-batch2")

    def add(self, period, brand, model, base, raw, units=1):
        year = int(period[:4])
        n = self.conn.execute("select count(*) n from fact_registration").fetchone()["n"]
        unit = f"batch2.{brand}.{model}.{n}".lower().replace(" ", "_")
        group = (
            "HYBRID" if base in {"HEV", "PHEV", "REEV"}
            else "ZERO_EMISSION" if base in {"BEV", "FCEV"}
            else "COMBUSTION"
        )
        market = (
            "HYBRID" if base == "HEV" else "PLUGIN" if base == "PHEV" else
            "REEV" if base == "REEV" else "ELECTRIC" if base in {"BEV", "FCEV"}
            else "FUEL"
        )
        self.conn.execute(
            "INSERT INTO dim_unit (unit_id,catalog_year,grain,brand,model,powertrain,"
            "powertrain_group,market_powertrain,market_scope,is_electrified,is_plug_in) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (unit, year, "MODEL", brand, model, base, group, market, "CORE",
             0 if base == "ICE" else 1, 1 if base in {"PHEV", "REEV", "BEV"} else 0),
        )
        self.conn.execute(
            "INSERT INTO fact_registration "
            "(period,registration_type,province,unit_id,grain,units,source_id,raw_label) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (period, "RY1", "ALL", unit, "MODEL", units, self.source, raw),
        )

    def values(self):
        return {r["powertrain"]: r["units"] for r in run(self.conn, ["powertrain"]).rows}

    def test_carnival_changes_from_ice_to_mixed_but_explicit_hev_wins(self):
        self.add("2025-10", "Kia", "Carnival", "ICE", "CARNIVAL")
        self.add("2025-11", "Kia", "Carnival", "ICE", "CARNIVAL")
        self.add("2026-08", "Kia", "Carnival", "ICE", "CARNIVAL HEV 7P LUXURY")
        self.assertEqual(self.values(), {"HEV": 1, "ICE": 1, "MIXED": 1})

    def test_s07_sealion6_and_staria_owner_defaults(self):
        self.add("2026-08", "Deepal", "Deepal S07", "MIXED", "S07")
        self.add("2026-08", "BYD", "Sealion 6 DM-i", "MIXED", "BYD SEALION 6")
        self.add("2026-08", "Hyundai", "Staria", "MIXED", "STARIA")
        self.assertEqual(self.values(), {"BEV": 1, "ICE": 1, "PHEV": 1})

    def test_porsche_generic_is_mixed_and_explicit_ehybrid_is_phev(self):
        self.add("2026-08", "Porsche", "Cayenne", "PHEV", "CAYENNE")
        self.add("2026-08", "Porsche", "Cayenne", "PHEV", "CAYENNE E-HYBRID COUPE")
        self.add("2026-08", "Porsche", "Panamera", "PHEV", "PANAMERA")
        self.assertEqual(self.values(), {"MIXED": 2, "PHEV": 1})

    def test_audi_q8_and_a8_rules_preserve_explicit_transition_labels(self):
        self.add("2024-02", "Audi", "A8", "ICE", "A8")
        self.add("2024-04", "Audi", "A8", "ICE", "A8 L TFSI E QUATTRO")
        self.add("2024-06", "Audi", "A8", "PHEV", "A8 L 55 TFSI q Premium")
        self.add("2024-06", "Audi", "A8", "ICE", "A8")
        self.add("2026-08", "Audi", "Q8", "ICE", "Q8")
        self.add("2026-08", "Audi", "Q8", "ICE", "Q8 60 TFSI e q S line BE")
        self.assertEqual(self.values(), {"ICE": 2, "MIXED": 2, "PHEV": 2})

    def test_range_rover_sport_and_velar_are_real_catalog_targets(self):
        for year in range(2021, 2027):
            cat = Catalog.load(DATA_DIR, year)
            sport, _, _ = cat.model_index.lookup("LAND ROVER RANGE ROVER SPORT 3.0 LITRE")
            velar, _, _ = cat.model_index.lookup("LAND ROVER RANGE ROVER VELAR 2.0 LITRE")
            base, _, _ = cat.model_index.lookup("LAND ROVER RANGE ROVER 3.0 LITRE")
            self.assertEqual(sport, "land_rover.range_rover_sport", year)
            self.assertEqual(velar, "land_rover.range_rover_velar", year)
            self.assertEqual(base, "land_rover.range_rover", year)

    def test_range_rover_sport_velar_powertrain_rules(self):
        self.add("2026-08", "Land Rover", "Range Rover Sport", "UNKNOWN", "RANGE ROVER SPORT")
        self.add("2026-08", "Land Rover", "Range Rover Sport", "UNKNOWN", "RANGE ROVER SPORT 3.0 L PHEV")
        self.add("2026-08", "Land Rover", "Range Rover Velar", "UNKNOWN", "RANGE ROVER VELAR")
        self.assertEqual(self.values(), {"MIXED": 2, "PHEV": 1})

    def test_batch2_models_are_owner_reviewed(self):
        for brand, model in (
            ("Kia", "Carnival"), ("Deepal", "Deepal S07"),
            ("BYD", "Sealion 6 DM-i"), ("Hyundai", "Staria"),
            ("Porsche", "Cayenne"), ("Porsche", "Panamera"),
            ("Land Rover", "Range Rover Sport"), ("Land Rover", "Range Rover Velar"),
            ("Audi", "Q8"), ("Audi", "A8"),
        ):
            with self.subTest(brand=brand, model=model):
                self.assertTrue(is_owner_reviewed(brand, model))


if __name__ == "__main__":
    unittest.main()
