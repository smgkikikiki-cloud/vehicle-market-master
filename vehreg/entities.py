"""The four identity layers and the facet-resolution chain.

    Brand  ->  Model  ->  Generation  ->  Variant

Each layer declares only the facets that are genuinely constant at that layer.
A lower layer may override anything a higher layer said, except the two facets
that define what a model *is* (see below). ``resolve()`` walks the chain from
the most specific layer outwards, takes the first non-empty value, and records
which layer supplied it, so any number in a report can be traced back to the row
that asserted it.

Everything here is scoped to one **catalog year**. A car's price, import route
and positioning are whatever the catalog for that year says - there is no
back-dating and no interpolation across years. Last year's answers live in last
year's catalog and are not consulted.

Why the layers exist:

* ``Brand``       - brand_segment, oem_group, brand origin. One row per marque.
* ``Model``       - the nameplate *as sold in one body*. Body type and, for
                    pickups, cab type live here, and they are not overridable:
                    one nameplate sold in two bodies is two models, and each
                    pickup cab is its own model, because that is how the
                    registration class splits. ``nameplate`` puts the pieces
                    back together for reporting - every Hilux model, Revo and
                    Champ and every cab, rolls up to "Hilux". ``market_scope``
                    says whether the model belongs in the owner's numbers at
                    all (CORE) or is a halo/grey row kept only so DLT lines
                    still resolve.
* ``Generation``  - the "โฉม". Segment and seat count sit here so a mid-year
                    changeover can be recorded without editing the old row.
* ``Variant``     - the spec line. DLT does not publish by trim, so this is
                    deliberately *not* a full trim list: split a model only
                    where a trim differs on a facet that is reported on -
                    powertrain, drivetrain, import route, or a price that lands
                    in a different band. ``price_min_thb``/``price_max_thb``
                    record the real spread of the trims folded into one line.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Optional

from .taxonomy import (
    BodyType, BrandSegment, CabType, Drivetrain, ImportType, MarketPosition,
    MarketScope, Powertrain, RegistrationType, Segment,
    check_body_segment, check_origin, check_powertrain, check_registration,
    is_electrified, is_locally_assembled, is_plug_in, market_position_for_price,
    normalize_country, powertrain_group, registration_type_for,
)

#: Facet -> the layer that owns it. Used for validation messages and for the
#: "where should I put this?" hint in the CLI.
FACET_HOME_LAYER: dict[str, str] = {
    "brand_segment": "brand",
    "oem_group": "brand",
    "brand_origin": "brand",
    "nameplate": "model",
    "market_scope": "model",
    "body_type": "model",
    "cab_type": "model",
    "registration_type": "model",
    "segment": "generation",
    "seats": "generation",
    "powertrain": "variant",
    "drivetrain": "variant",
    "engine_cc": "variant",
    "battery_kwh": "variant",
    "price_thb": "variant",
    "import_type": "variant",
    "origin_country": "variant",
}

#: Most specific first. This is the whole override mechanism.
RESOLUTION_CHAIN: tuple[str, ...] = ("variant", "generation", "model", "brand")

#: Overriding these below the model layer would let one model row mean two
#: different cars, which is exactly what splitting models is meant to prevent.
LOCKED_AT_MODEL: frozenset[str] = frozenset({"body_type", "cab_type"})

_UNSET = (None, "", "UNKNOWN")


def _is_set(value: Any) -> bool:
    if value in _UNSET:
        return False
    if hasattr(value, "value") and value.value == "UNKNOWN":
        return False
    return True


@dataclass(frozen=True, slots=True)
class Brand:
    id: str                                   # stable slug, e.g. "toyota"
    name_en: str
    name_th: str
    brand_segment: BrandSegment = BrandSegment.UNKNOWN
    oem_group: str = "UNKNOWN"                # e.g. "Toyota Group", "Geely"
    brand_origin: str = "UNKNOWN"             # ISO-2 of the marque's home market
    #: True when DLT prints trim inside the รุ่น field for this brand, which is
    #: the case for the Chinese marques and Tesla and not for the Japanese ones.
    #: The master facts stay folded to the model either way; this flag is what
    #: routes the extra detail into the separate trim ledger.
    trim_detail: bool = False
    aliases: tuple[str, ...] = ()
    overrides: dict[str, Any] = field(default_factory=dict)

    def facets(self) -> dict[str, Any]:
        out = {
            "brand": self.name_en,
            "brand_segment": self.brand_segment,
            "oem_group": self.oem_group,
            "brand_origin": normalize_country(self.brand_origin),
        }
        out.update(self.overrides)
        return out


@dataclass(frozen=True, slots=True)
class Model:
    """One nameplate in one body. ``Mazda2 Sedan`` and ``Mazda2 Hatchback`` are
    two of these, and so are ``Hilux Revo Double Cab`` and ``... Smart Cab``."""

    id: str                                   # "toyota.yaris_ativ"
    brand_id: str
    name_en: str
    name_th: str = ""
    nameplate: str = ""                       # reporting roll-up, e.g. "Hilux"
    body_type: BodyType = BodyType.OTHER
    cab_type: CabType = CabType.NOT_APPLICABLE
    registration_type: RegistrationType = RegistrationType.RY1
    market_scope: MarketScope = MarketScope.CORE
    aliases: tuple[str, ...] = ()
    notes: str = ""
    overrides: dict[str, Any] = field(default_factory=dict)

    def facets(self) -> dict[str, Any]:
        out = {
            "model": self.name_en,
            "nameplate": self.nameplate or self.name_en,
            "body_type": self.body_type,
            "cab_type": self.cab_type,
            "registration_type": self.registration_type,
            "market_scope": self.market_scope,
        }
        out.update(self.overrides)
        return out

    def validate(self) -> list[str]:
        problems = check_registration(self.body_type, self.cab_type,
                                      self.registration_type)
        if self.body_type is BodyType.PICKUP and \
                self.cab_type is CabType.NOT_APPLICABLE:
            problems.append("a pickup model must name its cab_type; split the "
                            "nameplate into one model per cab")
        if self.body_type is not BodyType.PICKUP and \
                self.cab_type is not CabType.NOT_APPLICABLE:
            problems.append(f"cab_type is only valid for PICKUP, got "
                            f"{self.body_type.value}")
        return [f"model {self.id}: {p}" for p in problems]


@dataclass(frozen=True, slots=True)
class Generation:
    id: str                                   # "toyota.yaris_ativ.mxpa10"
    model_id: str
    code: str = ""                            # factory code, e.g. "MXPA10"
    segment: Segment = Segment.UNKNOWN
    seats: Optional[int] = None
    launched: Optional[str] = None            # ISO date, first Thai sale
    ended: Optional[str] = None
    overrides: dict[str, Any] = field(default_factory=dict)

    def facets(self) -> dict[str, Any]:
        out: dict[str, Any] = {"generation": self.code or self.id.rsplit(".", 1)[-1],
                               "segment": self.segment}
        if self.seats:
            out["seats"] = self.seats
        out.update(self.overrides)
        return out


@dataclass(frozen=True, slots=True)
class Variant:
    """One รุ่นย่อย, priced for the catalog year it belongs to."""

    id: str                                   # "toyota.yaris_ativ.mxpa10.smart"
    generation_id: str
    name: str                                 # trim as marketed, e.g. "1.2 Smart"
    powertrain: Powertrain = Powertrain.UNKNOWN
    drivetrain: Drivetrain = Drivetrain.UNKNOWN
    engine_cc: Optional[int] = None
    battery_kwh: Optional[float] = None
    price_thb: Optional[float] = None         # representative list price
    price_min_thb: Optional[float] = None     # spread of the folded trims
    price_max_thb: Optional[float] = None
    import_type: ImportType = ImportType.UNKNOWN
    origin_country: str = "UNKNOWN"
    price_note: str = ""
    aliases: tuple[str, ...] = ()
    overrides: dict[str, Any] = field(default_factory=dict)

    def facets(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "variant": self.name,
            "powertrain": self.powertrain,
            "drivetrain": self.drivetrain,
            "price_thb": self.price_thb,
            "market_position": market_position_for_price(self.price_thb),
            "import_type": self.import_type,
            "origin_country": normalize_country(self.origin_country),
        }
        if self.price_min_thb:
            out["price_min_thb"] = self.price_min_thb
        if self.price_max_thb:
            out["price_max_thb"] = self.price_max_thb
        if self.engine_cc:
            out["engine_cc"] = self.engine_cc
        if self.battery_kwh:
            out["battery_kwh"] = self.battery_kwh
        out.update(self.overrides)
        return out

    def validate(self) -> list[str]:
        problems = check_powertrain(self.powertrain, self.battery_kwh,
                                    self.engine_cc)
        problems += check_origin(self.import_type, self.origin_country)
        locked = LOCKED_AT_MODEL & set(self.overrides)
        if locked:
            problems.append(
                f"cannot override {', '.join(sorted(locked))} on a variant - "
                "a nameplate sold in two bodies is two models")
        low, high = self.price_min_thb, self.price_max_thb
        if low and high and low > high:
            problems.append(f"price_min_thb {low:,.0f} > price_max_thb {high:,.0f}")
        if low and high and market_position_for_price(low) is not \
                market_position_for_price(high):
            problems.append(
                f"folded trims span {market_position_for_price(low).value} to "
                f"{market_position_for_price(high).value}; split this line so "
                "each one sits in a single price band")
        for bound in (low, high):
            if bound and self.price_thb and not (
                    (low or 0) <= self.price_thb <= (high or self.price_thb)):
                problems.append("price_thb is outside price_min_thb..price_max_thb")
                break
        return [f"variant {self.id}: {p}" for p in problems]


@dataclass(frozen=True, slots=True)
class ResolvedVehicle:
    """One fully cross-classified row: every facet plus where it came from."""

    variant_id: str
    year: int
    facets: dict[str, Any]
    provenance: dict[str, str]

    def __getitem__(self, key: str) -> Any:
        return self.facets.get(key)

    def get(self, key: str, default: Any = None) -> Any:
        return self.facets.get(key, default)

    def as_row(self) -> dict[str, Any]:
        row = {}
        for key, value in self.facets.items():
            row[key] = value.value if hasattr(value, "value") else value
        row["variant_id"] = self.variant_id
        row["year"] = self.year
        return row


def resolve(brand: Brand, model: Model, generation: Generation, variant: Variant,
            year: int) -> ResolvedVehicle:
    """Collapse the four layers into one classified row for ``year``.

    The first layer in ``RESOLUTION_CHAIN`` that asserts a facet wins. Values
    that are ``None``/``""``/``UNKNOWN`` do not count as asserted, so a lower
    layer leaving a field blank falls through to the layer above instead of
    erasing it.
    """
    layers = {
        "variant": {k: v for k, v in variant.facets().items()
                    if k not in LOCKED_AT_MODEL},
        "generation": generation.facets(),
        "model": model.facets(),
        "brand": brand.facets(),
    }

    facets: dict[str, Any] = {}
    provenance: dict[str, str] = {}
    for layer_name in RESOLUTION_CHAIN:
        for key, value in layers[layer_name].items():
            if key in facets:
                continue
            if _is_set(value):
                facets[key] = value
                provenance[key] = layer_name

    # Derived facets. They are computed, never stored, so they can never
    # disagree with the layer that produced their input.
    pt = facets.get("powertrain", Powertrain.UNKNOWN)
    facets["powertrain_group"] = powertrain_group(pt)
    facets["is_electrified"] = is_electrified(pt)
    facets["is_plug_in"] = is_plug_in(pt)
    facets.setdefault("market_position", MarketPosition.UNKNOWN)
    facets.setdefault("segment", Segment.UNKNOWN)
    facets.setdefault("body_type", BodyType.OTHER)
    facets.setdefault("cab_type", CabType.NOT_APPLICABLE)
    facets.setdefault("import_type", ImportType.UNKNOWN)
    facets.setdefault("origin_country", "UNKNOWN")
    facets.setdefault("market_scope", MarketScope.UNKNOWN)
    facets["is_locally_assembled"] = is_locally_assembled(
        facets["import_type"], facets["origin_country"])
    for derived in ("powertrain_group", "is_electrified", "is_plug_in",
                    "is_locally_assembled"):
        provenance[derived] = "derived"

    return ResolvedVehicle(variant.id, year, facets, provenance)


def cross_check(resolved: ResolvedVehicle) -> list[str]:
    """Rules that only make sense once the layers are combined."""
    f = resolved.facets
    body = BodyType.parse(f["body_type"])
    cab = CabType.parse(f["cab_type"])
    problems = check_body_segment(body, cab, f["segment"])
    problems += check_powertrain(f.get("powertrain", Powertrain.UNKNOWN),
                                 f.get("battery_kwh"), f.get("engine_cc"))
    problems += check_origin(f["import_type"], f["origin_country"])
    problems += check_registration(body, cab, f["registration_type"])
    return [f"{resolved.variant_id}@{resolved.year}: {p}" for p in problems]


def to_jsonable(obj: Any) -> Any:
    """dataclass -> plain JSON types, with enums flattened to their key."""
    if hasattr(obj, "value") and not isinstance(obj, (str, int, float)):
        return obj.value
    if isinstance(obj, dict):
        return {k: to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_jsonable(v) for v in obj]
    if hasattr(obj, "__dataclass_fields__"):
        return {k: to_jsonable(v) for k, v in asdict(obj).items()}
    return obj
