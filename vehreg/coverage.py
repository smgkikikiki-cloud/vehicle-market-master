"""How much of a month is actually in the warehouse, and whether two months
are secretly the same file.

Two failures motivate this module, both found by opening the app rather than
by reading the data:

* DLT publishes a resource for the current month before the month is over.
  ``2026-02`` arrived with six rows and eighteen units. Every page picked the
  latest period by position, so the whole product opened on a stub and the
  analyst deck reported a leader share of 100%.
* Two different DLT resource ids returned the same payload. December 2022 and
  December 2023 carry identical unit counts on 449 of 453 rows; the four that
  differ differ only in spelling. The fetcher stamps the requested period onto
  every row, so a duplicated payload cannot be spotted from the file itself.

Neither problem is fixed by editing data. A provisional month is real, just
incomplete, and a duplicated payload needs a human to decide which month is
wrong. So this module only labels: it never drops, rewrites or reweights a row.
"""

from __future__ import annotations

import csv
import hashlib
import re
import sqlite3
from pathlib import Path
from statistics import median
from typing import Iterable, Mapping, Sequence

#: A month holding less than this share of its trailing baseline is treated as
#: provisional. A real Thai month has never moved by anything close to this:
#: the largest fall in the 50 months loaded is December 2024 at 74% of its
#: baseline, and the stub that prompted the rule sits at 0.03%.
PROVISIONAL_RATIO = 0.40

#: Months of history the baseline is taken from.
BASELINE_MONTHS = 6

PERIOD_RE = re.compile(r"(\d{4}-\d{2})")


def period_totals(conn: sqlite3.Connection) -> dict[str, float]:
    """Registered units per period, oldest first."""
    rows = conn.execute(
        "SELECT period, SUM(units) AS units FROM fact_registration "
        "GROUP BY period ORDER BY period"
    ).fetchall()
    return {str(row["period"]): float(row["units"] or 0.0) for row in rows}


def provisional_periods(
    totals: Mapping[str, float],
    *,
    ratio: float = PROVISIONAL_RATIO,
    baseline_months: int = BASELINE_MONTHS,
) -> dict[str, dict[str, float]]:
    """Periods that look like a partial publication, with the evidence.

    The first ``baseline_months`` periods have no baseline to be judged against
    and are never called provisional: a short first month is a collection
    decision, not a partial file.
    """
    ordered = sorted(totals)
    out: dict[str, dict[str, float]] = {}
    for index, period in enumerate(ordered):
        if index < baseline_months:
            continue
        window = [totals[p] for p in ordered[max(0, index - baseline_months):index]]
        baseline = median(window)
        if baseline <= 0:
            continue
        units = totals[period]
        if units < baseline * ratio:
            out[period] = {
                "units": units,
                "baseline": baseline,
                "ratio": units / baseline,
            }
    return out


def settled_periods(
    totals: Mapping[str, float], provisional: Mapping[str, object] | None = None
) -> list[str]:
    """Periods safe to open a page on, oldest first."""
    skip = set(provisional or provisional_periods(totals))
    return [period for period in sorted(totals) if period not in skip]


def latest_settled_period(
    totals: Mapping[str, float], provisional: Mapping[str, object] | None = None
) -> str | None:
    """The period a page should default to, or None when nothing is loaded.

    If every period looks provisional the newest one is still returned: an
    empty screen helps nobody, and the banner will say what it is showing.
    """
    settled = settled_periods(totals, provisional)
    if settled:
        return settled[-1]
    ordered = sorted(totals)
    return ordered[-1] if ordered else None


def _normalise_cell(value: str) -> str:
    """Fold the spellings that differ between two exports of the same payload.

    The December pair differs only in empty-vs-``None`` model names and a
    trailing ``.0``. Neither changes a single unit count, so neither should
    hide the duplication.
    """
    text = (value or "").strip()
    if text.lower() in {"none", "null", "nan", "-"}:
        return ""
    if re.fullmatch(r"-?\d+\.0", text):
        return text[:-2]
    return text


def payload_rows(path: Path | str) -> list[tuple[str, ...]]:
    """Every data row of a DLT export, minus the period column.

    The fetcher writes the requested period into every row, so that column
    says what was asked for rather than what came back. Dropping it is what
    lets two months be compared at all.
    """
    path = Path(path)
    with open(path, newline="", encoding="utf-8-sig") as handle:
        reader = csv.reader(handle)
        header = next(reader, None)
        if header is None:
            return []
        drop = _period_column_index(header)
        return [
            tuple(_normalise_cell(cell) for i, cell in enumerate(row) if i != drop)
            for row in reader
            if any((cell or "").strip() for cell in row)
        ]


def payload_fingerprint(path: Path | str) -> str:
    """Hash a DLT export ignoring the period column the fetcher stamps on."""
    digest = hashlib.sha256()
    for row in payload_rows(path):
        digest.update(("\x1f".join(row) + "\x1e").encode("utf-8"))
    return digest.hexdigest()


def _period_column_index(header: Sequence[str]) -> int | None:
    for index, name in enumerate(header):
        folded = (name or "").strip().lower()
        if folded in {"period", "month", "\u0e40\u0e14\u0e37\u0e2d\u0e19", "\u0e1b\u0e35\u0e40\u0e14\u0e37\u0e2d\u0e19", "\u0e07\u0e27\u0e14"}:
            return index
    return 0 if header else None


