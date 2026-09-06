from __future__ import annotations

import sqlite3

import pytest

from vehreg import coverage


def _totals(**pairs: float) -> dict[str, float]:
    return dict(pairs)


def steady(months: int = 8, units: float = 50_000.0) -> dict[str, float]:
    return {f"2025-{m:02d}": units for m in range(1, months + 1)}


class TestProvisionalPeriods:
    def test_a_stub_month_is_flagged_with_its_evidence(self):
        totals = steady(6)
        totals["2025-07"] = 15.0
        found = coverage.provisional_periods(totals)
        assert set(found) == {"2025-07"}
        assert found["2025-07"]["baseline"] == 50_000.0
        assert found["2025-07"]["ratio"] == pytest.approx(0.0003)

    def test_an_ordinary_seasonal_dip_is_not_flagged(self):
        totals = steady(6)
        totals["2025-07"] = 30_000.0  # 60% of baseline: a bad month, not a stub
        assert coverage.provisional_periods(totals) == {}

    def test_early_months_have_no_baseline_and_are_never_flagged(self):
        # A short first month is a collection decision, not a partial file.
        totals = {"2025-01": 12.0, "2025-02": 50_000.0, "2025-03": 50_000.0}
        assert coverage.provisional_periods(totals) == {}

    def test_the_real_december_2024_fall_stays_out_of_the_net(self):
        # Guards the threshold against the sharpest real drop in the data:
        # 30,163 units against a 40,569 baseline.
        totals = {
            "2024-06": 53_077.0, "2024-07": 51_077.0, "2024-08": 48_957.0,
            "2024-09": 43_565.0, "2024-10": 40_848.0, "2024-11": 40_290.0,
            "2024-12": 30_163.0,
        }
        assert coverage.provisional_periods(totals) == {}


class TestDefaultPeriod:
    def test_pages_open_on_the_last_settled_month(self):
        totals = steady(6)
        totals["2025-07"] = 15.0
        assert coverage.latest_settled_period(totals) == "2025-06"

    def test_index_points_at_that_month(self):
        totals = steady(6)
        totals["2025-07"] = 15.0
        periods = sorted(totals)
        assert periods[coverage.default_period_index(periods, totals)] == "2025-06"

    def test_everything_provisional_still_shows_something(self):
        totals = {"2025-01": 5.0}
        assert coverage.latest_settled_period(totals) == "2025-01"

    def test_no_data_at_all(self):
        assert coverage.latest_settled_period({}) is None
        assert coverage.default_period_index([], {}) == 0

    def test_a_page_narrowing_its_period_list_does_not_raise(self):
        totals = steady(6)
        totals["2025-07"] = 15.0
        narrowed = ["2025-01", "2025-02"]
        index = coverage.default_period_index(narrowed, totals)
        assert narrowed[index] == "2025-02"


class TestDuplicatePayloads:
    HEADER = "เดือน,ประเภท,ยี่ห้อ,แบบรถ,จำนวน\n"

    def write(self, directory, period: str, rows: list[str]) -> None:
        body = "".join(f"{period},{row}\n" for row in rows)
        (directory / f"dlt_{period}.csv").write_text(
            self.HEADER + body, encoding="utf-8"
        )

    def test_two_months_carrying_one_payload_are_reported(self, tmp_path):
        rows = ["RY1,TOYOTA,HILUX,10", "RY1,ISUZU,D-MAX,20"]
        self.write(tmp_path, "2022-12", rows)
        self.write(tmp_path, "2023-12", rows)
        found = coverage.duplicate_payload_periods(tmp_path)
        assert len(found) == 1
        assert found[0]["periods"] == ["2022-12", "2023-12"]
        assert found[0]["units"] == 30
        assert found[0]["exact"] is True

    def test_spelling_only_differences_do_not_hide_the_duplication(self, tmp_path):
        # The real pair differs in empty-vs-"None" model names on four rows and
        # in no unit count at all.
        self.write(tmp_path, "2022-12", ["RY1,TOYOTA,,10", "RY1,ISUZU,D-MAX,20"])
        self.write(tmp_path, "2023-12", ["RY1,TOYOTA,None,10", "RY1,ISUZU,D-MAX,20"])
        found = coverage.duplicate_payload_periods(tmp_path)
        assert found and found[0]["periods"] == ["2022-12", "2023-12"]

    def test_distinct_months_are_left_alone(self, tmp_path):
        self.write(tmp_path, "2025-01", ["RY1,TOYOTA,HILUX,10"])
        self.write(tmp_path, "2025-02", ["RY1,TOYOTA,HILUX,11"])
        assert coverage.duplicate_payload_periods(tmp_path) == []

    def test_the_period_column_is_ignored_when_fingerprinting(self, tmp_path):
        self.write(tmp_path, "2025-01", ["RY1,TOYOTA,HILUX,10"])
        self.write(tmp_path, "2025-02", ["RY1,TOYOTA,HILUX,10"])
        left = coverage.payload_fingerprint(tmp_path / "dlt_2025-01.csv")
        right = coverage.payload_fingerprint(tmp_path / "dlt_2025-02.csv")
        assert left == right

    def test_missing_directory_is_not_an_error(self, tmp_path):
        assert coverage.duplicate_payload_periods(tmp_path / "nope") == []


