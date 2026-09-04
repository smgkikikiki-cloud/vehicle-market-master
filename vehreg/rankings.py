"""Reader-facing rankings above the canonical registration facts.

Ordinary trim/grade/drivetrain differences stay folded into one model. If one
catalog model spans multiple powertrains and the DLT label identifies the
powertrain, reporting treats each powertrain as a separate market model.

The Chinese EV trim ranking reads fact_trim only. It never feeds trim rows back
into the canonical market facts, so the detailed ranking cannot double-count
master registrations.
"""

from __future__ import annotations

import csv
import sqlite3
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Optional

from .trimledger import parse_trim

PLUGIN_POWERTRAINS = frozenset({"BEV", "PHEV", "REEV"})
DEFAULT_SCOPES = ("CORE", "EDGE")

# Some DLT labels identify only the non-default powertrain. January 2026 is the
# clean example: "S05 REEV MAX" is explicit, while "S05 MAX" / "S05 PLUS" are
# the BEV. Keep this map tiny and auditable; never infer a default generically.
UNLABELED_POWERTRAIN_DEFAULTS: dict[str, str] = {
    "deepal.deepal_s05": "BEV",
}


def source_powertrain(unit_id: str, catalog_powertrain: Optional[str],
                      raw_label: str) -> Optional[str]:
    """Return the powertrain justified by the source row."""
    catalog_pt = str(catalog_powertrain or "UNKNOWN").upper()
    if catalog_pt not in {"MIXED", "UNKNOWN", ""}:
        return catalog_pt

    hint = parse_trim(raw_label or "").powertrain_hint
    if hint:
        return str(hint).upper()
    if catalog_pt == "MIXED":
        return UNLABELED_POWERTRAIN_DEFAULTS.get(unit_id, "MIXED")
    return catalog_pt or "UNKNOWN"


def market_model_name(model: Optional[str], catalog_powertrain: Optional[str],
                      report_powertrain: Optional[str]) -> str:
    """Append a powertrain suffix only when the catalog model is mixed."""
    name = str(model or "UNKNOWN")
    if str(catalog_powertrain or "").upper() == "MIXED":
        pt = str(report_powertrain or "MIXED").upper()
        if pt not in {"MIXED", "UNKNOWN", ""}:
            return f"{name} {pt}"
    return name


def _scope_sql(scopes: Optional[Iterable[str]]) -> tuple[str, list[str]]:
    if scopes is None:
        return "", []
    values = [str(s).upper() for s in scopes]
    if not values:
        return "", []
    return (f" AND (market_scope IN ({', '.join('?' for _ in values)}) "
            "OR market_scope IS NULL OR market_scope='MIXED')", values)


def model_ranking(conn: sqlite3.Connection, period: str, *,
                  registration_type: Optional[str] = None,
                  brand: Optional[str] = None,
                  scopes: Optional[Iterable[str]] = DEFAULT_SCOPES,
                  limit: Optional[int] = None) -> list[dict[str, Any]]:
    """Master model ranking with mixed-powertrain models split by DLT label.

    Ordinary trims remain folded exactly as in the master warehouse. The split
    changes only the reporting identity of a catalog model whose model-level
    powertrain is MIXED.
    """
    sql = (
        "SELECT period, fact_registration_type, grain, units, raw_label, unit_id, "
        "brand, model, powertrain, market_scope "
        "FROM fact_classified WHERE period=? AND grain IN ('MODEL','VARIANT')"
    )
    params: list[Any] = [period]
    if registration_type and registration_type != "ALL":
        sql += " AND fact_registration_type=?"
        params.append(registration_type)
    if brand and brand != "ALL":
        sql += " AND lower(brand)=?"
        params.append(brand.lower())
    scope_clause, scope_params = _scope_sql(scopes)
    sql += scope_clause
    params.extend(scope_params)

    mixed_models = {
        (str(r["brand"] or ""), str(r["model"] or ""))
        for r in conn.execute(
            "SELECT brand, model FROM dim_unit "
            "WHERE catalog_year=? AND grain='MODEL' AND powertrain='MIXED'",
            (int(period[:4]),),
        )
    }

    grouped: dict[tuple[str, str, str], float] = defaultdict(float)
    for row in conn.execute(sql, params):
        catalog_pt = str(row["powertrain"] or "UNKNOWN").upper()
        is_mixed_parent = (
            catalog_pt == "MIXED" or
            (str(row["brand"] or ""), str(row["model"] or "")) in mixed_models
        )
        if (str(row["grain"] or "") == "VARIANT" and
                catalog_pt not in {"MIXED", "UNKNOWN", ""}):
            report_pt = catalog_pt
        else:
            report_pt = source_powertrain(
                str(row["unit_id"] or ""),
                "MIXED" if is_mixed_parent else catalog_pt,
                str(row["raw_label"] or ""),
            )
        report_model = market_model_name(
            row["model"], "MIXED" if is_mixed_parent else catalog_pt, report_pt
        )
        grouped[(str(row["brand"] or "UNKNOWN"), report_model,
                 str(report_pt or "UNKNOWN"))] += float(row["units"] or 0)

    total = sum(grouped.values())
    out = [
        {
            "brand": key[0], "model": key[1], "powertrain": key[2],
            "units": units, "share": units / total if total else 0.0,
        }
        for key, units in grouped.items()
    ]
    out.sort(key=lambda r: (-r["units"], r["brand"], r["model"]))
    for i, row in enumerate(out, 1):
        row["rank"] = i
    return out[:limit] if limit else out


