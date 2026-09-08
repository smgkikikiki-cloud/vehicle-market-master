import json
from pathlib import Path

from vehreg.catalog import Catalog
from vehreg.homologation import ECOStickerSpecStore, spec_dir


MODEL_ID = "jaecoo.jaecoo_5_ev"
DYNAMIC = "jaecoo.jaecoo_5_ev.j5.trim.long_range_dynamic_bev"
LONG_MAX = "jaecoo.jaecoo_5_ev.j5.trim.long_range_max_bev"
MAX_PLUS = "jaecoo.jaecoo_5_ev.j5.trim.max_plus_bev"
ULTRA = "jaecoo.jaecoo_5_ev.j5.trim.ultra_bev"


def test_jaecoo_5_ecosticker_phase1_specs_load_and_match_market_trims():
    catalog = Catalog.load(year=2026)
    store = ECOStickerSpecStore.load(year=2026, catalog=catalog)

    assert set(store.records) >= {DYNAMIC, LONG_MAX, MAX_PLUS}
    assert ULTRA not in store.records
    assert store.validate_against_catalog() == []

    dynamic = store.get(DYNAMIC)
    assert dynamic is not None
    assert dynamic.chassis_code == "T361"
    assert dynamic.battery_chemistry == "LFP"
    assert dynamic.battery_supplier == "CATL"
    assert dynamic.battery_voltage_v == 360.2
    assert dynamic.declared_total_weight_kg == 1715
    assert dynamic.factory == "China, Chery Automobile Co., Ltd."
    assert dynamic.rated_range_km == 461.0
    assert dynamic.tire_size == "235/55R18"
    assert dynamic.seats == 5
    assert dynamic.powertrain.value == "BEV"

    long_max = store.get(LONG_MAX)
    assert long_max is not None
    assert long_max.chassis_code == "T361"
    assert long_max.battery_supplier == "CATL"
    assert long_max.battery_voltage_v == 360.2
    assert long_max.declared_total_weight_kg == 1715
    assert long_max.rated_range_km == 461.0

    max_plus = store.get(MAX_PLUS)
    assert max_plus is not None
    assert max_plus.chassis_code == "T361"
    assert max_plus.battery_chemistry == "LFP"
    assert max_plus.battery_supplier == "Hefei Gotion High-tech Power Energy Co., Ltd."
    assert max_plus.battery_voltage_v == 365.9
    assert max_plus.declared_total_weight_kg == 1645
    assert "ประเทศไทย" in max_plus.factory
    assert max_plus.rated_range_km == 405.0


def test_ecosticker_phase1_spec_file_contains_no_price_fields():
    path = spec_dir(Path("vehreg/data"), 2026) / "jaecoo.json"
    payload = json.loads(path.read_text(encoding="utf-8"))

    for row in payload["specs"]:
        assert not any("price" in key.lower() for key in row)


def test_ecosticker_spec_enrichment_does_not_change_registration_grain():
    catalog = Catalog.load(year=2026)
    before = [row.variant_id for row in catalog.iter_resolved()]

    store = ECOStickerSpecStore.load(year=2026, catalog=catalog)
    assert store.validate_against_catalog() == []

    after = [row.variant_id for row in catalog.iter_resolved()]
    assert after == before
    assert all(".trim." not in variant_id for variant_id in after)


def test_ecosticker_j5_coverage_is_explicit_about_what_the_source_has():
    catalog = Catalog.load(year=2026)
    store = ECOStickerSpecStore.load(year=2026, catalog=catalog)
    coverage = store.coverage()

    assert coverage["records"] >= 3
    assert coverage["with_chassis_code"] >= 3
    assert coverage["with_battery_chemistry"] >= 3
    assert coverage["with_battery_supplier"] >= 3
    assert coverage["with_battery_voltage"] >= 3
    assert coverage["with_declared_total_weight"] >= 3
    assert coverage["with_tire_size"] >= 3
    assert coverage["with_rated_range"] >= 3
