"""Cross-tab queries over the classified facts.

Any facet may be grouped by, filtered on, or crossed with any other - that is
the whole point of keeping the dimensions orthogonal. Two rules the cube
enforces on top of that:

* **Honesty about grain.** A query grouped by ``powertrain`` shows a ``MIXED``
  bucket where volume only arrived at model level for a model that sells
  several powertrains, unless an allocation profile has been supplied.
* **Scope is explicit.** By default only ``CORE`` models are counted - no grey
  imports, no supercars, nothing outside the official distributor. Anything
  left out is reported on every result rather than silently dropped.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional, Sequence

from .db import DIM_FACETS, DIM_FLAGS, DIM_NUMERIC, MIXED
from .taxonomy import DEFAULT_SCOPES

#: Columns a caller may group by or filter on. Anything else is rejected, which
#: is also what keeps the generated SQL injection-free.
GROUPABLE: frozenset[str] = frozenset(
    DIM_FACETS + DIM_FLAGS + ("period", "province", "grain",
                              "fact_registration_type", "unit_id", "year",
                              "quarter", "catalog_year")
)
FILTERABLE: frozenset[str] = GROUPABLE | frozenset(DIM_NUMERIC)

_EXPR = {
    "year": "substr(period, 1, 4)",
    "quarter": "substr(period, 1, 4) || '-Q' || "
               "CAST((CAST(substr(period, 6, 2) AS INTEGER) + 2) / 3 AS TEXT)",
}

_OPS = {
    "eq": "=", "ne": "!=", "lt": "<", "lte": "<=", "gt": ">", "gte": ">=",
}


def _column(name: str) -> str:
    return _EXPR.get(name, name)


@dataclass
class CubeResult:
    dimensions: list[str]
    rows: list[dict[str, Any]]
    total_units: float
    mixed_units: float = 0.0
    estimated_units: float = 0.0
    excluded_by_scope: dict[str, float] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    @property
    def excluded_units(self) -> float:
        return sum(self.excluded_by_scope.values())

    def render(self, limit: int = 40, width: int = 26) -> str:
        if not self.rows:
            return "no rows"
        headers = self.dimensions + ["units", "share"]
        lines = [" | ".join(h.ljust(width if h in self.dimensions else 10)
                            for h in headers)]
        lines.append("-" * len(lines[0]))
        for row in self.rows[:limit]:
            cells = [str(row.get(d) if row.get(d) is not None else "-")[:width]
                     .ljust(width) for d in self.dimensions]
            cells.append(f"{row['units']:,.0f}".rjust(10))
            cells.append(f"{row['share']:.1%}".rjust(10))
            lines.append(" | ".join(cells))
        if len(self.rows) > limit:
            lines.append(f"... {len(self.rows) - limit} more rows")
        lines.append(f"total: {self.total_units:,.0f} units")
        if self.excluded_by_scope:
            detail = ", ".join(f"{k} {v:,.0f}" for k, v in
                               sorted(self.excluded_by_scope.items()))
            lines.append(f"excluded by scope: {detail} "
                         "(pass --scope all to include them)")
        if self.mixed_units:
            lines.append(
                f"of which {self.mixed_units:,.0f} sit in a MIXED bucket because "
                "the source only reported that far down")
        if self.estimated_units:
            lines.append(f"of which {self.estimated_units:,.0f} are allocated "
                         "estimates, not reported values")
        for note in self.notes:
            lines.append(f"note: {note}")
        return "\n".join(lines)


#: Pass this as ``scopes`` to count everything, grey imports included.
ALL_SCOPES = "all"


def _normalise_scopes(scopes: Optional[Sequence[str] | str]
                      ) -> Optional[list[str]]:
    if scopes is None:
        return list(DEFAULT_SCOPES)
    if isinstance(scopes, str):
        return None if scopes.lower() == ALL_SCOPES else [scopes.upper()]
    values = [str(s).upper() for s in scopes]
    return None if not values or ALL_SCOPES.upper() in values else values


def _build_where(filters: Optional[dict[str, Any]],
                 period_from: Optional[str], period_to: Optional[str],
                 grains: Optional[Sequence[str]],
                 scopes: Optional[Sequence[str]] = None) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if scopes:
        # A brand-grain row has no single scope; keep it rather than lose the
        # volume, and let the MIXED marker say what happened.
        clauses.append(
            f"(market_scope IN ({', '.join('?' for _ in scopes)}) "
            "OR market_scope IS NULL OR market_scope = 'MIXED')")
        params.extend(scopes)
    for key, value in (filters or {}).items():
        column, _, op = key.partition("__")
        if column not in FILTERABLE:
            raise ValueError(f"cannot filter on {column!r}")
        expr = _column(column)
        if op and op not in _OPS:
            raise ValueError(f"unknown operator {op!r}")
        if isinstance(value, (list, tuple, set)):
            values = list(value)
            if not values:
                continue
            clauses.append(f"{expr} IN ({', '.join('?' for _ in values)})")
            params.extend(values)
        elif value is None:
            clauses.append(f"{expr} IS NULL")
        else:
            clauses.append(f"{expr} {_OPS.get(op, '=')} ?")
            params.append(value)
    if period_from:
        clauses.append("period >= ?")
        params.append(period_from)
    if period_to:
        clauses.append("period <= ?")
        params.append(period_to)
    if grains:
        clauses.append(f"grain IN ({', '.join('?' for _ in grains)})")
        params.extend(grains)
    return (" WHERE " + " AND ".join(clauses)) if clauses else "", params


ALLOCATED_SOURCE = """
WITH allocated AS (
    SELECT f.fact_id, f.period, f.registration_type AS fact_registration_type,
           f.province, f.units * w.weight AS units, f.raw_label, f.source_id,
           f.match_how, f.match_score, 'VARIANT' AS grain, w.unit_id AS unit_id,
           1 AS estimated
    FROM fact_registration f
    JOIN allocation_weight w
      ON w.model_id = f.unit_id AND w.period = f.period
    WHERE f.grain = 'MODEL'
    UNION ALL
    SELECT f.fact_id, f.period, f.registration_type, f.province, f.units,
           f.raw_label, f.source_id, f.match_how, f.match_score, f.grain,
           f.unit_id, 0 AS estimated
    FROM fact_registration f
    WHERE f.grain != 'MODEL'
       OR NOT EXISTS (SELECT 1 FROM allocation_weight w
                      WHERE w.model_id = f.unit_id AND w.period = f.period)
)
SELECT a.*, d.catalog_year, {facets}
FROM allocated a
LEFT JOIN dim_unit d
       ON d.unit_id = a.unit_id AND d.grain = a.grain
      AND d.catalog_year = CAST(substr(a.period, 1, 4) AS INTEGER)
