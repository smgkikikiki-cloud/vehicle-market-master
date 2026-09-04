"""The trim ledger: a second set of books for the brands that report trim.

DLT prints one ``รุ่น`` field, and what goes in it depends on the marque. The
Japanese brands write the nameplate and nothing else ("YARIS ATIV", "HILUX
REVO"). The Chinese marques and Tesla push trim, battery size, range and
drivetrain into the same field::

    BYD ATTO3 (410KM-PREMIUM)
    AION UT 420 STANDARD
    JAECOO 5 EV Long Range Max
    CHERY V23 4WD PEAK
    DEEPAL S05 REEV MAX

Throwing that away would lose real, published detail; keeping it in the master
facts would make the master inconsistent - Toyota folded, BYD split - and no
brand-versus-brand comparison would be safe again.

So the master stays folded to the model for every brand, and this module keeps
the detail separately for the brands flagged ``trim_detail``. The two are
independent sets of rows over the same source, and ``reconcile()`` proves they
still add up to the same totals.
"""

from __future__ import annotations

import csv
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional

from .catalog import Catalog
from .normalize import fold, slug

#: Grades the Chinese marques actually use in the DLT field, longest first so
#: "LONG RANGE MAX" wins over "MAX".
GRADE_WORDS = (
    "LONG RANGE MAX", "LONG RANGE PRO", "STANDARD RANGE", "LONG RANGE",
    "PERFORMANCE", "EXECUTIVE", "PREMIUM", "STANDARD", "DYNAMIC", "LUXURY",
    "ULTRA", "SMART", "PEAK", "PLUS", "PLAY", "PRO", "MAX", "STD", "EXT",
    "GT", "SE", "RS",
)

_DRIVE = re.compile(r"\b(2WD|4WD|AWD|FWD|RWD|E-?FOUR|4MATIC|XDRIVE)\b", re.I)
_RANGE_KM = re.compile(r"(\d{3,4})\s*KM\b", re.I)
_BARE_RANGE = re.compile(r"\b(\d{3})\b")
_KWH = re.compile(r"(\d{2,3}(?:\.\d+)?)\s*KWH\b", re.I)
_POWERTRAIN = re.compile(
    r"\b(DM-?I|DMO|REEV|PHEV|BEV|EV|SHS|HEV|HYBRID|E-?POWER|PLUG-?IN)\b", re.I)

_POWERTRAIN_CANON = {
    "DMI": "PHEV", "DM-I": "PHEV", "DMO": "PHEV", "SHS": "PHEV",
    "PLUGIN": "PHEV", "PLUG-IN": "PHEV", "EPOWER": "REEV", "E-POWER": "REEV",
    "HYBRID": "HEV", "EV": "BEV",
}


@dataclass
class TrimSpec:
    trim_label: str
    grade: Optional[str] = None
    drive: Optional[str] = None
    range_km: Optional[float] = None
    battery_kwh: Optional[float] = None
    powertrain_hint: Optional[str] = None


def parse_trim(trim_label: str) -> TrimSpec:
    """Pull the structured bits out of whatever the marque wrote."""
    text = " ".join(str(trim_label or "").split())
    spec = TrimSpec(trim_label=text)
    if not text:
        return spec

    upper = text.upper()

    drive = _DRIVE.search(upper)
    if drive:
        value = drive.group(1).upper().replace("-", "")
        spec.drive = {"EFOUR": "AWD", "4MATIC": "AWD", "XDRIVE": "AWD"}.get(
            value, value)

    km = _RANGE_KM.search(upper)
    if km:
        spec.range_km = float(km.group(1))
    kwh = _KWH.search(upper)
    if kwh:
        spec.battery_kwh = float(kwh.group(1))
    if spec.range_km is None and spec.battery_kwh is None:
        # "AION UT 420 STANDARD" - a bare three-digit number in these labels is
        # the range figure, so record it but keep it distinguishable.
        bare = _BARE_RANGE.search(upper)
        if bare:
            spec.range_km = float(bare.group(1))

    powertrain = _POWERTRAIN.search(upper)
    if powertrain:
        token = powertrain.group(1).upper().replace("-", "")
        spec.powertrain_hint = _POWERTRAIN_CANON.get(token, token)

    for grade in GRADE_WORDS:
        if re.search(rf"\b{re.escape(grade)}\b", upper):
            spec.grade = grade
            break
    return spec


def residual_trim(catalog: Catalog, model_id: str, raw_label: str) -> str:
    """What the DLT label says beyond the brand and model names.

    Word order is preserved so the ledger shows the marque's own wording, not a
    reshuffled bag of tokens.
    """
    model = catalog.models[model_id]
    brand = catalog.brands[model.brand_id]
    known: set[str] = set()
    for name in (model.name_en, model.name_th, model.nameplate,
                 brand.name_en, brand.name_th, *model.aliases):
        known.update(fold(name).split())

    kept: list[str] = []
    for word in str(raw_label or "").replace("(", " ").replace(")", " ").split():
        folded = fold(word).split()
        if folded and all(token in known for token in folded):
            continue
        kept.append(word.strip("-,"))
    return " ".join(w for w in kept if w)


