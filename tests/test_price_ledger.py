from datetime import date

import pytest

from vehreg.catalog import Catalog
from vehreg.pricing import PriceLedger, PriceType, PricingError


TRIM_ID = "acme.one.g1.trim.premium_bev"


def catalog_with_trim():
    c = Catalog(2026)
    c.add_brand_payload({
        "brand": {"id": "acme", "name_en": "Acme", "name_th": ""},
        "models": [{
            "id": "one",
            "name_en": "One",
            "body_type": "CROSSOVER",
            "generations": [{
                "code": "G1",
                "segment": "C",
                "variants": [{
                    "name": "BEV",
                    "powertrain": "BEV",
                    "drivetrain": "FWD",
                    "battery_kwh": 60,
                    "import_type": "CBU",
                    "origin_country": "CN",
                }],
                "trims": [{
                    "id": "premium_bev",
                    "name": "Premium",
                    "variant": "BEV",
                    "powertrain": "BEV",
                    "battery_kwh": 60,
                    "tire_front": "235/55 R18",
                    "tire_rear": "235/55 R18",
                }],
            }],
        }],
    }, source="<price-test>")
    c.build_indexes()
    return c


def test_price_ledger_keeps_market_state_outside_trim_identity():
    catalog = catalog_with_trim()
    trim = catalog.trims[TRIM_ID]

    ledger = PriceLedger(2026, catalog=catalog)
    ledger.add_payload({"prices": [{
        "trim_id": TRIM_ID,
        "amount_thb": 999000,
        "price_type": "LIST_PRICE",
        "effective_from": "2026-01-01",
        "source": "official_oem",
        "source_ref": "price-list-2026-01",
    }]})

    assert trim.id == TRIM_ID
    assert trim.powertrain.value == "BEV"
    assert trim.tire_front == "235/55 R18"
    assert ledger.current_list_amount(TRIM_ID, as_of=date(2026, 2, 1)) == 999000
    # Registration analytics still resolves exactly one analytical variant.
    assert len(list(catalog.iter_resolved())) == 1


def test_ecosticker_price_never_becomes_canonical_list_price():
    catalog = catalog_with_trim()
    ledger = PriceLedger(2026, catalog=catalog)
    ledger.add_payload({"prices": [{
        "trim_id": TRIM_ID,
        "amount_thb": 879000,
        "price_type": "ECO_STICKER_PRICE",
        "observed_at": "2026-09-07",
        "source": "ecosticker",
        "source_ref": "eco-uuid",
    }]})

    latest = ledger.latest(TRIM_ID, price_type=PriceType.ECO_STICKER_PRICE)
    assert latest is not None
    assert latest.amount_thb == 879000
    assert ledger.current_list_price(TRIM_ID, as_of=date(2026, 9, 8)) is None


def test_price_history_is_time_scoped_and_easy_to_update():
    catalog = catalog_with_trim()
    ledger = PriceLedger(2026, catalog=catalog)
    ledger.add_payload({"prices": [
        {
            "trim_id": TRIM_ID,
            "amount_thb": 1099000,
            "price_type": "LIST_PRICE",
            "effective_from": "2026-01-01",
            "effective_to": "2026-05-31",
            "source": "official_oem",
        },
        {
            "trim_id": TRIM_ID,
            "amount_thb": 999000,
            "price_type": "LIST_PRICE",
            "effective_from": "2026-06-01",
            "source": "official_oem",
        },
        {
            "trim_id": TRIM_ID,
            "amount_thb": 949000,
            "price_type": "CAMPAIGN_PRICE",
            "effective_from": "2026-06-15",
            "effective_to": "2026-06-30",
            "source": "official_oem",
        },
    ]})

    assert ledger.current_list_amount(TRIM_ID, as_of=date(2026, 3, 1)) == 1099000
    assert ledger.current_list_amount(TRIM_ID, as_of=date(2026, 6, 20)) == 999000
    assert ledger.latest(TRIM_ID, price_type=PriceType.CAMPAIGN_PRICE).amount_thb == 949000


def test_price_ledger_fails_closed_on_unknown_trim():
    ledger = PriceLedger(2026, catalog=catalog_with_trim())
    with pytest.raises(PricingError, match="unknown trim_id"):
        ledger.add_payload({"prices": [{
            "trim_id": "acme.nope.g1.trim.fake",
            "amount_thb": 999000,
            "price_type": "LIST_PRICE",
            "effective_from": "2026-01-01",
        }]})


def test_2026_jaecoo_eco_prices_do_not_override_official_list():
    catalog = Catalog.load(year=2026)
    ledger = PriceLedger.load(year=2026, catalog=catalog)

    expected = {
        "chery.jaecoo_j5.j5.trim.long_range_dynamic_bev": 629000,
        "chery.jaecoo_j5.j5.trim.long_range_max_bev": 679000,
        "chery.jaecoo_j5.j5.trim.max_plus_bev": 699000,
    }
    for trim_id, amount in expected.items():
        row = ledger.latest(trim_id, price_type=PriceType.ECO_STICKER_PRICE)
        assert row is not None
        assert row.amount_thb == amount
        if trim_id.endswith("max_plus_bev"):
            current = ledger.current_list_price(trim_id, as_of=date(2026, 9, 8))
            assert current.source == "official_oem"
            assert current.amount_thb == 699000
            assert ledger.current_list_price(trim_id, as_of=date(2026, 9, 7)) is None
        else:
            assert ledger.current_list_price(trim_id, as_of=date(2026, 9, 8)) is None

    coverage = ledger.coverage(as_of=date(2026, 9, 8))
    assert coverage["records"] >= 3
    assert coverage["eco_sticker_price_records"] >= 3
    assert coverage["trims_with_current_list_price"] == 1
