"""Facet vocabulary for Thai vehicle-registration intelligence.

Every dimension the owner listed is an independent *facet*. A facet never
encodes another facet: ``segment`` says nothing about ``body_type``, and
``market_position`` is derived from a dated price, not from the trim name.
Cross-tabulation is therefore always legal, and the cube can slice on any
combination without a special case.

Facets that change over the life of a variant (price, import route, assembly
country) are not stored here; they live on dated ``VariantPeriod`` records in
``entities.py``. This module only defines the closed vocabularies, their
roll-ups, and the consistency rules that bind two facets together.
"""

from __future__ import annotations

from enum import Enum
from typing import Iterable, Optional


class Facet(str, Enum):
    """Base class: value is the stable storage key, ``.th`` the Thai label."""

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value

    @property
    def th(self) -> str:
        return THAI_LABELS.get(self.__class__.__name__, {}).get(self.value, self.value)

    @classmethod
    def parse(cls, raw: object) -> "Facet":
        if isinstance(raw, cls):
            return raw
        key = str(raw).strip().upper().replace("-", "_").replace(" ", "_")
        try:
            return cls[key]
        except KeyError:
            pass
        for member in cls:
            if member.value.upper() == key:
                return member
        aliases = FACET_ALIASES.get(cls.__name__, {})
        if key in aliases:
            return cls[aliases[key]]
        raise ValueError(f"{cls.__name__}: unknown value {raw!r}")


# --------------------------------------------------------------------------
# 1. Size segment (owner's scheme: A B C D E F, where F is pickup)
# --------------------------------------------------------------------------
class Segment(Facet):
    A = "A"          # city car / kei-adjacent
    B = "B"          # sub-compact
    C = "C"          # compact
    D = "D"          # mid-size
    E = "E"          # full-size / executive
    F = "F"          # pickup (owner's definition; see docs/VEHREG_TAXONOMY.md)
    UNKNOWN = "UNKNOWN"


# --------------------------------------------------------------------------
# 2. Body type + pickup cab sub-type
# --------------------------------------------------------------------------
class BodyType(Facet):
    HATCHBACK = "HATCHBACK"
    SEDAN = "SEDAN"
    CROSSOVER = "CROSSOVER"          # monocoque, car-derived
    SUV = "SUV"                      # monocoque, SUV-proportioned
    PPV = "PPV"                      # body-on-frame SUV built off a pickup
    COUPE = "COUPE"
    MPV = "MPV"
    PICKUP = "PICKUP"
    WAGON = "WAGON"      # estate / shooting brake
    VAN = "VAN"          # fleet passenger van: Commuter, Hiace, Vito, Sprinter
    TRUCK = "TRUCK"      # light/medium truck registered รย.3 alongside pickups
    OTHER = "OTHER"


class CabType(Facet):
    """Only meaningful when ``body_type == PICKUP``.

    The catalog splits a pickup nameplate the way the registration data does,
    which is two ways and not three: a double cab is รย.1 and everything else is
    รย.3. ``SINGLE_SMART`` is that รย.3 group. ``SINGLE_CAB`` and ``SMART_CAB``
    stay in the vocabulary for anyone who later gets a source that tells them
    apart - DLT does not.
    """

    DOUBLE_CAB = "DOUBLE_CAB"
    SINGLE_SMART = "SINGLE_SMART"    # single + smart/space/club cab, i.e. รย.3
    SMART_CAB = "SMART_CAB"          # half / space / extended cab
    SINGLE_CAB = "SINGLE_CAB"
    NOT_APPLICABLE = "NOT_APPLICABLE"


BODY_ON_FRAME = frozenset({BodyType.PPV, BodyType.PICKUP})


# --------------------------------------------------------------------------
# 3. Market position (price band). Derived, never hand-typed.
# --------------------------------------------------------------------------
class MarketPosition(Facet):
    ENTRY = "ENTRY"                  # < 500,000
    VOLUME = "VOLUME"                # 500,000 - 999,999
    UPPER = "UPPER"                  # 1,000,000 - 1,799,999
    LUXURY = "LUXURY"                # >= 1,800,000
    UNKNOWN = "UNKNOWN"


