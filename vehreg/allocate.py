"""Splitting model-grain volume across trims.

DLT usually publishes to the นameplate, not the รุ่นย่อย. Those rows still carry
a segment, a body type and a brand, but they cannot answer "how many Fortuner
2.8 GR Sport" on their own. Where the same source *does* break some months out
by trim, that observed mix is the best available estimate of the rest.

Weights are derived, stored and applied explicitly, and every unit produced this
way is counted separately in the cube, so an estimate is never presented as a
reported figure.
"""

from __future__ import annotations

import sqlite3
from typing import Iterable, Optional

FALLBACKS = ("period", "year", "all")


def observed_mix(conn: sqlite3.Connection) -> dict[tuple[str, str], dict[str, float]]:
    """Variant-grain units per (model_id, period)."""
    mix: dict[tuple[str, str], dict[str, float]] = {}
    # Read the fact table directly: joining dim_unit here would multiply a
    # variant's units by however many type-2 rows it has.
    for row in conn.execute(
        "SELECT period, unit_id AS variant_id, SUM(units) AS units "
        "FROM fact_registration WHERE grain = 'VARIANT' "
        "GROUP BY period, unit_id"
    ):
        variant_id = row["variant_id"]
        # variant ids are '<brand>.<model>.<generation>.<trim>'
        model_id = ".".join(variant_id.split(".")[:2])
        mix.setdefault((model_id, row["period"]), {})[variant_id] = row["units"]
    return mix


def _normalise(counts: dict[str, float]) -> dict[str, float]:
    total = sum(counts.values())
    return {k: v / total for k, v in counts.items()} if total else {}


def derive_weights(conn: sqlite3.Connection, *,
                   fallback: str = "year") -> tuple[int, int]:
    """Fill ``allocation_weight`` from the trim mix this dataset already shows.

    ``fallback`` decides what to use for a month with no trim breakdown:
    ``period`` (that month only - leaves gaps), ``year`` (that calendar year),
    or ``all`` (the whole loaded history). Months with no evidence at any level
    get no weights, and their facts stay at model grain.
    """
    if fallback not in FALLBACKS:
        raise ValueError(f"fallback must be one of {FALLBACKS}")

    mix = observed_mix(conn)
    by_year: dict[tuple[str, str], dict[str, float]] = {}
    by_model: dict[str, dict[str, float]] = {}
    for (model_id, period), counts in mix.items():
        year_bucket = by_year.setdefault((model_id, period[:4]), {})
        all_bucket = by_model.setdefault(model_id, {})
        for variant_id, units in counts.items():
            year_bucket[variant_id] = year_bucket.get(variant_id, 0.0) + units
            all_bucket[variant_id] = all_bucket.get(variant_id, 0.0) + units

    targets = conn.execute(
        "SELECT DISTINCT unit_id AS model_id, period FROM fact_registration "
        "WHERE grain = 'MODEL'").fetchall()

    rows: list[tuple[str, str, str, float]] = []
    covered = 0
    for target in targets:
        model_id, period = target["model_id"], target["period"]
        counts = mix.get((model_id, period))
        if not counts and fallback in {"year", "all"}:
            counts = by_year.get((model_id, period[:4]))
        if not counts and fallback == "all":
            counts = by_model.get(model_id)
        if not counts:
            continue
        covered += 1
        for variant_id, weight in _normalise(counts).items():
            rows.append((model_id, period, variant_id, weight))

    with conn:
        conn.execute("DELETE FROM allocation_weight")
        conn.executemany(
            "INSERT INTO allocation_weight (model_id, period, unit_id, weight) "
            "VALUES (?,?,?,?)", rows)
    return covered, len(targets)


def load_weights(conn: sqlite3.Connection, rows: Iterable[dict]) -> int:
    """Load owner-supplied weights (model_id, period, unit_id, weight)."""
    payload = [(r["model_id"], r["period"], r["unit_id"], float(r["weight"]))
               for r in rows]
    with conn:
        conn.executemany(
            "INSERT INTO allocation_weight (model_id, period, unit_id, weight) "
            "VALUES (?,?,?,?) ON CONFLICT (model_id, period, unit_id) "
            "DO UPDATE SET weight = excluded.weight", payload)
    return len(payload)


def weight_health(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Model-periods whose weights do not sum to 1 - a loading mistake."""
    return conn.execute(
        "SELECT model_id, period, SUM(weight) AS total FROM allocation_weight "
        "GROUP BY model_id, period HAVING ABS(SUM(weight) - 1.0) > 1e-6"
    ).fetchall()
