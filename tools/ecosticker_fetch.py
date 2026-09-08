#!/usr/bin/env python3
"""Harvest the public ECO Sticker car register into a reproducible raw snapshot.

The Phase 2 snapshot used to arrive as an opaque ``raw.jsonl.gz`` with no way to
refresh it.  This is the harvester that produces that file.

Two public endpoints are used, both read-only:

``GET  {API}/v2/landing-page/cars?page=N``
    The paged inventory list.  Twelve rows per page; the response carries
    ``info.total_pages`` and ``info.total_rows``.

``POST {API}/v2/landing-page/compare``  body ``{"id": [...]}``
    The detail record behind each list row: dimensions, ``wheel_size``,
    ``engine_name``, battery, factory, weight.  The service rejects fewer than
    two and more than four IDs per call, so details go out in batches of four.

Nothing here writes to the warehouse or to the catalog.  The output is a raw
snapshot file for :func:`vehreg.ecosticker_ingest.build_snapshot` to normalize.

Usage::

    python tools/ecosticker_fetch.py --out raw.jsonl.gz
    python tools/ecosticker_fetch.py --out raw.jsonl.gz --limit 40 --no-detail

Progress is cached per page/batch under ``--cache-dir`` so an interrupted run
resumes instead of re-requesting everything.
"""

from __future__ import annotations

import argparse
import gzip
import io
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Iterable, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vehreg.ecosticker_ingest import _atomic_write, _jsonl_bytes  # noqa: E402

API = "https://api-car.ecosticker.go.th/api"
LIST_PATH = "/v2/landing-page/cars"
COMPARE_PATH = "/v2/landing-page/compare"
DETAIL_PAGE = "https://car.ecosticker.go.th/landing-page/detail/"

# The compare endpoint answers "Data carID less than 2" / "greater than 4".
COMPARE_MIN = 2
COMPARE_MAX = 4

# Detail fields worth keeping. Everything else on the compare record is
# presentation (signed image URLs, formatted price strings) or duplicated by the
# list row, and would only add churn between snapshots.
DETAIL_FIELDS = (
    "cartype_name", "engine_name", "fuel_name", "gear_name", "gear_speed",
    "capacity_cylinder", "car_style", "car_width", "car_length", "car_height",
    "car_seats", "wheel_size", "front_wheel", "back_wheel", "total_weight",
    "battery_type", "battery_brand", "battery_capacity", "nominal_voltage",
    "motor", "driving_range", "energy_consumption", "type_charge",
    "on_board_charger", "emissions_CO2", "rate_energy", "factory", "year",
    "model_year", "eco_sticker_id", "approval_at_latest", "company_name_en",
    "car_tyre",
)


class FetchError(RuntimeError):
    pass


def _request(url: str, *, payload: Optional[dict] = None, timeout: float = 60.0,
             attempts: int = 4, pause: float = 2.0) -> dict:
    """One JSON call with backoff. Only 5xx and transport errors are retried."""
    body = None
    headers = {"Accept": "application/json",
               "User-Agent": "vehicle-market-master/ecosticker-harvester"}
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    last: Exception | None = None
    for attempt in range(attempts):
        request = urllib.request.Request(url, data=body, headers=headers,
                                         method="POST" if body else "GET")
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:200]
            if exc.code < 500:
                raise FetchError(f"{url}: HTTP {exc.code}: {detail}") from exc
            last = FetchError(f"{url}: HTTP {exc.code}: {detail}")
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            last = FetchError(f"{url}: {exc}")
        if attempt + 1 < attempts:
            time.sleep(pause * (2 ** attempt))
    raise last or FetchError(f"{url}: exhausted retries")


def _cached(cache_dir: Optional[Path], key: str, produce) -> dict:
    if cache_dir is None:
        return produce()
    path = cache_dir / f"{key}.json"
    if path.is_file():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            path.unlink()  # A half-written cache entry must not poison the run.
    payload = produce()
    cache_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return payload


