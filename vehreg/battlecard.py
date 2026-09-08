"""Deterministic battle-card output over comparable specification views."""

from __future__ import annotations

from datetime import date
from typing import Any, Optional, TYPE_CHECKING

from .comparable_specs import (
    ComparisonRule, ComparableSpecError, ECOCandidateSpecStore, SpecFact,
    SpecRegistry, ValueState,
)
from .entities import to_jsonable
from .pricing import PriceType

if TYPE_CHECKING:  # pragma: no cover
    from .product import ProductMaster


def _value(field_key: str, value: Any, unit: str = "", *,
           qualifiers: Optional[dict[str, str]] = None,
           source: str = "market_trim", source_ref: Any = None,
           verification_status: str = "VERIFIED") -> dict:
    return {
        "field_key": field_key, "value_state": "KNOWN", "value": value,
        "unit": unit, "qualifiers": qualifiers or {}, "source": source,
        "source_ref": source_ref, "verification_status": verification_status,
    }


def _display(definition, cell: dict) -> Optional[str]:
    if cell["value_state"] != "KNOWN":
        return None
    value = cell["value"]
    if definition.value_type.value == "NUMBER" and definition.display_precision is not None:
        value = f"{value:.{definition.display_precision}f}"
    if definition.value_type.value == "BOOLEAN":
        return "มี" if value else "ไม่มี"
    return f"{value} {cell['unit']}".strip()


