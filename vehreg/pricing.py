"""Market-price history for retail trims.

Pricing is deliberately separate from :class:`vehreg.entities.MarketTrim`.
A trim is product identity/specification; a price is time-varying market state.
Keeping the two apart lets price maintenance run independently without changing
vehicle IDs or registration analytics.

Price rows are stored under::

    vehreg/data/<year>/market/prices/*.json

and always reference a stable ``MarketTrim.id``.  The ledger never participates
in ``Catalog.iter_resolved()`` and therefore cannot redistribute DLT volume.

A **campaign** is a dated promotion a brand runs across one or more trims.  Its
alternatives are :class:`CampaignOption` rows: "cash discount" *or* "0% finance"
are two options, and a buyer takes one.  Conditions inside one option are AND;
options are OR.  Nothing here merges the best of two options into one offer.

Campaign prices never overwrite MSRP.  They are separate records on the same
trim, and when a campaign ends nothing is deleted -- :meth:`PriceLedger.
current_campaign_offers` simply stops selecting it.

A price type says what *kind of money* a number is, never when it applies.
When it applies is ``effective_from``/``effective_to``, and an announced future
price is an ordinary ``LIST_PRICE`` whose window has not opened yet.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
import json
import re
from pathlib import Path
from typing import Iterable, Optional, TYPE_CHECKING

from .catalog import DATA_DIR, DEFAULT_YEAR

if TYPE_CHECKING:  # pragma: no cover - import only for static typing
    from .catalog import Catalog


class PricingError(ValueError):
    pass


class OfferStatus(str, Enum):
    """Whether an option can still be taken, which the calendar cannot say.

    A quota campaign ends when the cars run out, not when the month does. Suzuki
    published the Fronx GL cash price to 30 September and closed it on 25 August
    when the 200 cars were gone; a calendar-only model would have gone on
    quoting a price nobody could buy.
    """

    ACTIVE = "ACTIVE"
    SOLD_OUT = "SOLD_OUT"
    WITHDRAWN = "WITHDRAWN"
    SUPERSEDED = "SUPERSEDED"

    @classmethod
    def parse(cls, raw: object) -> "OfferStatus":
        value = str(raw or "ACTIVE").strip().upper()
        try:
            return cls(value)
        except ValueError as exc:
            raise PricingError(f"unknown offer status {raw!r}") from exc

    @property
    def open(self) -> bool:
        return self is OfferStatus.ACTIVE


class PriceType(str, Enum):
    """Meaning of a quoted price, not the authority of its source."""

    LIST_PRICE = "LIST_PRICE"
    INTRODUCTORY_PRICE = "INTRODUCTORY_PRICE"
    CAMPAIGN_PRICE = "CAMPAIGN_PRICE"
    FINANCE_PRICE = "FINANCE_PRICE"
    ESTIMATED_PRICE = "ESTIMATED_PRICE"
    # One dealer's number, not the manufacturer's.
    DEALER_PRICE = "DEALER_PRICE"
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


def campaign_dir(data_dir: Path | str, year: int) -> Path:
    return Path(data_dir) / str(year) / "market" / "campaigns"


def _iso_date(raw: object, field_name: str) -> Optional[str]:
    if raw in (None, ""):
        return None
    value = str(raw)
    try:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise ValueError(value)
        date.fromisoformat(value)
    except ValueError as exc:
        raise PricingError(f"{field_name} must be YYYY-MM-DD, got {value!r}") from exc
    return value


@dataclass(frozen=True, slots=True)
class Conditions:
    """What a buyer must do to get a campaign price.

    Only the fields the resolver branches on are modelled.  Eligible colours,
    customer groups, sales channel, trade-in, interest rate and down payment are
    displayed rather than computed, so they stay verbatim in ``text`` in the
    words the source used.  A field earns a column by being read by code.
    """

    booking_from: Optional[str] = None
    booking_to: Optional[str] = None
    delivery_by: Optional[str] = None
    #: Announced cap. Never counted down: nobody publishes live remaining quota,
    #: so the cap and its date are shown and no expiry is inferred from it.
    quota_units: Optional[int] = None
    finance_required: bool = False
    text: str = ""

    def validate(self) -> list[str]:
        problems: list[str] = []
        for field_name in ("booking_from", "booking_to", "delivery_by"):
            try:
                _iso_date(getattr(self, field_name), field_name)
            except PricingError as exc:
                problems.append(str(exc))
        if self.booking_from and self.booking_to and \
                self.booking_from > self.booking_to:
            problems.append("booking_from is after booking_to")
        if self.quota_units is not None and (
                type(self.quota_units) is not int or self.quota_units <= 0):
            problems.append("quota_units must be a positive integer")
        if not isinstance(self.finance_required, bool):
            problems.append("finance_required must be a boolean")
        return problems

    def open_on(self, when: date) -> bool:
        day = when.isoformat()
        if self.booking_from and day < self.booking_from:
            return False
        if self.booking_to and day > self.booking_to:
            return False
        return True


@dataclass(frozen=True, slots=True)
class CampaignOption:
    """One alternative inside a campaign. Options are OR, never combined.

    An option carries its own window and status because alternatives inside one
    campaign do not end together: a capped cash price sells out while the
    finance option beside it runs to the published date.
    """

    id: str
    label: str = ""
    conditions: Conditions = field(default_factory=Conditions)
    starts: Optional[str] = None
    #: The date the brand published. ``closed_at`` is the date it really ended.
    ends: Optional[str] = None
    status: OfferStatus = OfferStatus.ACTIVE
    closed_at: Optional[str] = None
    notes: str = ""

    def validate(self) -> list[str]:
        problems = ["option id is required"] if not self.id else []
        for field_name in ("starts", "ends", "closed_at"):
            try:
                _iso_date(getattr(self, field_name), field_name)
            except PricingError as exc:
                problems.append(f"option {self.id}: {exc}")
        if self.starts and self.ends and self.starts > self.ends:
            problems.append(f"option {self.id}: starts is after ends")
        if not self.status.open and not self.closed_at:
            problems.append(
                f"option {self.id}: {self.status.value} must say closed_at")
        if self.closed_at and self.status.open:
            problems.append(
                f"option {self.id}: closed_at needs a closed status")
        return problems + [f"option {self.id}: {p}"
                           for p in self.conditions.validate()]

    def open_on(self, when: date) -> bool:
        """Live today. A sold-out option is shut on the day it sold out.

        Not on the day its calendar ran out -- that is the whole point of
        recording ``closed_at`` separately from ``ends``.
        """
        day = when.isoformat()
        if self.closed_at and day > self.closed_at:
            return False
        if not self.status.open and not self.closed_at:
            return False
        if self.starts and day < self.starts:
            return False
        if self.ends and day > self.ends:
            return False
        return self.conditions.open_on(when)

    def status_on(self, when: date) -> OfferStatus:
        """What this option *was* on ``when`` -- never what it is now.

        ``status`` is today's record of how the option ended.  Reading it into
        a quote dated while the offer was still running backdates the ending:
        on 20 August the Fronx cash price was ACTIVE, and it became SOLD_OUT on
        the 25th.  A quote for the 20th that says SOLD_OUT is telling the reader
        something that was not true on the day it claims to describe.

        Deliberately blind to ``starts``/``ends``/conditions.  Those say whether
        an offer was *bookable* on a given day, which is :meth:`open_on`'s
        question; this one answers only "had it closed yet".
        """
        day = when.isoformat()
        if self.closed_at:
            return self.status if day > self.closed_at else OfferStatus.ACTIVE
        # Closed with no date recorded: validation forbids it, so this is only
        # reachable on an unvalidated object. Say closed rather than guess a day.
        return self.status


@dataclass(frozen=True, slots=True)
class Campaign:
    """A dated promotion covering one or more trims of one brand."""

    id: str
    brand_id: str
    name: str = ""
    starts: Optional[str] = None
    ends: Optional[str] = None
    source: str = ""
    source_ref: str = ""
    options: tuple[CampaignOption, ...] = ()
    #: One cap shared by every option, when the brand caps the promotion rather
    #: than each alternative inside it. Suzuki's September offer is 499 cars for
    #: the whole campaign; writing 499 on each of its four options would read as
    #: 1,996. A cap that really is per-option belongs on the option instead, and
    #: an option may not restate a campaign-level cap as its own.
    quota_units: Optional[int] = None
    notes: str = ""

    def validate(self) -> list[str]:
        problems: list[str] = []
        if not self.id:
            problems.append("campaign id is required")
        if self.quota_units is not None and (
                type(self.quota_units) is not int or self.quota_units <= 0):
            problems.append(
                f"campaign {self.id}: quota_units must be a positive integer")
        if not self.brand_id:
            problems.append(f"campaign {self.id}: brand_id is required")
        for field_name in ("starts", "ends"):
            try:
                _iso_date(getattr(self, field_name), field_name)
            except PricingError as exc:
                problems.append(f"campaign {self.id}: {exc}")
        if self.starts and self.ends and self.starts > self.ends:
            problems.append(f"campaign {self.id}: starts is after ends")
        if not self.options:
            problems.append(f"campaign {self.id}: at least one option is required")
        seen: set[str] = set()
        for option in self.options:
            if option.id in seen:
                problems.append(f"campaign {self.id}: duplicate option {option.id}")
            seen.add(option.id)
            if self.quota_units is not None and \
                    option.conditions.quota_units is not None:
                problems.append(
                    f"campaign {self.id}: option {option.id} restates the "
                    f"campaign quota; a shared pool is counted once")
            problems.extend(f"campaign {self.id}: {p}" for p in option.validate())
        return problems

    def option(self, option_id: str) -> Optional[CampaignOption]:
        return next((o for o in self.options if o.id == option_id), None)

    def live_on(self, when: date) -> bool:
        day = when.isoformat()
        if self.starts and day < self.starts:
            return False
        if self.ends and day > self.ends:
            return False
        return True


def to_conditions_dict(conditions: Conditions) -> dict:
    """Only the parts a reader needs; empty fields are noise on a page."""
    payload = {
        "booking_from": conditions.booking_from,
        "booking_to": conditions.booking_to,
        "delivery_by": conditions.delivery_by,
        "quota_units": conditions.quota_units,
        "finance_required": conditions.finance_required,
        "text": conditions.text,
    }
    return {k: v for k, v in payload.items() if v not in (None, "", False)}


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise PricingError(f"{path}: invalid JSON: {exc}") from exc


def _quota(raw: object, source: str) -> Optional[int]:
    if raw is None:
        return None
    if isinstance(raw, bool) or not re.fullmatch(r"[0-9]+", str(raw)):
        raise PricingError(f"{source}: quota_units must be a positive integer")
    return int(raw)


def _parse_conditions(raw: object, source: str) -> Conditions:
    if raw in (None, {}):
        return Conditions()
    if not isinstance(raw, dict):
        raise PricingError(f"{source}: conditions must be an object")
    unknown = set(raw) - set(Conditions.__dataclass_fields__)
    if unknown:
        raise PricingError(f"{source}: unknown condition fields: {sorted(unknown)}")
    return Conditions(
        booking_from=_iso_date(raw.get("booking_from"), "booking_from"),
        booking_to=_iso_date(raw.get("booking_to"), "booking_to"),
        delivery_by=_iso_date(raw.get("delivery_by"), "delivery_by"),
        quota_units=_quota(raw.get("quota_units"), source),
        finance_required=bool(raw.get("finance_required", False)),
        text=str(raw.get("text") or "").strip(),
    )


def _parse_campaign(raw: object, source: str) -> Campaign:
    if not isinstance(raw, dict):
        raise PricingError(f"{source}: campaign must be an object")
    unknown = set(raw) - set(Campaign.__dataclass_fields__)
    if unknown:
        raise PricingError(f"{source}: unknown campaign fields: {sorted(unknown)}")
    options = raw.get("options") or []
    if not isinstance(options, list):
        raise PricingError(f"{source}: campaign options must be an array")
    parsed: list[CampaignOption] = []
    for option in options:
        if not isinstance(option, dict):
            raise PricingError(f"{source}: campaign option must be an object")
        extra = set(option) - set(CampaignOption.__dataclass_fields__)
        if extra:
            raise PricingError(f"{source}: unknown option fields: {sorted(extra)}")
        parsed.append(CampaignOption(
            id=str(option.get("id") or "").strip(),
            label=str(option.get("label") or "").strip(),
            conditions=_parse_conditions(option.get("conditions"), source),
            starts=_iso_date(option.get("starts"), "starts"),
            ends=_iso_date(option.get("ends"), "ends"),
            status=OfferStatus.parse(option.get("status")),
            closed_at=_iso_date(option.get("closed_at"), "closed_at"),
            notes=str(option.get("notes") or ""),
        ))
    return Campaign(
        id=str(raw.get("id") or "").strip(),
        brand_id=str(raw.get("brand_id") or "").strip(),
        name=str(raw.get("name") or "").strip(),
        starts=_iso_date(raw.get("starts"), "starts"),
        ends=_iso_date(raw.get("ends"), "ends"),
        source=str(raw.get("source") or "").strip(),
        source_ref=str(raw.get("source_ref") or "").strip(),
        options=tuple(parsed),
        quota_units=_quota(raw.get("quota_units"), source),
        notes=str(raw.get("notes") or ""),
    )


@dataclass(frozen=True, slots=True)
class PriceRecord:
    """One price a source stated for one trim, over one window.

    A campaign price carries ``campaign_id``/``option_id`` back to the promotion
    that produced it, and ``reference_price_thb`` is the "from" figure the source
    quoted beside it.  Those three fields are the whole of what a campaign adds:
    the number itself is an ordinary price row, so a campaign can never overwrite
    or hide the MSRP.
    """

    trim_id: str
    amount_thb: int
    price_type: PriceType
    effective_from: Optional[str] = None
    effective_to: Optional[str] = None
    observed_at: Optional[str] = None
    source: str = ""
    source_ref: str = ""
    notes: str = ""
    campaign_id: Optional[str] = None
    option_id: Optional[str] = None
    #: The price this one is discounted from, as the source stated it.
    reference_price_thb: Optional[int] = None
    #: A row that was wrong. It stops counting immediately but is never deleted:
    #: a published number has to stay auditable even once it is withdrawn.
    #: Contrast with ``effective_to``, which says a correct price ended.
    retracted_at: Optional[str] = None
    retraction_reason: str = ""
    #: Who made the last manual decision about this row.
    reviewed_by: str = ""

    @property
    def retracted(self) -> bool:
        return bool(self.retracted_at)

    @property
    def discount_thb(self) -> Optional[int]:
        """Derived, never stored: a stored copy is one more thing to disagree."""
        if self.reference_price_thb is None:
            return None
        return self.reference_price_thb - self.amount_thb

    def validate(self) -> list[str]:
        problems: list[str] = []
        if not self.trim_id:
            problems.append("trim_id is required")
        if type(self.amount_thb) is not int or self.amount_thb <= 0:
            problems.append("amount_thb must be a positive integer")
        if not isinstance(self.price_type, PriceType):
            problems.append("price_type must be a PriceType")
        if self.reference_price_thb is not None and (
                type(self.reference_price_thb) is not int
                or self.reference_price_thb <= 0):
            problems.append("reference_price_thb must be a positive integer")
        if self.price_type is PriceType.CAMPAIGN_PRICE and not self.campaign_id:
            problems.append("CAMPAIGN_PRICE requires a campaign_id")
        if self.option_id and not self.campaign_id:
            problems.append("option_id without campaign_id")
        if self.campaign_id and self.price_type not in (
                PriceType.CAMPAIGN_PRICE, PriceType.FINANCE_PRICE):
            problems.append(
                f"{self.price_type.value} must not belong to a campaign")
        for field_name in ("effective_from", "effective_to", "observed_at",
                           "retracted_at"):
            try:
                _iso_date(getattr(self, field_name), field_name)
            except PricingError as exc:
                problems.append(str(exc))
        if self.retracted_at and not self.retraction_reason:
            problems.append("a retracted price must say why")
        if self.price_type is PriceType.LIST_PRICE and not (
                self.effective_from or self.observed_at):
            problems.append("LIST_PRICE requires effective_from or observed_at")
        if self.effective_from and self.effective_to and \
                self.effective_from > self.effective_to:
            problems.append("effective_from is after effective_to")
        return problems

    def active_on(self, when: date) -> bool:
        start = self.effective_from or self.observed_at
        if start and date.fromisoformat(start) > when:
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
        self.campaigns: dict[str, Campaign] = {}

    @classmethod
    def load(cls, data_dir: Path | str = DATA_DIR, *,
             year: int = DEFAULT_YEAR,
             catalog: Optional["Catalog"] = None) -> "PriceLedger":
        ledger = cls(year, catalog=catalog)
        # Campaigns first: a price row may not name a campaign that is unknown.
        for path in sorted(campaign_dir(data_dir, year).glob("*.json")) \
                if campaign_dir(data_dir, year).is_dir() else []:
            ledger.add_campaign_payload(_read_json(path), source=str(path))
        folder = price_dir(data_dir, year)
        if not folder.is_dir():
            return ledger
        for path in sorted(folder.glob("*.json")):
            ledger.add_payload(_read_json(path), source=str(path))
        return ledger

    def add_campaign_payload(self, payload: dict, *,
                             source: str = "<memory>") -> None:
        if not isinstance(payload, dict) or not isinstance(
                payload.get("campaigns"), list):
            raise PricingError(f"{source}: campaigns must be an array")
        staged: list[Campaign] = []
        for raw in payload["campaigns"]:
            campaign = _parse_campaign(raw, source)
            if campaign.id in self.campaigns or any(
                    c.id == campaign.id for c in staged):
                raise PricingError(f"{source}: duplicate campaign {campaign.id}")
            problems = campaign.validate()
            if problems:
                raise PricingError(f"{source}: " + "; ".join(problems))
            staged.append(campaign)
        # A malformed later campaign must not leave earlier ones half-imported.
        self.campaigns.update({c.id: c for c in staged})

    def add_payload(self, payload: dict, *, source: str = "<memory>") -> None:
        if not isinstance(payload, dict) or not isinstance(payload.get("prices"), list):
            raise PricingError(f"{source}: prices must be an array")
        staged = []
        for raw in payload["prices"]:
            if not isinstance(raw, dict):
                raise PricingError(f"{source}: price row must be an object")
            unknown = set(raw) - set(PriceRecord.__dataclass_fields__)
            if unknown:
                raise PricingError(f"{source}: unknown price fields: {sorted(unknown)}")
            trim_id = str(raw.get("trim_id") or "").strip()
            if self.catalog is not None and trim_id not in self.catalog.trims:
                raise PricingError(f"{source}: unknown trim_id {trim_id!r}")
            try:
                value = raw["amount_thb"]
                if isinstance(value, bool) or not re.fullmatch(r"[0-9]+", str(value)):
                    raise ValueError(value)
                amount = int(value)
            except (KeyError, TypeError, ValueError) as exc:
                raise PricingError(f"{source}: invalid amount_thb for {trim_id!r}") from exc
            reference = raw.get("reference_price_thb")
            if reference is not None:
                if isinstance(reference, bool) or not re.fullmatch(
                        r"[0-9]+", str(reference)):
                    raise PricingError(
                        f"{source}: invalid reference_price_thb for {trim_id!r}")
                reference = int(reference)
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
                campaign_id=str(raw.get("campaign_id") or "").strip() or None,
                option_id=str(raw.get("option_id") or "").strip() or None,
                reference_price_thb=reference,
                retracted_at=_iso_date(raw.get("retracted_at"), "retracted_at"),
                retraction_reason=str(raw.get("retraction_reason") or "").strip(),
                reviewed_by=str(raw.get("reviewed_by") or "").strip(),
            )
            problems = record.validate()
            if problems:
                raise PricingError(
                    f"{source}: price for {trim_id or '<missing>'}: " + "; ".join(problems))
            # A malformed last row must not leave earlier rows half-imported.
            if record not in self.records and record not in staged:
                staged.append(record)
        self.records.extend(staged)

    def records_for(self, trim_id: str, *,
                    price_type: Optional[PriceType] = None,
                    include_retracted: bool = False) -> list[PriceRecord]:
        """Resolution order. Retracted rows are excluded unless asked for."""
        rows = [r for r in self.records if r.trim_id == trim_id
                and (include_retracted or not r.retracted)]
        if price_type is not None:
            rows = [r for r in rows if r.price_type is price_type]
        return sorted(rows, key=self._sort_key)

    @staticmethod
    def _sort_key(record: PriceRecord) -> tuple[str, str, int]:
        return (
            record.effective_from or record.observed_at or "0001-01-01",
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
            if (r.effective_from or r.observed_at or "9999-12-31") <= when.isoformat()
        ]
        if not rows:
            return None
        # A newer list supersedes an older open-ended list. Expiring the newer
        # record must not resurrect an obsolete MSRP.
        start = max(r.effective_from or r.observed_at for r in rows)
        latest = [r for r in rows if (r.effective_from or r.observed_at) == start
                  and r.active_on(when)]
        if len({r.amount_thb for r in latest}) > 1:
            raise PricingError(f"{trim_id}: conflicting LIST_PRICE at {start}; review required")
        return latest[-1] if latest else None

    def current_list_amount(self, trim_id: str, *,
                            as_of: Optional[date] = None) -> Optional[int]:
        row = self.current_list_price(trim_id, as_of=as_of)
        return row.amount_thb if row else None

    def current_campaign_offers(self, trim_id: str, *,
                                as_of: Optional[date] = None) -> list[PriceRecord]:
        """Every campaign price live today, one row per option.

        Options are alternatives, so all of them are returned and none is
        declared best: a cash discount and a finance deal are not comparable,
        and choosing between them is the buyer's decision.
        """
        when = as_of or date.today()
        live: list[PriceRecord] = []
        for record in self.records_for(trim_id,
                                       price_type=PriceType.CAMPAIGN_PRICE):
            if not record.active_on(when):
                continue
            campaign = self.campaigns.get(record.campaign_id or "")
            if campaign is not None:
                if not campaign.live_on(when):
                    continue
                option = campaign.option(record.option_id or "")
                if option is not None and not option.open_on(when):
                    continue
            live.append(record)
        return live

    def campaign_quote(self, trim_id: str, *,
                       as_of: Optional[date] = None) -> dict:
        """What a page needs to show: the list price and every live option.

        Every option carries both ``status_as_of`` -- true on ``as_of`` -- and
        ``current_status``/``closed_at``, which are what is known today.  A
        quote dated inside a campaign that has since sold out reads ACTIVE for
        the day it describes and SOLD_OUT for now, and neither field is allowed
        to answer for the other.
        """
        when = as_of or date.today()
        listed = self.current_list_price(trim_id, as_of=when)
        offers = []
        for record in self.current_campaign_offers(trim_id, as_of=when):
            campaign = self.campaigns.get(record.campaign_id or "")
            option = campaign.option(record.option_id or "") if campaign else None
            offers.append({
                "amount_thb": record.amount_thb,
                "reference_price_thb": record.reference_price_thb,
                "discount_thb": record.discount_thb,
                "campaign_id": record.campaign_id,
                "campaign_name": campaign.name if campaign else "",
                "option_id": record.option_id,
                "option_label": option.label if option else "",
                # Two different questions, and merging them backdates the
                # ending: what the offer was on the quoted day, and what the
                # record says about it today.
                "status_as_of": option.status_on(when).value if option else None,
                "current_status": option.status.value if option else None,
                "closed_at": option.closed_at if option else None,
                "conditions": to_conditions_dict(option.conditions) if option else {},
                # The cap, and whether it is this option's own or shared with
                # every other option in the campaign.
                "quota_units": (option.conditions.quota_units if option else None)
                               or (campaign.quota_units if campaign else None),
                "quota_scope": ("OPTION" if option and option.conditions.quota_units
                                else "CAMPAIGN" if campaign and campaign.quota_units
                                else None),
                "valid_to": record.effective_to,
                "source": record.source,
                "source_ref": record.source_ref,
            })
        return {
            "trim_id": trim_id,
            "as_of": when.isoformat(),
            "list_price_thb": listed.amount_thb if listed else None,
            # Alternatives, never merged and never ranked.
            "campaign_options": offers,
        }

    def validate(self) -> list[str]:
        problems: list[str] = []
        for campaign in self.campaigns.values():
            problems.extend(campaign.validate())
        for record in self.records:
            problems.extend(
                f"price {record.trim_id}: {problem}" for problem in record.validate())
            if self.catalog is not None and record.trim_id not in self.catalog.trims:
                problems.append(f"price {record.trim_id}: trim does not exist in catalog")
            if record.campaign_id:
                campaign = self.campaigns.get(record.campaign_id)
                if campaign is None:
                    problems.append(
                        f"price {record.trim_id}: unknown campaign "
                        f"{record.campaign_id}")
                elif record.option_id and campaign.option(record.option_id) is None:
                    problems.append(
                        f"price {record.trim_id}: campaign {record.campaign_id} "
                        f"has no option {record.option_id}")
        for trim_id in {r.trim_id for r in self.records}:
            for start in {r.effective_from or r.observed_at for r in self.records_for(
                    trim_id, price_type=PriceType.LIST_PRICE)} - {None}:
                try:
                    self.current_list_price(trim_id, as_of=date.fromisoformat(start))
                except (PricingError, ValueError) as exc:
                    problems.append(str(exc))
        return problems

    def coverage(self, *, as_of: Optional[date] = None) -> dict[str, int]:
        trims_with_any = {r.trim_id for r in self.records}
        current_list = {trim_id for trim_id in trims_with_any
                        if self.current_list_price(trim_id, as_of=as_of) is not None}
        return {
            "records": len(self.records),
            "trims_with_any_price_evidence": len(trims_with_any),
            "trims_with_current_list_price": len(current_list),
            "eco_sticker_price_records": sum(
                r.price_type is PriceType.ECO_STICKER_PRICE for r in self.records),
            "campaigns": len(self.campaigns),
            "campaign_price_records": sum(
                r.price_type is PriceType.CAMPAIGN_PRICE for r in self.records),
            "trims_with_live_campaign": len({
                trim_id for trim_id in trims_with_any
                if self.current_campaign_offers(trim_id, as_of=as_of)}),
        }
