"""Reading the DLT pivot workbook.

The failure this file exists to prevent is arithmetic, not parsing: the pivot
carries year and brand subtotal rows above the model rows, and a reader that
treats every row as data counts the market three times.
"""

from __future__ import annotations

import pytest

from vehreg import dlt_pivot


HEADER = ("ปี", "ยี่ห้อรถ", "รุ่นรถ", *dlt_pivot.THAI_MONTHS, "รวม")


def sheet(*body: tuple) -> list[tuple]:
    return [
        ("สถิติการจดทะเบียนรถใหม่", *[None] * 15),
        (None,) * 16,
        ("จังหวัด", "(ทั้งหมด)", *[None] * 14),
        HEADER,
        *body,
    ]


def months(**values: float) -> tuple:
    """Twelve month cells plus the row total, keyed m1..m12."""
    cells = [values.get(f"m{i}", 0) for i in range(1, 13)]
    return (*cells, sum(cells))


class TestStructure:
    def test_the_header_is_found_not_assumed(self):
        rows = sheet(("2568", "", "", *months(m1=10)))
        assert dlt_pivot.find_header(rows) == 3

    def test_a_sheet_without_month_names_is_refused(self):
        with pytest.raises(ValueError, match="month names"):
            dlt_pivot.find_header([("a", "b"), ("c", "d")])

    def test_months_are_read_by_name_not_by_position(self):
        shuffled = ("ปี", "ยี่ห้อรถ", "รุ่นรถ", *reversed(dlt_pivot.THAI_MONTHS))
        columns = dlt_pivot.month_columns(shuffled)
        assert columns[0] == 14 and columns[11] == 3


class TestSubtotalsAreNotData:
    def test_year_and_brand_rows_are_read_for_context_only(self):
        rows = sheet(
            ("2568", "", "", *months(m1=30)),          # year subtotal
            ("", "TOYOTA", "", *months(m1=30)),        # brand subtotal
            ("", "", "Hilux Revo", *months(m1=20)),
            ("", "", "Yaris", *months(m1=10)),
        )
        got = list(dlt_pivot.read_rows(rows))
        assert [(r.period, r.brand, r.model, r.units) for r in got] == [
            ("2025-01", "TOYOTA", "Hilux Revo", 20.0),
            ("2025-01", "TOYOTA", "Yaris", 10.0),
        ]

    def test_model_rows_reconcile_against_the_declared_subtotal(self):
        rows = sheet(
            ("2568", "", "", *months(m1=30, m2=5)),
            ("", "TOYOTA", "", *months(m1=30, m2=5)),
            ("", "", "Hilux Revo", *months(m1=20, m2=5)),
            ("", "", "Yaris", *months(m1=10)),
        )
        assert dlt_pivot.period_totals(rows) == dlt_pivot.declared_period_totals(rows)

    def test_the_brand_carries_down_to_its_models(self):
        rows = sheet(
            ("2568", "", "", *months(m1=3)),
            ("", "TOYOTA", "", *months(m1=1)),
            ("", "", "Yaris", *months(m1=1)),
            ("", "ISUZU", "", *months(m1=2)),
            ("", "", "D-MAX", *months(m1=2)),
        )
        assert {r.model: r.brand for r in dlt_pivot.read_rows(rows)} == {
            "Yaris": "TOYOTA", "D-MAX": "ISUZU",
        }


class TestValues:
    def test_buddhist_years_convert(self):
        rows = sheet(
            ("2564", "", "", *months(m3=1)),
            ("", "HONDA", "", *months(m3=1)),
            ("", "", "City", *months(m3=1)),
        )
        assert next(iter(dlt_pivot.read_rows(rows))).period == "2021-03"

    def test_zero_months_are_dropped_not_stored(self):
        rows = sheet(
            ("2568", "", "", *months(m1=5)),
            ("", "HONDA", "", *months(m1=5)),
            ("", "", "City", *months(m1=5)),
        )
        assert len(list(dlt_pivot.read_rows(rows))) == 1

    def test_thousand_separators_are_read(self):
        rows = sheet(
            ("2568", "", "", "1,234", *[0] * 11, "1,234"),
            ("", "HONDA", "", "1,234", *[0] * 11, "1,234"),
            ("", "", "City", "1,234", *[0] * 11, "1,234"),
        )
        assert next(iter(dlt_pivot.read_rows(rows))).units == 1234.0

    def test_the_unspecified_model_bucket_is_kept(self):
        # DLT's "ไม่ระบุ" is real volume, not a blank row; dropping it would
        # quietly shrink the month.
        rows = sheet(
            ("2568", "", "", *months(m1=7)),
            ("", "HONDA", "", *months(m1=7)),
            ("", "", dlt_pivot.UNSPECIFIED_MODEL, *months(m1=7)),
        )
        assert next(iter(dlt_pivot.read_rows(rows))).units == 7.0


