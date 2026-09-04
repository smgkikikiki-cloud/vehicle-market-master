"""Month-effective vehicle state for fields that genuinely change over time.

V1 deliberately keeps only three temporal facets:

* price_thb
* origin_country
* import_type

Rows are sparse change-points, not monthly snapshots. A value entered for
2026-05 remains effective until a later row changes that field. Editing a
change-point updates vehicle history while an append-only audit table preserves
what the analyst changed and why.
"""

from __future__ import annotations

import re
import sqlite3
from typing import Any

from .db import DIM_FACETS, DIM_FLAGS, DIM_NUMERIC
from .price_taxonomy import price_band_sql
from .taxonomy import ImportType, normalize_country

_UNSET = object()
_ALLOWED_GRAINS = {"MODEL", "VARIANT"}
_STATE_FIELDS = ("price_thb", "origin_country", "import_type")
_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS monthly_vehicle_state (
    unit_id          TEXT NOT NULL,
    grain            TEXT NOT NULL,
    effective_month  TEXT NOT NULL,
    price_thb        REAL,
    origin_country   TEXT,
    import_type      TEXT,
    note             TEXT,
    created_at       TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at       TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (unit_id, grain, effective_month)
);
CREATE INDEX IF NOT EXISTS ix_monthly_state_lookup
    ON monthly_vehicle_state(unit_id, grain, effective_month);

