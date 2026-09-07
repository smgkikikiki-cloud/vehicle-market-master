import unittest

from vehreg import db
from vehreg.cube import run
from vehreg.powertrain_rules import is_owner_reviewed


class OwnerPowertrainBatch3Tests(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")
        self.source = db.register_source(self.conn, "test")
        self.seq = 0

    def add(self, period, brand, model, base, raw, units=1):
        year = int(period[:4])
        self.seq += 1
        unit = f"x.{self.seq}.{brand}.{model}.{raw}".lower().replace(" ", "_")
        self.conn.execute(
            "INSERT INTO dim_unit (unit_id,catalog_year,grain,brand,model,powertrain,"
            "powertrain_group,market_powertrain,market_scope,is_electrified,is_plug_in) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (unit, year, "MODEL", brand, model, base,
             "HYBRID" if base in {"HEV","PHEV","REEV"} else "ZERO_EMISSION" if base == "BEV" else "COMBUSTION",
             "HYBRID" if base == "HEV" else "PLUGIN" if base == "PHEV" else "ELECTRIC" if base == "BEV" else "FUEL",
             "CORE", 0 if base == "ICE" else 1, 1 if base in {"PHEV","REEV","BEV"} else 0)
        )
        self.conn.execute(
            "INSERT INTO fact_registration "
            "(period,registration_type,province,unit_id,grain,units,source_id,raw_label) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (period, "RY1", "ALL", unit, "MODEL", units, self.source, raw))

    def values(self):
        return {r["powertrain"]: r["units"] for r in run(self.conn, ["powertrain"]).rows}

    def test_countryman_period_and_explicit_labels(self):
        self.add("2023-06", "MINI", "Countryman", "BEV", "MINI Cooper S Countryman RHD")
        self.add("2025-06", "MINI", "Countryman", "BEV", "MINI Countryman S ALL4")
        self.add("2025-06", "MINI", "Countryman", "ICE", "MINI Countryman SE ALL4 RHD")
        self.add("2025-06", "MINI", "Countryman", "ICE", "MINI Countryman")
        self.assertEqual(self.values(), {"BEV": 2, "ICE": 2})

    def test_a5_current_default_and_explicit_legacy(self):
        self.add("2025-10", "Audi", "A5", "ICE", "AUDI A5")
        self.add("2025-12", "Audi", "A5", "ICE", "AUDI A5")
        self.add("2026-01", "Audi", "A5", "ICE", "AUDI A5 SB e-hybrid q Tech Pro")
        self.add("2026-01", "Audi", "A5", "PHEV", "AUDI A5 CP 40 TFSI S line eo")
        self.assertEqual(self.values(), {"ICE": 2, "PHEV": 2})

    def test_note_serena_step_wgn(self):
        self.add("2026-08", "Nissan", "Note", "BEV", "NOTE")
        self.add("2026-08", "Nissan", "Serena", "ICE", "SERENA")
        self.add("2026-08", "Honda", "Step WGN", "ICE", "STEP WGN")
        self.assertEqual(self.values(), {"HEV": 2, "ICE": 1})

    def test_four_series_owner_default_preserves_explicit_ice(self):
        self.add("2026-08", "BMW", "4 Series", "ICE", "BMW 430i Coupe RHD")
        self.add("2026-08", "BMW", "4 Series", "ICE", "BMW 4 Series")
        self.assertEqual(self.values(), {"BEV": 1, "ICE": 1})

    def test_remaining_batch_is_reviewed(self):
        for brand, model in [
            ("Jaecoo", "Jaecoo 5 EV"), ("Honda", "Jazz"),
            ("MG", "MG S5 EV"), ("BYD", "Sealion 7"),
            ("Audi", "A5"), ("MINI", "Countryman"),
            ("MINI", "Cooper"), ("BMW", "4 Series"),
            ("Honda", "Step WGN"), ("BMW", "iX"),
            ("MINI", "Aceman"),
        ]:
            self.assertTrue(is_owner_reviewed(brand, model), (brand, model))


if __name__ == "__main__":
    unittest.main()
