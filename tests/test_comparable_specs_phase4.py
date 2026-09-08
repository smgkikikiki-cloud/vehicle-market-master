from copy import deepcopy
from datetime import date
import json
from pathlib import Path
import shutil

import pytest

from vehreg.battlecard import BattleCardEngine
from vehreg.catalog import Catalog, CatalogError, DATA_DIR
from vehreg.cli import main
from vehreg.comparable_specs import (
    ComparableCohort, ComparableSpecError, ECOCandidateSpecStore, SpecLedger,
    SpecRegistry,
)
from vehreg.product import ProductMaster, import_spec_facts


ATTO3 = "762c0806-4101-4155-9343-7c2dc815dd3b"
MGS5 = "ee5085a9-67ca-40f6-9944-550da794d94c"
EX5 = "e9901aa9-5f90-406e-a56d-3d19da56b895"
JAECOO_TRIM = "jaecoo.jaecoo_5_ev.j5.trim.max_plus_bev"


@pytest.fixture
def local_data(tmp_path):
    shutil.copytree(DATA_DIR / "2026", tmp_path / "2026")
    return tmp_path


def fact(**changes):
    row = {
        "fact_id": "test.jaecoo.max_plus.power.2026",
        "trim_id": JAECOO_TRIM,
        "field_key": "powertrain.max_power_kw",
        "value_state": "KNOWN",
        "value": 155,
        "unit": "kW",
        "qualifiers": {"output_scope": "MOTOR", "rating_basis": "PEAK"},
        "effective_from": "2026-01-01",
        "effective_to": None,
        "observed_at": "2026-09-08",
        "claim_ids": ["claim.official.example"],
        "verification_status": "VERIFIED",
        "source": "official_oem",
        "source_ref": "https://example.com/specification",
        "source_locator": "Powertrain table / MAX+",
    }
    row.update(changes)
    return row


def payload(*facts):
    return {"schema_version": 1, "facts": list(facts)}


def test_registry_and_c_crossover_cohort_are_closed_and_valid():
    registry = SpecRegistry.load()
    assert len(registry.fields) == 50
    assert set(registry.profiles) == {
        "c_crossover_core", "c_crossover_safety", "c_crossover_comfort",
    }
    cohort = ComparableCohort.load()
    catalog = Catalog.load()
    assert cohort.validate(catalog) == []
    for model_id in cohort.model_ids:
        assert catalog.models[model_id].body_type.value == "CROSSOVER"
        assert any(g.segment.value == "C" for g in catalog.generations_of(model_id))


def test_the_cohort_is_the_rule_it_says_it_is():
    """A hand-picked list described as a segment is not a segment.

    Leaving the X1, the XC40 and the Q3 out of "C-crossover" while keeping cars
    with a single ECO row would make every card in it quietly unrepresentative.
    """
    import gzip
    import json as _json
    cohort = ComparableCohort.load()
    catalog = Catalog.load()
    eligible = {
        model_id for model_id, model in catalog.models.items()
        if model.body_type.value == "CROSSOVER"
        and any(g.segment.value == "C" for g in catalog.generations_of(model_id))}
    path = (DATA_DIR / "2026/ingest/ecosticker/snapshots/2026-09-08"
            / "normalized.jsonl.gz")
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        rows = [_json.loads(line) for line in handle]
    with_evidence = {
        row["matched_model_id"] for row in rows
        if row["detail_status"] == "available" and row.get("powertrain_candidate")}
    assert set(cohort.model_ids) == eligible & with_evidence


def test_a_model_without_a_representative_stays_in_the_segment():
    """Dropping it would hide a whole car and still call the result the segment."""
    cohort = ComparableCohort.load()
    missing = cohort.models_without_representative
    assert set(missing) <= set(cohort.model_ids)
    assert cohort.validate(Catalog.load()) == []


def test_eco_candidates_cover_the_cohort_but_publish_nothing():
    store = ECOCandidateSpecStore.load()
    coverage = store.coverage()
    assert coverage == {
        "cohort_models": 31,
        "models_with_candidates": 31,
        "candidate_trims": 118,
        "representative_candidates": 20,
        "models_without_representative": 11,
        "candidate_spec_values": 1842,
        "published_market_trims": 0,
    }
    representatives = store.list(representatives_only=True)
    assert len(representatives) == 20
    assert all(r["publication_status"] == "PROVISIONAL_UNRESOLVED_TRIM"
               for r in representatives)
    assert all(r["price_classification"] == "ECO_STICKER_PRICE"
               for r in representatives)


