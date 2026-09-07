"""Source-backed homologation/basic-spec evidence for retail trims.

This is Phase-1 product enrichment, not registration logic.  Records are keyed
by stable ``MarketTrim.id`` and can be joined to the catalog without ever
creating or allocating DLT facts.

ECO Sticker is useful evidence for fields such as chassis code, tyre size,
battery chemistry/supplier/voltage, declared weight, factory and rated EV
range.  It is *not* the canonical retail-price source; price keys are rejected
here on purpose and belong in :mod:`vehreg.pricing` instead.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Optional

from .catalog import Catalog, DATA_DIR, DEFAULT_YEAR
from .taxonomy import Powertrain


class HomologationError(ValueError):
    pass


def spec_dir(data_dir: Path | str, year: int) -> Path:
    return Path(data_dir) / str(year) / "product" / "specs" / "ecosticker"


@dataclass(frozen=True, slots=True)
class ECOStickerSpec:
    """Normalized subset of one public ECO Sticker vehicle record.

    Names are source-neutral where practical. ``declared_total_weight_kg`` is
    intentionally not called curb weight because the public API labels the
    value only as ``total_weight`` and we should not infer a more specific
    engineering definition than the source provides.
    """

    trim_id: str
    source_ref: str
    approval_at: str = ""
    powertrain: Powertrain = Powertrain.UNKNOWN
    seats: Optional[int] = None
    tire_size: str = ""
    chassis_code: str = ""
    battery_chemistry: str = ""
    battery_supplier: str = ""
    battery_voltage_v: Optional[float] = None
    declared_total_weight_kg: Optional[int] = None
    factory: str = ""
    rated_range_km: Optional[float] = None

    def validate(self) -> list[str]:
        problems: list[str] = []
        if not self.trim_id:
            problems.append("trim_id is required")
        if not self.source_ref:
            problems.append("source_ref is required")
        if self.powertrain is Powertrain.UNKNOWN:
            problems.append("powertrain must be exact")
        if self.seats is not None and self.seats <= 0:
            problems.append("seats must be positive")
        if self.battery_voltage_v is not None and self.battery_voltage_v <= 0:
            problems.append("battery_voltage_v must be positive")
        if self.declared_total_weight_kg is not None and self.declared_total_weight_kg <= 0:
            problems.append("declared_total_weight_kg must be positive")
        if self.rated_range_km is not None and self.rated_range_km <= 0:
            problems.append("rated_range_km must be positive")
        return problems


class ECOStickerSpecStore:
    """Year-scoped, source-backed spec observations keyed by MarketTrim id."""

    def __init__(self, year: int = DEFAULT_YEAR, *, catalog: Optional[Catalog] = None) -> None:
        self.year = year
        self.catalog = catalog
        self.records: dict[str, ECOStickerSpec] = {}

    @classmethod
    def load(cls, data_dir: Path | str = DATA_DIR, year: int = DEFAULT_YEAR,
             *, catalog: Optional[Catalog] = None) -> "ECOStickerSpecStore":
        store = cls(year, catalog=catalog)
        root = spec_dir(data_dir, year)
        if not root.is_dir():
            return store
        for path in sorted(root.glob("*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                raise HomologationError(f"{path}: invalid JSON: {exc}") from exc
            store.add_payload(payload, source=str(path))
        return store

    def add_payload(self, payload: dict, source: str = "<memory>") -> None:
        for raw in payload.get("specs", []):
            # Price is deliberately a different data product.  Fail closed so a
            # future ECO import cannot accidentally smuggle recommended price
            # back into canonical product specs.
            price_keys = sorted(k for k in raw if "price" in str(k).lower())
            if price_keys:
                raise HomologationError(
                    f"{source}: price fields are not allowed in ECO spec data: "
                    f"{', '.join(price_keys)}")

            trim_id = str(raw.get("trim_id") or "").strip()
            if trim_id in self.records:
                raise HomologationError(f"{source}: duplicate trim_id {trim_id!r}")

            row = ECOStickerSpec(
                trim_id=trim_id,
                source_ref=str(raw.get("source_ref") or "").strip(),
                approval_at=str(raw.get("approval_at") or "").strip(),
                powertrain=Powertrain.parse(raw.get("powertrain") or "UNKNOWN"),
                seats=raw.get("seats"),
                tire_size=str(raw.get("tire_size") or "").strip(),
                chassis_code=str(raw.get("chassis_code") or "").strip(),
                battery_chemistry=str(raw.get("battery_chemistry") or "").strip(),
                battery_supplier=str(raw.get("battery_supplier") or "").strip(),
                battery_voltage_v=raw.get("battery_voltage_v"),
                declared_total_weight_kg=raw.get("declared_total_weight_kg"),
                factory=str(raw.get("factory") or "").strip(),
                rated_range_km=raw.get("rated_range_km"),
            )
            problems = row.validate()
            if problems:
                raise HomologationError(
                    f"{source}: invalid ECO spec for {trim_id!r}: " + "; ".join(problems))
            if self.catalog is not None and trim_id not in self.catalog.trims:
                raise HomologationError(f"{source}: unknown trim_id {trim_id!r}")
            self.records[trim_id] = row

    def get(self, trim_id: str) -> Optional[ECOStickerSpec]:
        return self.records.get(trim_id)

    def validate_against_catalog(self, catalog: Optional[Catalog] = None) -> list[str]:
        """Check source facts against the already-canonical Phase-1 trim fields.

        This never rewrites the catalog. A mismatch is an evidence conflict for
        owner review, not permission to mutate registration or product identity.
        """
        catalog = catalog or self.catalog
        if catalog is None:
            raise HomologationError("catalog is required for cross-validation")

        problems: list[str] = []
        for trim_id, row in self.records.items():
            trim = catalog.trims.get(trim_id)
            if trim is None:
                problems.append(f"{trim_id}: trim does not exist in catalog")
                continue
            refs = trim.source_refs.get("ecosticker", ())
            if row.source_ref not in refs:
                problems.append(f"{trim_id}: ECO source_ref is not attached to MarketTrim")
            if row.powertrain is not trim.powertrain:
                problems.append(
                    f"{trim_id}: ECO powertrain {row.powertrain.value} != "
                    f"MarketTrim {trim.powertrain.value}")
            if row.seats is not None and trim.seats is not None and row.seats != trim.seats:
                problems.append(f"{trim_id}: ECO seats {row.seats} != MarketTrim {trim.seats}")
            if row.tire_size:
                normalized = row.tire_size.replace(" ", "").upper()
                front = trim.tire_front.replace(" ", "").upper()
                rear = trim.tire_rear.replace(" ", "").upper()
                if front and normalized != front:
                    problems.append(
                        f"{trim_id}: ECO tyre {row.tire_size} != front {trim.tire_front}")
                if rear and normalized != rear:
                    problems.append(
                        f"{trim_id}: ECO tyre {row.tire_size} != rear {trim.tire_rear}")
        return problems

    def coverage(self) -> dict[str, int]:
        rows = list(self.records.values())
        return {
            "records": len(rows),
            "with_chassis_code": sum(bool(x.chassis_code) for x in rows),
            "with_battery_chemistry": sum(bool(x.battery_chemistry) for x in rows),
            "with_battery_supplier": sum(bool(x.battery_supplier) for x in rows),
            "with_battery_voltage": sum(x.battery_voltage_v is not None for x in rows),
            "with_declared_total_weight": sum(
                x.declared_total_weight_kg is not None for x in rows),
            "with_tire_size": sum(bool(x.tire_size) for x in rows),
            "with_rated_range": sum(x.rated_range_km is not None for x in rows),
        }
