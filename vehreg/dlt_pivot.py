"""Reading DLT's pivot-table download of new registrations by brand and model.

This is a second shape of the same statistic the monthly API exports carry. The
workbook is a spreadsheet pivot: a row per year, a subtotal row per brand under
it, and a detail row per model under that, with the twelve months across the
columns. Reading it wrong in the obvious way -- treating every row as data --
counts the whole market three times over.

It is worth reading because it reaches further than the API exports do in both
directions: back to 2021, and forward to whatever month DLT has published,
where the committed CSVs stop wherever the last fetch happened to stop.

Two things it does not carry. There is no registration class per row, so a
pickup's รย.1 and รย.3 rows are already summed together and the cab split those
classes let the matcher make is not available. And the pivot's class selection
("ประเภทรถ (หลายรายการ)") is not stated in the file, which is why its months run
a few hundred units above the API export of the same month rather than matching
it exactly. Both facts belong in the source note of anything loaded from here.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

#: The pivot leaves the registration class out, and "*" is the matcher's own
#: token for "any class" - it stops the class filter narrowing on a value the
#: file never stated.
ANY_CLASS = "*"

#: Thai month names in the header, in calendar order.
THAI_MONTHS: tuple[str, ...] = (
    "มกราคม", "กุมภาพันธ์", "มีนาคม", "เมษายน", "พฤษภาคม", "มิถุนายน",
    "กรกฎาคม", "สิงหาคม", "กันยายน", "ตุลาคม", "พฤศจิกายน", "ธันวาคม",
)

#: Buddhist-era years are offset by this from the Gregorian year.
BE_OFFSET = 543

#: DLT writes this where a model was not recorded. It is a real bucket of
#: registrations, not a blank, so it is kept and left for the matcher to queue.
UNSPECIFIED_MODEL = "ไม่ระบุ"


@dataclass(frozen=True)
class PivotRow:
    period: str
    brand: str
    model: str
    units: float


def _number(value: object) -> float:
    if value is None:
        return 0.0
    try:
        return float(str(value).replace(",", "").strip())
    except ValueError:
        return 0.0


def _text(value: object) -> str:
    return "" if value is None else str(value).strip()


def find_header(rows: list[tuple]) -> int:
    """Index of the row carrying the month names.

    The pivot puts a variable number of title and filter rows above the table,
    so the header is found rather than assumed.
    """
    for index, row in enumerate(rows):
        cells = {_text(cell) for cell in row}
        if THAI_MONTHS[0] in cells and THAI_MONTHS[-1] in cells:
            return index
    raise ValueError("no header row carrying the Thai month names")


def month_columns(header: tuple) -> list[int]:
    """Column index per calendar month, in order."""
    lookup = {_text(cell): index for index, cell in enumerate(header)}
    missing = [name for name in THAI_MONTHS if name not in lookup]
    if missing:
        raise ValueError(f"header is missing months: {', '.join(missing)}")
    return [lookup[name] for name in THAI_MONTHS]


def read_rows(rows: list[tuple]) -> Iterator[PivotRow]:
    """Model-level registrations, one row per model per month with a count.

    Year and brand rows are read for context and never emitted: they are
    subtotals of the rows below them, and yielding them would double and treble
    the market.
    """
    start = find_header(rows)
    columns = month_columns(rows[start])

    year: int | None = None
    brand = ""
    for row in rows[start + 1:]:
        first, second, third = (_text(row[0]), _text(row[1]), _text(row[2]))
        if first.isdigit():
            year = int(first) - BE_OFFSET
            brand = ""
            continue
        if second:
            brand = second
            continue
        if not third or year is None:
            continue
        for month, column in enumerate(columns, start=1):
            units = _number(row[column] if column < len(row) else None)
            if units:
                yield PivotRow(f"{year:04d}-{month:02d}", brand, third, units)


def load_workbook_rows(path: Path | str, sheet: str | None = None) -> list[tuple]:
    import openpyxl

    book = openpyxl.load_workbook(path, read_only=True, data_only=True)
    worksheet = book[sheet] if sheet else book[book.sheetnames[0]]
    return list(worksheet.iter_rows(values_only=True))


def period_totals(rows: list[tuple]) -> dict[str, float]:
    """Units per period, from the model rows only."""
    totals: dict[str, float] = {}
    for row in read_rows(rows):
        totals[row.period] = totals.get(row.period, 0.0) + row.units
    return dict(sorted(totals.items()))


def declared_period_totals(rows: list[tuple]) -> dict[str, float]:
    """Units per period as the pivot's own year rows state them.

    Checking the model rows against the workbook's subtotals is what proves the
    hierarchy was walked correctly; a parser that mistook a brand row for data
    would sail past every other check.
    """
    start = find_header(rows)
    columns = month_columns(rows[start])
    totals: dict[str, float] = {}
    for row in rows[start + 1:]:
        first = _text(row[0])
        if not first.isdigit():
            continue
        year = int(first) - BE_OFFSET
        for month, column in enumerate(columns, start=1):
            units = _number(row[column] if column < len(row) else None)
            if units:
                totals[f"{year:04d}-{month:02d}"] = units
    return dict(sorted(totals.items()))


CSV_HEADER = ("period", "registration_type", "brand", "model", "units")


def write_period_csv(rows: list[tuple], period: str, path: Path | str) -> int:
    """Write one month as a long CSV the ordinary ingest can read.

    Returns the number of data rows written.
    """
    import csv

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with open(path, "w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(CSV_HEADER)
        for row in read_rows(rows):
            if row.period != period:
                continue
            writer.writerow([row.period, ANY_CLASS, row.brand, row.model,
                             f"{row.units:g}"])
            written += 1
    return written
