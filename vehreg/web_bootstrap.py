"""Small reusable database bootstrap for Streamlit secondary pages."""

from __future__ import annotations

import os
from pathlib import Path

from . import dlt
from .catalog import DATA_DIR, Catalog, available_years
from .db import connect, rebuild_dimension
from .ingest import ingest_csv
from .monthly_state import ensure_schema as ensure_monthly_schema
from .state_seed import load_seed_csv

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = ROOT / "data" / "vehreg.sqlite3"
DEFAULT_RAW_DIR = ROOT / "data" / "raw"
DEFAULT_PIVOT_DIR = ROOT / "data" / "raw_pivot"
DEFAULT_STATE_SEED = ROOT / "data" / "research" / "monthly_production_state.csv"
PROVINCIAL_SOURCE_NAME = "DLT Provincial Brand-Model-Province"


def database_path() -> Path:
    return Path(os.environ.get("VEHREG_DB", str(DEFAULT_DB_PATH)))


def pivot_dir() -> Path:
    """Months read from the DLT pivot workbook rather than the monthly API.

    Kept in their own directory because they are a weaker source: the pivot
    carries no registration class, so a pickup's cab split is not available and
    that volume queues for review instead of classifying. They are loaded only
    for months the API exports do not cover.
    """
    return Path(os.environ.get("VEHREG_PIVOT_DIR", str(DEFAULT_PIVOT_DIR)))


def raw_dir() -> Path:
    """Where the committed monthly DLT exports live.

    Pages need this to check one month's payload against another's, which is a
    question about the files rather than about the warehouse.
    """
    return Path(os.environ.get("VEHREG_RAW_DIR", str(DEFAULT_RAW_DIR)))


def bootstrap_database(db_path: Path | str | None = None,
                       raw_dir: Path | str | None = None) -> dict[str, object]:
    """Build dimensions and ingest configured DLT sources idempotently.

    The committed month-effective production seed is applied on every boot.
    Without it a fresh database reports Thailand-built volume about three
    points low, because models such as HAVAL H6 and TANK 300 keep their
    imported origin for the months before the seed's change-points. Re-running
    is safe: ``load_seed_csv`` is idempotent.

    National monthly CSVs remain committed under ``data/raw`` as before.
    Provincial data is intentionally private: when
    ``VEHREG_PROVINCIAL_XLSX`` points to a server-side workbook, the snapshot is
    ingested into the separate provincial fact table. No provincial workbook is
    required for the national app to boot.
    """
    db = Path(db_path) if db_path is not None else database_path()
    raw = Path(raw_dir) if raw_dir is not None else DEFAULT_RAW_DIR
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = connect(db)
    ensure_monthly_schema(conn)

    catalogs: dict[int, Catalog] = {}
    rebuilt: list[int] = []
    for year in available_years(DATA_DIR):
        catalog = Catalog.load(DATA_DIR, year)
        catalogs[year] = catalog
        rebuild_dimension(conn, catalog)
        rebuilt.append(year)

    ingested: list[str] = []
    duplicates: list[dict[str, str]] = []
    for path in sorted(raw.glob("dlt_????-??.csv")):
        period = path.stem.removeprefix("dlt_")
        try:
            year = int(period[:4])
        except ValueError:
            continue
        if year not in catalogs:
            continue
        absolute = str(path.resolve())
        already = conn.execute(
            "SELECT 1 FROM dim_source WHERE file_name=? OR file_name LIKE ? "
            "OR file_name LIKE ? OR name IN (?,?,?) LIMIT 1",
            (absolute, f"%/{path.name}", f"%\\{path.name}",
             f"DLT {period}", path.name, f"WEB {period}"),
        ).fetchone()
        if already:
            continue
        try:
            ingest_csv(conn, catalogs[year], path, f"WEB {period}",
                       colmap=dlt.column_map(), publisher="DLT")
        except ValueError as exc:
            # A month whose payload repeats one already loaded is left out
            # rather than doubling a year's registrations. Booting has to keep
            # working, so this is reported, not raised.
            if "already loaded as" not in str(exc):
                raise
            duplicates.append({"period": period, "reason": str(exc)})
            continue
        ingested.append(period)

    # Secondary sources come after the exports, best first, and only where
    # nothing better already covers the period. Precedence is export > long >
    # pivot, which is the order of how much each one can say: the export and the
    # long sheet both carry the registration class the matcher needs to split a
    # pickup by cab, the pivot does not.
    pivot = Path(os.environ.get("VEHREG_PIVOT_DIR", str(DEFAULT_PIVOT_DIR)))
    covered = {p.stem.removeprefix("dlt_") for p in raw.glob("dlt_????-??.csv")}
    secondary = (sorted(pivot.glob("long_????-??.csv"))
                 + sorted(pivot.glob("pivot_????-??.csv")))
    for path in secondary:
        period = path.stem.split("_", 1)[1]
        if period in covered:
            continue
        try:
            year = int(period[:4])
        except ValueError:
            continue
        if year not in catalogs:
            continue
        label = "LONG" if path.name.startswith("long_") else "PIVOT"
        already = conn.execute(
            "SELECT 1 FROM dim_source WHERE file_name=? OR file_name LIKE ? "
            "OR name IN (?,?) LIMIT 1",
            (str(path.resolve()), f"%/{path.name}",
             f"PIVOT {period}", f"LONG {period}"),
        ).fetchone()
        if already:
            continue
        note = ("DLT long sheet; carries the registration class"
                if label == "LONG" else
                "DLT pivot workbook; no registration class, so cab-split "
                "volume stays on the brand")
        try:
            ingest_csv(conn, catalogs[year], path, f"{label} {period}",
                       publisher="DLT", notes=note)
        except ValueError as exc:
            if "already loaded as" not in str(exc):
                raise
            duplicates.append({"period": period, "reason": str(exc)})
            continue
        covered.add(period)
        ingested.append(period)

    seeded: dict[str, object] | None = None
    seed_path = Path(os.environ.get("VEHREG_STATE_SEED", str(DEFAULT_STATE_SEED)))
    if seed_path.exists():
        report = load_seed_csv(conn, seed_path)
        seeded = {"path": str(seed_path), "rows": report["rows"],
                  "applied": report["applied"], "unchanged": report["unchanged"],
                  "errors": report["errors"]}

    provincial_state: dict[str, object] | None = None
    provincial_env = os.environ.get("VEHREG_PROVINCIAL_XLSX", "").strip()
    if provincial_env:
        provincial_path = Path(provincial_env)
        if provincial_path.exists():
            # Local import avoids making the ordinary national bootstrap depend
            # on openpyxl unless a private provincial workbook is configured.
            from .provincial import ensure_schema as ensure_provincial_schema
            from .provincial import ingest_provincial_xlsx

            ensure_provincial_schema(conn)
            report = ingest_provincial_xlsx(
                conn,
                catalogs,
                provincial_path,
                source_name=PROVINCIAL_SOURCE_NAME,
            )
            provincial_state = {
                "path": str(provincial_path),
                "unchanged": report.unchanged,
                "facts_written": report.facts_written,
                "review_rows": report.review_rows,
                "units_ingested": report.units_ingested,
                "units_review": report.units_review,
            }
        else:
            provincial_state = {
                "path": str(provincial_path),
                "error": "VEHREG_PROVINCIAL_XLSX path does not exist",
            }

    conn.close()
    return {
        "years": rebuilt,
        "ingested": ingested,
        "duplicates": duplicates,
        "state_seed": seeded,
        "provincial": provincial_state,
        "db": str(db),
    }