CREATE TABLE IF NOT EXISTS monthly_state_audit (
    audit_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    unit_id          TEXT NOT NULL,
    grain            TEXT NOT NULL,
    effective_month  TEXT NOT NULL,
    field            TEXT NOT NULL,
    old_value        TEXT,
    new_value        TEXT,
    reason           TEXT,
    changed_at       TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS ix_monthly_audit_unit
    ON monthly_state_audit(unit_id, grain, effective_month, changed_at);
"""


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA)


def _month(value: str) -> str:
    token = str(value).strip()
    if not _MONTH_RE.match(token):
        raise ValueError("effective_month must be YYYY-MM")
    return token


def _grain(value: str) -> str:
    token = str(value).strip().upper()
    if token not in _ALLOWED_GRAINS:
        raise ValueError("monthly state supports MODEL or VARIANT grain only")
    return token


def _normalise_price(value: Any) -> float | None:
    if value is None:
        return None
    price = float(str(value).replace(",", ""))
    if price < 0:
        raise ValueError("price_thb must not be negative")
    return price


def _normalise_import(value: Any) -> str | None:
    if value is None:
        return None
    return ImportType.parse(value).value


def _normalise_origin(value: Any) -> str | None:
    if value is None:
        return None
    return normalize_country(str(value))


def _assert_unit(conn: sqlite3.Connection, unit_id: str, grain: str,
                 effective_month: str) -> None:
    year = int(effective_month[:4])
    row = conn.execute(
        "SELECT 1 FROM dim_unit WHERE unit_id = ? AND grain = ? "
        "AND catalog_year = ? LIMIT 1",
        (unit_id, grain, year),
    ).fetchone()
    if row is None:
        raise ValueError(
            f"unknown {grain} unit {unit_id!r} in catalog year {year}"
        )


def set_state(conn: sqlite3.Connection, unit_id: str, effective_month: str, *,
              grain: str = "MODEL", price_thb: Any = _UNSET,
              origin_country: Any = _UNSET, import_type: Any = _UNSET,
              note: Any = _UNSET, reason: str | None = None) -> bool:
    """Insert or edit one monthly change-point.

    Omitted fields are untouched. Passing ``None`` explicitly clears that field
    from this change-point, causing earlier history/base catalog data to apply.
    Returns True only when something actually changed.
    """
    ensure_schema(conn)
    month = _month(effective_month)
    grain = _grain(grain)
    unit_id = str(unit_id).strip()
    _assert_unit(conn, unit_id, grain, month)

    existing = conn.execute(
        "SELECT * FROM monthly_vehicle_state WHERE unit_id=? AND grain=? "
        "AND effective_month=?",
        (unit_id, grain, month),
    ).fetchone()
    current = dict(existing) if existing else {
        "price_thb": None, "origin_country": None, "import_type": None,
        "note": None,
    }

    supplied: dict[str, Any] = {}
    if price_thb is not _UNSET:
        supplied["price_thb"] = _normalise_price(price_thb)
    if origin_country is not _UNSET:
        supplied["origin_country"] = _normalise_origin(origin_country)
    if import_type is not _UNSET:
        supplied["import_type"] = _normalise_import(import_type)
    if note is not _UNSET:
        supplied["note"] = None if note is None else str(note).strip() or None
    if not supplied:
        return False

    changed = {k: v for k, v in supplied.items() if current.get(k) != v}
    if not changed:
        return False

    new = dict(current)
    new.update(supplied)
    with conn:
        for field, value in changed.items():
            conn.execute(
                "INSERT INTO monthly_state_audit "
                "(unit_id, grain, effective_month, field, old_value, new_value, reason) "
                "VALUES (?,?,?,?,?,?,?)",
                (unit_id, grain, month, field,
                 None if current.get(field) is None else str(current.get(field)),
                 None if value is None else str(value), reason),
            )

        if all(new.get(f) is None for f in _STATE_FIELDS) and new.get("note") is None:
            conn.execute(
                "DELETE FROM monthly_vehicle_state WHERE unit_id=? AND grain=? "
                "AND effective_month=?", (unit_id, grain, month))
        else:
            conn.execute(
                "INSERT INTO monthly_vehicle_state "
                "(unit_id, grain, effective_month, price_thb, origin_country, "
                " import_type, note) VALUES (?,?,?,?,?,?,?) "
                "ON CONFLICT(unit_id, grain, effective_month) DO UPDATE SET "
                "price_thb=excluded.price_thb, origin_country=excluded.origin_country, "
                "import_type=excluded.import_type, note=excluded.note, "
                "updated_at=datetime('now')",
                (unit_id, grain, month, new.get("price_thb"),
                 new.get("origin_country"), new.get("import_type"), new.get("note")),
            )
    return True


def delete_change(conn: sqlite3.Connection, unit_id: str, effective_month: str, *,
                  grain: str = "MODEL", reason: str | None = None) -> bool:
    """Remove a mistaken change-point; audit history is preserved."""
    ensure_schema(conn)
    month = _month(effective_month)
    grain = _grain(grain)
    row = conn.execute(
        "SELECT * FROM monthly_vehicle_state WHERE unit_id=? AND grain=? "
        "AND effective_month=?", (unit_id, grain, month)).fetchone()
    if row is None:
        return False
    row = dict(row)
    with conn:
        for field in (*_STATE_FIELDS, "note"):
            if row.get(field) is not None:
                conn.execute(
                    "INSERT INTO monthly_state_audit "
                    "(unit_id, grain, effective_month, field, old_value, new_value, reason) "
                    "VALUES (?,?,?,?,?,NULL,?)",
                    (unit_id, grain, month, field, str(row[field]), reason),
                )
        conn.execute(
            "DELETE FROM monthly_vehicle_state WHERE unit_id=? AND grain=? "
            "AND effective_month=?", (unit_id, grain, month))
    return True


def history(conn: sqlite3.Connection, unit_id: str, *, grain: str = "MODEL") -> list[dict[str, Any]]:
    ensure_schema(conn)
    grain = _grain(grain)
    return [dict(r) for r in conn.execute(
        "SELECT * FROM monthly_vehicle_state WHERE unit_id=? AND grain=? "
        "ORDER BY effective_month", (unit_id, grain))]


def audit_log(conn: sqlite3.Connection, unit_id: str | None = None, *,
              grain: str | None = None) -> list[dict[str, Any]]:
    ensure_schema(conn)
    clauses: list[str] = []
    params: list[Any] = []
    if unit_id is not None:
        clauses.append("unit_id=?")
        params.append(unit_id)
    if grain is not None:
        clauses.append("grain=?")
        params.append(_grain(grain))
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    return [dict(r) for r in conn.execute(
        "SELECT * FROM monthly_state_audit" + where +
        " ORDER BY audit_id", params)]


def _latest_value(conn: sqlite3.Connection, unit_id: str, grain: str,
                  month: str, field: str) -> tuple[Any, str | None]:
    row = conn.execute(
        f"SELECT {field}, effective_month FROM monthly_vehicle_state "
        f"WHERE unit_id=? AND grain=? AND effective_month<=? "
        f"AND {field} IS NOT NULL ORDER BY effective_month DESC LIMIT 1",
        (unit_id, grain, month),
    ).fetchone()
    return ((row[field], row["effective_month"]) if row else (None, None))


def effective_state(conn: sqlite3.Connection, unit_id: str, month: str, *,
                    grain: str = "MODEL") -> dict[str, Any]:
    """Resolve catalog base + latest sparse monthly changes as of YYYY-MM."""
    ensure_schema(conn)
    month = _month(month)
    grain = _grain(grain)
    year = int(month[:4])
    base = conn.execute(
        "SELECT * FROM dim_unit WHERE unit_id=? AND grain=? AND catalog_year=?",
        (unit_id, grain, year),
    ).fetchone()
    if base is None:
        raise ValueError(f"unknown {grain} unit {unit_id!r} in catalog year {year}")
    out = dict(base)
    sources: dict[str, str] = {}
    for field in _STATE_FIELDS:
        value, effective_month = _latest_value(conn, unit_id, grain, month, field)
        if effective_month is not None:
            out[field] = value
            sources[field] = effective_month
    out["effective_months"] = sources
    return out


def _latest_sql(field: str, alias: str = "b") -> str:
    return (
        f"(SELECT ms.{field} FROM monthly_vehicle_state ms "
        f"WHERE ms.unit_id={alias}.unit_id AND ms.grain={alias}.grain "
        f"AND ms.effective_month<={alias}.period AND ms.{field} IS NOT NULL "
        f"ORDER BY ms.effective_month DESC LIMIT 1)"
    )


def _legacy_market_position_sql(price_expr: str) -> str:
    return (
        "CASE "
        f"WHEN {price_expr} < 500000 THEN 'ENTRY' "
        f"WHEN {price_expr} < 1000000 THEN 'VOLUME' "
        f"WHEN {price_expr} < 1800000 THEN 'UPPER' "
        "ELSE 'LUXURY' END"
    )


def _direct_price_band_sql(price_expr: str) -> str:
    return (
        "CASE "
        f"WHEN {price_expr} < 1000000 THEN 'UNDER_1M' "
        f"WHEN {price_expr} < 2000000 THEN '1M_TO_2M' "
        "ELSE '2M_PLUS' END"
    )


def effective_source_sql(base_sql: str) -> str:
    """Wrap a cube source so every fact uses state effective in its own month."""
    p = _latest_sql("price_thb")
    o = _latest_sql("origin_country")
    i = _latest_sql("import_type")
    effective_price = f"COALESCE({p}, b.price_thb)"
    effective_origin = f"COALESCE({o}, b.origin_country)"
    effective_import = f"COALESCE({i}, b.import_type)"

    meta = (
        "b.fact_id, b.period, b.fact_registration_type, b.province, b.grain, "
        "b.units, b.raw_label, b.source_id, b.match_how, b.match_score, "
        "b.unit_id, b.catalog_year, b.estimated"
    )
    facets: list[str] = []
    for field in DIM_FACETS:
        if field == "origin_country":
            facets.append(f"{effective_origin} AS origin_country")
        elif field == "import_type":
            facets.append(f"{effective_import} AS import_type")
        elif field == "market_position":
            facets.append(
                f"CASE WHEN {p} IS NOT NULL THEN "
                f"{_legacy_market_position_sql(p)} ELSE b.market_position END "
                "AS market_position"
            )
        else:
            facets.append(f"b.{field}")

    numeric = [f"{effective_price} AS price_thb" if field == "price_thb"
               else f"b.{field}" for field in DIM_NUMERIC]
    flags: list[str] = []
    for field in DIM_FLAGS:
        if field == "is_locally_assembled":
            flags.append(
                f"CASE WHEN {i} IS NULL AND {o} IS NULL THEN b.is_locally_assembled "
                f"WHEN {effective_import} IN ('CKD','SKD') OR "
                f"({effective_import}='CBU' AND {effective_origin}='TH') "
                "THEN 1 ELSE 0 END AS is_locally_assembled"
            )
        else:
            flags.append(f"b.{field}")

    price_band = (
        f"CASE WHEN {p} IS NOT NULL THEN {_direct_price_band_sql(p)} "
        f"ELSE {price_band_sql('b')} END AS price_band"
    )
    columns = ", ".join([meta, *facets, *numeric, *flags, price_band])
    return f"SELECT {columns} FROM ({base_sql}) b"
