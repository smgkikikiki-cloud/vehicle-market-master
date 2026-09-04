"""Reading the real thing: DLT's open-data CKAN API.

Source: https://gdcatalog.dlt.go.th - dataset
"สถิติจำนวนรถจดทะเบียนครั้งแรก ตามกฎหมายว่าด้วยรถยนต์", which publishes one
resource per month (มกราคม 2565 onwards) plus a whole-year resource per year.
Each record is::

    {"ปี พ.ศ.": 2569, "เดือน": "มกราคม",
     "ประเภทรถ": "รถยนต์นั่งส่วนบุคคลไม่เกิน 7 คน",
     "ยี่ห้อ": "TOYOTA", "รุ่น": "YARIS ATIV", "จำนวน": 4213}

Three things about this feed shape the rest of the tool:

* ``ประเภทรถ`` is the DLT class in words, and the same nameplate appears under
  several of them - HILUX REVO shows up in รย.1 (double cab), รย.3 (single and
  smart cab) and รย.2. The class is therefore load-bearing, not decoration.
* ``รุ่น`` is usually the nameplate only, but some brands - BYD, Jaecoo, Aion,
  Deepal - push trim and battery size into it ("BYD DOLPHIN (435KM-STD)").
  So trim-level volume exists for part of the market and not for the rest.
* The dataset covers far more than cars. Tractors, motorcycles and trailers are
  in the same resource; anything outside รย.1/รย.2/รย.3 is counted and reported,
  never quietly dropped.

Only the standard library is used, and only public read endpoints are called.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Optional

from .normalize import THAI_MONTHS, period_key
from .taxonomy import RegistrationType

CKAN_BASE = "https://gdcatalog.dlt.go.th/api/3/action"

#: "สถิติจำนวนรถจดทะเบียนครั้งแรก ตามกฎหมายว่าด้วยรถยนต์"
PACKAGE_ID = "59a045dc-3ec4-4908-b035-ba789101b7f5"

PAGE_SIZE = 10_000
USER_AGENT = "vehreg/0.1 (Thai registration intelligence; stdlib urllib)"

#: The three classes this warehouse reports on. Everything else in the feed is
#: a different kind of vehicle and is skipped with a count.
REGISTRATION_BY_THAI_TYPE: dict[str, RegistrationType] = {
    "รถยนต์นั่งส่วนบุคคลไม่เกิน 7 คน": RegistrationType.RY1,
    "รถยนต์นั่งส่วนบุคคลเกิน 7 คน": RegistrationType.RY2,
    "รถยนต์บรรทุกส่วนบุคคล": RegistrationType.RY3,
}

CSV_HEADER = ["เดือน", "ประเภท", "ยี่ห้อ", "แบบรถ", "จำนวน", "ประเภทรถ (ต้นทาง)"]

_MONTH_IN_NAME = re.compile("|".join(sorted(
    (m for m in THAI_MONTHS if len(m) > 3), key=len, reverse=True)))


class DltError(RuntimeError):
    pass


@dataclass(frozen=True)
class Resource:
    id: str
    name: str
    period: Optional[str]       # 'YYYY-MM' for a monthly resource
    year: Optional[int]         # Gregorian year for a whole-year resource

    @property
    def is_monthly(self) -> bool:
        return self.period is not None


def _get(action: str, timeout: int = 120, **params: Any) -> dict:
    url = f"{CKAN_BASE}/{action}?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except OSError as exc:
        raise DltError(f"{action} failed: {exc}") from exc
    if not payload.get("success"):
        raise DltError(f"{action} returned success=false: "
                       f"{str(payload.get('error'))[:200]}")
    return payload["result"]


def _classify_resource(name: str) -> tuple[Optional[str], Optional[int]]:
    """Read the period out of a resource name.

    Monthly names end "<เดือน> <พ.ศ.>"; yearly ones end "ปี <พ.ศ.>".
    """
    years = re.findall(r"\b(25\d\d)\b", name)
    if not years:
        return None, None
    year = int(years[-1]) - 543
    if _MONTH_IN_NAME.search(name):
        try:
            return period_key(name), year
        except ValueError:
            return None, year
    return None, year


def list_resources(package_id: str = PACKAGE_ID) -> list[Resource]:
    """Every published resource, newest period first."""
    result = _get("package_show", id=package_id)
    out: list[Resource] = []
    for raw in result.get("resources", []):
        period, year = _classify_resource(raw.get("name", ""))
        out.append(Resource(raw["id"], raw.get("name", ""), period, year))
    return sorted(out, key=lambda r: (r.period or "", r.year or 0), reverse=True)


def monthly_index(package_id: str = PACKAGE_ID) -> dict[str, Resource]:
    return {r.period: r for r in list_resources(package_id) if r.is_monthly}


def fetch_records(resource_id: str, page_size: int = PAGE_SIZE
                  ) -> Iterator[dict]:
    """All rows of one resource, paged through datastore_search."""
    offset = 0
    while True:
        result = _get("datastore_search", resource_id=resource_id,
                      limit=page_size, offset=offset)
        records = result.get("records", [])
        if not records:
            return
        yield from records
        offset += len(records)
        if offset >= int(result.get("total", 0)):
            return


@dataclass
class FetchReport:
    period: str
    resource_id: str
    rows_in: int = 0
    rows_kept: int = 0
    units_kept: int = 0
    skipped_by_type: dict[str, int] = None      # type: ignore[assignment]
    path: Optional[Path] = None
    sha256: str = ""

    def render(self) -> str:
        lines = [
            f"period          : {self.period}",
            f"rows from DLT   : {self.rows_in}",
            f"rows kept       : {self.rows_kept} (รย.1 / รย.2 / รย.3)",
            f"units kept      : {self.units_kept:,}",
        ]
        if self.skipped_by_type:
            top = sorted(self.skipped_by_type.items(), key=lambda kv: -kv[1])[:5]
            lines.append("skipped classes : " + ", ".join(
                f"{k} {v:,}" for k, v in top))
        if self.path:
            lines.append(f"written         : {self.path}")
        return "\n".join(lines)


def _to_rows(records: Iterable[dict], period: str
             ) -> tuple[list[dict[str, Any]], dict[str, int], int]:
    rows: list[dict[str, Any]] = []
    skipped: dict[str, int] = {}
    units = 0
    for record in records:
        thai_type = str(record.get("ประเภทรถ", "")).strip()
        registration = REGISTRATION_BY_THAI_TYPE.get(thai_type)
        count = record.get("จำนวน")
        try:
            count = int(str(count).replace(",", ""))
        except (TypeError, ValueError):
            count = 0
        if registration is None:
            skipped[thai_type or "(ว่าง)"] = skipped.get(thai_type or "(ว่าง)",
                                                         0) + count
            continue
        rows.append({
            "เดือน": period,
            "ประเภท": registration.value,
            "ยี่ห้อ": str(record.get("ยี่ห้อ", "")).strip(),
            "แบบรถ": str(record.get("รุ่น", "")).strip(),
            "จำนวน": count,
            "ประเภทรถ (ต้นทาง)": thai_type,
        })
        units += count
    return rows, skipped, units


def fetch_month(period: str, out_dir: Path | str, *,
                resources: Optional[dict[str, Resource]] = None) -> FetchReport:
    """Download one month and write it as a CSV the ingest layer can read."""
    index = resources if resources is not None else monthly_index()
    resource = index.get(period)
    if resource is None:
        available = ", ".join(sorted(index)[-6:])
        raise DltError(f"DLT publishes no resource for {period}; "
                       f"most recent are {available}")

    records = list(fetch_records(resource.id))
    rows, skipped, units = _to_rows(records, period)

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"dlt_{period}.csv"
    with open(path, "w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_HEADER)
        writer.writeheader()
        writer.writerows(rows)

    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    meta = {
        "period": period,
        "resource_id": resource.id,
        "resource_name": resource.name,
        "package_id": PACKAGE_ID,
        "api": f"{CKAN_BASE}/datastore_search?resource_id={resource.id}",
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "rows_from_dlt": len(records),
        "rows_kept": len(rows),
        "units_kept": units,
        "skipped_units_by_class": skipped,
        "sha256": digest,
    }
    path.with_suffix(".meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    return FetchReport(period, resource.id, len(records), len(rows), units,
                       skipped, path, digest)


def months_of(year: int, resources: Optional[dict[str, Resource]] = None
              ) -> list[str]:
    index = resources if resources is not None else monthly_index()
    return sorted(p for p in index if p.startswith(f"{year:04d}-"))


def column_map():
    """The exact columns ``fetch_month`` writes - no header sniffing needed."""
    from .ingest import ColumnMap
    return ColumnMap(period="เดือน", brand="ยี่ห้อ", model="แบบรถ",
                     units="จำนวน", registration_type="ประเภท")
