"""SQLite warehouse: one dimension row per unit per year, plus a fact table.

The dimension is rebuilt from the catalog, never hand-edited. There is exactly
one row per (unit, year, grain), because a year's catalog is a single settled
answer - no valid-from/valid-to, no back-dating, no reading last year's file to
classify this year's volume. Rebuilding a year replaces only that year.

DLT does not always publish down to the trim. A fact row records the grain it
actually arrived at - ``BRAND``, ``MODEL`` or ``VARIANT`` - and joins a
dimension row of the same grain and the same year. Where a model spans several
powertrains, the model-grain row reports ``MIXED`` for that facet rather than
picking one; the cube can then either show MIXED honestly or split it with an
allocation profile.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Sequence

from .catalog import Catalog
from .taxonomy import Grain

MIXED = "MIXED"

#: Facet columns materialised on every dimension row.
DIM_FACETS: tuple[str, ...] = (
    "brand", "nameplate", "model", "variant", "generation", "segment",
    "body_type", "cab_type", "market_position", "powertrain",
    "powertrain_group", "origin_country", "import_type", "brand_segment",
    "oem_group", "brand_origin", "drivetrain", "registration_type",
    "market_scope",
)
DIM_NUMERIC: tuple[str, ...] = ("price_thb", "price_min_thb", "price_max_thb",
                                "seats", "engine_cc", "battery_kwh")
DIM_FLAGS: tuple[str, ...] = ("is_electrified", "is_plug_in", "is_locally_assembled")

SCHEMA = f"""
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS dim_unit (
    unit_id      TEXT NOT NULL,
    catalog_year INTEGER NOT NULL,
    grain        TEXT NOT NULL,
    {", ".join(f"{c} TEXT" for c in DIM_FACETS)},
    {", ".join(f"{c} REAL" for c in DIM_NUMERIC)},
    {", ".join(f"{c} INTEGER" for c in DIM_FLAGS)},
    PRIMARY KEY (unit_id, catalog_year)
);
CREATE INDEX IF NOT EXISTS ix_dim_unit_grain
    ON dim_unit(catalog_year, grain);

CREATE TABLE IF NOT EXISTS dim_source (
    source_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL UNIQUE,
    publisher   TEXT,
    url         TEXT,
    file_name   TEXT,
    file_sha256 TEXT,
    fetched_at  TEXT,
    notes       TEXT
);

CREATE TABLE IF NOT EXISTS fact_registration (
    fact_id           INTEGER PRIMARY KEY AUTOINCREMENT,
    period            TEXT NOT NULL,         -- 'YYYY-MM'
    registration_type TEXT NOT NULL,
    province          TEXT NOT NULL DEFAULT 'ALL',
    unit_id           TEXT NOT NULL,
    grain             TEXT NOT NULL,
    units             REAL NOT NULL,
    source_id         INTEGER NOT NULL REFERENCES dim_source(source_id),
    raw_label         TEXT,
    match_how         TEXT,
    match_score       REAL,
    UNIQUE (period, registration_type, province, unit_id, source_id, raw_label)
);
CREATE INDEX IF NOT EXISTS ix_fact_period ON fact_registration(period);
CREATE INDEX IF NOT EXISTS ix_fact_unit ON fact_registration(unit_id, period);

-- Raw labels the owner has taught the matcher. Applied before fuzzy matching.
-- reg_type is part of the key because the same label means different cars in
-- different DLT files: "REVO" in a รย.1 export is the double cab, in a รย.3
-- export it is a single or smart cab. '*' matches any file.
CREATE TABLE IF NOT EXISTS alias_override (
    scope     TEXT NOT NULL,                -- 'brand' | 'model' | 'variant'
    raw       TEXT NOT NULL,
    reg_type  TEXT NOT NULL DEFAULT '*',
    target_id TEXT NOT NULL,
    added_at  TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (scope, raw, reg_type)
);

-- Anything the ingest refused to guess at. Never dropped, never auto-resolved.
CREATE TABLE IF NOT EXISTS ingest_review (
    review_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id  INTEGER NOT NULL REFERENCES dim_source(source_id),
    period     TEXT,
    raw_brand  TEXT,
    raw_model  TEXT,
    raw_label  TEXT,
    units      REAL,
    reason     TEXT NOT NULL,
    best_guess TEXT,
    score      REAL,
    status     TEXT NOT NULL DEFAULT 'open'  -- open | mapped | ignored
);

