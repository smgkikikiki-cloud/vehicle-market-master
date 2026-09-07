from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace(path: str, old: str, new: str) -> None:
    p = ROOT / path
    text = p.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"expected text not found in {path}: {old[:80]!r}")
    p.write_text(text.replace(old, new, 1), encoding="utf-8")


# Canonical policy: REEV/EREV is its own reader-facing category when the maker
# markets the vehicle that way. Nissan e-Power remains HEV; do not infer REEV
# merely from the generic phrase "range extender".
replace(
    "vehreg/taxonomy.py",
    '    REEV is reserved for a car that is charged from a socket and carries an\n'
    '    engine for when the battery runs out - a Deepal S05 REEV, a Geely EX5 REEV.\n'
    '    It is NOT Nissan e-Power, whose battery is only ever charged by its own\n'
    '    engine and which has no socket at all; that is HEV.\n',
    '    REEV is a market label, not a guess from drivetrain architecture. Use it\n'
    '    when the manufacturer markets the vehicle as REEV/EREV. Nissan e-Power\n'
    '    remains HEV in this catalog; a generic "range extender" description is\n'
    '    not enough to reclassify it as REEV.\n',
)
replace(
    "vehreg/taxonomy.py",
    'class MarketPowertrain(Facet):\n'
    '    """The four buckets a Thai showroom, and the site, actually sell in.\n',
    'class MarketPowertrain(Facet):\n'
    '    """Reader-facing market buckets.\n',
)
replace(
    "vehreg/taxonomy.py",
    '    FUEL = "FUEL"            # ICE, mild hybrids included\n'
    '    HYBRID = "HYBRID"        # HEV and REEV: electrified, no plug\n'
    '    PLUGIN = "PLUGIN"        # PHEV: a plug and an engine\n'
    '    ELECTRIC = "ELECTRIC"    # BEV and FCEV\n',
    '    FUEL = "FUEL"            # ICE, mild hybrids included\n'
    '    HYBRID = "HYBRID"        # HEV, including Nissan e-Power\n'
    '    PLUGIN = "PLUGIN"        # PHEV\n'
    '    REEV = "REEV"            # maker-positioned REEV / EREV\n'
    '    ELECTRIC = "ELECTRIC"    # BEV and FCEV\n',
)
replace(
    "vehreg/taxonomy.py",
    '    Powertrain.HEV: MarketPowertrain.HYBRID,\n'
    '    Powertrain.REEV: MarketPowertrain.HYBRID,\n'
    '    Powertrain.PHEV: MarketPowertrain.PLUGIN,\n',
    '    Powertrain.HEV: MarketPowertrain.HYBRID,\n'
    '    Powertrain.REEV: MarketPowertrain.REEV,\n'
    '    Powertrain.PHEV: MarketPowertrain.PLUGIN,\n',
)
replace(
    "vehreg/taxonomy.py",
    '#: Thai labels for the four, for anything reader-facing.\n'
    'MARKET_POWERTRAIN_TH: dict[str, str] = {\n'
    '    MarketPowertrain.FUEL.value: "น้ำมัน/ดีเซล",\n'
    '    MarketPowertrain.HYBRID.value: "ไฮบริด",\n'
    '    MarketPowertrain.PLUGIN.value: "ปลั๊กอินไฮบริด",\n'
    '    MarketPowertrain.ELECTRIC.value: "ไฟฟ้า",\n',
    '#: Thai labels for reader-facing market buckets.\n'
    'MARKET_POWERTRAIN_TH: dict[str, str] = {\n'
    '    MarketPowertrain.FUEL.value: "น้ำมัน/ดีเซล",\n'
    '    MarketPowertrain.HYBRID.value: "ไฮบริด",\n'
    '    MarketPowertrain.PLUGIN.value: "ปลั๊กอินไฮบริด",\n'
    '    MarketPowertrain.REEV.value: "REEV",\n'
    '    MarketPowertrain.ELECTRIC.value: "ไฟฟ้า",\n',
)
replace(
    "vehreg/taxonomy.py",
    '        "PHEV": "ปลั๊กอินไฮบริด", "REEV": "อีวีเพิ่มระยะทาง",\n',
    '        "PHEV": "ปลั๊กอินไฮบริด", "REEV": "REEV",\n',
)
replace(
    "vehreg/taxonomy.py",
    '        "PLUG_IN_HYBRID": "PHEV", "PLUGIN": "PHEV",\n'
    '        "EREV": "REEV", "RANGE_EXTENDER": "REEV", "GASOLINE": "ICE",\n',
    '        "PLUG_IN_HYBRID": "PHEV", "PLUGIN": "PHEV",\n'
    '        # Only the explicit maker labels REEV/EREV map here. Generic\n'
    '        # RANGE_EXTENDER is ambiguous (notably Nissan e-Power) and must\n'
    '        # not auto-classify a vehicle as REEV.\n'
    '        "EREV": "REEV", "GASOLINE": "ICE",\n',
)