class BattleCardEngine:
    def __init__(self, registry: SpecRegistry) -> None:
        self.registry = registry

    def candidate_card(self, store: ECOCandidateSpecStore, source_ids: list[str],
                       *, profile_id: str = "c_crossover_core") -> dict:
        subjects = []
        for source_id in source_ids:
            candidate = store.get(source_id)
            subjects.append({
                "subject_id": candidate["subject_id"], "label": candidate["label"],
                "model_id": candidate["model_id"], "trim_id": None,
                "powertrain": candidate.get("powertrain") or "",
                "publication_status": candidate["publication_status"],
                "current_list_price": None,
                "price_evidence": {
                    "amount_thb": candidate["recommended_price_thb"],
                    "price_type": candidate["price_classification"],
                    "canonical_retail_price": False,
                },
                "values": [dict(v, source=candidate["source"],
                                source_ref=candidate["source_ref"],
                                verification_status="PROVISIONAL")
                           for v in candidate["values"]],
            })
        return self._build(subjects, profile_id=profile_id,
                           mode="PROVISIONAL_ECO_CANDIDATES")

    def trim_card(self, master: "ProductMaster", trim_ids: list[str], *,
                  profile_id: str = "c_crossover_core",
                  as_of: Optional[date] = None) -> dict:
        when = as_of or date.today()
        subjects = [self._trim_view(master, trim_id, when) for trim_id in trim_ids]
        return self._build(subjects, profile_id=profile_id,
                           mode="PUBLISHED_MARKET_TRIMS", as_of=when.isoformat())

    def _trim_view(self, master: "ProductMaster", trim_id: str, when: date) -> dict:
        if trim_id not in master.catalog.trims:
            raise ComparableSpecError(f"unknown trim_id {trim_id!r}")
        trim = master.catalog.trims[trim_id]
        model = master.catalog.model_for_trim(trim_id)
        brand = master.catalog.brand_for_trim(trim_id)
        source_refs = {key: list(values) for key, values in trim.source_refs.items()}
        values: list[dict] = []
        mappings = [
            ("identity.powertrain", trim.powertrain.value, ""),
            ("powertrain.drivetrain", trim.drivetrain.value, ""),
            ("engine.displacement_cc", trim.engine_cc, "cc"),
            ("battery.catalog_capacity_kwh", trim.battery_kwh, "kWh"),
            ("powertrain.transmission", trim.transmission, ""),
            ("vehicle.seats", trim.seats, "seat"),
            ("vehicle.length_mm", trim.length_mm, "mm"),
            ("vehicle.width_mm", trim.width_mm, "mm"),
            ("vehicle.height_mm", trim.height_mm, "mm"),
            ("vehicle.wheelbase_mm", trim.wheelbase_mm, "mm"),
            ("fitment.tyre_front", trim.tire_front, ""),
            ("fitment.tyre_rear", trim.tire_rear, ""),
        ]
        for key, raw, unit in mappings:
            if key in self.registry.fields and raw not in (None, "", "UNKNOWN"):
                values.append(_value(key, raw, unit, source_ref=source_refs))
        eco = master.eco.get(trim_id)
        if eco:
            eco_ref = f"https://car.ecosticker.go.th/landing-page/detail/{eco.source_ref}"
            eco_values = [
                ("vehicle.declared_total_weight_kg", eco.declared_total_weight_kg, "kg"),
                ("fitment.tyre_size", eco.tire_size, ""),
                ("battery.chemistry", eco.battery_chemistry, ""),
                ("battery.supplier", eco.battery_supplier, ""),
                ("battery.nominal_voltage_v", eco.battery_voltage_v, "V"),
                ("manufacturing.factory", eco.factory, ""),
            ]
            for key, raw, unit in eco_values:
                if key in self.registry.fields and raw not in (None, ""):
                    values.append(_value(key, raw, unit, source="ecosticker",
                                         source_ref=eco_ref))
            if eco.rated_range_km is not None:
                values.append(_value(
                    "ev.rated_range_km", eco.rated_range_km, "km",
                    qualifiers={"measurement_basis": "ECO_STICKER_DECLARED",
                                "range_scope": "ELECTRIC_ONLY"
                                if trim.powertrain.value in ("PHEV", "REEV")
                                else "FULL"},
                    source="ecosticker", source_ref=eco_ref))
        # Authored facts take precedence over the Phase-1 baseline for the same
        # field and comparison context, while retaining both sources in storage.
        for fact in master.comparable_specs.resolved(trim_id, as_of=when):
            definition = self.registry.fields[fact.field_key]
            qkey = fact.qualifier_key(definition)
            values = [v for v in values if not (
                v["field_key"] == fact.field_key
                and tuple((key, str(v["qualifiers"].get(key, "")))
                          for key in definition.comparison_qualifiers) == qkey)]
            values.append({
                "field_key": fact.field_key,
                "value_state": fact.value_state.value,
                "value": fact.value, "unit": fact.unit,
                "qualifiers": fact.qualifiers, "source": fact.source,
                "source_ref": fact.source_ref,
                "source_locator": fact.source_locator,
                "verification_status": fact.verification_status.value,
                "fact_id": fact.fact_id,
            })
        current = master.prices.current_list_price(trim_id, as_of=when)
        campaigns = [r for r in master.prices.records_for(
            trim_id, price_type=PriceType.CAMPAIGN_PRICE) if r.active_on(when)]
        return {
            "subject_id": trim_id, "trim_id": trim_id, "model_id": model.id,
            "powertrain": trim.powertrain.value,
            "label": f"{brand.name_en} {model.name_en} {trim.name}",
            "publication_status": "VERIFIED_MARKET_TRIM",
            "current_list_price": to_jsonable(current) if current else None,
            "active_campaign_prices": [to_jsonable(r) for r in campaigns],
            "values": values,
        }

    def _build(self, subjects: list[dict], *, profile_id: str, mode: str,
               as_of: Optional[str] = None) -> dict:
        if not 2 <= len(subjects) <= 6:
            raise ComparableSpecError("battle card requires 2 to 6 subjects")
        try:
            field_keys = self.registry.profiles[profile_id]
        except KeyError as exc:
            raise ComparableSpecError(f"unknown comparison profile {profile_id!r}") from exc
        subject_ids = [s["subject_id"] for s in subjects]
        if len(subject_ids) != len(set(subject_ids)):
            raise ComparableSpecError("battle card subjects must be distinct")
        powertrains = {s["subject_id"]: s.get("powertrain") or ""
                       for s in subjects}
        by_subject: dict[str, dict[str, list[dict]]] = {}
        for subject in subjects:
            fields: dict[str, list[dict]] = {}
            for value in subject["values"]:
                fields.setdefault(value["field_key"], []).append(value)
            by_subject[subject["subject_id"]] = fields
        rows = []
        comparable_rows = rows_with_gaps = 0
        for field_key in field_keys:
            definition = self.registry.fields[field_key]
            contexts = {
                tuple((key, str(value["qualifiers"].get(key, "")))
                      for key in definition.comparison_qualifiers)
                for subject in subjects
                for value in by_subject[subject["subject_id"]].get(field_key, [])
            }
            # More than one context means these cars were not measured the
            # same way -- a plug-in's electric-only range against a BEV's total,
            # or NEDC against WLTP. Each becomes its own row, and a row holding
            # one of them is not a gap in the research.
            split_context = len(contexts) > 1
            for context in sorted(contexts or {()}):
                cells: dict[str, dict] = {}
                known: list[tuple[str, dict]] = []
                for subject in subjects:
                    matches = [
                        value for value in by_subject[subject["subject_id"]].get(field_key, [])
                        if tuple((key, str(value["qualifiers"].get(key, "")))
                                 for key in definition.comparison_qualifiers) == context
                    ]
                    if len(matches) > 1:
                        raise ComparableSpecError(
                            f"{subject['subject_id']}: duplicate {field_key} context {context}")
                    cell = matches[0] if matches else None
                    if cell is None:
                        # A BEV has no engine displacement. Reporting that as a
                        # gap in our research would be a lie about the car.
                        powertrain = powertrains.get(subject["subject_id"], "")
                        state = ("NOT_APPLICABLE"
                                 if definition.applicable_powertrains and powertrain
                                 and powertrain not in definition.applicable_powertrains
                                 else "UNKNOWN")
                        cell = {"field_key": field_key, "value_state": state,
                                "value": None, "unit": definition.canonical_unit,
                                "qualifiers": dict(context), "source": None,
                                "source_ref": None, "verification_status": None}
                    cell = dict(cell)
                    cell["display"] = _display(definition, cell)
                    cells[subject["subject_id"]] = cell
                    if cell["value_state"] == ValueState.KNOWN.value:
                        known.append((subject["subject_id"], cell))
                if not known:
                    continue
                # A ranked field that names the powertrains it applies to means
                # something different in each of them: a plug-in hybrid's 150 km
                # of electric range is not a worse version of a BEV's 500 km,
                # and its smaller battery is not a smaller version of the same
                # thing. Show every value, crown nobody.
                ranked = definition.comparison_rule in (
                    ComparisonRule.HIGHER_BETTER, ComparisonRule.LOWER_BETTER)
                spanned = {powertrains.get(sid, "") for sid, _ in known}
                applicable = [s for s in subjects
                              if not definition.applicable_powertrains
                              or not powertrains.get(s["subject_id"])
                              or powertrains[s["subject_id"]]
                              in definition.applicable_powertrains]
                if (ranked and definition.applicable_powertrains
                        and len(spanned - {""}) > 1):
                    comparison_status = "NOT_COMPARABLE_ACROSS_POWERTRAIN"
                    leaders = []
                elif len(applicable) < 2:
                    # Only one of these cars even has the thing. That is not a
                    # gap in the research, and calling it one reads as a fault.
                    comparison_status, leaders = "NOT_APPLICABLE_TO_OTHERS", []
                elif len(known) < 2:
                    comparison_status = ("CONTEXT_NOT_SHARED" if split_context
                                         else "INSUFFICIENT_DATA")
                    leaders = []
                elif definition.comparison_rule is ComparisonRule.INFORMATION_ONLY:
                    comparison_status, leaders = "INFORMATION_ONLY", []
                elif definition.comparison_rule in (
                        ComparisonRule.HIGHER_BETTER, ComparisonRule.LOWER_BETTER):
                    choose = (max if definition.comparison_rule
                              is ComparisonRule.HIGHER_BETTER else min)
                    best = choose(cell["value"] for _, cell in known)
                    leaders = [sid for sid, cell in known if cell["value"] == best]
                    comparison_status = "COMPARABLE" if len(known) == len(subjects) \
                        else "COMPARABLE_WITH_GAPS"
                elif definition.comparison_rule is ComparisonRule.PRESENCE:
                    leaders = [sid for sid, cell in known if cell["value"] is True]
                    comparison_status = "COMPARABLE" if len(known) == len(subjects) \
                        else "COMPARABLE_WITH_GAPS"
                else:
                    comparison_status, leaders = "SET_DIFFERENCE", []
                if comparison_status.startswith("COMPARABLE"):
                    comparable_rows += 1
                    rows_with_gaps += comparison_status.endswith("WITH_GAPS")
                rows.append({
                    "field_key": field_key, "group": definition.group,
                    "label_th": definition.label_th, "label_en": definition.label_en,
                    "comparison_rule": definition.comparison_rule.value,
                    "comparison_context": dict(context),
                    "comparison_status": comparison_status, "leaders": leaders,
                    "cells": cells,
                })
        return {
            "schema_version": 1, "mode": mode, "profile_id": profile_id,
            "as_of": as_of, "subjects": [{k: v for k, v in subject.items()
                                            if k != "values"} for subject in subjects],
            "rows": rows,
            "coverage": {
                "profile_fields": len(field_keys), "rows_with_any_value": len(rows),
                "comparable_rows": comparable_rows,
                "comparable_rows_with_gaps": rows_with_gaps,
            },
            "global_winner": None,
        }