# Contiguous upper bounds in THB. The owner's brief listed "1M-1.8M" then
# "2M+", which leaves 1.8M-2.0M unclassified; the gap is closed at 1.8M so
# every price lands in exactly one band. Change this tuple to re-band the
# whole warehouse - nothing else hard-codes a price boundary.
PRICE_BAND_EDGES: tuple[tuple[int, MarketPosition], ...] = (
    (500_000, MarketPosition.ENTRY),
    (1_000_000, MarketPosition.VOLUME),
    (1_800_000, MarketPosition.UPPER),
)


def market_position_for_price(price_thb: Optional[float]) -> MarketPosition:
    """Map an on-the-road price in THB to its band."""
    if price_thb is None:
        return MarketPosition.UNKNOWN
    if price_thb < 0:
        raise ValueError("price_thb must not be negative")
    for edge, band in PRICE_BAND_EDGES:
        if price_thb < edge:
            return band
    return MarketPosition.LUXURY


# --------------------------------------------------------------------------
# 4. Powertrain
# --------------------------------------------------------------------------
class Powertrain(Facet):
    """What moves the car.

    There is deliberately no MHEV. A 48V belt-driven starter cannot move the
    car on its own and nothing in this market is sold on it - neither layer of
    the site has a column for it, and splitting it out only ever produced a
    category readers had to be told to ignore. "MHEV" and "MILD_HYBRID" parse
    to ICE, so a source or a catalog file that spells it still loads and simply
    lands where it belongs; it cannot enter the warehouse as its own value.

    REEV is a market label, not a guess from drivetrain architecture. Use it
    when the manufacturer markets the vehicle as REEV/EREV. Nissan e-Power
    remains HEV in this catalog; a generic "range extender" description is
    not enough to reclassify it as REEV.
    """

    ICE = "ICE"                      # petrol or diesel, mild hybrids included
    HEV = "HEV"                      # full hybrid, no plug - includes e-Power
    PHEV = "PHEV"
    REEV = "REEV"                    # plug-in, engine never drives the wheels
    BEV = "BEV"
    FCEV = "FCEV"
    UNKNOWN = "UNKNOWN"


class PowertrainGroup(Facet):
    COMBUSTION = "COMBUSTION"        # ICE
    HYBRID = "HYBRID"                # HEV, PHEV, REEV
    ZERO_EMISSION = "ZERO_EMISSION"  # BEV, FCEV
    UNKNOWN = "UNKNOWN"


_POWERTRAIN_GROUP = {
    Powertrain.ICE: PowertrainGroup.COMBUSTION,
    Powertrain.HEV: PowertrainGroup.HYBRID,
    Powertrain.PHEV: PowertrainGroup.HYBRID,
    Powertrain.REEV: PowertrainGroup.HYBRID,
    Powertrain.BEV: PowertrainGroup.ZERO_EMISSION,
    Powertrain.FCEV: PowertrainGroup.ZERO_EMISSION,
    Powertrain.UNKNOWN: PowertrainGroup.UNKNOWN,
}

class MarketPowertrain(Facet):
    """Reader-facing market buckets.

    ``PowertrainGroup`` folds too far for a buyer - it puts a Prius and an
    Outlander PHEV in one bucket - and ``Powertrain`` splits further than the
    market does: it separates a Prius from an Outlander PHEV, which is the
    distinction a buyer is shopping, and folds nothing a showroom sells on.

    The warehouse keeps the precise code either way. This is what to group and
    filter by when the answer is going in front of a reader.
    """

    FUEL = "FUEL"            # ICE, mild hybrids included
    HYBRID = "HYBRID"        # HEV, including Nissan e-Power
    PLUGIN = "PLUGIN"        # PHEV
    REEV = "REEV"            # maker-positioned REEV / EREV
    ELECTRIC = "ELECTRIC"    # BEV and FCEV
    MIXED = "MIXED"
    UNKNOWN = "UNKNOWN"


