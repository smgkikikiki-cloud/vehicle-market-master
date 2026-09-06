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

#: A month with more than this share of its units recorded at BRAND grain is
#: called out. Months read from the DLT pivot workbook run 20-30% because that
#: source carries no registration class, so a pickup cannot be split by cab and
#: the volume lands on the brand instead of the model. Ordinary export months
#: sit at 0.1%.
BRAND_GRAIN_LIMIT = 0.05

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


def brand_grain_share(conn: sqlite3.Connection) -> dict[str, float]:
    """Share of each period's units that never reached a model.

    A model ranking for such a month is not wrong so much as incomplete: the
    total and the brand split are right, but the biggest pickups are missing
    from it entirely, which reads as "they sold nothing" rather than as "this
    source could not say which cab".
    """
    rows = conn.execute(
        "SELECT f.period AS period, u.grain AS grain, SUM(f.units) AS units "
        "FROM fact_registration f JOIN dim_unit u "
        "  ON u.unit_id = f.unit_id "
        " AND u.catalog_year = CAST(substr(f.period, 1, 4) AS INTEGER) "
        "GROUP BY f.period, u.grain"
    ).fetchall()
    totals: dict[str, float] = {}
    brand: dict[str, float] = {}
    for row in rows:
        period = str(row["period"])
        units = float(row["units"] or 0.0)
        totals[period] = totals.get(period, 0.0) + units
        if str(row["grain"]) == "BRAND":
            brand[period] = brand.get(period, 0.0) + units
    return {period: brand.get(period, 0.0) / total
            for period, total in totals.items() if total > 0}


def coarse_periods(shares: Mapping[str, float],
                   limit: float = BRAND_GRAIN_LIMIT) -> dict[str, float]:
    return {period: share for period, share in shares.items() if share > limit}


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


#: Grains to read when a month carries volume that never reached a model.
#: BRAND-grain rows are residuals -- volume the matcher could not attribute to a
#: model, not a rollup of the model rows -- so adding them to the default pair
#: completes the total instead of double counting it.
FULL_GRAINS: tuple[str, ...] = ("MODEL", "VARIANT", "BRAND")


def analysis_grains(period: str, coarse: Mapping[str, float]
                    ) -> tuple[str, ...] | None:
    """Grains a page should read for this period; None means the default.

    Without this a pivot month reports 43,735 registrations where the file says
    62,332, because the cube's default analysis grains drop the residual. The
    missing third is not an edge case anyone would notice as missing -- it just
    looks like a quiet month.
    """
    return FULL_GRAINS if period in coarse else None


def coarse_notice(period: str, share: float) -> str:
    return (
        f"{period} อ่านจากไฟล์ pivot ของ DLT ซึ่งไม่มีคอลัมน์ประเภทรถ (รย.) "
        f"กระบะจึงแยกตัวถังไม่ได้ ยอด {share * 100:.0f}% ของเดือนนี้ "
        "(ส่วนใหญ่คือ D-Max, Hilux, Ranger, Triton) รู้แค่ยี่ห้อ ไม่รู้รุ่น "
        "ยอดรวมและส่วนแบ่งรายยี่ห้อถูกต้องครบ แต่ในตารางแยกรายรุ่น "
        "ยอดก้อนนี้จะไปรวมอยู่ในแถว UNKNOWN ไม่ได้กระจายเข้ารุ่นไหน"
    )


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


# --------------------------------------------------------------------------
# Facets asserted rather than observed
# --------------------------------------------------------------------------
#: A nameplate this far above the noise is worth checking by hand before its
#: powertrain is quoted anywhere. Below it the arithmetic barely moves.
ASSUMED_UNITS_FLOOR = 1000.0


def assumed_powertrain(conn: sqlite3.Connection) -> list[dict[str, object]]:
    """Model-grain volume carrying a powertrain the source never stated.

    DLT publishes a nameplate, not a spec: the รุ่น cell says "TOYOTA Corolla"
    and nothing about ICE or HEV. So that volume lands at model grain and takes
    whatever the model row says, and the model row is the consensus of the
    variants the catalog happens to list - MIXED when they disagree, one value
    when they do not.

    That is right when the catalog lists every powertrain the nameplate sells
    and wrong when it does not, and nothing in the data distinguishes the two.
    The Corolla Altis lists ICE and HEV, so it reads MIXED and the honesty
    holds. The HR-V lists only its two e:HEV trims, so every HR-V registered -
    including the 1.5 Turbo RS - is counted HEV. The 5 Series lists only the
    530e, so a 520d is counted a plug-in hybrid.

    This returns the exposure, biggest first: the nameplates whose powertrain
    is an assertion inherited from an incomplete variant list rather than
    something the registration data or a checked catalog says. It is a work
    list, not a verdict - most of these are genuinely single-powertrain.
    """
    rows = conn.execute(
        "SELECT f.unit_id, d.powertrain, d.brand, d.model, "
        "  COUNT(DISTINCT f.raw_label) AS labels, SUM(f.units) AS units, "
        "  MIN(f.period) AS first_period, MAX(f.period) AS last_period "
        "FROM fact_registration f JOIN dim_unit d "
        "  ON d.unit_id = f.unit_id AND d.grain = f.grain "
        " AND d.catalog_year = CAST(substr(f.period, 1, 4) AS INTEGER) "
        "WHERE f.grain = 'MODEL' AND d.powertrain IS NOT NULL "
        "  AND d.powertrain NOT IN ('MIXED', 'UNKNOWN') "
        "GROUP BY f.unit_id, d.powertrain, d.brand, d.model "
        "ORDER BY units DESC"
    ).fetchall()
    return [
        {"unit_id": str(row["unit_id"]), "brand": row["brand"],
         "model": row["model"], "powertrain": str(row["powertrain"]),
         "units": float(row["units"] or 0.0), "labels": int(row["labels"]),
         "periods": f"{row['first_period']}–{row['last_period']}"}
        for row in rows if float(row["units"] or 0.0) >= ASSUMED_UNITS_FLOOR
    ]


def observed_share(conn: sqlite3.Connection) -> dict[str, float]:
    """How much of the warehouse's powertrain reading is actually evidenced.

    ``variant`` is volume DLT itself resolved to a spec line. ``mixed`` is
    model-grain volume the catalog honestly refuses to pin down. ``assumed`` is
    model-grain volume wearing a powertrain from a variant list that may or may
    not be complete - the number this module exists to surface.
    """
    row = conn.execute(
        "SELECT "
        "  COALESCE(SUM(CASE WHEN f.grain = 'VARIANT' THEN f.units END), 0) "
        "    AS variant, "
        "  COALESCE(SUM(CASE WHEN f.grain = 'MODEL' "
        "    AND (d.powertrain IS NULL OR d.powertrain IN ('MIXED','UNKNOWN')) "
        "    THEN f.units END), 0) AS mixed, "
        "  COALESCE(SUM(CASE WHEN f.grain = 'MODEL' "
        "    AND d.powertrain NOT IN ('MIXED','UNKNOWN') "
        "    THEN f.units END), 0) AS assumed, "
        "  COALESCE(SUM(CASE WHEN f.grain = 'BRAND' THEN f.units END), 0) "
        "    AS brand_only "
        "FROM fact_registration f LEFT JOIN dim_unit d "
        "  ON d.unit_id = f.unit_id AND d.grain = f.grain "
        " AND d.catalog_year = CAST(substr(f.period, 1, 4) AS INTEGER)"
    ).fetchone()
    return {key: float(row[key] or 0.0)
            for key in ("variant", "mixed", "assumed", "brand_only")}