class TestNotices:
    def test_clean_data_says_nothing(self):
        assert coverage.coverage_notices({}, []) == []

    def test_each_problem_names_its_months(self):
        provisional = {"2026-02": {"units": 15.0, "baseline": 46_423.0,
                                   "ratio": 15.0 / 46_423.0}}
        duplicates = [{"periods": ["2022-12", "2023-12"], "row_count": 453,
                       "units": 47_635.0, "identical_rows": 452, "exact": False}]
        notices = coverage.coverage_notices(provisional, duplicates)
        assert len(notices) == 2
        assert "2026-02" in notices[0]
        assert "2022-12" in notices[1] and "2023-12" in notices[1]


class TestChartHeight:
    def test_one_row_does_not_fill_the_screen(self):
        assert coverage.chart_height(1) == 220

    def test_height_grows_with_rows(self):
        assert coverage.chart_height(20) > coverage.chart_height(5)

    def test_a_long_ranking_is_capped(self):
        assert coverage.chart_height(500) == 900


class TestIngestRefusesADuplicatePayload:
    """The guard has to hold on the path the CLI uses, not only in the app."""

    def _fixture(self, tmp_path):
        from tests.test_vehreg import tiny_catalog
        from vehreg.db import connect, rebuild_dimension

        catalog = tiny_catalog()
        conn = connect(tmp_path / "db.sqlite3")
        rebuild_dimension(conn, catalog)
        # Facts only classify against a year the catalog covers, so the test
        # months follow the fixture catalog rather than a fixed 2025.
        return catalog, conn, catalog.year

    HEADER = "period,brand,model,units\n"

    def test_second_month_with_the_same_rows_is_refused(self, tmp_path):
        from vehreg.ingest import ingest_csv

        catalog, conn, year = self._fixture(tmp_path)
        first = tmp_path / f"dlt_{year}-01.csv"
        second = tmp_path / f"dlt_{year}-02.csv"
        first.write_text(self.HEADER + f"{year}-01,Acme,Volt,10\n", encoding="utf-8")
        second.write_text(self.HEADER + f"{year}-02,Acme,Volt,10\n", encoding="utf-8")

        ingest_csv(conn, catalog, first, f"WEB {year}-01")
        with pytest.raises(ValueError, match="already loaded as"):
            ingest_csv(conn, catalog, second, f"WEB {year}-02")

        # The owner can still override once they know which month is the real
        # one; the guard is a stop sign, not a locked door.
        ingest_csv(conn, catalog, second, f"WEB {year}-02",
                   allow_duplicate_payload=True)
        loaded = [row["period"] for row in conn.execute(
            "SELECT DISTINCT period FROM fact_registration ORDER BY period")]
        assert loaded == [f"{year}-01", f"{year}-02"]
        conn.close()

    def test_a_genuinely_different_month_loads_normally(self, tmp_path):
        from vehreg.ingest import ingest_csv

        catalog, conn, year = self._fixture(tmp_path)
        first = tmp_path / f"dlt_{year}-01.csv"
        second = tmp_path / f"dlt_{year}-02.csv"
        first.write_text(self.HEADER + f"{year}-01,Acme,Volt,10\n", encoding="utf-8")
        second.write_text(self.HEADER + f"{year}-02,Acme,Volt,11\n", encoding="utf-8")
        ingest_csv(conn, catalog, first, f"WEB {year}-01")
        ingest_csv(conn, catalog, second, f"WEB {year}-02")
        loaded = [row["period"] for row in conn.execute(
            "SELECT DISTINCT period FROM fact_registration ORDER BY period")]
        assert loaded == [f"{year}-01", f"{year}-02"]
        conn.close()

    def test_reingesting_the_same_file_is_not_a_duplicate(self, tmp_path):
        from vehreg.ingest import ingest_csv

        catalog, conn, year = self._fixture(tmp_path)
        path = tmp_path / f"dlt_{year}-01.csv"
        path.write_text(self.HEADER + f"{year}-01,Acme,Volt,10\n", encoding="utf-8")
        ingest_csv(conn, catalog, path, f"WEB {year}-01")
        ingest_csv(conn, catalog, path, f"WEB {year}-01")  # must not raise
        conn.close()


