"""Small reusable database bootstrap for Streamlit secondary pages."""

from __future__ import annotations

import gzip
import os
import tempfile
from pathlib import Path

from . import dlt
from .catalog import DATA_DIR, Catalog, available_years
from .db import connect, rebuild_dimension
from .ingest import ingest_csv, sha256_of
from .monthly_state import ensure_schema as ensure_monthly_schema

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = ROOT / "data" / "vehreg.sqlite3"
DEFAULT_RAW_DIR = ROOT / "data" / "raw"
PROVINCIAL_SOURCE_NAME = "DLT Provincial Brand-Model-Province"


def database_path() -> Path:
    return Path(os.environ.get("VEHREG_DB", str(DEFAULT_DB_PATH)))


def _period_from_raw_path(path: Path) -> str | None:
    name = path.name
    if name.startswith("dlt_") and name.endswith(".csv.gz"):
        return name[4:-7]
    if name.startswith("dlt_") and name.endswith(".csv"):
        return name[4:-4]
    return None


def _national_sources(raw: Path) -> dict[str, Path]:
    """One committed source per month; a later official .csv beats .csv.gz.

    The gzip form is used for provenance-preserving private-workbook backfills
    without bloating the public repository. If DLT later publishes a complete
    official monthly resource, ``dlt_YYYY-MM.csv`` naturally supersedes the
    backfill on the next boot.
    """
    selected: dict[str, Path] = {}
    for path in sorted(raw.glob("dlt_????-??.csv.gz")):
        period = _period_from_raw_path(path)
        if period:
            selected[period] = path
    for path in sorted(raw.glob("dlt_????-??.csv")):
        period = _period_from_raw_path(path)
        if period:
            selected[period] = path
    return selected


def _existing_national_source(conn, path: Path, period: str):
    """Find the source row previously used for one committed monthly source."""
    absolute = str(path.resolve())
    filename = path.name
    return conn.execute(
        "SELECT source_id, name, file_sha256 FROM dim_source "
        "WHERE file_name=? OR file_name LIKE ? OR file_name LIKE ? "
        "OR name IN (?,?,?,?) LIMIT 1",
        (
            absolute,
            f"%/{filename}",
            f"%\\\\{filename}",
            f"DLT {period}",
            f"WEB {period}",
            f"BACKFILL {period}",
            filename,
        ),
    ).fetchone()


def _clear_source_facts(conn, source_id: int) -> None:
    """Remove one stale snapshot before re-ingesting a changed source file."""
    with conn:
        conn.execute("DELETE FROM fact_trim WHERE source_id=?", (source_id,))
        conn.execute("DELETE FROM fact_registration WHERE source_id=?", (source_id,))
        conn.execute("DELETE FROM ingest_review WHERE source_id=?", (source_id,))


def _plain_csv(path: Path) -> tuple[Path, bool]:
    """Return a readable CSV path and whether it is a temporary gunzip."""
    if not path.name.endswith(".csv.gz"):
        return path, False
    with gzip.open(path, "rb") as source:
        payload = source.read()
    handle = tempfile.NamedTemporaryFile(
        prefix=path.name[:-7] + "_", suffix=".csv", delete=False
    )
    try:
        handle.write(payload)
    finally:
        handle.close()
    return Path(handle.name), True


def bootstrap_database(db_path: Path | str | None = None,
                       raw_dir: Path | str | None = None) -> dict[str, object]:
    """Build dimensions and ingest configured DLT sources idempotently.

    National monthly files remain committed under ``data/raw``. Official DLT
    resources use ordinary CSV. Provenance-documented national backfills may be
    gzip-compressed CSV; they carry exactly the same six-column schema and are
    decompressed only for ingest.

    A committed source can be replaced (for example when a broken DLT resource
    is backfilled): SHA-256 is checked, only that source's old facts are
    cleared, then the replacement is ingested. This prevents a persistent DB
    from silently retaining an older partial snapshot.

    Provincial data is intentionally private: when
    ``VEHREG_PROVINCIAL_XLSX`` points to a server-side workbook, the snapshot is
    ingested into the separate provincial fact table.
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
    refreshed: list[str] = []
    for period, path in sorted(_national_sources(raw).items()):
        try:
            year = int(period[:4])
        except ValueError:
            continue
        if year not in catalogs:
            continue

        digest = sha256_of(path)
        existing = _existing_national_source(conn, path, period)
        if existing and existing["file_sha256"] == digest:
            continue

        source_name = (
            f"BACKFILL {period}" if path.name.endswith(".csv.gz")
            else f"WEB {period}"
        )
        if existing:
            source_name = str(existing["name"])
            _clear_source_facts(conn, int(existing["source_id"]))
            refreshed.append(period)

        ingest_path, temporary = _plain_csv(path)
        try:
            report = ingest_csv(
                conn,
                catalogs[year],
                ingest_path,
                source_name,
                colmap=dlt.column_map(),
                publisher="DLT",
                notes=(
                    "Committed national monthly source. Adjacent .meta.json "
                    "records whether this is an official monthly DLT resource "
                    "or a provenance-documented provincial aggregate backfill. "
                    "TDR canonical taxonomy is applied by Resolver/reporting."
                ),
            )
        finally:
            if temporary:
                ingest_path.unlink(missing_ok=True)

        with conn:
            conn.execute(
                "UPDATE dim_source SET file_name=?, file_sha256=? WHERE source_id=?",
                (str(path), digest, report.source_id),
            )
        ingested.append(period)

    provincial_state: dict[str, object] | None = None
    provincial_env = os.environ.get("VEHREG_PROVINCIAL_XLSX", "").strip()
    if provincial_env:
        provincial_path = Path(provincial_env)
        if provincial_path.exists():
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
        "refreshed": refreshed,
        "provincial": provincial_state,
        "db": str(db),
    }