def trim_id_for(model_id: str, trim_label: str) -> str:
    return f"{model_id}#{slug(trim_label) if trim_label else 'base'}"


def record(conn: sqlite3.Connection, catalog: Catalog, rows: Iterable[dict],
           source_id: int) -> int:
    """Write ledger rows for the trim-detail brands. Returns rows written.

    ``rows`` are ``{period, registration_type, province, model_id, units,
    raw_label}`` produced by the master ingest - the ledger reads the same
    resolved rows so the two can never disagree about which car it was.
    """
    detail_brands = set(catalog.trim_detail_brands())
    if not detail_brands:
        return 0

    dims: dict[str, tuple] = {}
    facts: list[tuple] = []
    for row in rows:
        model_id = row.get("model_id")
        if not model_id or model_id not in catalog.models:
            continue
        model = catalog.models[model_id]
        if model.brand_id not in detail_brands:
            continue

        label = residual_trim(catalog, model_id, row.get("raw_label", ""))
        spec = parse_trim(label)
        tid = trim_id_for(model_id, spec.trim_label)
        brand = catalog.brands[model.brand_id]
        dims[tid] = (
            tid, catalog.year, brand.id, brand.name_en, model_id,
            model.nameplate or model.name_en, model.name_en, spec.trim_label,
            spec.grade, spec.drive, spec.range_km, spec.battery_kwh,
            spec.powertrain_hint, row.get("raw_label", ""),
        )
        facts.append((row["period"], row["registration_type"],
                      row.get("province", "ALL"), tid, row["units"], source_id,
                      row.get("raw_label", "")))

    with conn:
        conn.executemany(
            "INSERT INTO dim_trim (trim_id, catalog_year, brand_id, brand, "
            "model_id, nameplate, model, trim_label, grade, drive, range_km, "
            "battery_kwh, powertrain_hint, raw_example) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT (trim_id, catalog_year) DO UPDATE SET "
            "grade=excluded.grade, drive=excluded.drive, "
            "range_km=excluded.range_km, battery_kwh=excluded.battery_kwh, "
            "powertrain_hint=excluded.powertrain_hint",
            list(dims.values()))
        conn.executemany(
            "INSERT INTO fact_trim (period, registration_type, province, "
            "trim_id, units, source_id, raw_label) VALUES (?,?,?,?,?,?,?) "
            "ON CONFLICT (period, registration_type, province, trim_id, "
            "source_id, raw_label) DO UPDATE SET units = excluded.units",
            facts)
    return len(facts)


def reconcile(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Per model and month, ledger units minus master units.

    An empty result means the two sets of books agree everywhere, which is the
    only state in which the folded master and the split ledger can both be
    quoted in the same report.
    """
    return conn.execute("""
        WITH ledger AS (
            SELECT t.model_id AS model_id, f.period AS period,
                   SUM(f.units) AS units
            FROM fact_trim f
            JOIN dim_trim t
              ON t.trim_id = f.trim_id
             -- dim_trim is keyed by (trim_id, catalog_year); without the year
             -- the join fans a fact out once per year the trim exists in.
             AND t.catalog_year = CAST(substr(f.period, 1, 4) AS INTEGER)
            GROUP BY t.model_id, f.period
        ), master AS (
            SELECT unit_id AS model_id, period, SUM(units) AS units
            FROM fact_registration WHERE grain = 'MODEL'
            GROUP BY unit_id, period
        )
        SELECT ledger.model_id, ledger.period,
               ledger.units AS ledger_units,
               COALESCE(master.units, 0) AS master_units,
               ledger.units - COALESCE(master.units, 0) AS difference
        FROM ledger LEFT JOIN master
          ON master.model_id = ledger.model_id AND master.period = ledger.period
        WHERE ABS(ledger.units - COALESCE(master.units, 0)) > 0.001
        ORDER BY ABS(ledger.units - COALESCE(master.units, 0)) DESC
    """).fetchall()


TRIM_COLUMNS = ("period", "registration_type", "brand", "nameplate", "model",
                "trim_label", "grade", "drive", "range_km", "battery_kwh",
                "powertrain_hint", "segment", "body_type", "market_position",
                "powertrain", "brand_segment", "units", "raw_label")


def rows(conn: sqlite3.Connection, *, period_from: Optional[str] = None,
         period_to: Optional[str] = None, brand: Optional[str] = None
         ) -> list[dict[str, Any]]:
    clauses, params = [], []
    if period_from:
        clauses.append("period >= ?"); params.append(period_from)
    if period_to:
        clauses.append("period <= ?"); params.append(period_to)
    if brand:
        clauses.append("lower(brand) = ?"); params.append(brand.lower())
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    sql = (f"SELECT {', '.join(TRIM_COLUMNS)} FROM trim_classified{where} "
           "ORDER BY units DESC")
    return [dict(r) for r in conn.execute(sql, params)]


def export_csv(conn: sqlite3.Connection, path: Path | str, **filters: Any) -> int:
    """Write the ledger to its own file, separate from the master warehouse."""
    data = rows(conn, **filters)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(TRIM_COLUMNS),
                                extrasaction="ignore")
        writer.writeheader()
        writer.writerows(data)
    return len(data)
