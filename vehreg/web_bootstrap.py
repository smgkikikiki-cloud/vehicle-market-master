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
DEFAULT_STATE_SEED = ROOT / "data" / "research" / "monthly_production_state.csv"
PROVINCIAL_SOURCE_NAME = "DLT Provincial Brand-Model-Province"


def database_path() -> Path:
    return Path(os.environ.get("VEHREG_DB", str(DEFAULT_DB_PATH)))


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
        ingest_csv(conn, catalogs[year], path, f"WEB {period}",
                   colmap=dlt.column_map(), publisher="DLT")
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
        "state_seed": seeded,
        "provincial": provincial_state,
        "db": str(db),
    }