_MARKET_POWERTRAIN = {
    Powertrain.ICE: MarketPowertrain.FUEL,
    Powertrain.HEV: MarketPowertrain.HYBRID,
    Powertrain.REEV: MarketPowertrain.REEV,
    Powertrain.PHEV: MarketPowertrain.PLUGIN,
    Powertrain.BEV: MarketPowertrain.ELECTRIC,
    Powertrain.FCEV: MarketPowertrain.ELECTRIC,
    Powertrain.UNKNOWN: MarketPowertrain.UNKNOWN,
}

#: Thai labels for reader-facing market buckets.
MARKET_POWERTRAIN_TH: dict[str, str] = {
    MarketPowertrain.FUEL.value: "น้ำมัน/ดีเซล",
    MarketPowertrain.HYBRID.value: "ไฮบริด",
    MarketPowertrain.PLUGIN.value: "ปลั๊กอินไฮบริด",
    MarketPowertrain.REEV.value: "REEV",
    MarketPowertrain.ELECTRIC.value: "ไฟฟ้า",
    MarketPowertrain.MIXED.value: "ปนกัน",
    MarketPowertrain.UNKNOWN.value: "ไม่ทราบ",
}


def market_powertrain(pt: Powertrain) -> MarketPowertrain:
    return _MARKET_POWERTRAIN[Powertrain.parse(pt)]


#: Cars that can be charged from a socket. REEV is here because a range
#: extender is charged and then burns fuel when it runs out - which is true of
#: an i3 REx or a Li Auto and is NOT true of Nissan e-Power, whose battery is
#: only ever charged by its own engine. Filing e-Power as REEV therefore made
#: every one of its units read as a plug-in car; it is HEV in this catalog for
#: that reason, which is also how Thai excise treats it.
_PLUGGABLE = frozenset({Powertrain.PHEV, Powertrain.REEV, Powertrain.BEV})
#: xEV in the DLT/FTI sense. Mild hybrids used to be in here, which quietly put
#: 34,345 units of ordinary petrol car into every "electrified share" figure.
_ELECTRIFIED = frozenset(
    {Powertrain.HEV, Powertrain.PHEV, Powertrain.REEV,
     Powertrain.BEV, Powertrain.FCEV}
)


def powertrain_group(pt: Powertrain) -> PowertrainGroup:
    return _POWERTRAIN_GROUP[Powertrain.parse(pt)]


def is_plug_in(pt: Powertrain) -> bool:
    return Powertrain.parse(pt) in _PLUGGABLE


def is_electrified(pt: Powertrain) -> bool:
    """xEV in the DLT/FTI sense: anything with a traction battery."""
    return Powertrain.parse(pt) in _ELECTRIFIED


# --------------------------------------------------------------------------
# 5. Assembly origin and import route
# --------------------------------------------------------------------------
class ImportType(Facet):
    CBU = "CBU"                      # complete unit, imported
    SKD = "SKD"                      # semi knocked-down, local final assembly
    CKD = "CKD"                      # complete knocked-down, local assembly
    UNKNOWN = "UNKNOWN"


LOCALLY_ASSEMBLED = frozenset({ImportType.SKD, ImportType.CKD})


def is_locally_assembled(import_type: ImportType, origin_country: str) -> bool:
    it = ImportType.parse(import_type)
    return it in LOCALLY_ASSEMBLED or (
        it is ImportType.CBU and (origin_country or "").upper() == "TH"
    )


