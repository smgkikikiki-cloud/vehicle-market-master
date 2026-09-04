"""Load reviewed month-effective vehicle state from a committed CSV.

The SQLite database is local and disposable, while the analyst-reviewed state
history belongs in Git.  This loader bridges the two: every app bootstrap can
re-apply the committed change-points idempotently through ``set_state`` so the
normal audit trail and validation rules stay in force.
"""

from __future__ import annotations

import csv
import sqlite3
from pathlib import Path
from typing import Any

from .monthly_state import set_state


SEED_COLUMNS = (
    "unit_id",
    "grain",
    "effective_month",
    "origin_country",
    "import_type",
    "source_url",
    "evidence",
)


def load_seed_csv(conn: sqlite3.Connection, path: Path | str) -> dict[str, Any]:
    """Apply a production-state seed CSV and return a compact load report.

    Blank state cells are deliberately omitted rather than interpreted as
    clears.  Re-running the same seed is safe: ``set_state`` returns False when
    the effective row already contains the same values, so no duplicate audit
    records are created.
    """
    path = Path(path)
    report: dict[str, Any] = {
        "path": str(path),
        "rows": 0,
        "applied": 0,
        "unchanged": 0,
        "errors": [],
    }
    if not path.exists():
        return report

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = [c for c in SEED_COLUMNS if c not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(
                "monthly state seed missing columns: " + ", ".join(missing)
            )

        for line_no, row in enumerate(reader, start=2):
            report["rows"] += 1
            unit_id = (row.get("unit_id") or "").strip()
            grain = (row.get("grain") or "MODEL").strip().upper()
            month = (row.get("effective_month") or "").strip()
            if not unit_id or not month:
                report["errors"].append(
                    f"line {line_no}: unit_id and effective_month are required"
                )
                continue

            kwargs: dict[str, Any] = {}
            origin = (row.get("origin_country") or "").strip()
            import_type = (row.get("import_type") or "").strip()
            if origin:
                kwargs["origin_country"] = origin
            if import_type:
                kwargs["import_type"] = import_type

            evidence = (row.get("evidence") or "").strip()
            source_url = (row.get("source_url") or "").strip()
            note_parts = [part for part in (evidence, source_url) if part]
            if note_parts:
                kwargs["note"] = " | ".join(note_parts)

            try:
                changed = set_state(
                    conn,
                    unit_id,
                    month,
                    grain=grain,
                    reason="committed production-country research seed",
                    **kwargs,
                )
            except Exception as exc:  # keep one bad research row from killing app startup
                report["errors"].append(f"line {line_no} {unit_id}: {exc}")
                continue

            report["applied" if changed else "unchanged"] += 1

    return report