def fetch_list(*, cache_dir: Optional[Path] = None, delay: float = 0.4,
               limit: Optional[int] = None, log=lambda *_: None) -> list[dict]:
    """Return one row per ECO sticker record, in list-page order."""
    rows: list[dict] = []
    page, total_pages = 1, 1
    while page <= total_pages:
        payload = _cached(cache_dir, f"list-{page:04d}",
                          lambda: _request(f"{API}{LIST_PATH}?page={page}"))
        data = payload.get("data") or {}
        info = data.get("info") or {}
        total_pages = int(info.get("total_pages") or total_pages)
        for entry in data.get("car_list") or []:
            source_id = str(entry.get("id") or "").strip()
            if not source_id:
                continue
            rows.append({
                "source_id": source_id,
                "brand_raw": str(entry.get("brand") or "").strip(),
                "model_raw": str(entry.get("model") or "").strip(),
                "importer_raw": str(entry.get("company_name") or "").strip(),
                "price_thb": entry.get("recomend_retail_price"),
                "list_page": page,
                "source_url": DETAIL_PAGE + source_id,
            })
        log(f"list page {page}/{total_pages} -> {len(rows)} rows")
        if limit is not None and len(rows) >= limit:
            return rows[:limit]
        page += 1
        if page <= total_pages:
            time.sleep(delay)
    return rows


def _batches(ids: list[str]) -> Iterable[list[str]]:
    for start in range(0, len(ids), COMPARE_MAX):
        chunk = ids[start:start + COMPARE_MAX]
        if len(chunk) < COMPARE_MIN:
            # The service refuses a single ID; pad from the previous batch and
            # discard the duplicate answer at merge time.
            chunk = ids[max(0, len(ids) - COMPARE_MIN):]
        yield chunk


def fetch_details(ids: list[str], *, cache_dir: Optional[Path] = None,
                  delay: float = 0.4, log=lambda *_: None) -> dict[str, dict]:
    """Return ``source_id -> trimmed detail record`` for the IDs that answer."""
    details: dict[str, dict] = {}
    batches = list(_batches(ids))
    for index, chunk in enumerate(batches, start=1):
        key = "detail-" + "-".join(sorted(chunk))[:120]
        payload = _cached(cache_dir, key, lambda: _request(
            f"{API}{COMPARE_PATH}", payload={"id": chunk}))
        for record in payload.get("data") or []:
            source_id = str(record.get("id") or "").strip()
            if not source_id:
                continue
            details[source_id] = {field: record.get(field)
                                  for field in DETAIL_FIELDS
                                  if record.get(field) not in (None, "", [], {})}
        if index % 25 == 0 or index == len(batches):
            log(f"detail batch {index}/{len(batches)} -> {len(details)} records")
        if index < len(batches):
            time.sleep(delay)
    return details


def write_raw(rows: list[dict], path: Path) -> None:
    """Write the snapshot deterministically: same rows in, same bytes out."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = _jsonl_bytes(rows)
    buffer = io.BytesIO()
    with gzip.GzipFile(fileobj=buffer, mode="wb", mtime=0) as handle:
        handle.write(payload)
    _atomic_write(path, buffer.getvalue())


def harvest(*, out: Path, cache_dir: Optional[Path], delay: float,
            limit: Optional[int], want_detail: bool,
            log=lambda *_: None) -> dict[str, Any]:
    rows = fetch_list(cache_dir=cache_dir, delay=delay, limit=limit, log=log)
    if want_detail:
        details = fetch_details([row["source_id"] for row in rows],
                                cache_dir=cache_dir, delay=delay, log=log)
        for row in rows:
            detail = details.get(row["source_id"])
            row["detail"] = detail or {}
            row["detail_status"] = "available" if detail else "unavailable"
    write_raw(rows, out)
    with_detail = sum(row.get("detail_status") == "available" for row in rows)
    return {"records": len(rows), "records_with_detail": with_detail,
            "output": str(out)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", required=True, type=Path,
                        help="destination raw.jsonl.gz")
    parser.add_argument("--cache-dir", type=Path, default=None,
                        help="resume directory for partial runs")
    parser.add_argument("--delay", type=float, default=0.4,
                        help="seconds between requests (default 0.4)")
    parser.add_argument("--limit", type=int, default=None,
                        help="stop after N list rows (for smoke tests)")
    parser.add_argument("--no-detail", action="store_true",
                        help="list pages only; skip the compare endpoint")
    args = parser.parse_args(argv)
    summary = harvest(out=args.out, cache_dir=args.cache_dir, delay=args.delay,
                      limit=args.limit, want_detail=not args.no_detail,
                      log=lambda message: print(message, file=sys.stderr))
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
