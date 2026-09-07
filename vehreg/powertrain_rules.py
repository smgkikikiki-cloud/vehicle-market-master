"""Owner-reviewed fact-level powertrain rules.

DLT often reports only a nameplate.  The annual catalog is still the canonical
vehicle definition, but a model-grain registration can need a more precise
answer than annual variant consensus can provide: a mid-year powertrain
changeover, a source label that explicitly says HEV/PHEV/REEV, or an owner
reviewed market convention for a bare label.

These rules affect MODEL-grain analytical facts only.  Variant-grain facts keep
their resolved variant powertrain.  First matching rule wins.  This is
classification, never allocation: units are not split or redistributed.
"""

from __future__ import annotations

from dataclasses import dataclass
import re

from .db import DIM_FACETS, DIM_FLAGS, DIM_NUMERIC

MIXED = "MIXED"


@dataclass(frozen=True, slots=True)
class Rule:
    brand: str
    model: str
    powertrain: str
    start: str | None = None
    end: str | None = None
    raw_any: tuple[str, ...] = ()
    raw_none: tuple[str, ...] = ()
    base_powertrain: str | None = None
    note: str = ""


def R(brand: str, model: str, powertrain: str, *, start: str | None = None,
      end: str | None = None, raw_any: tuple[str, ...] = (),
      raw_none: tuple[str, ...] = (), base_powertrain: str | None = None,
      note: str = "") -> Rule:
    return Rule(brand, model, powertrain, start, end, raw_any, raw_none,
                base_powertrain, note)


