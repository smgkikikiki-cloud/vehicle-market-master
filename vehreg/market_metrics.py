"""Reader-safe registration-market comparison helpers.

DLT first-registration counts are administrative registration activity, not a
monthly retail-sales ledger. These helpers deliberately emphasize market share
and comparable windows instead of interpreting raw month-to-month volume as
sales growth.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence


def _period_index(period: str) -> int:
    try:
        year_text, month_text = period.split("-", 1)
        year = int(year_text)
        month = int(month_text)
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError(f"invalid period {period!r}; expected YYYY-MM") from exc
    if len(year_text) != 4 or not 1 <= month <= 12:
        raise ValueError(f"invalid period {period!r}; expected YYYY-MM")
    return year * 12 + month - 1


def _period_from_index(value: int) -> str:
    year, month0 = divmod(value, 12)
    return f"{year:04d}-{month0 + 1:02d}"


def shift_period(period: str, months: int) -> str:
    """Shift a YYYY-MM period by a whole number of calendar months."""
    return _period_from_index(_period_index(period) + int(months))


def period_range(start: str, end: str) -> list[str]:
    """Inclusive calendar-month range."""
    left = _period_index(start)
    right = _period_index(end)
    if right < left:
        raise ValueError("end period must not be earlier than start period")
    return [_period_from_index(value) for value in range(left, right + 1)]


def rolling_window(period: str, months: int = 3) -> tuple[str, str]:
    if months < 1:
        raise ValueError("months must be at least 1")
    return shift_period(period, -(months - 1)), period


def previous_window(period: str, months: int = 3) -> tuple[str, str]:
    """Return the non-overlapping window immediately before rolling_window."""
    current_start, _ = rolling_window(period, months)
    previous_end = shift_period(current_start, -1)
    previous_start = shift_period(previous_end, -(months - 1))
    return previous_start, previous_end


def ytd_window(period: str) -> tuple[str, str]:
    year = int(period[:4])
    _period_index(period)  # validate the full token
    return f"{year:04d}-01", period


def missing_periods(available: Sequence[str], start: str, end: str) -> list[str]:
    known = set(available)
    return [period for period in period_range(start, end) if period not in known]


def window_is_complete(available: Sequence[str], start: str, end: str) -> bool:
    return not missing_periods(available, start, end)


def compare_share_rows(
    previous_rows: Sequence[Mapping[str, Any]],
    current_rows: Sequence[Mapping[str, Any]],
    dimension: str,
) -> list[dict[str, Any]]:
    """Merge two cube result row sets and calculate share movement in pp.

    Raw unit changes are retained for audit context, but share_change_pp is the
    primary movement metric. This allows a model to lose registrations while
    still gaining relative market position when the whole market contracts.
    """
    previous = {row.get(dimension): row for row in previous_rows}
    current = {row.get(dimension): row for row in current_rows}
    keys = set(previous) | set(current)

    out: list[dict[str, Any]] = []
    for key in keys:
        left = previous.get(key, {})
        right = current.get(key, {})
        units_previous = float(left.get("units") or 0.0)
        units_current = float(right.get("units") or 0.0)
        share_previous = float(left.get("share") or 0.0)
        share_current = float(right.get("share") or 0.0)
        out.append({
            dimension: key,
            "units_previous": units_previous,
            "units_current": units_current,
            "units_change": units_current - units_previous,
            "share_previous": share_previous,
            "share_current": share_current,
            "share_change_pp": (share_current - share_previous) * 100.0,
        })

    out.sort(
        key=lambda row: (
            -row["share_change_pp"],
            -row["units_current"],
            str(row.get(dimension)),
        )
    )
    return out