def test_candidate_battle_card_keeps_price_noncanonical_and_has_cell_sources():
    store = ECOCandidateSpecStore.load()
    card = BattleCardEngine(store.registry).candidate_card(
        store, [ATTO3, MGS5, EX5])
    assert card["mode"] == "PROVISIONAL_ECO_CANDIDATES"
    assert card["global_winner"] is None
    assert all(s["current_list_price"] is None for s in card["subjects"])
    assert all(s["price_evidence"]["price_type"] == "ECO_STICKER_PRICE"
               and not s["price_evidence"]["canonical_retail_price"]
               for s in card["subjects"])
    range_row = next(r for r in card["rows"]
                     if r["field_key"] == "ev.rated_range_km")
    assert range_row["comparison_status"] == "COMPARABLE"
    assert range_row["leaders"] == [f"ecosticker:{EX5}"]
    assert range_row["cells"][f"ecosticker:{ATTO3}"]["source_ref"].startswith(
        "https://car.ecosticker.go.th/")


def test_unknown_is_not_rendered_as_false_and_mismatched_basis_is_not_compared():
    registry = SpecRegistry.load()
    engine = BattleCardEngine(registry)
    subjects = [
        {"subject_id": "a", "label": "A", "values": [
            {"field_key": "safety.aeb", "value_state": "KNOWN", "value": False,
             "unit": "", "qualifiers": {}, "source": "oem", "source_ref": "a",
             "verification_status": "VERIFIED"},
            {"field_key": "ev.rated_range_km", "value_state": "KNOWN", "value": 500,
             "unit": "km", "qualifiers": {"measurement_basis": "WLTP"},
             "source": "oem", "source_ref": "a", "verification_status": "VERIFIED"},
        ]},
        {"subject_id": "b", "label": "B", "values": [
            {"field_key": "ev.rated_range_km", "value_state": "KNOWN", "value": 600,
             "unit": "km", "qualifiers": {"measurement_basis": "NEDC"},
             "source": "oem", "source_ref": "b", "verification_status": "VERIFIED"},
        ]},
    ]
    profile = deepcopy(registry.profiles)
    registry.profiles["test"] = ["safety.aeb", "ev.rated_range_km"]
    card = engine._build(subjects, profile_id="test", mode="TEST")
    aeb = card["rows"][0]
    assert aeb["cells"]["a"]["display"] == "ไม่มี"
    assert aeb["cells"]["b"]["value_state"] == "UNKNOWN"
    assert aeb["cells"]["b"]["display"] is None
    range_rows = [row for row in card["rows"]
                  if row["field_key"] == "ev.rated_range_km"]
    assert {row["comparison_context"]["measurement_basis"] for row in range_rows} \
        == {"NEDC", "WLTP"}
    # Two cars measured on different cycles are two rows, and neither wins.
    # This is a context split, not a hole in the research, and it says so.
    assert all(row["comparison_status"] == "CONTEXT_NOT_SHARED"
               and not row["leaders"] for row in range_rows)
    registry.profiles = profile


def test_fact_ledger_is_temporal_and_never_resurrects_expired_new_fact():
    registry = SpecRegistry.load()
    ledger = SpecLedger(registry)
    ledger.add_payload(payload(
        fact(fact_id="old", value=150, effective_from="2026-01-01"),
        fact(fact_id="new", value=160, effective_from="2026-06-01",
             effective_to="2026-06-30"),
    ))
    assert ledger.resolved(JAECOO_TRIM, as_of=date(2026, 6, 15))[0].value == 160
    assert ledger.resolved(JAECOO_TRIM, as_of=date(2026, 7, 1)) == []


def test_conflicting_values_at_one_start_fail_closed():
    registry = SpecRegistry.load()
    ledger = SpecLedger(registry)
    ledger.add_payload(payload(
        fact(fact_id="a"), fact(fact_id="b", value=999),
    ))
    assert any("conflicting" in problem for problem in ledger.validate())