-- Optional variant mix used to split a model-grain fact. Weights per model and
-- month; rows produced this way are flagged estimated in the cube.
CREATE TABLE IF NOT EXISTS allocation_weight (
    model_id  TEXT NOT NULL,
    period    TEXT NOT NULL,
    unit_id   TEXT NOT NULL,
    weight    REAL NOT NULL,
    PRIMARY KEY (model_id, period, unit_id)
);

-- The trim ledger. A second, finer set of books kept only for the brands whose
-- DLT รุ่น field carries trim - the Chinese marques and Tesla. The master facts
-- above stay folded to the model; nothing here feeds them, and the two are
-- reconciled by `trim check`.
CREATE TABLE IF NOT EXISTS dim_trim (
    trim_id        TEXT NOT NULL,
    catalog_year   INTEGER NOT NULL,
    brand_id       TEXT NOT NULL,
    brand          TEXT,
    model_id       TEXT NOT NULL,
    nameplate      TEXT,
    model          TEXT,
    trim_label     TEXT NOT NULL,      -- '' when the label named no trim
    grade          TEXT,               -- PREMIUM, MAX, PRO, STD, ...
    drive          TEXT,               -- 2WD / 4WD / AWD / FWD / RWD
    range_km       REAL,
    battery_kwh    REAL,
    powertrain_hint TEXT,              -- EV / REEV / PHEV / DM-i / SHS / HEV
    raw_example    TEXT,
    PRIMARY KEY (trim_id, catalog_year)
);
CREATE INDEX IF NOT EXISTS ix_dim_trim_model ON dim_trim(model_id);

CREATE TABLE IF NOT EXISTS fact_trim (
    trim_fact_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    period            TEXT NOT NULL,
    registration_type TEXT NOT NULL,
    province          TEXT NOT NULL DEFAULT 'ALL',
    trim_id           TEXT NOT NULL,
    units             REAL NOT NULL,
    source_id         INTEGER NOT NULL REFERENCES dim_source(source_id),
    raw_label         TEXT,
    UNIQUE (period, registration_type, province, trim_id, source_id, raw_label)
);
CREATE INDEX IF NOT EXISTS ix_fact_trim_period ON fact_trim(period);

CREATE VIEW IF NOT EXISTS trim_classified AS
SELECT f.period, f.registration_type, f.province, f.units, f.raw_label,
       f.source_id, t.trim_id, t.brand, t.nameplate, t.model, t.model_id,
       t.trim_label, t.grade, t.drive, t.range_km, t.battery_kwh,
       t.powertrain_hint, t.catalog_year,
       d.segment, d.body_type, d.market_position, d.powertrain,
       d.powertrain_group, d.import_type, d.origin_country, d.brand_segment,
       d.market_scope, d.price_thb
FROM fact_trim f
JOIN dim_trim t
  ON t.trim_id = f.trim_id
 AND t.catalog_year = CAST(substr(f.period, 1, 4) AS INTEGER)
LEFT JOIN dim_unit d
  ON d.unit_id = t.model_id AND d.grain = 'MODEL'
 AND d.catalog_year = t.catalog_year;

CREATE VIEW IF NOT EXISTS fact_classified AS
SELECT f.fact_id, f.period, f.registration_type AS fact_registration_type,
       f.province, f.grain, f.units, f.raw_label, f.source_id,
       f.match_how, f.match_score,
       d.unit_id, d.catalog_year,
       {", ".join(f"d.{c}" for c in DIM_FACETS)},
       {", ".join(f"d.{c}" for c in DIM_NUMERIC)},
       {", ".join(f"d.{c}" for c in DIM_FLAGS)}
FROM fact_registration f
LEFT JOIN dim_unit d
       ON d.unit_id = f.unit_id
      AND d.grain = f.grain
      AND d.catalog_year = CAST(substr(f.period, 1, 4) AS INTEGER);
