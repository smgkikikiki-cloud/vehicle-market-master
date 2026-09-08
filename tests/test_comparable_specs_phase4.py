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
    assert len(registry.fields) == 48
    assert set(registry.profiles) == {
        "c_crossover_core", "c_crossover_safety", "c_crossover_comfort",
    }
    cohort = ComparableCohort.load()
    catalog = Catalog.load()
    assert len(cohort.model_ids) == 20
    assert len(cohort.representative_source_ids) == 20
    assert cohort.validate(catalog) == []
    for model_id in cohort.model_ids:
        assert catalog.models[model_id].body_type.value == "CROSSOVER"
        assert any(g.segment.value == "C" for g in catalog.generations_of(model_id))


def test_eco_candidates_cover_twenty_models_but_publish_nothing():
    store = ECOCandidateSpecStore.load()
    coverage = store.coverage()
    assert coverage == {
        "cohort_models": 20,
        "models_with_candidates": 20,
        "candidate_trims": 80,
        "representative_candidates": 20,
        "candidate_spec_values": 1174,
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
    assert {tuple(row["comparison_context"].items()) for row in range_rows} == {
        (("measurement_basis", "NEDC"),),
        (("measurement_basis", "WLTP"),),
    }
    assert all(row["comparison_status"] == "INSUFFICIENT_DATA"
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


def test_conflict_and_price_smuggling_fail_closed():
    registry = SpecRegistry.load()
    ledger = SpecLedger(registry)
    ledger.add_payload(payload(
        fact(fact_id="a"), fact(fact_id="b", value=999),
    ))
    assert any("conflicting" in problem for problem in ledger.validate())
    with pytest.raises(ComparableSpecError, match="prices belong in PriceLedger"):
        ledger.add_payload({"schema_version": 1, "facts": [
            dict(fact(), price_thb=1)
        ]})


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
    assert json.loads(capsys.readouterr().out)["candidates"]["cohort_models"] == 20
    assert main(["market", "battle-card", "--candidate", ATTO3,
                 "--candidate", MGS5]) == 0
    assert json.loads(capsys.readouterr().out)["mode"] == \
        "PROVISIONAL_ECO_CANDIDATES"
    assert main(["market", "battle-card", "--candidate", ATTO3]) == 2
    assert "2 to 6" in capsys.readouterr().err