# Main dashboard: expose the new reader-facing category explicitly.
replace(
    "app.py",
    '["ALL", "FUEL", "HYBRID", "PLUGIN", "ELECTRIC", "MIXED", "UNKNOWN"],\n',
    '["ALL", "FUEL", "HYBRID", "PLUGIN", "REEV", "ELECTRIC", "MIXED", "UNKNOWN"],\n',
)
replace(
    "app.py",
    '    help="สี่หมวดที่หน้าเว็บใช้จริง — mild hybrid นับเป็นน้ำมัน และ e-Power "\n'
    '         "นับเป็นไฮบริด กรองแบบละเอียดอยู่ช่องถัดไป",\n',
    '    help="หมวดที่หน้าเว็บใช้จริง — mild hybrid นับเป็นน้ำมัน, e-Power "\n'
    '         "อยู่ HEV/ไฮบริด และรถที่ผู้ผลิตเรียก REEV/EREV แยกเป็น REEV",\n',
)

# Keep comments/docs from teaching the old four-bucket rule to the next agent.
replace(
    "vehreg/db.py",
    '        # The four buckets the site sells in. Derived, so a rebuild fills it;\n',
    '        # Reader-facing powertrain buckets. Derived, so a rebuild fills it;\n',
)
replace(
    "docs/HANDOVER.md",
    '**Four buckets for anything reader-facing.** `market_powertrain` is\n'
    'FUEL / HYBRID / PLUGIN / ELECTRIC with Thai labels. Group and filter by it on\n'
    'any page. The seven-code `powertrain` stays for analysis.\n',
    '**Reader-facing powertrain buckets.** `market_powertrain` is\n'
    'FUEL / HYBRID / PLUGIN / REEV / ELECTRIC. HEV includes Nissan e-Power;\n'
    'REEV stays separate and is used when the manufacturer markets the vehicle as\n'
    'REEV/EREV. Do not infer REEV from the generic phrase "range extender". The\n'
    'seven-code `powertrain` stays for analysis.\n',
)

# Regression coverage: HEV/e-Power policy and explicit REEV must never collapse
# back into one reader-facing bucket.
replace(
    "tests/test_vehreg.py",
    '        self.assertIs(taxonomy.powertrain_group(Powertrain.parse("MHEV")),\n'
    '                      taxonomy.PowertrainGroup.COMBUSTION)\n'
    '        self.assertTrue(taxonomy.is_plug_in(Powertrain.PHEV))\n',
    '        self.assertIs(taxonomy.powertrain_group(Powertrain.parse("MHEV")),\n'
    '                      taxonomy.PowertrainGroup.COMBUSTION)\n'
    '        self.assertIs(taxonomy.market_powertrain(Powertrain.HEV),\n'
    '                      taxonomy.MarketPowertrain.HYBRID)\n'
    '        self.assertIs(taxonomy.market_powertrain(Powertrain.REEV),\n'
    '                      taxonomy.MarketPowertrain.REEV)\n'
    '        self.assertIs(Powertrain.parse("EREV"), Powertrain.REEV)\n'
    '        with self.assertRaises(ValueError):\n'
    '            Powertrain.parse("RANGE_EXTENDER")\n'
    '        self.assertTrue(taxonomy.is_plug_in(Powertrain.PHEV))\n',
)

# Remove the one-shot machinery from the resulting commit.
(ROOT / "tools" / "_apply_reev_policy.py").unlink()
(ROOT / ".github" / "workflows" / "_apply_reev_policy.yml").unlink()