# ISO-3166 alpha-2 for the plants that actually feed the Thai market.
KNOWN_ORIGIN_COUNTRIES: dict[str, str] = {
    "TH": "ไทย",
    "CN": "จีน",
    "ID": "อินโดนีเซีย",
    "MY": "มาเลเซีย",
    "VN": "เวียดนาม",
    "JP": "ญี่ปุ่น",
    "KR": "เกาหลีใต้",
    "IN": "อินเดีย",
    "PH": "ฟิลิปปินส์",
    "DE": "เยอรมนี",
    "AT": "ออสเตรีย",
    "GB": "สหราชอาณาจักร",
    "ES": "สเปน",
    "CZ": "เช็กเกีย",
    "SK": "สโลวาเกีย",
    "HU": "ฮังการี",
    "TR": "ตุรกี",
    "IT": "อิตาลี",
    "SE": "สวีเดน",
    "US": "สหรัฐอเมริกา",
    "MX": "เม็กซิโก",
    "ZA": "แอฟริกาใต้",
    "AR": "อาร์เจนตินา",
    "BR": "บราซิล",
    "UNKNOWN": "ไม่ทราบ",
}


def normalize_country(code: Optional[str]) -> str:
    if not code:
        return "UNKNOWN"
    key = code.strip().upper()
    return key if key in KNOWN_ORIGIN_COUNTRIES else key


# --------------------------------------------------------------------------
# 6. Brand positioning
# --------------------------------------------------------------------------
class BrandSegment(Facet):
    BUDGET = "BUDGET"
    MASS = "MASS"
    PREMIUM_TECH = "PREMIUM_TECH"
    PERFORMANCE = "PERFORMANCE"
    PREMIUM_LUXURY = "PREMIUM_LUXURY"
    UNKNOWN = "UNKNOWN"


# --------------------------------------------------------------------------
# 7. DLT registration class. รย.1 is the owner's target, but a pickup is
#    registered รย.3, so the class has to be an explicit column rather than an
#    assumption baked into the loader.
# --------------------------------------------------------------------------
class RegistrationType(Facet):
    RY1 = "RY1"    # รย.1 รถยนต์นั่งส่วนบุคคลไม่เกิน 7 คน
    RY2 = "RY2"    # รย.2 รถยนต์นั่งส่วนบุคคลเกิน 7 คน (van, large MPV)
    RY3 = "RY3"    # รย.3 รถยนต์บรรทุกส่วนบุคคล (single cab, smart cab)
    RY12 = "RY12"  # รย.12 รถจักรยานยนต์ - out of scope, kept for completeness
    OTHER = "OTHER"


#: Bodies whose รย. class the data decides, not the taxonomy: a van can be
#: รย.2 or รย.3 and a truck is รย.3, but neither follows from a cab type.
FLEET_BODIES = frozenset({BodyType.VAN, BodyType.TRUCK})


def registration_type_for(body: BodyType, cab: CabType) -> RegistrationType:
    """Which DLT class a car is registered under.

    A double-cab pickup is registered รย.1 - it is a passenger car in DLT's
    eyes - while single and smart cabs are รย.3. That split is why cab type is
    a model-level fact here and why each cab body is its own model row.
    """
    body = BodyType.parse(body)
    cab = CabType.parse(cab)
    if body is BodyType.PICKUP:
        return RegistrationType.RY1 if cab is CabType.DOUBLE_CAB \
            else RegistrationType.RY3
    if body is BodyType.TRUCK:
        return RegistrationType.RY3
    return RegistrationType.RY1


class MarketScope(Facet):
    """Whether a model belongs in the numbers the owner actually reads.

    The owner's brief: no grey imports, no supercars, nothing that is not sold
    by the official Thai distributor, nothing insignificant. Rather than delete
    those rows - which would push every stray DLT line into the review queue
    forever - each model declares its scope, and reports default to CORE.
    """

    CORE = "CORE"              # official distributor, meaningful volume
    NICHE = "NICHE"            # official but halo / exotic / very low volume
    GREY = "GREY"              # not sold by the official Thai distributor
    COMMERCIAL = "COMMERCIAL"  # trucks and fleet vans - a different market
    UNKNOWN = "UNKNOWN"


