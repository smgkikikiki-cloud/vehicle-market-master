from vehreg.market_metrics import (
    compare_share_rows,
    missing_periods,
    period_range,
    previous_window,
    rolling_window,
    shift_period,
    window_is_complete,
    ytd_window,
)


def test_period_windows_cross_year_boundaries():
    assert shift_period("2026-01", -1) == "2025-12"
    assert shift_period("2025-12", 1) == "2026-01"
    assert period_range("2025-11", "2026-02") == [
        "2025-11", "2025-12", "2026-01", "2026-02"
    ]
    assert rolling_window("2026-08", 3) == ("2026-06", "2026-08")
    assert previous_window("2026-08", 3) == ("2026-03", "2026-05")
    assert ytd_window("2026-08") == ("2026-01", "2026-08")


def test_window_completeness_reports_missing_months():
    available = ["2026-01", "2026-02", "2026-04"]
    assert missing_periods(available, "2026-01", "2026-04") == ["2026-03"]
    assert not window_is_complete(available, "2026-01", "2026-04")
    assert window_is_complete(available, "2026-01", "2026-02")


def test_share_can_rise_while_raw_registrations_fall():
    previous_rows = [
        {"model": "Hilux", "units": 12000, "share": 0.40},
        {"model": "Other", "units": 18000, "share": 0.60},
    ]
    current_rows = [
        {"model": "Hilux", "units": 8000, "share": 8 / 18},
        {"model": "Other", "units": 10000, "share": 10 / 18},
    ]

    rows = compare_share_rows(previous_rows, current_rows, "model")
    hilux = next(row for row in rows if row["model"] == "Hilux")

    assert hilux["units_current"] < hilux["units_previous"]
    assert round(hilux["share_change_pp"], 3) == 4.444
    assert rows[0]["model"] == "Hilux"