class TestSignatureCatchesTheRealCollision:
    """The December pair is not byte-identical, and must still be caught."""

    HEADER = "period,brand,model,units\n"

    def test_spelling_differences_do_not_change_the_signature(self, tmp_path):
        left = tmp_path / "dlt_2022-12.csv"
        right = tmp_path / "dlt_2023-12.csv"
        left.write_text(
            self.HEADER
            + "2022-12,MERCEDES BENZ,,2\n"
            + "2022-12,PORSCHE,MACAN 2.0,1\n", encoding="utf-8")
        right.write_text(
            self.HEADER
            + "2023-12,MERCEDES BENZ,None,2\n"
            + "2023-12,PORSCHE,MACAN 2,1\n", encoding="utf-8")

        assert coverage.payload_fingerprint(left) != coverage.payload_fingerprint(right)
        assert coverage.payload_signature(left) == coverage.payload_signature(right)
        assert coverage.duplicate_payload_periods(tmp_path)

    def test_a_month_that_merely_totals_the_same_over_different_rows(self, tmp_path):
        # Same units, different row count: not the collision, not reported.
        (tmp_path / "dlt_2025-01.csv").write_text(
            self.HEADER + "2025-01,TOYOTA,HILUX,30\n", encoding="utf-8")
        (tmp_path / "dlt_2025-02.csv").write_text(
            self.HEADER + "2025-02,TOYOTA,HILUX,10\n"
            + "2025-02,ISUZU,D-MAX,20\n", encoding="utf-8")
        assert coverage.duplicate_payload_periods(tmp_path) == []


class TestChartColour:
    """The colour rules, so a later edit cannot quietly reintroduce a rainbow."""

    def test_the_biggest_value_gets_the_darkest_step(self):
        from vehreg.charting import SEQUENTIAL_BLUE, magnitude_colors

        colours = magnitude_colors([100, 50, 1])
        assert colours[0] == SEQUENTIAL_BLUE[-1]
        assert colours[0] != colours[-1]

    def test_equal_values_get_equal_colour(self):
        from vehreg.charting import magnitude_colors

        assert len(set(magnitude_colors([7, 7, 7]))) == 1

    def test_a_shade_follows_the_value_not_the_row_position(self):
        # Dropping the leader must not repaint everyone below it.
        from vehreg.charting import magnitude_colors

        full = magnitude_colors([100, 60, 20])
        without_a_smaller_one = magnitude_colors([100, 60])
        assert full[:2] == without_a_smaller_one

    def test_all_zero_does_not_divide_by_zero(self):
        from vehreg.charting import magnitude_colors

        assert magnitude_colors([0, 0]) and magnitude_colors([]) == []

    def test_sign_picks_the_hue_on_a_movement_chart(self):
        import pandas as pd

        from vehreg.charting import NEGATIVE, NEUTRAL, POSITIVE, signed_bar

        frame = pd.DataFrame({
            "entity": ["up", "flat", "down"],
            "change": [1.5, 0.0, -2.0],
        })
        figure = signed_bar(frame, x="change", y="entity", height=300)
        assert list(figure.data[0].marker.color) == [POSITIVE, NEUTRAL, NEGATIVE]

    def test_long_labels_are_never_clipped(self):
        import pandas as pd

        from vehreg.charting import rank_bar

        frame = pd.DataFrame({
            "label": ["Aion Hyptec HT — 620 PREMIUM ตัวท็อป"],
            "units": [11],
        })
        figure = rank_bar(frame, x="units", y="label", height=300)
        assert figure.layout.yaxis.automargin is True