#: What `cube` counts unless the caller asks for more.
DEFAULT_SCOPES: tuple[str, ...] = (MarketScope.CORE.value,)


class Drivetrain(Facet):
    FWD = "FWD"
    RWD = "RWD"
    AWD = "AWD"
    FOURWD = "4WD"
    UNKNOWN = "UNKNOWN"


class Grain(Facet):
    """How precisely a fact row could be resolved against the catalog."""

    BRAND = "BRAND"
    MODEL = "MODEL"
    VARIANT = "VARIANT"


GRAIN_RANK = {Grain.BRAND: 0, Grain.MODEL: 1, Grain.VARIANT: 2}


# --------------------------------------------------------------------------
# Cross-facet consistency rules
# --------------------------------------------------------------------------
def check_registration(body: BodyType, cab: CabType,
                       reg: RegistrationType) -> list[str]:
    """รย. class must follow from body and cab, with รย.2 as the only opt-out."""
    expected = registration_type_for(body, cab)
    reg = RegistrationType.parse(reg)
    if reg is RegistrationType.RY2:
        return []                      # >7 seats: van and large MPV, owner's call
    if BodyType.parse(body) in FLEET_BODIES:
        return []                      # the source file decides for these
    if reg is not expected:
        return [f"{BodyType.parse(body).value}/{CabType.parse(cab).value} is "
                f"registered {expected.value}, not {reg.value}"]
    return []


def check_body_segment(body: BodyType, cab: CabType, segment: Segment) -> list[str]:
    """Return human-readable problems; empty list means consistent."""
    problems: list[str] = []
    body = BodyType.parse(body)
    cab = CabType.parse(cab)
    segment = Segment.parse(segment)

    if body is BodyType.PICKUP and cab is CabType.NOT_APPLICABLE:
        problems.append("pickup must declare a cab_type")
    if body is not BodyType.PICKUP and cab is not CabType.NOT_APPLICABLE:
        problems.append(f"cab_type is only valid for PICKUP, got body={body.value}")
    if body is BodyType.PICKUP and segment is not Segment.F:
        problems.append("owner scheme: every pickup is segment F")
    if segment is Segment.F and body is not BodyType.PICKUP:
        problems.append("segment F is reserved for pickups in the owner scheme")
    return problems


def check_powertrain(pt: Powertrain, battery_kwh: Optional[float],
                     engine_cc: Optional[int]) -> list[str]:
    problems: list[str] = []
    pt = Powertrain.parse(pt)
    if pt is Powertrain.BEV and engine_cc:
        problems.append("BEV must not declare engine_cc")
    if pt is Powertrain.ICE and battery_kwh:
        problems.append("plain ICE must not declare a traction battery")
    if pt in _PLUGGABLE and pt is not Powertrain.BEV and not engine_cc:
        problems.append(f"{pt.value} needs engine_cc")
    if pt in {Powertrain.BEV, Powertrain.PHEV, Powertrain.REEV} and not battery_kwh:
        problems.append(f"{pt.value} needs battery_kwh")
    return problems


def check_origin(import_type: ImportType, origin_country: str) -> list[str]:
    problems: list[str] = []
    it = ImportType.parse(import_type)
    country = normalize_country(origin_country)
    if it in LOCALLY_ASSEMBLED and country != "TH":
        problems.append(
            f"{it.value} means assembled in Thailand, but origin_country={country}"
        )
    return problems


