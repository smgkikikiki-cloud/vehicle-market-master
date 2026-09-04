"""Small reusable database bootstrap for Streamlit secondary pages."""

from __future__ import annotations

import os
from pathlib import Path

from . import dlt
from .catalog import DATA_DIR, Catalog, available_years
from .db import connect, rebuild_dimension
from .ingest import ingest_csv
from .monthly_state import ensure_schema as ensure_monthly_schema

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = ROOT / "data" / "vehreg.sqlite3"
DEFAULT_RAW_DIR = ROOT / "data" / "raw"


def database_path() -> Path:
    return Path(os.environ.get("VEHREG_DB", str(DEFAULT_DB_PATH)))


def bootstrap_database(db_path: Path | str | None = None,
                       raw_dir: Path | str | None = None) -> dict[str, object]:
    """Build dimensions and ingest committed monthly DLT files idempotently."""
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

    conn.close()
    return {"years": rebuilt, "ingested": ingested, "db": str(db)}