class TestCoarseMonths:
    """A month whose pickups never reached a model must say so."""

    def test_a_pivot_month_is_flagged_and_an_export_month_is_not(self):
        shares = {"2026-01": 0.001, "2026-05": 0.198}
        assert set(coverage.coarse_periods(shares)) == {"2026-05"}

    def test_the_notice_names_what_is_missing_from_the_ranking(self):
        text = coverage.coarse_notice("2026-05", 0.198)
        assert "2026-05" in text and "20%" in text
        assert "D-Max" in text

    def test_share_is_read_off_the_grain_of_the_matched_unit(self, tmp_path):
        from vehreg.db import connect

        conn = connect(tmp_path / "db.sqlite3")
        conn.execute("INSERT INTO dim_source (name) VALUES ('t')")
        for unit, grain in (("u-model", "MODEL"), ("u-brand", "BRAND")):
            conn.execute(
                "INSERT INTO dim_unit (unit_id, catalog_year, grain, brand) "
                "VALUES (?,?,?,?)", (unit, 2026, grain, "Isuzu"))
        for unit, units in (("u-model", 75.0), ("u-brand", 25.0)):
            conn.execute(
                "INSERT INTO fact_registration "
                "(period, registration_type, unit_id, grain, units, source_id) "
                "VALUES ('2026-05','RY1',?,?,?,1)", (unit, "MODEL", units))
        conn.commit()
        assert coverage.brand_grain_share(conn)["2026-05"] == pytest.approx(0.25)
        conn.close()

    def test_a_coarse_month_is_read_at_every_grain(self):
        # Without this the cube's default grains drop the residual and the
        # month reports about two thirds of itself as if it were a quiet month.
        coarse = {"2026-08": 0.25}
        assert coverage.analysis_grains("2026-08", coarse) == coverage.FULL_GRAINS
        assert coverage.analysis_grains("2026-01", coarse) is None

    def test_the_notice_no_longer_claims_the_ranking_is_merely_incomplete(self):
        text = coverage.coarse_notice("2026-08", 0.25)
        assert "UNKNOWN" in text


class TestDownloadShape:
    """The file has to read like the screen it came from."""

    def _frame(self):
        import pandas as pd
        return pd.DataFrame({
            "entity": ["Toyota", "Honda"],
            "units": [19468.0, 5414.0],
            "share_pct": [32.71437933757919, 9.097783528541902],
            "share_change_pp": [1.23456, -0.5],
            "range_km": [620.5, 490.0],
        })

    def test_whole_counts_stop_being_floats(self):
        from ui import _for_file
        out = _for_file(self._frame())
        assert list(out["units"]) == [19468, 5414]

    def test_shares_are_rounded_to_what_the_page_shows(self):
        from ui import _for_file
        out = _for_file(self._frame())
        assert list(out["share_pct"]) == [32.71, 9.1]
        assert list(out["share_change_pp"]) == [1.23, -0.5]

    def test_a_genuinely_fractional_column_is_left_alone(self):
        from ui import _for_file
        out = _for_file(self._frame())
        assert list(out["range_km"]) == [620.5, 490.0]

    def test_the_original_frame_is_not_modified(self):
        from ui import _for_file
        frame = self._frame()
        _for_file(frame)
        assert frame["units"].dtype.kind == "f"

    def test_the_file_name_carries_period_and_scope(self):
        from ui import _slug
        assert _slug("Market structure") == "market-structure"
        assert _slug("2026-08") == "2026-08"
