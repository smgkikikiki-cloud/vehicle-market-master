from vehreg.catalog import Catalog
from vehreg.taxonomy import Powertrain


MODEL_ID = "chery.jaecoo_j5"


def test_jaecoo_5_has_retail_trim_catalog_without_changing_registration_grain():
    catalog = Catalog.load(year=2026)
    trims = {trim.name: trim for trim in catalog.trims_of(MODEL_ID)}

    assert set(trims) == {
        "Long Range Dynamic",
        "Long Range Max",
        "MAX+",
        "ULTRA",
    }
    assert all(trim.powertrain is Powertrain.BEV for trim in trims.values())
    assert all(trim.drivetrain.value == "FWD" for trim in trims.values())
    assert all(trim.tire_front == "235/55 R18" for trim in trims.values())
    assert all(trim.tire_rear == "235/55 R18" for trim in trims.values())
    assert all(trim.length_mm == 4380 for trim in trims.values())
    assert all(trim.width_mm == 1860 for trim in trims.values())
    assert all(trim.height_mm == 1650 for trim in trims.values())
    assert all(trim.wheelbase_mm == 2620 for trim in trims.values())

    # Retail price has one authority: the separate PriceLedger.
    assert all(trim.price_thb is None for trim in trims.values())

    assert trims["Long Range Dynamic"].source_refs["ecosticker"] == (
        "d744d9f3-d393-4ac3-b441-17a022098fed",
    )
    assert trims["Long Range Max"].source_refs["ecosticker"] == (
        "b4529bb4-d813-416b-b272-430b123cc06c",
    )
    assert trims["MAX+"].source_refs["ecosticker"] == (
        "98c1d7de-79db-4581-b332-69abe657a532",
    )
    assert "ecosticker" not in trims["ULTRA"].source_refs

    # Market trims are catalog enrichment. Registration analytics still sees
    # analytical variants only and therefore cannot allocate volume by trim.
    resolved_ids = {row.variant_id for row in catalog.iter_resolved()}
    assert all(".trim." not in vehicle_id for vehicle_id in resolved_ids)
    assert not any(trim.id in resolved_ids for trim in trims.values())


def test_jaecoo_5_trim_ids_include_retail_identity_not_price_or_tyre():
    catalog = Catalog.load(year=2026)
    trims = {trim.name: trim for trim in catalog.trims_of(MODEL_ID)}

    assert trims["Long Range Dynamic"].id == (
        "chery.jaecoo_j5.j5.trim.long_range_dynamic_bev"
    )
    assert trims["Long Range Max"].id == (
        "chery.jaecoo_j5.j5.trim.long_range_max_bev"
    )
    assert trims["MAX+"].id == "chery.jaecoo_j5.j5.trim.max_plus_bev"
    assert trims["ULTRA"].id == "chery.jaecoo_j5.j5.trim.ultra_bev"
