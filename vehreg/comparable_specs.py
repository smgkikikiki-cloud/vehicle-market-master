"""Evidence-backed comparable specifications for retail vehicle products.

The canonical grain is ``MarketTrim``.  ECO rows which have not passed trim
review remain preview candidates: they can be inspected and compared, but they
cannot silently become published product facts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
import gzip
import json
import math
from pathlib import Path
import re
from typing import Any, Iterable, Optional, TYPE_CHECKING

from .catalog import DATA_DIR, DEFAULT_YEAR

if TYPE_CHECKING:  # pragma: no cover
    from .catalog import Catalog


class ComparableSpecError(ValueError):
    pass


class ValueType(str, Enum):
    NUMBER = "NUMBER"
    BOOLEAN = "BOOLEAN"
    ENUM = "ENUM"
    TEXT = "TEXT"
    SET = "SET"


class ComparisonRule(str, Enum):
    HIGHER_BETTER = "HIGHER_BETTER"
    LOWER_BETTER = "LOWER_BETTER"
    PRESENCE = "PRESENCE"
    SET_DIFFERENCE = "SET_DIFFERENCE"
    INFORMATION_ONLY = "INFORMATION_ONLY"


class ValueState(str, Enum):
    KNOWN = "KNOWN"
    NOT_AVAILABLE = "NOT_AVAILABLE"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class VerificationStatus(str, Enum):
    VERIFIED = "VERIFIED"
    PROVISIONAL = "PROVISIONAL"


def comparable_spec_root(data_dir: Path | str, year: int) -> Path:
    return Path(data_dir) / str(year) / "product" / "comparable_specs"


def _parse_enum(enum_cls, raw: object, field_name: str):
    try:
        return enum_cls(str(raw))
    except ValueError as exc:
        raise ComparableSpecError(f"unknown {field_name} {raw!r}") from exc


def _iso_date(raw: object, field_name: str, *, required: bool = False) -> Optional[str]:
    if raw in (None, ""):
        if required:
            raise ComparableSpecError(f"{field_name} is required")
        return None
    value = str(raw)
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ComparableSpecError(f"{field_name} must be YYYY-MM-DD")
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise ComparableSpecError(f"{field_name} must be YYYY-MM-DD") from exc
    return value


@dataclass(frozen=True, slots=True)
class SpecFieldDefinition:
    key: str
    group: str
    label_th: str
    label_en: str
    value_type: ValueType
    comparison_rule: ComparisonRule
    canonical_unit: str = ""
    applicable_powertrains: tuple[str, ...] = ()
    comparison_qualifiers: tuple[str, ...] = ()
    display_precision: Optional[int] = None

    def validate_value(self, state: ValueState, value: Any, unit: str) -> list[str]:
        problems: list[str] = []
        if state is not ValueState.KNOWN:
            if value is not None:
                problems.append("non-KNOWN value_state requires null value")
            return problems
        if value is None:
            return ["KNOWN requires a value"]
        if self.value_type is ValueType.NUMBER:
            if type(value) not in (int, float) or not math.isfinite(value):
                problems.append("numeric field requires a finite number")
            elif value < 0:
                problems.append("numeric field cannot be negative")
            if unit != self.canonical_unit:
                problems.append(f"unit must be {self.canonical_unit!r}")
        elif unit:
            problems.append("non-numeric field cannot carry a unit")
        if self.value_type is ValueType.BOOLEAN and type(value) is not bool:
            problems.append("boolean field requires true or false")
        if self.value_type in (ValueType.ENUM, ValueType.TEXT) and (
                not isinstance(value, str) or not value.strip()):
            problems.append("text/enum field requires nonempty text")
        if self.value_type is ValueType.SET and (
                not isinstance(value, list) or not value
                or not all(isinstance(v, str) and v.strip() for v in value)):
            problems.append("set field requires a nonempty string array")
        return problems


class SpecRegistry:
    def __init__(self, fields: Iterable[SpecFieldDefinition] = (),
                 profiles: Optional[dict[str, list[str]]] = None) -> None:
        self.fields: dict[str, SpecFieldDefinition] = {}
        for definition in fields:
            if definition.key in self.fields:
                raise ComparableSpecError(f"duplicate spec field {definition.key}")
            self.fields[definition.key] = definition
        self.profiles = profiles or {}

    @classmethod
    def load(cls, data_dir: Path | str = DATA_DIR,
             year: int = DEFAULT_YEAR) -> "SpecRegistry":
        root = comparable_spec_root(data_dir, year)
        fields_path, profiles_path = root / "registry.json", root / "profiles.json"
        if not fields_path.exists():
            return cls()
        payload = json.loads(fields_path.read_text(encoding="utf-8"))
        if payload.get("schema_version") != 1 or not isinstance(payload.get("fields"), list):
            raise ComparableSpecError(f"{fields_path}: invalid registry schema")
        definitions = []
        allowed = {"key", "group", "label_th", "label_en", "value_type",
                   "comparison_rule", "canonical_unit", "applicable_powertrains",
                   "comparison_qualifiers", "display_precision"}
        for raw in payload["fields"]:
            if not isinstance(raw, dict) or set(raw) - allowed:
                raise ComparableSpecError(f"{fields_path}: invalid field definition")
            definitions.append(SpecFieldDefinition(
                key=str(raw.get("key") or ""), group=str(raw.get("group") or ""),
                label_th=str(raw.get("label_th") or ""),
                label_en=str(raw.get("label_en") or ""),
                value_type=_parse_enum(ValueType, raw.get("value_type"), "value_type"),
                comparison_rule=_parse_enum(
                    ComparisonRule, raw.get("comparison_rule"), "comparison_rule"),
                canonical_unit=str(raw.get("canonical_unit") or ""),
                applicable_powertrains=tuple(raw.get("applicable_powertrains") or ()),
                comparison_qualifiers=tuple(raw.get("comparison_qualifiers") or ()),
                display_precision=raw.get("display_precision"),
            ))
        profiles: dict[str, list[str]] = {}
        if profiles_path.exists():
            profile_payload = json.loads(profiles_path.read_text(encoding="utf-8"))
            if profile_payload.get("schema_version") != 1:
                raise ComparableSpecError(f"{profiles_path}: invalid profile schema")
            for profile in profile_payload.get("profiles", []):
                pid = str(profile.get("id") or "")
                fields = profile.get("fields")
                if not pid or not isinstance(fields, list) or not all(
                        isinstance(key, str) for key in fields):
                    raise ComparableSpecError(f"{profiles_path}: invalid profile")
                profiles[pid] = fields
        registry = cls(definitions, profiles)
        problems = registry.validate()
        if problems:
            raise ComparableSpecError("; ".join(problems))
        return registry

    def validate(self) -> list[str]:
        problems: list[str] = []
        for key, definition in self.fields.items():
            if not key or not re.fullmatch(r"[a-z][a-z0-9_.]*", key):
                problems.append(f"invalid field key {key!r}")
            if not definition.group or not definition.label_th or not definition.label_en:
                problems.append(f"{key}: group and labels are required")
            if definition.value_type is ValueType.NUMBER and not definition.canonical_unit:
                problems.append(f"{key}: numeric field requires canonical_unit")
            if definition.display_precision is not None and (
                    type(definition.display_precision) is not int
                    or definition.display_precision < 0):
                problems.append(f"{key}: invalid display_precision")
        for profile, fields in self.profiles.items():
            unknown = [key for key in fields if key not in self.fields]
            if unknown:
                problems.append(f"profile {profile}: unknown fields {unknown}")
            if len(fields) != len(set(fields)):
                problems.append(f"profile {profile}: duplicate fields")
        return problems


@dataclass(frozen=True, slots=True)
class SpecFact:
    fact_id: str
    trim_id: str
    field_key: str
    value_state: ValueState
    value: Any = None
    unit: str = ""
    qualifiers: dict[str, str] = field(default_factory=dict)
    effective_from: Optional[str] = None
    effective_to: Optional[str] = None
    observed_at: Optional[str] = None
    claim_ids: tuple[str, ...] = ()
    verification_status: VerificationStatus = VerificationStatus.VERIFIED
    source: str = ""
    source_ref: str = ""
    source_locator: str = ""

    @property
    def start(self) -> Optional[str]:
        return self.effective_from or self.observed_at

    def active_on(self, when: date) -> bool:
        if self.start and self.start > when.isoformat():
            return False
        return not self.effective_to or self.effective_to >= when.isoformat()

    def qualifier_key(self, definition: SpecFieldDefinition) -> tuple[tuple[str, str], ...]:
        return tuple((key, str(self.qualifiers.get(key, "")))
                     for key in definition.comparison_qualifiers)


class SpecLedger:
    def __init__(self, registry: SpecRegistry, year: int = DEFAULT_YEAR,
                 *, catalog: Optional["Catalog"] = None) -> None:
        self.registry, self.year, self.catalog = registry, year, catalog
        self.facts: list[SpecFact] = []
        self._by_id: dict[str, SpecFact] = {}

    @classmethod
    def load(cls, data_dir: Path | str = DATA_DIR, year: int = DEFAULT_YEAR,
             *, registry: Optional[SpecRegistry] = None,
             catalog: Optional["Catalog"] = None) -> "SpecLedger":
        registry = registry or SpecRegistry.load(data_dir, year)
        ledger = cls(registry, year, catalog=catalog)
        root = comparable_spec_root(data_dir, year) / "facts"
        if root.is_dir():
            for path in sorted(root.glob("*.json")):
                ledger.add_payload(json.loads(path.read_text(encoding="utf-8")),
                                   source=str(path))
        return ledger

    def add_payload(self, payload: dict, *, source: str = "<memory>") -> None:
        if not isinstance(payload, dict) or payload.get("schema_version") != 1 \
                or not isinstance(payload.get("facts"), list):
            raise ComparableSpecError(f"{source}: expected schema_version 1 and facts")
        staged: list[SpecFact] = []
        staged_by_id: dict[str, SpecFact] = {}
        allowed = {name for name in SpecFact.__dataclass_fields__}
        for raw in payload["facts"]:
            if isinstance(raw, dict) and any(
                    "price" in str(key).lower() for key in raw):
                raise ComparableSpecError(f"{source}: prices belong in PriceLedger")
            if not isinstance(raw, dict) or set(raw) - allowed:
                raise ComparableSpecError(f"{source}: invalid/unknown fact fields")
            fact = SpecFact(
                fact_id=str(raw.get("fact_id") or "").strip(),
                trim_id=str(raw.get("trim_id") or "").strip(),
                field_key=str(raw.get("field_key") or "").strip(),
                value_state=_parse_enum(ValueState, raw.get("value_state"), "value_state"),
                value=raw.get("value"), unit=str(raw.get("unit") or ""),
                qualifiers={str(k): str(v) for k, v in (raw.get("qualifiers") or {}).items()},
                effective_from=_iso_date(raw.get("effective_from"), "effective_from"),
                effective_to=_iso_date(raw.get("effective_to"), "effective_to"),
                observed_at=_iso_date(raw.get("observed_at"), "observed_at"),
                claim_ids=tuple(str(x) for x in (raw.get("claim_ids") or ())),
                verification_status=_parse_enum(
                    VerificationStatus, raw.get("verification_status") or "VERIFIED",
                    "verification_status"),
                source=str(raw.get("source") or "").strip(),
                source_ref=str(raw.get("source_ref") or "").strip(),
                source_locator=str(raw.get("source_locator") or "").strip(),
            )
            problems = self._validate_fact(fact)
            if problems:
                raise ComparableSpecError(f"{source}: {fact.fact_id or '<missing>'}: "
                                          + "; ".join(problems))
            existing = self._by_id.get(fact.fact_id)
            if existing and existing != fact:
                raise ComparableSpecError(f"{source}: fact_id {fact.fact_id!r} changed")
            if fact.fact_id in staged_by_id and staged_by_id[fact.fact_id] != fact:
                raise ComparableSpecError(f"{source}: fact_id {fact.fact_id!r} changed")
            if not existing and fact.fact_id not in staged_by_id:
                staged.append(fact)
                staged_by_id[fact.fact_id] = fact
        for fact in staged:
            self.facts.append(fact)
            self._by_id[fact.fact_id] = fact

    def _validate_fact(self, fact: SpecFact) -> list[str]:
        problems: list[str] = []
        if not fact.fact_id or not fact.trim_id or not fact.field_key:
            problems.append("fact_id, trim_id and field_key are required")
        definition = self.registry.fields.get(fact.field_key)
        if definition is None:
            problems.append("unknown field_key")
        else:
            problems.extend(definition.validate_value(
                fact.value_state, fact.value, fact.unit))
            unknown_qualifiers = set(fact.qualifiers) - set(definition.comparison_qualifiers)
            if unknown_qualifiers:
                problems.append(f"unknown qualifiers {sorted(unknown_qualifiers)}")
        if self.catalog is not None and fact.trim_id not in self.catalog.trims:
            problems.append("trim does not exist")
        elif (definition is not None and definition.applicable_powertrains
              and self.catalog is not None
              and self.catalog.trims[fact.trim_id].powertrain.value
              not in definition.applicable_powertrains):
            problems.append(
                f"field does not apply to {self.catalog.trims[fact.trim_id].powertrain.value}")
        if not fact.observed_at or not fact.source or not fact.source_ref:
            problems.append("observed_at, source and source_ref are required")
        if fact.effective_from and fact.effective_to \
                and fact.effective_from > fact.effective_to:
            problems.append("effective_from is after effective_to")
        return problems

    def validate(self) -> list[str]:
        problems: list[str] = []
        for fact in self.facts:
            problems.extend(f"spec {fact.fact_id}: {p}" for p in self._validate_fact(fact))
        # Equal start + equal qualifier context + different values is a conflict,
        # never a cue to choose the largest or newest file row.
        groups: dict[tuple, list[SpecFact]] = {}
        for fact in self.facts:
            definition = self.registry.fields.get(fact.field_key)
            if definition:
                key = (fact.trim_id, fact.field_key, fact.qualifier_key(definition), fact.start)
                groups.setdefault(key, []).append(fact)
        for key, facts in groups.items():
            values = {(f.value_state.value, json.dumps(f.value, sort_keys=True,
                                                       ensure_ascii=False)) for f in facts}
            if len(values) > 1:
                problems.append(f"conflicting comparable spec facts at {key}")
        return problems

    def resolved(self, trim_id: str, *, as_of: Optional[date] = None,
                 include_provisional: bool = False) -> list[SpecFact]:
        when = as_of or date.today()
        candidates = [f for f in self.facts if f.trim_id == trim_id
                      and (include_provisional
                           or f.verification_status is VerificationStatus.VERIFIED)
                      and (not f.start or f.start <= when.isoformat())]
        groups: dict[tuple, list[SpecFact]] = {}
        for fact in candidates:
            definition = self.registry.fields[fact.field_key]
            groups.setdefault((fact.field_key, fact.qualifier_key(definition)), []).append(fact)
        resolved: list[SpecFact] = []
        for facts in groups.values():
            latest_start = max(f.start or "0001-01-01" for f in facts)
            latest = [f for f in facts if (f.start or "0001-01-01") == latest_start]
            active = [f for f in latest if f.active_on(when)]
            values = {(f.value_state.value, json.dumps(f.value, sort_keys=True,
                                                       ensure_ascii=False)) for f in active}
            if len(values) > 1:
                raise ComparableSpecError(
                    f"{trim_id}: conflicting {latest[0].field_key} at {latest_start}")
            if active:
                resolved.append(sorted(active, key=lambda f: f.fact_id)[-1])
        return sorted(resolved, key=lambda f: (f.field_key, f.qualifier_key(
            self.registry.fields[f.field_key])))

    def coverage(self, *, as_of: Optional[date] = None) -> dict[str, int]:
        trim_ids = {f.trim_id for f in self.facts}
        return {
            "facts": len(self.facts),
            "verified_facts": sum(
                f.verification_status is VerificationStatus.VERIFIED for f in self.facts),
            "provisional_facts": sum(
                f.verification_status is VerificationStatus.PROVISIONAL for f in self.facts),
            "trims_with_facts": len(trim_ids),
            "resolved_facts": sum(len(self.resolved(t, as_of=as_of)) for t in trim_ids),
        }


@dataclass(frozen=True, slots=True)
class ComparableCohort:
    id: str
    segment: str
    body_type: str
    model_ids: tuple[str, ...]
    representative_source_ids: dict[str, str]
    notes: str = ""

    @classmethod
    def load(cls, data_dir: Path | str = DATA_DIR, year: int = DEFAULT_YEAR,
             cohort_id: str = "c_crossover") -> "ComparableCohort":
        path = comparable_spec_root(data_dir, year) / "cohorts" / f"{cohort_id}.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            id=str(payload["id"]), segment=str(payload["segment"]),
            body_type=str(payload["body_type"]),
            model_ids=tuple(payload["model_ids"]),
            representative_source_ids=dict(payload.get("representative_source_ids") or {}),
            notes=str(payload.get("notes") or ""),
        )

    def validate(self, catalog: "Catalog") -> list[str]:
        problems: list[str] = []
        if len(self.model_ids) != len(set(self.model_ids)):
            problems.append(f"cohort {self.id}: duplicate model ids")
        if set(self.representative_source_ids) != set(self.model_ids):
            problems.append(f"cohort {self.id}: representative map must cover every model")
        for model_id in self.model_ids:
            model = catalog.models.get(model_id)
            if model is None:
                problems.append(f"cohort {self.id}: unknown model {model_id}")
                continue
            if model.body_type.value != self.body_type:
                problems.append(f"cohort {self.id}: {model_id} is not {self.body_type}")
            if not any(g.segment.value == self.segment
                       for g in catalog.generations_of(model_id)):
                problems.append(f"cohort {self.id}: {model_id} is not segment {self.segment}")
        return problems


def _read_jsonl_gz(path: Path) -> list[dict]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def _positive_number(raw: object) -> Optional[float | int]:
    value = str(raw or "").strip().replace(",", "")
    if not re.fullmatch(r"\d+(?:\.\d+)?", value):
        return None
    number = float(value)
    if number <= 0:
        return None
    return int(number) if number.is_integer() else number


def _nonnegative_number(raw: object) -> Optional[float | int]:
    value = str(raw or "").strip().replace(",", "")
    if not re.fullmatch(r"\d+(?:\.\d+)?", value):
        return None
    number = float(value)
    return int(number) if number.is_integer() else number


def _candidate_value(field_key: str, value: Any, *, unit: str = "",
                     qualifiers: Optional[dict[str, str]] = None) -> dict:
    return {"field_key": field_key, "value_state": "KNOWN", "value": value,
            "unit": unit, "qualifiers": qualifiers or {}}


class ECOCandidateSpecStore:
    """Read-only comparable views over immutable Phase-2 ECO evidence."""

    def __init__(self, records: Iterable[dict], cohort: ComparableCohort,
                 registry: SpecRegistry) -> None:
        rows = list(records)
        self.records = {r["source_id"]: r for r in rows}
        self.cohort, self.registry = cohort, registry
        if len(self.records) != len(rows):
            raise ComparableSpecError("duplicate ECO candidate source ids")
        for record in self.records.values():
            for value in record["values"]:
                definition = registry.fields.get(value["field_key"])
                if definition is None:
                    raise ComparableSpecError(
                        f"candidate {record['source_id']}: unknown field {value['field_key']}")
                unknown = set(value["qualifiers"]) - set(definition.comparison_qualifiers)
                problems = definition.validate_value(
                    ValueState(value["value_state"]), value["value"], value["unit"])
                if unknown:
                    problems.append(f"unknown qualifiers {sorted(unknown)}")
                if problems:
                    raise ComparableSpecError(
                        f"candidate {record['source_id']} {value['field_key']}: "
                        + "; ".join(problems))
        missing_representatives = set(cohort.representative_source_ids.values()) - set(self.records)
        if missing_representatives:
            raise ComparableSpecError(
                f"cohort representatives missing from snapshot: {sorted(missing_representatives)}")

    @classmethod
    def load(cls, data_dir: Path | str = DATA_DIR, year: int = DEFAULT_YEAR,
             *, snapshot_date: str = "2026-09-08", cohort_id: str = "c_crossover",
             registry: Optional[SpecRegistry] = None) -> "ECOCandidateSpecStore":
        registry = registry or SpecRegistry.load(data_dir, year)
        cohort = ComparableCohort.load(data_dir, year, cohort_id)
        root = Path(data_dir) / str(year) / "ingest" / "ecosticker" / \
            "snapshots" / snapshot_date
        normalized = _read_jsonl_gz(root / "normalized.jsonl.gz")
        raw = {row["source_id"]: row for row in _read_jsonl_gz(root / "raw.jsonl.gz")}
        records: list[dict] = []
        for row in normalized:
            model_id = row.get("matched_model_id")
            if model_id not in cohort.model_ids:
                continue
            detail = (raw.get(row["source_id"]) or {}).get("detail") or {}
            values: list[dict] = []
            simple = [
                ("identity.powertrain", row.get("powertrain_candidate"), ""),
                ("vehicle.model_year", _positive_number(detail.get("model_year")), "year"),
                ("vehicle.length_mm", row.get("length_mm"), "mm"),
                ("vehicle.width_mm", row.get("width_mm"), "mm"),
                ("vehicle.height_mm", row.get("height_mm"), "mm"),
                ("vehicle.seats", row.get("seats"), "seat"),
                ("vehicle.declared_total_weight_kg", row.get("declared_total_weight_kg"), "kg"),
                ("fitment.tyre_size", row.get("wheel_size"), ""),
                ("engine.displacement_cc", _positive_number(detail.get("capacity_cylinder")), "cc"),
                ("powertrain.transmission", detail.get("gear_name"), ""),
                ("battery.chemistry", row.get("battery_chemistry"), ""),
                ("battery.supplier", row.get("battery_supplier"), ""),
                ("battery.nominal_voltage_v", _positive_number(detail.get("nominal_voltage")), "V"),
                ("powertrain.motor_type", detail.get("motor"), ""),
                ("emissions.co2_g_km", _nonnegative_number(detail.get("emissions_CO2")), "g/km"),
                ("manufacturing.factory", row.get("factory"), ""),
            ]
            for key, value, unit in simple:
                if value not in (None, "", "-") and key in registry.fields:
                    values.append(_candidate_value(key, value, unit=unit))
            range_km = _positive_number(detail.get("driving_range"))
            if range_km is not None:
                values.append(_candidate_value(
                    "ev.rated_range_km", range_km, unit="km",
                    qualifiers={"measurement_basis": "ECO_STICKER_DECLARED"}))
            consumption = _positive_number(detail.get("energy_consumption"))
            if consumption is not None:
                values.append(_candidate_value(
                    "ev.energy_consumption_wh_km", consumption, unit="Wh/km",
                    qualifiers={"measurement_basis": "ECO_STICKER_DECLARED"}))
            records.append({
                "subject_id": f"ecosticker:{row['source_id']}",
                "source_id": row["source_id"], "model_id": model_id,
                "generation_id": row.get("matched_generation_id"),
                "label": row["model_raw"],
                "powertrain": row.get("powertrain_candidate"),
                "review_status": row.get("review_status"),
                "publication_status": "PROVISIONAL_UNRESOLVED_TRIM",
                "source": "ecosticker", "source_ref": row["source_url"],
                "observed_at": row.get("snapshot_date"),
                "recommended_price_thb": row.get("recommended_price_thb"),
                "price_classification": "ECO_STICKER_PRICE",
                "values": values,
                "representative": cohort.representative_source_ids.get(model_id)
                                  == row["source_id"],
            })
        return cls(records, cohort, registry)

    def list(self, *, model_id: Optional[str] = None,
             representatives_only: bool = False) -> list[dict]:
        return sorted((r for r in self.records.values()
                       if (not model_id or r["model_id"] == model_id)
                       and (not representatives_only or r["representative"])),
                      key=lambda r: (r["model_id"], r["label"], r["source_id"]))

    def get(self, source_id: str) -> dict:
        try:
            return self.records[source_id]
        except KeyError as exc:
            raise ComparableSpecError(f"unknown ECO candidate {source_id!r}") from exc

    def coverage(self) -> dict[str, int]:
        rows = self.list()
        return {
            "cohort_models": len(self.cohort.model_ids),
            "models_with_candidates": len({r["model_id"] for r in rows}),
            "candidate_trims": len(rows),
            "representative_candidates": sum(r["representative"] for r in rows),
            "candidate_spec_values": sum(len(r["values"]) for r in rows),
            "published_market_trims": 0,
        }