"""


def _source_sql(allocate: bool) -> str:
    if not allocate:
        return "SELECT fc.*, 0 AS estimated FROM fact_classified fc"
    facets = ", ".join(f"d.{c}" for c in DIM_FACETS + DIM_NUMERIC + DIM_FLAGS)
    return ALLOCATED_SOURCE.format(facets=facets)


def run(conn: sqlite3.Connection, group_by: Sequence[str], *,
        filters: Optional[dict[str, Any]] = None,
        period_from: Optional[str] = None, period_to: Optional[str] = None,
        grains: Optional[Sequence[str]] = None,
        scopes: Optional[Sequence[str] | str] = None,
        allocate: bool = False, order_by: str = "units",
        descending: bool = True, limit: Optional[int] = None) -> CubeResult:
    dims = list(group_by)
    for dim in dims:
        if dim not in GROUPABLE:
            raise ValueError(
                f"cannot group by {dim!r}; known facets: "
                f"{', '.join(sorted(GROUPABLE))}")
    if order_by not in {"units", *dims}:
        raise ValueError(f"cannot order by {order_by!r}")

    kept = _normalise_scopes(scopes)
    where, params = _build_where(filters, period_from, period_to, grains, kept)
    select_dims = ", ".join(f"{_column(d)} AS {d}" for d in dims)
    group_expr = ", ".join(_column(d) for d in dims)
    source = _source_sql(allocate)

    sql = (
        f"SELECT {select_dims + ', ' if select_dims else ''}"
        "SUM(units) AS units, SUM(units * estimated) AS estimated_units "
        f"FROM ({source}) {where} "
        + (f"GROUP BY {group_expr} " if group_expr else "")
        + f"ORDER BY {'units' if order_by == 'units' else _column(order_by)} "
          f"{'DESC' if descending else 'ASC'}"
    )
    if limit:
        sql += f" LIMIT {int(limit)}"

    rows = [dict(r) for r in conn.execute(sql, params)]
    total = sum(r["units"] or 0 for r in rows)
    estimated = sum(r.get("estimated_units") or 0 for r in rows)
    mixed = sum(r["units"] or 0 for r in rows
                if any(r.get(d) == MIXED for d in dims))
    for row in rows:
        row["units"] = row["units"] or 0.0
        row["share"] = (row["units"] / total) if total else 0.0

    excluded: dict[str, float] = {}
    if kept:
        skip_where, skip_params = _build_where(filters, period_from, period_to,
                                               grains, None)
        excluded = {
            r["market_scope"]: r["units"] or 0.0
            for r in conn.execute(
                f"SELECT market_scope, SUM(units) AS units FROM ({source}) "
                f"{skip_where} " + ("AND" if skip_where else "WHERE") +
                f" market_scope NOT IN ({', '.join('?' for _ in kept)}) "
                "GROUP BY market_scope", skip_params + list(kept))
            if (r["units"] or 0) > 0
        }

    notes: list[str] = []
    if mixed:
        notes.append(
            "MIXED means the source reported at model level for a model that "
            "spans more than one value of this facet - load an allocation "
            "profile to split it")
    return CubeResult(dims, rows, total, mixed, estimated, excluded, notes)


def timeseries(conn: sqlite3.Connection, group_by: Sequence[str], *,
               bucket: str = "period", **kwargs: Any) -> CubeResult:
    """Same query, with a time bucket appended as the last dimension."""
    if bucket not in {"period", "quarter", "year"}:
        raise ValueError("bucket must be period, quarter or year")
    return run(conn, [*group_by, bucket], order_by=bucket, descending=False,
               **kwargs)


def growth(conn: sqlite3.Connection, dimension: str, *, base: str, compare: str,
           **kwargs: Any) -> list[dict[str, Any]]:
    """Volume and share change for one facet between two periods or years.

    ``base``/``compare`` accept ``YYYY`` or ``YYYY-MM``; the shorter form
    aggregates the whole year.
    """
    def window(token: str) -> dict[str, Any]:
        if len(token) == 4:
            return {"period_from": f"{token}-01", "period_to": f"{token}-12"}
        return {"period_from": token, "period_to": token}

    left = {r[dimension]: r for r in
            run(conn, [dimension], **window(base), **kwargs).rows}
    right = {r[dimension]: r for r in
             run(conn, [dimension], **window(compare), **kwargs).rows}

    out: list[dict[str, Any]] = []
    for key in sorted(set(left) | set(right),
                      key=lambda k: -(right.get(k, {}).get("units", 0))):
        a = left.get(key, {"units": 0.0, "share": 0.0})
        b = right.get(key, {"units": 0.0, "share": 0.0})
        out.append({
            dimension: key,
            "units_base": a["units"], "units_compare": b["units"],
            "units_change": b["units"] - a["units"],
            "growth": ((b["units"] - a["units"]) / a["units"]
                       if a["units"] else None),
            "share_base": a["share"], "share_compare": b["share"],
            "share_change_pp": (b["share"] - a["share"]) * 100,
        })
    return out


def pivot(result: CubeResult, column_dimension: str) -> tuple[list[str], list[dict]]:
    """Reshape a cube result into rows x one column facet."""
    if column_dimension not in result.dimensions:
        raise ValueError(f"{column_dimension} is not in this result")
    row_dims = [d for d in result.dimensions if d != column_dimension]
    columns = sorted({str(r.get(column_dimension)) for r in result.rows})
    table: dict[tuple, dict[str, Any]] = {}
    for row in result.rows:
        key = tuple(row.get(d) for d in row_dims)
        entry = table.setdefault(key, {d: row.get(d) for d in row_dims})
        entry[str(row.get(column_dimension))] = row["units"]
        entry["total"] = entry.get("total", 0.0) + row["units"]
    ordered = sorted(table.values(), key=lambda r: -r.get("total", 0))
    return row_dims + columns + ["total"], ordered


def coverage_report(conn: sqlite3.Connection) -> dict[str, Any]:
    """How much of the loaded volume is classified, and how deeply."""
    by_grain = {r["grain"]: r["units"] for r in conn.execute(
        "SELECT grain, SUM(units) AS units FROM fact_registration GROUP BY grain")}
    review = conn.execute(
        "SELECT COALESCE(SUM(units), 0) AS units, COUNT(*) AS rows "
        "FROM ingest_review WHERE status = 'open' AND best_guess IS NULL"
    ).fetchone()
    unjoined = conn.execute(
        "SELECT COALESCE(SUM(units), 0) AS units FROM fact_classified "
        "WHERE unit_id IS NULL").fetchone()
    years = [int(r["y"]) for r in conn.execute(
        "SELECT DISTINCT CAST(substr(period, 1, 4) AS INTEGER) AS y "
        "FROM fact_registration ORDER BY y")]
    by_scope = {r["market_scope"] or "UNJOINED": r["units"] for r in conn.execute(
        "SELECT market_scope, SUM(units) AS units FROM fact_classified "
        "GROUP BY market_scope")}
    total = sum(by_grain.values())
    return {
        "fact_years": years,
        "units_by_scope": by_scope,
        "units_by_grain": by_grain,
        "units_total": total,
        "units_variant_grain_pct": (by_grain.get("VARIANT", 0) / total
                                    if total else 0.0),
        "units_unmatched_in_review": review["units"],
        "rows_unmatched_in_review": review["rows"],
        "units_without_dimension_row": unjoined["units"],
    }