def _units_of(row: Sequence[str]) -> float:
    """Sum whatever in the row parses as a count.

    Reading the units column by name would mean re-deriving the header map
    here; every DLT row has exactly one numeric field, so this is the same
    number by a shorter path, and a row where it is not stays comparable
    because both sides are read the same way.
    """
    total = 0.0
    for cell in row:
        try:
            total += float(cell)
        except (TypeError, ValueError):
            continue
    return total


def payload_signature(path: Path | str) -> tuple[int, float]:
    """Row count and total units of an export: what identifies a payload.

    An exact hash is too strict for the collision that actually happened. The
    two Decembers differ on one row out of 453 -- an empty model name against
    the literal string ``None``, and ``MACAN 2.0`` against ``MACAN 2`` -- while
    every unit count matches. Folding those spellings by hand risks merging
    genuinely different trims, so the comparison is made on the two numbers
    that cannot coincide by accident instead.
    """
    rows = payload_rows(path)
    return len(rows), round(sum(_units_of(row) for row in rows), 3)


def _summarise(path: Path) -> dict[str, object]:
    rows = payload_rows(path)
    row_count, units = len(rows), round(sum(_units_of(row) for row in rows), 3)
    return {
        "path": path,
        "period": (PERIOD_RE.search(path.name).group(1)
                   if PERIOD_RE.search(path.name) else path.name),
        "rows": rows,
        "row_count": row_count,
        "units": units,
    }


def duplicate_payload_periods(raw_dir: Path | str) -> list[dict[str, object]]:
    """Months whose exports carry the same registrations as another month.

    Two files are reported when they agree on row count *and* on total units.
    Those two numbers matching across different months is not something a real
    market does, so the pair is flagged and the row-level overlap reported as
    the evidence. Nothing is deleted: which of the two months is the wrong one
    is a question for DLT, not for this function.
    """
    raw_dir = Path(raw_dir)
    if not raw_dir.is_dir():
        return []

    summaries = [_summarise(path)
                 for path in sorted(raw_dir.glob("dlt_????-??.csv"))]
    buckets: dict[tuple[int, float], list[dict[str, object]]] = {}
    for summary in summaries:
        if not summary["row_count"]:
            continue
        buckets.setdefault(
            (int(summary["row_count"]), round(float(summary["units"]), 3)), []
        ).append(summary)

    out: list[dict[str, object]] = []
    for (row_count, units), group in sorted(buckets.items()):
        if len(group) < 2:
            continue
        first = group[0]["rows"]
        identical = min(
            sum(1 for a, b in zip(first, other["rows"]) if a == b)
            for other in group[1:]
        )
        out.append({
            "periods": [str(item["period"]) for item in group],
            "row_count": row_count,
            "units": units,
            "identical_rows": identical,
            "exact": identical == row_count,
        })
    return out


def chart_height(row_count: int, *, per_row: int = 30, floor: int = 220,
                 ceiling: int = 900) -> int:
    """Height for a horizontal bar chart that does not balloon on one row.

    Plotly fills whatever box it is given, so a single-category chart rendered
    at the default height is a wall of colour that reads as a bug.
    """
    return max(floor, min(ceiling, int(row_count) * per_row + 120))


def default_period_index(
    periods: Sequence[str],
    totals: Mapping[str, float],
    provisional: Mapping[str, object] | None = None,
) -> int:
    """Position a period selector should open on.

    Falls back to the last position whenever the settled period is not in the
    list a page is offering, so a page can narrow ``periods`` without this
    raising on it.
    """
    if not periods:
        return 0
    target = latest_settled_period(totals, provisional)
    try:
        return list(periods).index(target)
    except ValueError:
        return len(periods) - 1


def coverage_notices(
    provisional: Mapping[str, Mapping[str, float]],
    duplicates: Sequence[Mapping[str, object]] = (),
) -> list[str]:
    """Reader-facing warnings, most urgent first. Empty when the data is clean.

    Written for the owner rather than for a log: each line says which month is
    affected, what the evidence is, and what it means for the numbers on
    screen.
    """
    notices: list[str] = []
    for period in sorted(provisional):
        fact = provisional[period]
        notices.append(
            f"{period} ยังเป็นข้อมูลไม่ครบเดือน — DLT ปล่อยมา "
            f"{fact['units']:,.0f} คัน เทียบกับค่ากลางย้อนหลัง 6 เดือนที่ "
            f"{fact['baseline']:,.0f} คัน ({fact['ratio'] * 100:.1f}%). "
            "หน้านี้จึงเปิดที่เดือนล่าสุดที่ครบแทน เลือกดูได้แต่ส่วนแบ่งตลาด"
            "จะไม่มีความหมาย"
        )
    for group in duplicates:
        periods = " และ ".join(str(p) for p in group.get("periods", []))
        notices.append(
            f"{periods} มีข้อมูลชุดเดียวกัน — {group.get('row_count')} แถว "
            f"ยอดรวม {float(group.get('units') or 0):,.0f} คันเท่ากันเป๊ะ "
            f"({group.get('identical_rows')} แถวตรงกันทุกตัวอักษร). "
            "แปลว่า DLT ส่ง payload ซ้ำให้คนละ resource เดือนใดเดือนหนึ่ง"
            "ไม่ใช่ข้อมูลจริง ต้องดึงใหม่ก่อนใช้อ้างอิง"
        )
    return notices
