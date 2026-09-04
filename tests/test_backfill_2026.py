from __future__ import annotations

import csv
import gzip
from pathlib import Path

from vehreg.web_bootstrap import _national_sources, _period_from_raw_path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"

EXPECTED = {
    "2026-02": (592, 48847),
    "2026-03": (602, 59486),
    "2026-04": (574, 49028),
    "2026-05": (586, 61608),
    "2026-06": (605, 62219),
    "2026-07": (588, 58402),
}


def test_backfill_gzip_months_have_expected_core_totals():
    for period, (expected_rows, expected_units) in EXPECTED.items():
        path = RAW / f"dlt_{period}.csv.gz"
        assert path.exists()
        with gzip.open(path, "rt", newline="", encoding="utf-8-sig") as handle:
            rows = list(csv.DictReader(handle))
        assert len(rows) == expected_rows
        assert {row["ประเภท"] for row in rows} <= {"RY1", "RY2", "RY3"}
        assert sum(int(float(row["จำนวน"])) for row in rows) == expected_units


def test_national_source_selection_prefers_future_official_csv(tmp_path):
    backfill = tmp_path / "dlt_2026-02.csv.gz"
    backfill.write_bytes(b"placeholder")
    assert _period_from_raw_path(backfill) == "2026-02"
    assert _national_sources(tmp_path)["2026-02"] == backfill

    official = tmp_path / "dlt_2026-02.csv"
    official.write_text("placeholder", encoding="utf-8")
    assert _period_from_raw_path(official) == "2026-02"
    assert _national_sources(tmp_path)["2026-02"] == official
