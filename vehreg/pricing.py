"""Market-price history for retail trims.

Pricing is deliberately separate from :class:`vehreg.entities.MarketTrim`.
A trim is product identity/specification; a price is time-varying market state.
Keeping the two apart lets price maintenance run independently without changing
vehicle IDs or registration analytics.

Price rows are stored under::

    vehreg/data/<year>/market/prices/*.json

and always reference a stable ``MarketTrim.id``.  The ledger never participates
in ``Catalog.iter_resolved()`` and therefore cannot redistribute DLT volume.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum
import json
from pathlib import Path
from typing import Iterable, Optional, TYPE_CHECKING

from .catalog import DATA_DIR, DEFAULT_YEAR

if TYPE_CHECKING:  # pragma: no cover - import only for static typing
    from .catalog import Catalog


class PricingError(ValueError):
    pass


class PriceType(str, Enum):
    """Meaning of a quoted price, not the authority of its source."""

    LIST_PRICE = "LIST_PRICE"
    INTRODUCTORY_PRICE = "INTRODUCTORY_PRICE"
    CAMPAIGN_PRICE = "CAMPAIGN_PRICE"
    FINANCE_PRICE = "FINANCE_PRICE"
    ESTIMATED_PRICE = "ESTIMATED_PRICE"
    ECO_STICKER_PRICE = "ECO_STICKER_PRICE"
    UNKNOWN = "UNKNOWN"

    @classmethod
    def parse(cls, raw: object) -> "PriceType":
        if isinstance(raw, cls):
            return raw
        value = str(raw or "UNKNOWN").strip().upper()
        try:
            return cls(value)
        except ValueError as exc:
            raise PricingError(f"unknown price_type {raw!r}") from exc


def price_dir(data_dir: Path | str, year: int) -> Path:
    return Path(data_dir) / str(year) / "market" / "prices"


def _iso_date(raw: object, field_name: str) -> Optional[str]:
    if raw in (None, ""):
        return None
    value = str(raw)
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise PricingError(f"{field_name} must be YYYY-MM-DD, got {value!r}") from exc
    return value


@dataclass(frozen=True, slots=True)
class PriceRecord:
    trim_id: str
    amount_thb: int
    price_type: PriceType
    effective_from: Optional[str] = None
    effective_to: Optional[str] = None
    observed_at: Optional[str] = None
    source: str = ""
    source_ref: str = ""
    notes: str = ""

    def validate(self) -> list[str]:
        problems: list[str] = []
        if not self.trim_id:
            problems.append("trim_id is required")
        if self.amount_thb <= 0:
            problems.append("amount_thb must be positive")
        if self.price_type is PriceType.LIST_PRICE and not self.effective_from:
            problems.append("LIST_PRICE requires effective_from")
        if self.effective_from and self.effective_to and \
                self.effective_from > self.effective_to:
            problems.append("effective_from is after effective_to")
        return problems

    def active_on(self, when: date) -> bool:
        if self.effective_from and date.fromisoformat(self.effective_from) > when:
            return False
        if self.effective_to and date.fromisoformat(self.effective_to) < when:
            return False
        return True


class PriceLedger:
    """Year-scoped market-state ledger keyed to stable ``MarketTrim`` IDs."""

    def __init__(self, year: int = DEFAULT_YEAR, *,
                 catalog: Optional["Catalog"] = None) -> None:
        self.year = year
        self.catalog = catalog
        self.records: list[PriceRecord] = []

    @classmethod
    def load(cls, data_dir: Path | str = DATA_DIR, *,
             year: int = DEFAULT_YEAR,
             catalog: Optional["Catalog"] = None) -> "PriceLedger":
        ledger = cls(year, catalog=catalog)
        folder = price_dir(data_dir, year)
        if not folder.is_dir():
            return ledger
        for path in sorted(folder.glob("*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                raise PricingError(f"{path}: invalid JSON: {exc}") from exc
            ledger.add_payload(payload, source=str(path))
        return ledger

    def add_payload(self, payload: dict, *, source: str = "<memory>") -> None:
        for raw in payload.get("prices", []):
            trim_id = str(raw.get("trim_id") or "").strip()
            if self.catalog is not None and trim_id not in self.catalog.trims:
                raise PricingError(f"{source}: unknown trim_id {trim_id!r}")
            try:
                amount = int(raw["amount_thb"])
            except (KeyError, TypeError, ValueError) as exc:
                raise PricingError(f"{source}: invalid amount_thb for {trim_id!r}") from exc
            record = PriceRecord(
                trim_id=trim_id,
                amount_thb=amount,
                price_type=PriceType.parse(raw.get("price_type")),
                effective_from=_iso_date(raw.get("effective_from"), "effective_from"),
                effective_to=_iso_date(raw.get("effective_to"), "effective_to"),
                observed_at=_iso_date(raw.get("observed_at"), "observed_at"),
                source=str(raw.get("source") or "").strip(),
                source_ref=str(raw.get("source_ref") or "").strip(),
                notes=str(raw.get("notes") or ""),
            )
            problems = record.validate()
            if problems:
                raise PricingError(
                    f"{source}: price for {trim_id or '<missing>'}: " + "; ".join(problems))
            self.records.append(record)

    def records_for(self, trim_id: str, *,
                    price_type: Optional[PriceType] = None) -> list[PriceRecord]:
        rows = [r for r in self.records if r.trim_id == trim_id]
        if price_type is not None:
            rows = [r for r in rows if r.price_type is price_type]
        return sorted(rows, key=self._sort_key)

    @staticmethod
    def _sort_key(record: PriceRecord) -> tuple[str, str, int]:
        return (
            record.effective_from or "0001-01-01",
            record.observed_at or "0001-01-01",
            record.amount_thb,
        )

    def latest(self, trim_id: str, *,
               price_type: Optional[PriceType] = None) -> Optional[PriceRecord]:
        rows = self.records_for(trim_id, price_type=price_type)
        return rows[-1] if rows else None

    def current_list_price(self, trim_id: str, *,
                           as_of: Optional[date] = None) -> Optional[PriceRecord]:
        """Return canonical current MSRP/list price, never a promo or ECO value."""
        when = as_of or date.today()
        rows = [
            r for r in self.records_for(trim_id, price_type=PriceType.LIST_PRICE)
            if r.active_on(when)
        ]
        return rows[-1] if rows else None

    def current_list_amount(self, trim_id: str, *,
                            as_of: Optional[date] = None) -> Optional[int]:
        row = self.current_list_price(trim_id, as_of=as_of)
        return row.amount_thb if row else None

    def validate(self) -> list[str]:
        problems: list[str] = []
        for record in self.records:
            problems.extend(
                f"price {record.trim_id}: {problem}" for problem in record.validate())
            if self.catalog is not None and record.trim_id not in self.catalog.trims:
                problems.append(f"price {record.trim_id}: trim does not exist in catalog")
        return problems

    def coverage(self, *, as_of: Optional[date] = None) -> dict[str, int]:
        trims_with_any = {r.trim_id for r in self.records}
        current_list = {
            r.trim_id for r in self.records
            if r.price_type is PriceType.LIST_PRICE
            and r.active_on(as_of or date.today())
        }
        return {
            "records": len(self.records),
            "trims_with_any_price_evidence": len(trims_with_any),
            "trims_with_current_list_price": len(current_list),
            "eco_sticker_price_records": sum(
                r.price_type is PriceType.ECO_STICKER_PRICE for r in self.records),
        }