def test_a_stray_field_on_a_fact_is_rejected():
    ledger = SpecLedger(SpecRegistry.load())
    with pytest.raises(ComparableSpecError, match="invalid/unknown fact fields"):
        ledger.add_payload({"schema_version": 1, "facts": [
            dict(fact(), price_thb=1)
        ]})


@pytest.mark.parametrize(("field_key", "unit"), [
    ("market.list_price_thb", "THB"),
    ("retail.msrp", ""),
    ("cost.total", ""),
    ("vehicle.range", "THB"),
])
def test_a_price_shaped_fact_is_rejected(field_key, unit):
    ledger = SpecLedger(SpecRegistry.load())
    with pytest.raises(ComparableSpecError, match="prices belong in PriceLedger"):
        ledger.add_payload({"schema_version": 1, "facts": [
            dict(fact(), field_key=field_key, unit=unit)
        ]})


def test_a_price_field_cannot_be_registered_at_all():
    """The only way a price gets into the spec store is by being registered.

    Guarding the payload alone was not a guard: a fact naming an unregistered
    key is refused anyway, and one naming a *registered* price key sailed
    through. The registry itself now refuses to hold a price field.
    """
    from vehreg.comparable_specs import SpecFieldDefinition, ValueType, ComparisonRule
    registry = SpecRegistry([SpecFieldDefinition(
        key="market.list_price_thb", group="identity", label_th="ราคา",
        label_en="List price", value_type=ValueType.NUMBER,
        comparison_rule=ComparisonRule.LOWER_BETTER, canonical_unit="THB")])
    assert any("PriceLedger" in problem for problem in registry.validate())


def test_spec_import_is_dry_run_idempotent_and_registration_safe(local_data):
    before = [r.as_row() for r in Catalog.load(local_data).iter_resolved()]
    data = payload(fact())
    dry = import_spec_facts(local_data, 2026, data)
    assert dry["added"] == 1 and not dry["written"]
    assert not Path(dry["path"]).exists()
    written = import_spec_facts(local_data, 2026, data, write=True)
    assert written["written"] and written["added"] == 1
    repeated = import_spec_facts(local_data, 2026, data, write=True)
    assert not repeated["written"] and repeated["added"] == 0
    master = ProductMaster.load(local_data)
    resolved = master.detail(JAECOO_TRIM, as_of=date(2026, 9, 8))["comparable_specs"]
    assert resolved[0]["value"] == 155
    assert master.validate() == []
    after = [r.as_row() for r in Catalog.load(local_data).iter_resolved()]
    assert after == before
    changed = payload(fact(value=999))
    with pytest.raises(CatalogError, match="fact_id"):
        import_spec_facts(local_data, 2026, changed, write=True)


def test_cli_exposes_coverage_candidates_and_battle_card(capsys):
    assert main(["market", "spec-coverage"]) == 0
    assert json.loads(capsys.readouterr().out)["candidates"]["cohort_models"] == 31
    assert main(["market", "battle-card", "--candidate", ATTO3,
                 "--candidate", MGS5]) == 0
    assert json.loads(capsys.readouterr().out)["mode"] == \
        "PROVISIONAL_ECO_CANDIDATES"
    assert main(["market", "battle-card", "--candidate", ATTO3]) == 2
    assert "2 to 6" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# A comparison that ranks incomparable things is worse than no comparison.
# ---------------------------------------------------------------------------

def _subject(subject_id, powertrain, values):
    return {"subject_id": subject_id, "label": subject_id,
            "powertrain": powertrain, "values": values}


def _range(value, scope, basis="ECO_STICKER_DECLARED"):
    return {"field_key": "ev.rated_range_km", "value_state": "KNOWN",
            "value": value, "unit": "km",
            "qualifiers": {"measurement_basis": basis, "range_scope": scope},
            "source": "ecosticker", "source_ref": "x",
            "verification_status": "PROVISIONAL"}


def _card(subjects, fields):
    registry = SpecRegistry.load()
    engine = BattleCardEngine(registry)
    keep = deepcopy(registry.profiles)
    registry.profiles["test"] = fields
    try:
        return engine._build(subjects, profile_id="test", mode="TEST")
    finally:
        registry.profiles = keep