class TestCsvOut:
    def test_one_month_is_written_with_no_class_claimed(self, tmp_path):
        rows = sheet(
            ("2568", "", "", *months(m1=10, m2=4)),
            ("", "TOYOTA", "", *months(m1=10, m2=4)),
            ("", "", "Yaris", *months(m1=10, m2=4)),
        )
        target = tmp_path / "pivot_2025-01.csv"
        assert dlt_pivot.write_period_csv(rows, "2025-01", target) == 1
        text = target.read_text(encoding="utf-8-sig")
        assert "2025-01,*,TOYOTA,Yaris,10" in text
        assert "2025-02" not in text


LONG_HEAD = dlt_pivot.LONG_HEADER


def long_sheet(*body: tuple) -> list[tuple]:
    return [
        ("สถิติการจดทะเบียนรถใหม่", *[None] * 6),
        ("หน่วย: คัน", *[None] * 6),
        LONG_HEAD,
        *body,
    ]


class TestLongSheet:
    def test_the_registration_class_is_read_off_the_label(self):
        assert dlt_pivot.registration_code("รย.1 รถยนต์นั่งส่วนบุคคล") == "RY1"
        assert dlt_pivot.registration_code("รย.3 รถยนต์บรรทุก") == "RY3"
        assert dlt_pivot.registration_code("") == ""
        assert dlt_pivot.registration_code("something else") == ""

    def test_a_row_keeps_its_class_and_province(self):
        rows = long_sheet(
            ("2569", "มกราคม", "รย.3 รถยนต์บรรทุกส่วนบุคคล", "ชลบุรี",
             "ISUZU", "D-MAX", "12"),
        )
        got = list(dlt_pivot.read_long_rows(rows))
        assert len(got) == 1
        row = got[0]
        assert (row.period, row.registration_type, row.province) == (
            "2026-01", "RY3", "ชลบุรี")
        assert row.units == 12.0

    def test_motorcycles_and_other_classes_are_left_out(self):
        # The long sheet carries every class DLT publishes; motorcycles alone
        # outnumber cars three to one and are not what this warehouse counts.
        rows = long_sheet(
            ("2569", "มกราคม", "รย.1 รถยนต์นั่ง", "กรุงเทพมหานคร", "HONDA", "City", "5"),
            ("2569", "มกราคม", "รย.12 รถจักรยานยนต์", "กรุงเทพมหานคร", "HONDA", "Wave", "900"),
        )
        assert dlt_pivot.long_period_totals(rows) == {"2026-01": 5.0}

    def test_every_class_can_be_asked_for(self):
        rows = long_sheet(
            ("2569", "มกราคม", "รย.1 รถยนต์นั่ง", "กรุงเทพมหานคร", "HONDA", "City", "5"),
            ("2569", "มกราคม", "รย.12 รถจักรยานยนต์", "กรุงเทพมหานคร", "HONDA", "Wave", "900"),
        )
        assert dlt_pivot.long_period_totals(rows, classes=None) == {"2026-01": 905.0}

    def test_provinces_are_summed_away_when_writing_a_month(self, tmp_path):
        rows = long_sheet(
            ("2569", "มกราคม", "รย.1 รถยนต์นั่ง", "กรุงเทพมหานคร", "HONDA", "City", "5"),
            ("2569", "มกราคม", "รย.1 รถยนต์นั่ง", "ชลบุรี", "HONDA", "City", "7"),
            ("2569", "กุมภาพันธ์", "รย.1 รถยนต์นั่ง", "ชลบุรี", "HONDA", "City", "3"),
        )
        target = tmp_path / "long_2026-01.csv"
        assert dlt_pivot.write_long_period_csv(rows, "2026-01", target) == 1
        text = target.read_text(encoding="utf-8-sig")
        assert "2026-01,RY1,HONDA,City,12" in text
        assert "2026-02" not in text

    def test_a_sheet_without_the_long_header_is_refused(self):
        with pytest.raises(ValueError, match="long-sheet columns"):
            dlt_pivot.find_long_header([("ปี", "ยี่ห้อรถ", "รุ่นรถ")])
