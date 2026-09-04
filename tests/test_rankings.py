import sqlite3

from vehreg.db import connect
from vehreg.rankings import chinese_ev_trim_ranking, model_ranking


def _source(conn: sqlite3.Connection) -> int:
    conn.execute("INSERT INTO dim_source(name, publisher) VALUES ('test','DLT')")
    conn.commit()
    return int(conn.execute("SELECT source_id FROM dim_source WHERE name='test'").fetchone()[0])


def _model_dim(conn: sqlite3.Connection, unit_id: str, brand: str, model: str,
               powertrain: str, origin: str = "CN") -> None:
    conn.execute(
        "INSERT INTO dim_unit(unit_id,catalog_year,grain,brand,model,powertrain,"
        "brand_origin,market_scope) VALUES (?,?,?,?,?,?,?,?)",
        (unit_id, 2026, "MODEL", brand, model, powertrain, origin, "CORE"),
    )
    conn.commit()


def test_model_ranking_splits_deepal_s05_by_powertrain_when_dlt_does():
    conn = connect(":memory:")
    source_id = _source(conn)
    _model_dim(conn, "deepal.deepal_s05", "Deepal", "Deepal S05", "MIXED")

    rows = [
        ("S05 MAX", 1927),
        ("S05 PLUS", 92),
        ("S05 REEV MAX", 320),
    ]
    conn.executemany(
        "INSERT INTO fact_registration(period,registration_type,province,unit_id,"
        "grain,units,source_id,raw_label) VALUES ('2026-01','RY1','ALL',"
        "'deepal.deepal_s05','MODEL',?,?,?)",
        [(units, source_id, label) for label, units in rows],
    )
    conn.commit()

    ranked = model_ranking(conn, "2026-01")
    by_model = {r["model"]: r["units"] for r in ranked}

    assert by_model["Deepal S05 BEV"] == 2019
    assert by_model["Deepal S05 REEV"] == 320
    assert "Deepal S05" not in by_model
    assert sum(by_model.values()) == 2339


def test_chinese_trim_ranking_keeps_dlt_unsplit_rows_unsplit():
    conn = connect(":memory:")
    source_id = _source(conn)
    _model_dim(conn, "gwm.ora_good_cat", "GWM", "Ora Good Cat", "BEV")
    _model_dim(conn, "byd.dolphin", "BYD", "Dolphin", "BEV")
    _model_dim(conn, "tesla.model_3", "Tesla", "Model 3", "BEV", origin="US")

    dims = [
        ("gwm.ora_good_cat#base", "gwm.ora_good_cat", "GWM", "Ora Good Cat", "", None),
        ("byd.dolphin#435km_std", "byd.dolphin", "BYD", "Dolphin", "435KM-STD", "STD"),
        ("byd.dolphin#500km_ext", "byd.dolphin", "BYD", "Dolphin", "500KM-EXT", "EXT"),
        ("tesla.model_3#lr", "tesla.model_3", "Tesla", "Model 3", "Long Range", "LONG RANGE"),
    ]
    conn.executemany(
        "INSERT INTO dim_trim(trim_id,catalog_year,brand_id,brand,model_id,nameplate,"
        "model,trim_label,grade) VALUES (?,2026,?,?,?,?,?,?,?)",
        [
            (tid, mid.split('.')[0], brand, mid, model, model, trim, grade)
            for tid, mid, brand, model, trim, grade in dims
        ],
    )
    facts = [
        ("gwm.ora_good_cat#base", 1904, "ORA GOOD CAT"),
        ("byd.dolphin#435km_std", 500, "BYD DOLPHIN 435KM-STD"),
        ("byd.dolphin#500km_ext", 300, "BYD DOLPHIN 500KM-EXT"),
        ("tesla.model_3#lr", 999, "TESLA MODEL 3 LONG RANGE"),
    ]
    conn.executemany(
        "INSERT INTO fact_trim(period,registration_type,province,trim_id,units,"
        "source_id,raw_label) VALUES ('2026-01','RY1','ALL',?,?,?,?)",
        [(tid, units, source_id, raw) for tid, units, raw in facts],
    )
    conn.commit()

    ranked = chinese_ev_trim_ranking(conn, "2026-01")
    assert sum(r["units"] for r in ranked) == 2704
    assert not any(r["brand"] == "Tesla" for r in ranked)

    good_cat = next(r for r in ranked if r["model"] == "Ora Good Cat")
    assert good_cat["trim"] == "DLT_UNSPLIT"
    assert good_cat["units"] == 1904
    assert good_cat["share_of_model"] == 1.0

    dolphin = [r for r in ranked if r["model"] == "Dolphin"]
    assert {r["trim"]: r["units"] for r in dolphin} == {
        "435KM-STD": 500,
        "500KM-EXT": 300,
    }
    assert {round(r["share_of_model"], 3) for r in dolphin} == {0.625, 0.375}