# Order is intentional: source-explicit labels beat a bare-nameplate default.
RULES: tuple[Rule, ...] = (
    # Chinese / trim-rich brands where the master deliberately stays MODEL grain.
    R("Deepal", "Deepal S05", "REEV", raw_any=("REEV",)),
    R("Deepal", "Deepal S05", "BEV"),
    R("Denza", "Denza D9", "PHEV", raw_any=("PHEV", "DM-I", "PLUG-IN")),
    R("Denza", "Denza D9", "BEV"),
    R("GWM", "Haval H6", "PHEV", raw_any=("PHEV", "PLUG-IN")),
    R("GWM", "Haval H6", "HEV", raw_any=("HEV", "HYBRID")),
    R("GWM", "Haval Jolion", "HEV"),
    R("GWM", "Tank 300", "HEV", raw_any=("HEV", "HYBRID")),
    R("GWM", "Tank 300", "ICE", raw_any=("DIESEL",)),
    R("GWM", "Tank 300", "HEV", end="2024-12"),
    R("GWM", "Tank 300", MIXED, start="2025-01"),
    R("GWM", "Tank 500", "HEV", raw_any=("HEV", "HYBRID")),
    R("GWM", "Tank 500", "ICE", raw_any=("DIESEL",)),
    R("GWM", "Tank 500", "HEV", end="2024-12"),
    R("GWM", "Tank 500", MIXED, start="2025-01"),

    # Honda: explicit owner cut-offs where annual catalogs are too coarse.
    R("Honda", "CR-V", MIXED, end="2025-11"),
    R("Honda", "CR-V", "HEV", start="2025-12"),
    R("Honda", "HR-V", "ICE", end="2021-10"),
    R("Honda", "HR-V", MIXED, start="2021-11", end="2021-11"),
    R("Honda", "HR-V", "HEV", start="2021-12"),
    R("Honda", "Accord", MIXED, end="2023-09"),
    R("Honda", "Accord", "HEV", start="2023-10"),
    R("Honda", "Civic", MIXED),
    R("Honda", "City", MIXED),
    R("Honda", "City Hatchback", MIXED),

    # Toyota owner calls, including generation/month cut-offs.
    R("Toyota", "Corolla Altis", MIXED),
    R("Toyota", "Camry", MIXED, end="2024-09"),
    R("Toyota", "Camry", "HEV", start="2024-10"),
    R("Toyota", "Corolla Cross", MIXED, end="2025-12"),
    R("Toyota", "Corolla Cross", "HEV", start="2026-01"),
    R("Toyota", "Yaris Cross", "HEV"),
    R("Toyota", "Innova Zenix", MIXED),
    R("Toyota", "C-HR", MIXED),
    R("Toyota", "Prius", "HEV"),
    R("Toyota", "Crown", "HEV"),
    R("Toyota", "Harrier", "HEV"),
    R("Toyota", "Voxy", "HEV"),
    R("Toyota", "Noah", "HEV"),
    # Owner explicitly treats official-Thai Alphard/Vellfire as HEV only.
    R("Toyota", "Alphard", "HEV"),
    R("Toyota", "Vellfire", "HEV"),

    # Nissan e-Power is HEV in the owner's taxonomy.
    R("Nissan", "Kicks e-Power", "HEV"),

    # Mitsubishi.
    R("Mitsubishi", "Outlander PHEV", "PHEV"),
    R("Mitsubishi", "Xpander", "HEV", raw_any=("HEV",)),
    R("Mitsubishi", "Xpander", "ICE"),
    R("Mitsubishi", "Xpander Cross", "HEV", raw_any=("HEV",)),
    R("Mitsubishi", "Xpander Cross", "ICE"),
    R("Mitsubishi", "Xforce", "HEV"),
    R("Mitsubishi", "Attrage", "ICE"),
    R("Mitsubishi", "Mirage", "ICE"),

    # MG. New MG3 Hybrid+ launched in Thailand in 2024-08.
    R("MG", "MG HS", "PHEV", raw_any=("PHEV",)),
    R("MG", "MG HS", "ICE"),
    R("MG", "MG3", "ICE", end="2024-07"),
    R("MG", "MG3", "HEV", start="2024-08"),

    # Lexus: explicit suffixes first; owner default for a bare family label is HEV.
    R("Lexus", "NX", "PHEV", raw_any=("450H+", "PHEV", "PLUG-IN")),
    R("Lexus", "NX", "HEV"),
    R("Lexus", "RX", "PHEV", raw_any=("450H+", "PHEV", "PLUG-IN")),
    R("Lexus", "RX", "HEV"),
    R("Lexus", "UX", "BEV", raw_any=("300E", "ELECTRIC", "BEV")),
    R("Lexus", "UX", "HEV"),
    R("Lexus", "ES", "HEV", raw_any=("ES300H", "300H", "ES350H", "350H")),
    R("Lexus", "ES", "BEV", raw_any=("ES350E", "350E")),
    R("Lexus", "ES", "HEV", end="2026-07"),
    R("Lexus", "ES", MIXED, start="2026-08",
      raw_none=("ES300H", "300H", "ES350H", "350H", "ES350E", "350E")),
    R("Lexus", "LM", "HEV"),
    R("Lexus", "IS", "HEV"),
    R("Lexus", "LBX", "HEV"),
    R("Lexus", "LS", "HEV"),
    R("Lexus", "RZ", "BEV"),

    # BMW: i cars remain separate nameplates in the catalog; these are the non-i families.
    R("BMW", "3 Series", MIXED),
    R("BMW", "5 Series", MIXED),
    R("BMW", "7 Series", MIXED),
    R("BMW", "X1", MIXED),
    R("BMW", "X3", MIXED),
    R("BMW", "X5", MIXED),
    R("BMW", "X6", "ICE"),
    R("BMW", "X7", "ICE"),

    # Volvo: owner's five-year rule is PHEV unless the model/source is clearly BEV.
    R("Volvo", "*", "BEV", base_powertrain="BEV"),
    R("Volvo", "*", "BEV", raw_any=("PURE ELECTRIC", "ELECTRIC", "BEV")),
    R("Volvo", "*", "PHEV", start="2021-01"),

    # Mercedes-Benz. Electric twins with their own nameplate are left alone.
    R("Mercedes-Benz", "C-Class", MIXED),
    R("Mercedes-Benz", "E-Class", MIXED),
    R("Mercedes-Benz", "GLC", MIXED),
    R("Mercedes-Benz", "GLE", MIXED),
    R("Mercedes-Benz", "S-Class", MIXED),
    R("Mercedes-Benz", "CLE", MIXED),
    R("Mercedes-Benz", "GLA", "ICE"),
    R("Mercedes-Benz", "GLB", "ICE"),
    R("Mercedes-Benz", "G-Class", "ICE"),
    R("Mercedes-Benz", "A-Class", "ICE"),
    # New CLA 250+ electric entered the Thai market in 2026-03.
    R("Mercedes-Benz", "CLA", "ICE", end="2026-02"),
    R("Mercedes-Benz", "CLA", "BEV", start="2026-03"),

    # Audi families the owner explicitly chose to keep mixed.
    R("Audi", "Q5", MIXED),
    R("Audi", "Audi Q7", MIXED),
    R("Audi", "Audi A6", MIXED),

    # Owner batch 2: high-impact worklist decisions reviewed against the
    # DLT source through 2026-08. Explicit source labels beat generic defaults.
    R("Deepal", "Deepal S07", "BEV"),
    R("BYD", "Sealion 6 DM-i", "PHEV"),

    # Kia Carnival: diesel-only historically; HEV appears in DLT from 2025-11
    # while generic CARNIVAL continues, so the unsplit current nameplate is MIXED.
    R("Kia", "Carnival", "HEV", raw_any=("HEV", "HYBRID")),
    R("Kia", "Carnival", "ICE", end="2025-10"),
    R("Kia", "Carnival", MIXED, start="2025-11"),

    R("Hyundai", "Staria", "ICE"),

    # Porsche: generic nameplates span ICE/PHEV; explicit E-Hybrid labels stay exact.
    R("Porsche", "Cayenne", "PHEV", raw_any=("E-HYBRID", "PHEV", "PLUG-IN")),
    R("Porsche", "Cayenne", MIXED),
    R("Porsche", "Panamera", "PHEV", raw_any=("E-HYBRID", "PHEV", "PLUG-IN")),
    R("Porsche", "Panamera", MIXED),

    # JLR Sport/Velar are separate canonical models after the catalog repair below.
    R("Land Rover", "Range Rover Sport", "PHEV", raw_any=("PHEV",)),
    R("Land Rover", "Range Rover Sport", MIXED),
    R("Land Rover", "Range Rover Velar", "PHEV", raw_any=("PHEV",)),
    R("Land Rover", "Range Rover Velar", MIXED),

    # Audi Q8 generic spans ICE/PHEV. Q8 e-tron remains a separate electric model.
    R("Audi", "Q8", "PHEV", raw_any=("TFSI E", "TFSIE", "PHEV", "PLUG-IN")),
    R("Audi", "Q8", MIXED),

    # A8 source evidence proves a transition overlap: TFSI e appears in 2024-04,
    # while a 55 TFSI ICE registration still appears in 2024-06. Keep explicit
    # labels exact and make only the post-transition bare nameplate MIXED.
    R("Audi", "A8", "PHEV", raw_any=("TFSI E", "TFSIE", "PHEV", "PLUG-IN")),
    R("Audi", "A8", "ICE", raw_any=("55 TFSI",)),
    R("Audi", "A8", "ICE", end="2024-03"),
    R("Audi", "A8", MIXED, start="2024-04"),

    # Owner batch 3: clear the remaining reviewed worklist.
    # Most entries are direct owner approval of the existing catalog assumption.
    R("Jaecoo", "Jaecoo 5 EV", "BEV"),
    R("Honda", "Jazz", "ICE"),
    R("MG", "MG S5 EV", "BEV"),
    R("BYD", "Sealion 7", "BEV"),
    R("Suzuki", "Suzuki Carry", "ICE"),
    R("BYD", "Seal", "BEV"),
    R("MG", "MG EP", "BEV"),
    R("MG", "MG Extender Double Cab", "ICE"),
    R("Isuzu", "Isuzu Elf", "ICE"),
    R("Chery", "Chery V23", "BEV"),
    R("Jaecoo", "Jaecoo 6 EV", "BEV"),
    R("Toyota", "Vios", "ICE"),
    R("Toyota", "Hiace Majesty", "ICE"),
    R("Changan", "Changan Lumin", "BEV"),
    R("Hyundai", "H-1", "ICE"),
    R("Suzuki", "Ciaz", "ICE"),
    R("BMW", "2 Series Gran Coupe", "ICE"),
    R("Mazda", "CX-8", "ICE"),
    R("Mercedes-Benz", "CLS", "ICE"),
    R("Nissan", "Terra", "ICE"),
    R("XPeng", "XPeng G6", "BEV"),
    R("MG", "MG VS HEV", "HEV"),
    R("Geely", "Geely EX5", "BEV"),
    R("Honda", "BR-V", "ICE"),
    R("Chery", "Omoda C5", "BEV"),
    R("MG", "MG Extender Cab", "ICE"),
    R("Nissan", "March", "ICE"),
    R("BYD", "BYD M6", "BEV"),
    R("Zeekr", "Zeekr X", "BEV"),
    R("Zeekr", "Zeekr 009", "BEV"),
    R("Honda", "WR-V", "ICE"),
    R("Nissan", "Note", "ICE"),
    R("Toyota", "Hiace", "ICE"),

    # MINI Countryman: the DLT history is ICE, then the U25 BEV appears as
    # Countryman SE ALL4 from 2024-11. ICE Countryman S/JCW registrations
    # continue alongside it, so explicit labels win over the current default.
    R("MINI", "Countryman", "BEV", raw_any=("COUNTRYMAN SE", "ELECTRIC")),
    R("MINI", "Countryman", "ICE", raw_any=("COOPER S COUNTRYMAN", "COUNTRYMAN S", "JCW COUNTRYMAN", "COOPER SD")),
    R("MINI", "Countryman", "ICE", end="2024-10"),
    R("MINI", "Countryman", "BEV", start="2024-11"),

    R("Nissan", "Serena", "HEV"),
    R("Hyundai", "Stargazer", "ICE"),
    R("Suzuki", "Ertiga", "ICE"),
    R("XPeng", "XPeng X9", "BEV"),
    R("Hino", "Hino Truck", "ICE"),
    R("Mazda", "BT-50 Double Cab", "ICE"),
    R("Toyota", "Sienta", "ICE"),
    R("MG", "MG IM6", "BEV"),
    R("Mazda", "BT-50 Cab", "ICE"),
    R("BMW", "iX3", "BEV"),

    # Audi A5: e-hybrid first appears in DLT in 2025-11. Legacy 40/45 TFSI
    # registrations continue after that, so keep those exact while the current
    # bare-nameplate default follows the owner's PHEV call.
    R("Audi", "A5", "PHEV", raw_any=("E-HYBRID", "PHEV", "PLUG-IN")),
    R("Audi", "A5", "ICE", raw_any=("40 TFSI", "45 TFSI", "2.0T FSI")),
    R("Audi", "A5", "ICE", end="2025-10"),
    R("Audi", "A5", "PHEV", start="2025-11"),

    R("BMW", "X4", "ICE"),
    R("BYD", "Seal 5 DM-i", "PHEV"),
    R("MG", "MG Maxus 9", "BEV"),
    R("Toyota", "Land Cruiser 300", "ICE"),

    # MINI Cooper also spans generations in this DLT window. Explicit old ICE
    # body/engine labels stay ICE; Electric/E/SE labels are BEV. A bare current
    # Cooper defaults BEV from the J01 launch window.
    R("MINI", "Cooper", "BEV", raw_any=("ELECTRIC", "COOPER SE", "COOPER E")),
    R("MINI", "Cooper", "ICE", raw_any=("COOPER S ", "COOPER D", "JOHN COOPER WORKS", "CLUBMAN", "CABRIO", "CONVERTIBLE", "HATCH", "5-TURER", "PACEMAN")),
    R("MINI", "Cooper", "ICE", end="2024-05"),
    R("MINI", "Cooper", "BEV", start="2024-06"),

    R("Hyundai", "Creta", "ICE"),
    R("Riddara", "Riddara RD6 Double Cab", "BEV"),
    R("Deepal", "Deepal L07", "BEV"),
    R("Kia", "EV5", "BEV"),
    R("Foton", "Foton Truck", "ICE"),
    R("Porsche", "Taycan", "BEV"),
    R("Honda", "Step WGN", "HEV"),
    R("Avatr", "Avatr 11", "BEV"),

    # Owner default: 4 Series = BEV. Existing DLT rows through 2026-08 are
    # explicitly 420/430/M440 (plus one stray 840i), all combustion; preserve
    # those exact source labels as ICE rather than rewriting historical facts.
    R("BMW", "4 Series", "ICE", raw_any=("420I", "420D", "430I", "430D", "M440I", "840I")),
    R("BMW", "4 Series", "BEV"),

    R("MG", "MG ES", "BEV"),
    R("Audi", "TT", "ICE"),
    R("Toyota", "bZ4X", "BEV"),
    R("Jaecoo", "Jaecoo 7", "PHEV"),
    R("BMW", "iX", "BEV"),
    R("MINI", "Aceman", "BEV"),

    # Mazda: petrol/diesel/mild-hybrid all fold to ICE in this taxonomy.
    R("Mazda", "Mazda2", "ICE"),
    R("Mazda", "Mazda3", "ICE"),
    R("Mazda", "CX-30", "ICE"),
    R("Mazda", "CX-5", "ICE"),
)