# --------------------------------------------------------------------------
# Labels and input aliases
# --------------------------------------------------------------------------
THAI_LABELS: dict[str, dict[str, str]] = {
    "Segment": {
        "A": "A - ซิตี้คาร์", "B": "B - ซับคอมแพกต์", "C": "C - คอมแพกต์",
        "D": "D - กลาง", "E": "E - ใหญ่/ผู้บริหาร", "F": "F - กระบะ",
        "UNKNOWN": "ไม่ระบุ",
    },
    "BodyType": {
        "HATCHBACK": "แฮทช์แบ็ก", "SEDAN": "ซีดาน", "CROSSOVER": "ครอสโอเวอร์",
        "SUV": "เอสยูวี", "PPV": "เอสยูวีบอดี้ออนเฟรม (PPV)", "COUPE": "คูเป้",
        "MPV": "เอ็มพีวี", "PICKUP": "กระบะ", "WAGON": "สเตชันแวกอน",
        "VAN": "รถตู้",
        "TRUCK": "รถบรรทุก", "OTHER": "อื่น ๆ",
    },
    "CabType": {
        "DOUBLE_CAB": "แค็บ 4 ประตู (รย.1)",
        "SINGLE_SMART": "ตอนเดียว/แค็บ (รย.3)",
        "SMART_CAB": "แค็บ/สเปซแค็บ", "SINGLE_CAB": "ตอนเดียว",
        "NOT_APPLICABLE": "-",
    },
    "MarketPosition": {
        "ENTRY": "0-5 แสนบาท", "VOLUME": "5 แสน-1 ล้านบาท",
        "UPPER": "1-1.8 ล้านบาท", "LUXURY": "1.8 ล้านบาทขึ้นไป",
        "UNKNOWN": "ไม่ทราบราคา",
    },
    "Powertrain": {
        "ICE": "สันดาป", "HEV": "ไฮบริด",
        "PHEV": "ปลั๊กอินไฮบริด", "REEV": "REEV",
        "BEV": "ไฟฟ้าล้วน", "FCEV": "เซลล์เชื้อเพลิง", "UNKNOWN": "ไม่ระบุ",
    },
    "PowertrainGroup": {
        "COMBUSTION": "เครื่องยนต์สันดาป", "HYBRID": "ไฮบริด",
        "ZERO_EMISSION": "ไร้มลพิษท่อไอเสีย", "UNKNOWN": "ไม่ระบุ",
    },
    "ImportType": {
        "CBU": "นำเข้าทั้งคัน (CBU)", "SKD": "ประกอบในประเทศ (SKD)",
        "CKD": "ประกอบในประเทศ (CKD)", "UNKNOWN": "ไม่ระบุ",
    },
    "BrandSegment": {
        "BUDGET": "Budget", "MASS": "Mass", "PREMIUM_TECH": "Premium tech",
        "PERFORMANCE": "Performance", "PREMIUM_LUXURY": "Premium luxury",
        "UNKNOWN": "ไม่ระบุ",
    },
    "RegistrationType": {
        "RY1": "รย.1 รถยนต์นั่งส่วนบุคคลไม่เกิน 7 คน",
        "RY2": "รย.2 รถยนต์นั่งส่วนบุคคลเกิน 7 คน",
        "RY3": "รย.3 รถยนต์บรรทุกส่วนบุคคล",
        "RY12": "รย.12 รถจักรยานยนต์",
        "OTHER": "อื่น ๆ",
    },
    "Drivetrain": {
        "FWD": "ขับหน้า", "RWD": "ขับหลัง", "AWD": "ขับสี่อัตโนมัติ",
        "4WD": "ขับสี่พาร์ทไทม์", "UNKNOWN": "ไม่ระบุ",
    },
    "Grain": {"BRAND": "ระดับยี่ห้อ", "MODEL": "ระดับรุ่น", "VARIANT": "ระดับรุ่นย่อย"},
    "MarketScope": {
        "CORE": "ตลาดหลัก (ตัวแทนจำหน่ายทางการ)",
        "NICHE": "เฉพาะกลุ่ม / ซูเปอร์คาร์ / ยอดน้อยมาก",
        "GREY": "เกรย์มาร์เก็ต ไม่ใช่ตัวแทนทางการ",
        "COMMERCIAL": "รถบรรทุก/รถตู้เชิงพาณิชย์",
        "UNKNOWN": "ยังไม่จัด",
    },
}