def test_a_plug_in_hybrid_does_not_lose_a_race_it_was_not_in():
    """150 km of electric range is not a worse version of 500 km of range."""
    card = _card([
        _subject("bev", "BEV", [_range(500, "FULL")]),
        _subject("phev", "PHEV", [_range(150, "ELECTRIC_ONLY")]),
    ], ["ev.rated_range_km"])
    rows = [r for r in card["rows"] if r["field_key"] == "ev.rated_range_km"]
    assert len(rows) == 2, "the two quantities must not share a row"
    assert all(not row["leaders"] for row in rows)
    assert {row["comparison_status"] for row in rows} == {"CONTEXT_NOT_SHARED"}


def test_two_bevs_are_still_ranked_on_range():
    card = _card([
        _subject("a", "BEV", [_range(500, "FULL")]),
        _subject("b", "BEV", [_range(410, "FULL")]),
    ], ["ev.rated_range_km"])
    row = card["rows"][0]
    assert (row["comparison_status"], row["leaders"]) == ("COMPARABLE", ["a"])


def test_a_ranked_field_is_not_crowned_across_powertrains():
    """A plug-in's smaller battery is not a smaller version of the same thing."""
    def battery(value):
        return {"field_key": "battery.gross_capacity_kwh", "value_state": "KNOWN",
                "value": value, "unit": "kWh", "qualifiers": {},
                "source": "oem", "source_ref": "x",
                "verification_status": "VERIFIED"}
    card = _card([_subject("bev", "BEV", [battery(82)]),
                  _subject("phev", "PHEV", [battery(18)])],
                 ["battery.gross_capacity_kwh"])
    row = card["rows"][0]
    assert row["comparison_status"] == "NOT_COMPARABLE_ACROSS_POWERTRAIN"
    assert row["leaders"] == []
    # Both numbers are still shown; refusing to rank is not refusing to report.
    assert {c["value"] for c in row["cells"].values()} == {82, 18}


def test_zero_tailpipe_co2_does_not_beat_a_hybrid():
    """A BEV emits nothing at the tailpipe by definition, not by merit."""
    def co2(value):
        return {"field_key": "emissions.co2_g_km", "value_state": "KNOWN",
                "value": value, "unit": "g/km",
                "qualifiers": {"measurement_basis": "ECO_STICKER_DECLARED"},
                "source": "ecosticker", "source_ref": "x",
                "verification_status": "PROVISIONAL"}
    card = _card([_subject("bev", "BEV", [co2(0)]),
                  _subject("phev", "PHEV", [co2(10)])], ["emissions.co2_g_km"])
    row = card["rows"][0]
    assert (row["comparison_status"], row["leaders"]) == (
        "NOT_COMPARABLE_ACROSS_POWERTRAIN", [])


def test_a_car_without_an_engine_is_not_missing_research():
    card = _card([
        _subject("bev", "BEV", []),
        _subject("phev", "PHEV", [{
            "field_key": "engine.displacement_cc", "value_state": "KNOWN",
            "value": 1498, "unit": "cc", "qualifiers": {}, "source": "ecosticker",
            "source_ref": "x", "verification_status": "PROVISIONAL"}]),
    ], ["engine.displacement_cc"])
    row = card["rows"][0]
    assert row["comparison_status"] == "NOT_APPLICABLE_TO_OTHERS"
    assert row["cells"]["bev"]["value_state"] == "NOT_APPLICABLE"


def test_one_battery_chemistry_is_written_one_way():
    from vehreg.comparable_specs import battery_chemistry_family, transmission_family
    for raw in ("LFP", "LiFePO4", "Lithium iron phosphate/graphite",
                "lithium-phosphate (LFP)", "Lithium Iron Phosphate (LFP)"):
        assert battery_chemistry_family(raw) == "LFP", raw
    assert battery_chemistry_family("NCM/Graphite") == "NMC"
    assert battery_chemistry_family("Li-Ion (NCA)") == "NCA"
    assert battery_chemistry_family("Lithium-ion") == "LI_ION_UNSPECIFIED"
    assert battery_chemistry_family("-") is None
    # CVT rows also say "automatic"; the more specific answer has to win.
    assert transmission_family("เกียร์อัตโนมัติ ประเภท CVT") == "CVT"
    assert transmission_family("เกียร์อัตโนมัติ") == "AUTOMATIC"
    assert transmission_family("เกียร์ธรรมดา") == "MANUAL"
    assert transmission_family("-") is None