def chinese_ev_trim_ranking(
    conn: sqlite3.Connection,
    period: str,
    *,
    registration_type: Optional[str] = None,
    brand: Optional[str] = None,
    model: Optional[str] = None,
    powertrain: Optional[str] = None,
    scopes: Optional[Iterable[str]] = DEFAULT_SCOPES,
    limit: Optional[int] = None,
) -> list[dict[str, Any]]:
    """Rank Chinese plug-in trims without touching master model facts.

    A blank trim label is kept as DLT_UNSPLIT. If DLT publishes only GOOD CAT in
    a month, the system must not manufacture a 400/500/600 allocation. When DLT
    publishes those labels, they appear as separate rows automatically.
    """
    sql = """
        SELECT f.period, f.registration_type, f.units, f.raw_label,
               t.model_id, t.brand, t.model, t.trim_label, t.grade, t.drive,
               t.range_km, t.battery_kwh, t.powertrain_hint,
               d.powertrain AS catalog_powertrain, d.brand_origin,
               d.market_scope
        FROM fact_trim f
        JOIN dim_trim t
          ON t.trim_id=f.trim_id
         AND t.catalog_year=CAST(substr(f.period,1,4) AS INTEGER)
        LEFT JOIN dim_unit d
          ON d.unit_id=t.model_id AND d.grain='MODEL'
         AND d.catalog_year=t.catalog_year
        WHERE f.period=? AND d.brand_origin='CN'
    """
    params: list[Any] = [period]
    if registration_type and registration_type != "ALL":
        sql += " AND f.registration_type=?"
        params.append(registration_type)
    if brand and brand != "ALL":
        sql += " AND lower(t.brand)=?"
        params.append(brand.lower())
    if model and model != "ALL":
        sql += " AND lower(t.model)=?"
        params.append(model.lower())
    scope_clause, scope_params = _scope_sql(scopes)
    sql += scope_clause
    params.extend(scope_params)

    grouped: dict[tuple[Any, ...], float] = defaultdict(float)
    for row in conn.execute(sql, params):
        pt = (str(row["powertrain_hint"] or "").upper()
              or source_powertrain(str(row["model_id"] or ""),
                                   row["catalog_powertrain"],
                                   str(row["raw_label"] or "")))
        if pt not in PLUGIN_POWERTRAINS:
            continue
        if powertrain and powertrain != "ALL" and pt != powertrain.upper():
            continue
        trim_label = str(row["trim_label"] or "").strip() or "DLT_UNSPLIT"
        key = (
            str(row["brand"] or "UNKNOWN"), str(row["model"] or "UNKNOWN"),
            trim_label, pt, row["grade"], row["drive"], row["range_km"],
            row["battery_kwh"],
        )
        grouped[key] += float(row["units"] or 0)

    model_totals: dict[tuple[str, str, str], float] = defaultdict(float)
    for key, units in grouped.items():
        model_totals[(key[0], key[1], key[3])] += units

    out: list[dict[str, Any]] = []
    for key, units in grouped.items():
        model_total = model_totals[(key[0], key[1], key[3])]
        out.append({
            "brand": key[0], "model": key[1], "trim": key[2],
            "powertrain": key[3], "grade": key[4], "drive": key[5],
            "range_km": key[6], "battery_kwh": key[7], "units": units,
            "model_total": model_total,
            "share_of_model": units / model_total if model_total else 0.0,
        })
    out.sort(key=lambda r: (-r["units"], r["brand"], r["model"], r["trim"]))
    per_model_rank: dict[tuple[str, str, str], int] = defaultdict(int)
    for i, row in enumerate(out, 1):
        row["rank"] = i
        mkey = (row["brand"], row["model"], row["powertrain"])
        per_model_rank[mkey] += 1
        row["trim_rank_in_model"] = per_model_rank[mkey]
    return out[:limit] if limit else out


def export_ranking_csv(rows: Iterable[dict[str, Any]], path: Path | str) -> int:
    """Export either ranking result to a standalone derived CSV."""
    data = list(rows)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not data:
        path.write_text("", encoding="utf-8-sig")
        return 0
    fields = list(data[0])
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(data)
    return len(data)