FACET_ALIASES: dict[str, dict[str, str]] = {
    "BodyType": {
        "SUV_BOF": "PPV", "BODY_ON_FRAME_SUV": "PPV", "PPV_SUV": "PPV",
        "MINIVAN": "MPV", "CONVERTIBLE": "COUPE",
        "CABRIOLET": "COUPE", "ESTATE": "WAGON", "PICK_UP": "PICKUP",
    },
    "CabType": {
        "CAB4": "DOUBLE_CAB", "4_DOOR": "DOUBLE_CAB", "CREW_CAB": "DOUBLE_CAB",
        "SPACE_CAB": "SMART_CAB", "EXTENDED_CAB": "SMART_CAB",
        "HALF_CAB": "SMART_CAB", "OPEN_CAB": "SMART_CAB",
        "STANDARD_CAB": "SINGLE_CAB", "CHASSIS": "SINGLE_CAB",
        "SINGLE_SMART_CAB": "SINGLE_SMART", "CAB": "SINGLE_SMART",
        "RY3_CAB": "SINGLE_SMART", "NA": "NOT_APPLICABLE",
        "NONE": "NOT_APPLICABLE",
    },
    "Powertrain": {
        "EV": "BEV", "ELECTRIC": "BEV", "HYBRID": "HEV", "FULL_HYBRID": "HEV",
        # A mild hybrid is a petrol car; it has no value of its own here.
        "MHEV": "ICE", "MILD_HYBRID": "ICE", "MILD_HEV": "ICE",
        "EQ_BOOST": "ICE", "48V": "ICE",
        "PLUG_IN_HYBRID": "PHEV", "PLUGIN": "PHEV",
        # Only the explicit maker labels REEV/EREV map here. Generic
        # RANGE_EXTENDER is ambiguous (notably Nissan e-Power) and must
        # not auto-classify a vehicle as REEV.
        "EREV": "REEV", "GASOLINE": "ICE",
        "PETROL": "ICE", "DIESEL": "ICE", "HYDROGEN": "FCEV",
    },
    "ImportType": {"IMPORTED": "CBU", "LOCAL": "CKD", "ASSEMBLED": "CKD"},
    "Drivetrain": {"2WD": "FWD", "FF": "FWD", "FR": "RWD", "4X4": "4WD",
                   "4X2": "RWD", "FOUR_WD": "4WD"},
    "RegistrationType": {
        "RY_1": "RY1", "1": "RY1", "รย.1": "RY1",
        "RY_2": "RY2", "2": "RY2", "รย.2": "RY2",
        "RY_3": "RY3", "3": "RY3", "รย.3": "RY3",
    },
    "MarketScope": {"MAIN": "CORE", "OFFICIAL": "CORE", "EXOTIC": "NICHE",
                    "SUPERCAR": "NICHE", "IMPORT": "GREY",
                    "GREY_MARKET": "GREY", "เกรย์": "GREY",
                    "TRUCK": "COMMERCIAL", "FLEET": "COMMERCIAL"},
    "BrandSegment": {"LUXURY": "PREMIUM_LUXURY", "PREMIUM": "PREMIUM_LUXURY",
                     "TECH": "PREMIUM_TECH", "SPORT": "PERFORMANCE",
                     "ECONOMY": "BUDGET", "VALUE": "BUDGET"},
}


#: Facet columns the cube may group by, in the owner's stated order.
FACET_COLUMNS: tuple[str, ...] = (
    "brand", "model", "variant", "segment", "body_type", "cab_type",
    "market_position", "powertrain", "powertrain_group", "origin_country",
    "import_type", "brand_segment", "oem_group", "brand_origin", "drivetrain",
    "registration_type", "province", "period",
)


def label(value: object) -> str:
    """Thai label for any facet member, safe on plain strings."""
    if isinstance(value, Facet):
        return value.th
    return str(value)


def all_members(facet_cls: type) -> Iterable[Facet]:
    return list(facet_cls)
