from pathlib import Path

RULES_PATH = Path('vehreg/powertrain_rules.py')
TEST_PATH = Path('tests/test_owner_powertrain_batch3.py')

rules = RULES_PATH.read_text(encoding='utf-8')
anchor = '    # Mazda: petrol/diesel/mild-hybrid all fold to ICE in this taxonomy.\n'
if '    # Owner batch 3: clear the remaining reviewed worklist.\n' not in rules:
    block = '''    # Owner batch 3: clear the remaining reviewed worklist.
    # Most entries are direct owner approval of the existing catalog assumption.
    R("Jaecoo", "Jaecoo 5 EV", "BEV"),
    R("Honda", "Jazz", "ICE"),
    R("MG", "MG S5 EV", "BEV"),
    R("BYD", "Sealion 7", "BEV"),
    R("Suzuki", "Suzuki Carry", "ICE"),
    R("BYD", "Seal", "BEV"),
    R("MG", "MG EP", "BEV"),
    R("MG", "MG Extender Double Cab", "ICE"),
    R("Isuzu", "Isuzu Elf", "ICE"),
    R("Chery", "Chery V23", "BEV"),
    R("Jaecoo", "Jaecoo 6 EV", "BEV"),
    R("Toyota", "Vios", "ICE"),
    R("Toyota", "Hiace Majesty", "ICE"),
    R("Changan", "Changan Lumin", "BEV"),
    R("Hyundai", "H-1", "ICE"),
    R("Suzuki", "Ciaz", "ICE"),
    R("BMW", "2 Series Gran Coupe", "ICE"),
    R("Mazda", "CX-8", "ICE"),
    R("Mercedes-Benz", "CLS", "ICE"),
    R("Nissan", "Terra", "ICE"),
    R("XPeng", "XPeng G6", "BEV"),
    R("MG", "MG VS HEV", "HEV"),
    R("Geely", "Geely EX5", "BEV"),
    R("Honda", "BR-V", "ICE"),
    R("Chery", "Omoda C5", "BEV"),
    R("MG", "MG Extender Cab", "ICE"),
    R("Nissan", "March", "ICE"),
    R("BYD", "BYD M6", "BEV"),
    R("Zeekr", "Zeekr X", "BEV"),
    R("Zeekr", "Zeekr 009", "BEV"),
    R("Honda", "WR-V", "ICE"),
    R("Nissan", "Note", "ICE"),
    R("Toyota", "Hiace", "ICE"),

    # MINI Countryman: the DLT history is ICE, then the U25 BEV appears as
    # Countryman SE ALL4 from 2024-11. ICE Countryman S/JCW registrations
    # continue alongside it, so explicit labels win over the current default.
    R("MINI", "Countryman", "BEV", raw_any=("COUNTRYMAN SE", "ELECTRIC")),
    R("MINI", "Countryman", "ICE", raw_any=("COOPER S COUNTRYMAN", "COUNTRYMAN S", "JCW COUNTRYMAN", "COOPER SD")),
    R("MINI", "Countryman", "ICE", end="2024-10"),
    R("MINI", "Countryman", "BEV", start="2024-11"),

    R("Nissan", "Serena", "HEV"),
    R("Hyundai", "Stargazer", "ICE"),
    R("Suzuki", "Ertiga", "ICE"),
    R("XPeng", "XPeng X9", "BEV"),
    R("Hino", "Hino Truck", "ICE"),
    R("Mazda", "BT-50 Double Cab", "ICE"),
    R("Toyota", "Sienta", "ICE"),
    R("MG", "MG IM6", "BEV"),
    R("Mazda", "BT-50 Cab", "ICE"),
    R("BMW", "iX3", "BEV"),

    # Audi A5: e-hybrid first appears in DLT in 2025-11. Legacy 40/45 TFSI
    # registrations continue after that, so keep those exact while the current
    # bare-nameplate default follows the owner's PHEV call.
    R("Audi", "A5", "PHEV", raw_any=("E-HYBRID", "PHEV", "PLUG-IN")),
    R("Audi", "A5", "ICE", raw_any=("40 TFSI", "45 TFSI", "2.0T FSI")),
    R("Audi", "A5", "ICE", end="2025-10"),
    R("Audi", "A5", "PHEV", start="2025-11"),

    R("BMW", "X4", "ICE"),
    R("BYD", "Seal 5 DM-i", "PHEV"),
    R("MG", "MG Maxus 9", "BEV"),
    R("Toyota", "Land Cruiser 300", "ICE"),

    # MINI Cooper also spans generations in this DLT window. Explicit old ICE
    # body/engine labels stay ICE; Electric/E/SE labels are BEV. A bare current
    # Cooper defaults BEV from the J01 launch window.
    R("MINI", "Cooper", "BEV", raw_any=("ELECTRIC", "COOPER SE", "COOPER E")),
    R("MINI", "Cooper", "ICE", raw_any=("COOPER S ", "COOPER D", "JOHN COOPER WORKS", "CLUBMAN", "CABRIO", "CONVERTIBLE", "HATCH", "5-TURER", "PACEMAN")),
    R("MINI", "Cooper", "ICE", end="2024-05"),
    R("MINI", "Cooper", "BEV", start="2024-06"),

    R("Hyundai", "Creta", "ICE"),
    R("Riddara", "Riddara RD6 Double Cab", "BEV"),
    R("Deepal", "Deepal L07", "BEV"),
    R("Kia", "EV5", "BEV"),
    R("Foton", "Foton Truck", "ICE"),
    R("Porsche", "Taycan", "BEV"),
    R("Honda", "Step WGN", "HEV"),
    R("Avatr", "Avatr 11", "BEV"),

    # Owner default: 4 Series = BEV. Existing DLT rows through 2026-08 are
    # explicitly 420/430/M440 (plus one stray 840i), all combustion; preserve
    # those exact source labels as ICE rather than rewriting historical facts.
    R("BMW", "4 Series", "ICE", raw_any=("420I", "420D", "430I", "430D", "M440I", "840I")),
    R("BMW", "4 Series", "BEV"),

    R("MG", "MG ES", "BEV"),
    R("Audi", "TT", "ICE"),
    R("Toyota", "bZ4X", "BEV"),
    R("Jaecoo", "Jaecoo 7", "PHEV"),
    R("BMW", "iX", "BEV"),
    R("MINI", "Aceman", "BEV"),

'''
    if anchor not in rules:
        raise SystemExit('powertrain rule insertion anchor not found')
    rules = rules.replace(anchor, block + anchor)
    RULES_PATH.write_text(rules, encoding='utf-8')

