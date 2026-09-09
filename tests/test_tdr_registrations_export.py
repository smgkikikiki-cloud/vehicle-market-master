"""The TDR export: a file in another product's schema, never a connection to it.

TDR (a separate repository, a separate Supabase database) already has a
``registrations`` table -- ``period date, brand_name_raw text not null,
model_name_raw text not null, registrations integer`` -- feeding a chart on
its own model pages and a reports page, both currently starved of data. This
module tests only the shape of what this warehouse can honestly hand over: no
credential, no network call, and nothing invented for volume this warehouse
has not itself resolved to a brand and a model.
"""

import unittest

from vehreg import cube, db


class TdrRegistrationsExportTests(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")
        self.conn.execute("INSERT INTO dim_source(name) VALUES ('test')")
        source_id = self.conn.execute(
            "SELECT source_id FROM dim_source WHERE name='test'").fetchone()["source_id"]
        self.conn.execute(
            "INSERT INTO dim_unit "
            "(unit_id,catalog_year,grain,brand,model,segment,body_type,market_scope) "
            "VALUES "
            "('x.car',2026,'MODEL','X','Car','C','SEDAN','CORE'),"
            "('x.van',2026,'MODEL','X','Van','C','VAN','GREY')"
        )
        self.conn.execute(
            "INSERT INTO fact_registration "
            "(period,registration_type,province,unit_id,grain,units,source_id,raw_label) "
            "VALUES "
            "('2026-04','RY1','ALL','x.car','MODEL',10,?,'X Car'),"
            "('2026-05','RY1','ALL','x.car','MODEL',26,?,'X Car'),"
            # GREY-scope volume: excluded by the default CORE scope, not by name.
            "('2026-04','RY1','ALL','x.van','MODEL',5,?,'X Van'),"
            # Unresolved: no dim_unit row for this unit_id at all.
            "('2026-04','RY1','ALL','z.ghost','MODEL',7,?,'Z Ghost')",
            (source_id, source_id, source_id, source_id),
        )

    def test_the_export_matches_tdrs_own_column_names_and_a_sql_date(self):
        rows = cube.tdr_registrations_export(self.conn)
        self.assertEqual(list(cube.TDR_REGISTRATIONS_COLUMNS),
                         ["period", "brand_name_raw", "model_name_raw",
                          "registrations"])
        self.assertEqual(rows, [
            {"period": "2026-04-01", "brand_name_raw": "X",
             "model_name_raw": "Car", "registrations": 10},
            {"period": "2026-05-01", "brand_name_raw": "X",
             "model_name_raw": "Car", "registrations": 26},
        ])

    def test_a_grey_scope_model_is_excluded_by_scope_not_by_silently_renaming_it(self):
        core_only = cube.tdr_registrations_export(self.conn)
        self.assertNotIn("Van", [r["model_name_raw"] for r in core_only])
        everything = cube.tdr_registrations_export(self.conn, scopes="all")
        self.assertIn("Van", [r["model_name_raw"] for r in everything])

    def test_unresolved_volume_is_dropped_from_the_export_not_mislabelled(self):
        """TDR's schema declares brand_name_raw/model_name_raw NOT NULL.

        A unit_id with no dim_unit row (still sitting in this warehouse's own
        review queue) has no name to export it under -- it must not appear in
        the file under a placeholder brand, and it must not be silently
        invisible either: it is counted and reported separately.
        """
        rows = cube.tdr_registrations_export(self.conn, scopes="all")
        for row in rows:
            self.assertIsNotNone(row["brand_name_raw"])
            self.assertIsNotNone(row["model_name_raw"])
        self.assertEqual(
            7, cube.tdr_registrations_unresolved_units(self.conn, scopes="all"))

    def test_rows_are_sorted_for_a_stable_diff_not_by_biggest_mover(self):
        rows = cube.tdr_registrations_export(self.conn)
        self.assertEqual(rows, sorted(
            rows, key=lambda r: (r["period"], r["brand_name_raw"],
                                 r["model_name_raw"])))

    def test_period_from_and_to_narrow_the_export_like_every_other_cube_query(self):
        rows = cube.tdr_registrations_export(
            self.conn, period_from="2026-05", period_to="2026-05")
        self.assertEqual([r["period"] for r in rows], ["2026-05-01"])


# ---------------------------------------------------------------------------
# The CLI, against the real repository warehouse.
# ---------------------------------------------------------------------------

def test_cli_writes_a_csv_in_tdrs_column_order_and_reports_the_unresolved_units(
        tmp_path, capsys):
    from vehreg.cli import main
    out = tmp_path / "tdr_registrations.csv"
    assert main(["export-tdr-registrations", "--csv", str(out)]) == 0
    captured = capsys.readouterr()
    assert "wrote " in captured.out and str(out) in captured.out
    assert "units excluded" in captured.err

    import csv as csv_mod
    with out.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv_mod.DictReader(handle))
    assert rows
    assert set(rows[0]) == {"period", "brand_name_raw", "model_name_raw",
                            "registrations"}
    for row in rows[:200]:
        assert row["period"][4] == "-" and row["period"][7] == "-"
        assert row["period"].endswith("-01")
        assert row["brand_name_raw"]
        assert row["model_name_raw"]
        assert int(row["registrations"]) >= 0


def test_cli_json_mode_prints_the_same_rows_the_export_function_returns(capsys):
    from vehreg.cli import main, DEFAULT_DB
    from vehreg.db import connect
    import json as json_mod

    assert main(["export-tdr-registrations", "--from", "2026-08",
                 "--to", "2026-08"]) == 0
    printed = json_mod.loads(capsys.readouterr().out)

    expected = cube.tdr_registrations_export(
        connect(DEFAULT_DB), period_from="2026-08", period_to="2026-08")
    assert printed == expected
    assert printed and all(row["period"] == "2026-08-01" for row in printed)


if __name__ == "__main__":
    unittest.main()