# These decisions were reviewed by the owner.  They no longer belong on the
# "catalog asserted a powertrain nobody checked" worklist, even when the final
# answer is deliberately MIXED.
_REVIEWED: tuple[tuple[str, str], ...] = tuple({(r.brand, r.model) for r in RULES})


def _key(value: object) -> str:
    return re.sub(r"[^A-Z0-9]+", "", str(value or "").upper())


_REVIEWED_KEYS = {(_key(b), _key(m)) for b, m in _REVIEWED if m != "*"}


def is_owner_reviewed(brand: object, model: object) -> bool:
    if _key(brand) == "VOLVO":
        return True
    return (_key(brand), _key(model)) in _REVIEWED_KEYS


def _q(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _cond(rule: Rule, alias: str) -> str:
    parts = [f"{alias}.grain='MODEL'",
             f"upper(COALESCE({alias}.brand,''))={_q(rule.brand.upper())}"]
    if rule.model != "*":
        parts.append(f"upper(COALESCE({alias}.model,''))={_q(rule.model.upper())}")
    if rule.start:
        parts.append(f"{alias}.period>={_q(rule.start)}")
    if rule.end:
        parts.append(f"{alias}.period<={_q(rule.end)}")
    if rule.base_powertrain:
        parts.append(f"upper(COALESCE({alias}.powertrain,''))={_q(rule.base_powertrain.upper())}")
    raw = f"upper(COALESCE({alias}.raw_label,''))"
    if rule.raw_any:
        parts.append("(" + " OR ".join(
            f"instr({raw},{_q(token.upper())})>0" for token in rule.raw_any) + ")")
    for token in rule.raw_none:
        parts.append(f"instr({raw},{_q(token.upper())})=0")
    return " AND ".join(parts)


def effective_powertrain_sql(alias: str = "b") -> str:
    whens = " ".join(
        f"WHEN {_cond(rule, alias)} THEN {_q(rule.powertrain)}" for rule in RULES
    )
    return f"CASE {whens} ELSE {alias}.powertrain END"


def _group_sql(pt: str, alias: str) -> str:
    return ("CASE "
            f"WHEN ({pt})='ICE' THEN 'COMBUSTION' "
            f"WHEN ({pt}) IN ('HEV','PHEV','REEV') THEN 'HYBRID' "
            f"WHEN ({pt}) IN ('BEV','FCEV') THEN 'ZERO_EMISSION' "
            f"WHEN ({pt})='MIXED' THEN 'MIXED' "
            f"ELSE {alias}.powertrain_group END")


def _market_sql(pt: str, alias: str) -> str:
    return ("CASE "
            f"WHEN ({pt})='ICE' THEN 'FUEL' "
            f"WHEN ({pt})='HEV' THEN 'HYBRID' "
            f"WHEN ({pt})='PHEV' THEN 'PLUGIN' "
            f"WHEN ({pt})='REEV' THEN 'REEV' "
            f"WHEN ({pt}) IN ('BEV','FCEV') THEN 'ELECTRIC' "
            f"WHEN ({pt})='MIXED' THEN 'MIXED' "
            f"ELSE {alias}.market_powertrain END")


def _electrified_sql(pt: str, alias: str) -> str:
    return ("CASE "
            f"WHEN ({pt})='ICE' THEN 0 "
            f"WHEN ({pt}) IN ('HEV','PHEV','REEV','BEV','FCEV') THEN 1 "
            f"WHEN ({pt})='MIXED' THEN 'MIXED' "
            f"ELSE {alias}.is_electrified END")


def _plug_sql(pt: str, alias: str) -> str:
    return ("CASE "
            f"WHEN ({pt}) IN ('PHEV','REEV','BEV') THEN 1 "
            f"WHEN ({pt}) IN ('ICE','HEV','FCEV') THEN 0 "
            f"WHEN ({pt})='MIXED' THEN 'MIXED' "
            f"ELSE {alias}.is_plug_in END")


def apply_powertrain_rules_sql(base_sql: str, *, include_price_band: bool = True) -> str:
    """Wrap a classified-fact source with the owner-reviewed rulebook."""
    alias = "b"
    pt = effective_powertrain_sql(alias)
    meta = (
        "b.fact_id, b.period, b.fact_registration_type, b.province, b.grain, "
        "b.units, b.raw_label, b.source_id, b.match_how, b.match_score, "
        "b.unit_id, b.catalog_year, b.estimated"
    )
    facets: list[str] = []
    for field in DIM_FACETS:
        if field == "powertrain":
            facets.append(f"{pt} AS powertrain")
        elif field == "powertrain_group":
            facets.append(f"{_group_sql(pt, alias)} AS powertrain_group")
        elif field == "market_powertrain":
            facets.append(f"{_market_sql(pt, alias)} AS market_powertrain")
        else:
            facets.append(f"b.{field}")
    numeric = [f"b.{field}" for field in DIM_NUMERIC]
    flags: list[str] = []
    for field in DIM_FLAGS:
        if field == "is_electrified":
            flags.append(f"{_electrified_sql(pt, alias)} AS is_electrified")
        elif field == "is_plug_in":
            flags.append(f"{_plug_sql(pt, alias)} AS is_plug_in")
        else:
            flags.append(f"b.{field}")
    columns = [meta, *facets, *numeric, *flags]
    if include_price_band:
        columns.append("b.price_band")
    return f"SELECT {', '.join(columns)} FROM ({base_sql}) b"