TEST_PATH.write_text('''import unittest\n\nfrom vehreg import db\nfrom vehreg.cube import run\nfrom vehreg.powertrain_rules import is_owner_reviewed\n\n\nclass OwnerPowertrainBatch3Tests(unittest.TestCase):\n    def setUp(self):\n        self.conn = db.connect(\":memory:\")\n        self.source = db.register_source(self.conn, \"test\")\n\n    def add(self, period, brand, model, base, raw, units=1):\n        year = int(period[:4])\n        unit = f\"x.{brand}.{model}.{raw}\".lower().replace(\" \", \"_\")\n        self.conn.execute(\n            \"INSERT INTO dim_unit (unit_id,catalog_year,grain,brand,model,powertrain,\"\n            \"powertrain_group,market_powertrain,market_scope,is_electrified,is_plug_in) \"\n            \"VALUES (?,?,?,?,?,?,?,?,?,?,?)\",\n            (unit, year, \"MODEL\", brand, model, base,\n             \"HYBRID\" if base in {\"HEV\",\"PHEV\",\"REEV\"} else \"ZERO_EMISSION\" if base == \"BEV\" else \"COMBUSTION\",\n             \"HYBRID\" if base == \"HEV\" else \"PLUGIN\" if base == \"PHEV\" else \"ELECTRIC\" if base == \"BEV\" else \"FUEL\",\n             \"CORE\", 0 if base == \"ICE\" else 1, 1 if base in {\"PHEV\",\"REEV\",\"BEV\"} else 0)\n        )\n        self.conn.execute(\n            \"INSERT INTO fact_registration \"\n            \"(period,registration_type,province,unit_id,grain,units,source_id,raw_label) \"\n            \"VALUES (?,?,?,?,?,?,?,?)\",\n            (period, \"RY1\", \"ALL\", unit, \"MODEL\", units, self.source, raw))\n\n    def values(self):\n        return {r[\"powertrain\"]: r[\"units\"] for r in run(self.conn, [\"powertrain\"]).rows}\n\n    def test_countryman_period_and_explicit_labels(self):\n        self.add(\"2023-06\", \"MINI\", \"Countryman\", \"BEV\", \"MINI Cooper S Countryman RHD\")\n        self.add(\"2025-06\", \"MINI\", \"Countryman\", \"BEV\", \"MINI Countryman S ALL4\")\n        self.add(\"2025-06\", \"MINI\", \"Countryman\", \"ICE\", \"MINI Countryman SE ALL4 RHD\")\n        self.add(\"2025-06\", \"MINI\", \"Countryman\", \"ICE\", \"MINI Countryman\")\n        self.assertEqual(self.values(), {\"BEV\": 2, \"ICE\": 2})\n\n    def test_a5_current_default_and_explicit_legacy(self):\n        self.add(\"2025-10\", \"Audi\", \"A5\", \"ICE\", \"AUDI A5\")\n        self.add(\"2025-12\", \"Audi\", \"A5\", \"ICE\", \"AUDI A5\")\n        self.add(\"2026-01\", \"Audi\", \"A5\", \"ICE\", \"AUDI A5 SB e-hybrid q Tech Pro\")\n        self.add(\"2026-01\", \"Audi\", \"A5\", \"PHEV\", \"AUDI A5 CP 40 TFSI S line eo\")\n        self.assertEqual(self.values(), {\"ICE\": 2, \"PHEV\": 2})\n\n    def test_note_serena_step_wgn(self):\n        self.add(\"2026-08\", \"Nissan\", \"Note\", \"BEV\", \"NOTE\")\n        self.add(\"2026-08\", \"Nissan\", \"Serena\", \"ICE\", \"SERENA\")\n        self.add(\"2026-08\", \"Honda\", \"Step WGN\", \"ICE\", \"STEP WGN\")\n        self.assertEqual(self.values(), {\"HEV\": 2, \"ICE\": 1})\n\n    def test_four_series_owner_default_preserves_explicit_ice(self):\n        self.add(\"2026-08\", \"BMW\", \"4 Series\", \"ICE\", \"BMW 430i Coupe RHD\")\n        self.add(\"2026-08\", \"BMW\", \"4 Series\", \"ICE\", \"BMW 4 Series\")\n        self.assertEqual(self.values(), {\"BEV\": 1, \"ICE\": 1})\n\n    def test_remaining_batch_is_reviewed(self):\n        for brand, model in [\n            (\"Jaecoo\", \"Jaecoo 5 EV\"), (\"Honda\", \"Jazz\"),\n            (\"MG\", \"MG S5 EV\"), (\"BYD\", \"Sealion 7\"),\n            (\"Audi\", \"A5\"), (\"MINI\", \"Countryman\"),\n            (\"MINI\", \"Cooper\"), (\"BMW\", \"4 Series\"),\n            (\"Honda\", \"Step WGN\"), (\"BMW\", \"iX\"),\n            (\"MINI\", \"Aceman\"),\n        ]:\n            self.assertTrue(is_owner_reviewed(brand, model), (brand, model))\n\n\nif __name__ == \"__main__\":\n    unittest.main()\n''', encoding='utf-8')
print('patched owner powertrain batch3 rules and tests')