"""


def connect(path: Path | str) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


# --------------------------------------------------------------------------
# Dimension build
# --------------------------------------------------------------------------
def _consensus(values: Sequence[Any]) -> Any:
    """One value if every child agrees, else MIXED."""
    kept = [v for v in values if v is not None]
    if not kept:
        return None
    first = kept[0]
    return first if all(v == first for v in kept) else MIXED


def _flat(resolved) -> dict[str, Any]:
    row = resolved.as_row()
    return {c: row.get(c) for c in DIM_FACETS + DIM_NUMERIC + DIM_FLAGS}


def build_dimension(catalog: Catalog) -> list[dict[str, Any]]:
    """Variant-, model- and brand-grain rows for ``catalog.year``."""
    rows: list[dict[str, Any]] = []
    year = catalog.year

    for variant_id in catalog.variants:
        row = _flat(catalog.resolve(variant_id))
        row.update(unit_id=variant_id, catalog_year=year, grain=Grain.VARIANT.value)
        rows.append(row)

    for model_id in catalog.models:
        flats = [_flat(catalog.resolve(v.id)) for v in catalog.variants_of(model_id)]
        if not flats:
            continue
        row = {c: _consensus([f[c] for f in flats])
               for c in DIM_FACETS + DIM_NUMERIC + DIM_FLAGS}
        row["variant"] = None                 # a model row has no single trim
        row.update(unit_id=model_id, catalog_year=year, grain=Grain.MODEL.value)
        rows.append(row)

    for brand_id, brand in catalog.brands.items():
        flats = [_flat(catalog.resolve(v.id))
                 for m in catalog.models_of(brand_id)
                 for v in catalog.variants_of(m.id)]
        if not flats:
            continue
        row = {c: _consensus([f[c] for f in flats])
               for c in DIM_FACETS + DIM_NUMERIC + DIM_FLAGS}
        row["variant"] = None
        row["model"] = None
        row["nameplate"] = None
        row["generation"] = None
        row["brand"] = brand.name_en
        row["brand_segment"] = brand.brand_segment.value
        row["oem_group"] = brand.oem_group
        row.update(unit_id=brand_id, catalog_year=year, grain=Grain.BRAND.value)
        rows.append(row)

    return rows


DIM_COLUMNS: tuple[str, ...] = (
    ("unit_id", "catalog_year", "grain") + DIM_FACETS + DIM_NUMERIC + DIM_FLAGS
)


def rebuild_dimension(conn: sqlite3.Connection, catalog: Catalog) -> int:
    """Replace the dimension for ``catalog.year``. Other years are untouched."""
    rows = build_dimension(catalog)
    placeholders = ", ".join("?" for _ in DIM_COLUMNS)
    with conn:
        conn.execute("DELETE FROM dim_unit WHERE catalog_year = ?",
                     (catalog.year,))
        conn.executemany(
            f"INSERT INTO dim_unit ({', '.join(DIM_COLUMNS)}) "
            f"VALUES ({placeholders})",
            [tuple(row.get(c) for c in DIM_COLUMNS) for row in rows],
        )
    return len(rows)


def loaded_years(conn: sqlite3.Connection) -> list[int]:
    return [int(r["catalog_year"]) for r in conn.execute(
        "SELECT DISTINCT catalog_year FROM dim_unit ORDER BY catalog_year")]


def register_source(conn: sqlite3.Connection, name: str, **fields: Any) -> int:
    with conn:
        conn.execute(
            "INSERT OR IGNORE INTO dim_source (name, publisher, url, file_name, "
            "file_sha256, fetched_at, notes) VALUES (?,?,?,?,?,?,?)",
            (name, fields.get("publisher"), fields.get("url"),
             fields.get("file_name"), fields.get("file_sha256"),
             fields.get("fetched_at"), fields.get("notes")),
        )
    row = conn.execute("SELECT source_id FROM dim_source WHERE name = ?",
                       (name,)).fetchone()
    return int(row["source_id"])


def unmatched_summary(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT substr(reason, 1, "
        "  CASE WHEN instr(reason, ':') > 0 THEN instr(reason, ':') - 1 "
        "       ELSE length(reason) END) AS reason, "
        "  COUNT(*) AS rows, SUM(units) AS units "
        "FROM ingest_review WHERE status = 'open' GROUP BY 1 "
        "ORDER BY units DESC"
    ).fetchall()
