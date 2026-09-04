from pathlib import Path

from vehreg.db import connect
from vehreg.provincial import (
    PublishedModelRule,
    ensure_schema,
    geographic_profile,
    normalize_province,
    period_from_thai,
    registration_type,
    region_for,
)


def _model(conn, unit_id: str, brand: str, model: str) -> None:
    conn.execute(
        "INSERT INTO dim_unit(unit_id,catalog_year,grain,brand,model,market_scope) "
        "VALUES (?,2026,'MODEL',?,?,'CORE')",
        (unit_id, brand, model),
    )


def _source(conn) -> int:
    conn.execute("INSERT INTO dim_source(name,publisher) VALUES ('prov-test','DLT')")
    conn.commit()
    return int(
        conn.execute("SELECT source_id FROM dim_source WHERE name='prov-test'").fetchone()[0]
    )


def test_thai_period_registration_and_province_normalization():
    assert period_from_thai("2569", "กรกฎาคม") == "2026-07"
    assert period_from_thai(2026, 7) == "2026-07"
    assert registration_type("รย.1 รถยนต์นั่งส่วนบุคคลไม่เกิน 7 คน") == "RY1"
    assert registration_type("RY3 private goods") == "RY3"
    assert normalize_province("จังหวัดกรุงเทพฯ") == "กรุงเทพมหานคร"
    assert region_for("ขอนแก่น") == "NORTHEAST"


def test_geographic_overindex_uses_same_curated_competitive_set():
    conn = connect(":memory:")
    ensure_schema(conn)
    source_id = _source(conn)
    _model(conn, "toyota.hilux", "Toyota", "Hilux Revo")
    _model(conn, "isuzu.dmax", "Isuzu", "D-Max")

    rows = [
        # Bangkok: Hilux 50%, Khon Kaen: Hilux 20%; nationwide Hilux 35%.
        ("กรุงเทพมหานคร", "toyota.hilux", 50),
        ("กรุงเทพมหานคร", "isuzu.dmax", 50),
        ("ขอนแก่น", "toyota.hilux", 20),
        ("ขอนแก่น", "isuzu.dmax", 80),
    ]
    conn.executemany(
        "INSERT INTO fact_registration_province "
        "(period,registration_type,province,model_id,units,source_id,raw_brand,raw_model) "
        "VALUES ('2026-07','RY1',?,?,?,?,?,?)",
        [
            (
                province,
                model_id,
                units,
                source_id,
                "Toyota" if model_id.startswith("toyota") else "Isuzu",
                "Hilux" if model_id.startswith("toyota") else "D-Max",
            )
            for province, model_id, units in rows
        ],
    )
    conn.commit()

    hilux = PublishedModelRule(
        "PICKUP", "Pickup", "Hilux", "Toyota", "Hilux%", 10, True, ""
    )
    dmax = PublishedModelRule(
        "PICKUP", "Pickup", "D-Max", "Isuzu", "%D-Max%", 20, True, ""
    )
    profile = geographic_profile(
        conn, hilux, [hilux, dmax], "2026-07", "2026-07", registration_types=["RY1"]
    )
    by_province = {row["province"]: row for row in profile}

    assert round(by_province["กรุงเทพมหานคร"]["national_category_share"], 3) == 0.35
    assert round(by_province["กรุงเทพมหานคร"]["local_category_share"], 3) == 0.50
    assert round(by_province["กรุงเทพมหานคร"]["over_index"], 3) == 1.429
    assert round(by_province["ขอนแก่น"]["local_category_share"], 3) == 0.20
    assert round(by_province["ขอนแก่น"]["over_index"], 3) == 0.571
    conn.close()
