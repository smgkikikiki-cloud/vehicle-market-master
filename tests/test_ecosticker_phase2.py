import json
import gzip
import hashlib
from pathlib import Path
import shutil

import pytest

from vehreg.catalog import Catalog, DATA_DIR
from vehreg.cli import main
from vehreg.ecosticker_ingest import (
    ECOIngestError,
    build_snapshot,
    infer_powertrain,
    ingestion_status,
    load_normalized_snapshot,
    load_raw_inventory,
    normalize_inventory,
    save_decisions,
    validate_decisions,
)
from vehreg.product import ProductMaster


SOURCE_ID = "98c1d7de-79db-4581-b332-69abe657a532"
TRIM_ID = "jaecoo.jaecoo_5_ev.j5.trim.max_plus_bev"
SNAPSHOT_DATE = "2026-09-08"


def raw_row(**changes):
    row = {
        "source_id": SOURCE_ID,
        "source_url": f"https://car.ecosticker.go.th/landing-page/detail/{SOURCE_ID}",
        "brand_raw": "JAECOO",
        "model_raw": "5 EV MAX+",
        "price_thb": 699000,
        "importer_raw": "บริษัท โอโมดา แอนด์ เจคู (ประเทศไทย) จำกัด",
        "list_page": 1,
        # As harvested: the ECO detail page is what says BEV, 235/55R18, 4380mm.
        "detail": {
            "cartype_name": "BEV",
            "car_length": "4380",
            "car_width": "1860",
            "car_height": "1650",
            "car_seats": "5",
            "total_weight": "1645",
            "wheel_size": "235/55R18",
            "battery_type": "Lithium iron phosphate (LFP)",
            "factory": "OMODA & JAECOO MANUFACTURING (THAILAND) CO., LTD.",
        },
        "detail_status": "available",
    }
    row.update(changes)
    return row


def write_jsonl(path, rows):
    contents = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)
    if path.suffix == ".gz":
        path.write_bytes(gzip.compress(contents.encode("utf-8"), mtime=0))
    else:
        path.write_text(contents, encoding="utf-8")


@pytest.fixture
def local_data(tmp_path):
    shutil.copytree(DATA_DIR / "2026", tmp_path / "2026")
    shutil.rmtree(tmp_path / "2026/ingest", ignore_errors=True)
    return tmp_path


def test_normalizer_lands_jaecoo_on_its_own_brand_without_a_collision():
    """The JAECOO 5 used to exist twice, so this row could not be matched.

    One nameplate under one brand is what makes the match unambiguous; the
    duplicate under CHERY is gone and the row now resolves on its own.
    """
    catalog = Catalog.load(year=2026)
    row = normalize_inventory([raw_row()], catalog, "2026-09-08")[0]
    assert row["brand_candidates"] == ["jaecoo"]
    assert {candidate["model_id"] for candidate in row["model_candidates"]} == {
        "jaecoo.jaecoo_5_ev",
    }
    assert row["matched_model_id"] == "jaecoo.jaecoo_5_ev"
    assert "brand_alias_collision" not in row["review_reasons"]
    assert row["price_classification"] == "ECO_STICKER_PRICE"


@pytest.mark.parametrize(("label", "expected"), [
    ("SEALION 6 DM-i PREMIUM", "PHEV"),
    ("6T REEV 4WD", "REEV"),
    ("CAMRY HEV PREMIUM", "HEV"),
    ("KICKS e-POWER VL", "HEV"),
    ("MIRAI FUEL CELL", "FCEV"),
    ("COROLLA ALTIS 1.8 SPORT", None),
    # A name is not evidence of electrification either way.
    ("GLE 53 4MATIC+ 48V", "ICE"),
    ("BENTAYGA HYBRID", None),
    ("AMG GLE 53 HYBRID 4MATIC+", None),
    ("MODEL 3 EV LONG RANGE", None),
])
def test_powertrain_inference_requires_a_decisive_label(label, expected):
    assert infer_powertrain(label)[0] == expected


@pytest.mark.parametrize(("label", "engine_name", "expected"), [
    # The ECO record's own declared engine type settles all three of these,
    # and the model name would have got two of them wrong.
    ("AMG GLE 53 HYBRID 4MATIC+", "\u0e44\u0e21\u0e25\u0e4c\u0e14\u0e44\u0e2e\u0e1a\u0e23\u0e34\u0e14 (MHEV)", "ICE"),
    ("BENTAYGA HYBRID", "\u0e1b\u0e25\u0e31\u0e4a\u0e01\u0e2d\u0e34\u0e19\u0e44\u0e2e\u0e1a\u0e23\u0e34\u0e14", "PHEV"),
    ("VELLFIRE HYBRID Z PREMIER", "\u0e44\u0e2e\u0e1a\u0e23\u0e34\u0e14 (HEV)", "HEV"),
    ("RANGER WILDTRAK", "\u0e14\u0e35\u0e40\u0e0b\u0e25", "ICE"),
    ("YARIS ATIV SMART", "\u0e41\u0e01\u0e4a\u0e2a\u0e42\u0e0b\u0e25\u0e35\u0e19", "ICE"),
    # A declared plug-in whose name says REEV keeps the range-extender label.
    ("6T REEV 4WD ULTRA", "\u0e1b\u0e25\u0e31\u0e4a\u0e01\u0e2d\u0e34\u0e19\u0e44\u0e2e\u0e1a\u0e23\u0e34\u0e14", "REEV"),
])
def test_declared_engine_type_outranks_the_model_name(label, engine_name, expected):
    powertrain, basis = infer_powertrain(label, {"engine_name": engine_name})
    assert (powertrain, basis) == (expected, "detail_engine_name")


def test_blank_engine_name_falls_back_to_the_coarse_eco_class():
    assert infer_powertrain("ATTO 3 EXTENDED RANGE",
                            {"engine_name": "", "cartype_name": "BEV"}) == (
        "BEV", "detail_cartype")


@pytest.mark.parametrize("changes", [
    {"source_id": "not-a-uuid"},
    {"price_thb": 1.5},
    {"price_thb": True},
    {"price_thb": 0},
    {"brand_raw": ""},
    {"list_page": 0},
    {"extra": "silent schema drift"},
])
def test_raw_inventory_rejects_malformed_rows(tmp_path, changes):
    path = tmp_path / "raw.jsonl"
    write_jsonl(path, [raw_row(**changes)])
    with pytest.raises(ECOIngestError):
        load_raw_inventory(path)


def test_raw_inventory_rejects_duplicate_ids_and_page_gaps(tmp_path):
    duplicate = tmp_path / "duplicate.jsonl"
    write_jsonl(duplicate, [raw_row(), raw_row()])
    with pytest.raises(ECOIngestError, match="duplicate source_id"):
        load_raw_inventory(duplicate)
    gap = tmp_path / "gap.jsonl"
    write_jsonl(gap, [raw_row(list_page=2)])
    with pytest.raises(ECOIngestError, match="page sequence has gaps"):
        load_raw_inventory(gap)


def test_snapshot_is_dry_run_then_reproducible_write(local_data, tmp_path):
    raw = tmp_path / "raw.jsonl"
    write_jsonl(raw, [raw_row()])
    before = [row.as_row() for row in Catalog.load(local_data, 2026).iter_resolved()]
    result = build_snapshot(raw, data_dir=local_data, year=2026,
                            snapshot_date="2026-09-08", expected_records=1)
    assert not result["written"]
    assert not Path(result["path"]).exists()
    written = build_snapshot(raw, data_dir=local_data, year=2026,
                             snapshot_date="2026-09-08", expected_records=1,
                             write=True)
    assert written["written"]
    root = Path(written["path"])
    assert {path.name for path in root.iterdir()} == {
        "manifest.json", "normalized.jsonl.gz", "raw.jsonl.gz", "review_queue.jsonl.gz",
    }
    assert load_normalized_snapshot(
        local_data, 2026, snapshot_date="2026-09-08")[0]["source_id"] == SOURCE_ID
    repeated = build_snapshot(raw, data_dir=local_data, year=2026,
                              snapshot_date="2026-09-08", expected_records=1,
                              write=True)
    assert repeated["written"] is False
    assert repeated["unchanged"] is True
    write_jsonl(raw, [raw_row(price_thb=700000)])
    with pytest.raises(ECOIngestError, match="immutable"):
        build_snapshot(raw, data_dir=local_data, year=2026,
                       snapshot_date="2026-09-08", expected_records=1, write=True)
    after = [row.as_row() for row in Catalog.load(local_data, 2026).iter_resolved()]
    assert after == before


def test_review_decisions_validate_against_snapshot_and_exact_powertrain(local_data, tmp_path):
    raw = tmp_path / "raw.jsonl"
    write_jsonl(raw, [raw_row()])
    build_snapshot(raw, data_dir=local_data, year=2026,
                   snapshot_date="2026-09-08", write=True)
    decision = tmp_path / "decision.json"
    decision.write_text(json.dumps({
        "schema_version": 1,
        "snapshot_date": "2026-09-08",
        "decisions": [{
            "source_id": SOURCE_ID,
            "action": "accept_existing_trim",
            "trim_id": TRIM_ID,
            "reviewer": "vehicle-master-owner",
            "reviewed_at": "2026-09-08",
            "notes": "JAECOO 5 reference implementation",
        }],
    }), encoding="utf-8")
    assert not save_decisions(decision, data_dir=local_data, year=2026,
                              snapshot_date="2026-09-08")["written"]
    result = save_decisions(decision, data_dir=local_data, year=2026,
                            snapshot_date="2026-09-08", write=True)
    assert result["accepted"] == 1
    status = ingestion_status(local_data, 2026, snapshot_date="2026-09-08")
    assert status["records"] == 1
    assert status["accepted_existing_trims"] == 1
    assert status["accepted_with_spec_evidence"] == 1
    assert status["accepted_with_tyre_evidence"] == 1
    assert status["source_ids_attached_to_market_trims"] == 1
    assert status["registration_database_touched"] is False


def test_review_cannot_force_powertrain_conflict(local_data, tmp_path):
    raw = tmp_path / "raw.jsonl"
    write_jsonl(raw, [raw_row(model_raw="5 EV MAX+")])
    build_snapshot(raw, data_dir=local_data, year=2026,
                   snapshot_date="2026-09-08", write=True)
    decision = tmp_path / "bad.json"
    decision.write_text(json.dumps({
        "schema_version": 1,
        "snapshot_date": "2026-09-08",
        "decisions": [{
            "source_id": SOURCE_ID,
            "action": "accept_existing_trim",
            "trim_id": "jaecoo.jaecoo_5_ev.j5.trim.max_plus_bev",
            "reviewer": "owner",
            "reviewed_at": "2026-09-08",
        }],
    }), encoding="utf-8")
    rows = load_normalized_snapshot(local_data, 2026, snapshot_date="2026-09-08")
    rows[0]["powertrain_candidate"] = "PHEV"
    snapshot = Path(local_data) / "2026/ingest/ecosticker/snapshots/2026-09-08/normalized.jsonl.gz"
    write_jsonl(snapshot, rows)
    with pytest.raises(ECOIngestError, match="powertrain conflict"):
        save_decisions(decision, data_dir=local_data, year=2026,
                       snapshot_date="2026-09-08")


def test_cli_ecosticker_workflow_never_creates_registration_db(local_data, tmp_path, capsys):
    raw = tmp_path / "raw.jsonl"
    write_jsonl(raw, [raw_row()])
    db = tmp_path / "must-not-exist.sqlite3"
    assert main([
        "--db", str(db), "--data-dir", str(local_data), "market", "eco-build",
        str(raw), "--snapshot-date", "2026-09-08", "--expected-records", "1",
        "--write",
    ]) == 0
    assert json.loads(capsys.readouterr().out)["records"] == 1
    assert main([
        "--db", str(db), "--data-dir", str(local_data), "market", "eco-status",
        "--snapshot-date", "2026-09-08",
    ]) == 0
    assert json.loads(capsys.readouterr().out)["registration_database_touched"] is False
    assert not db.exists()


def test_committed_1640_record_snapshot_and_reference_review_are_self_consistent():
    root = DATA_DIR / "2026/ingest/ecosticker/snapshots/2026-09-08"
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    raw_bytes = gzip.decompress((root / "raw.jsonl.gz").read_bytes())
    normalized_bytes = gzip.decompress((root / "normalized.jsonl.gz").read_bytes())
    raw = [json.loads(line) for line in raw_bytes.splitlines()]
    normalized = [json.loads(line) for line in normalized_bytes.splitlines()]
    assert manifest["records"] == len(raw) == len(normalized) == 1640
    assert manifest["unique_source_ids"] == len({row["source_id"] for row in raw}) == 1640
    assert manifest["pages"] == 137
    assert sum(row["list_page"] == 137 for row in raw) == 8
    assert hashlib.sha256(raw_bytes).hexdigest() == manifest["raw_sha256"]
    assert hashlib.sha256(normalized_bytes).hexdigest() == manifest["normalized_sha256"]
    assert manifest["counts_by_review_status"] == {
        "needs_model_review": 274,
        "needs_powertrain_review": 31,
        "ready_for_review": 1335,
    }
    assert manifest["records_with_unique_model"] == 1369
    assert manifest["records_with_unique_generation"] == 1366
    assert manifest["catalog_models_matched"] == 263
    # Every listed record now carries its own detail page, so the powertrain
    # comes from the manufacturer's declaration rather than the model name.
    assert manifest["coverage"]["detail_pages"] == "1640/1640"
    assert manifest["coverage"]["dimensions"] == 1640
    assert manifest["coverage"]["wheel_size"] == 1384
    assert manifest["powertrain_basis"]["explicit_label"] == 2
    assert manifest["counts_by_review_reason"].get("brand_alias_collision") is None
    status = ingestion_status(snapshot_date="2026-09-08")
    # Three reference mappings exist, and all three are still proposals.
    assert status["accepted_existing_trims"] == 0
    assert status["agent_proposed_existing_trims"] == 3
    # Staging all 1,640 public prices does not append them to the retail ledger.
    assert ProductMaster.load().prices.coverage()["eco_sticker_price_records"] == 3
    assert len(list(Catalog.load(year=2026).iter_resolved())) == 367


def _decision(**changes):
    row = {
        "source_id": SOURCE_ID,
        "action": "accept_existing_trim",
        "trim_id": TRIM_ID,
        "reviewer": "agent-proposed",
        "reviewed_at": "2026-09-08",
        "notes": "",
    }
    row.update(changes)
    return {"schema_version": 1, "snapshot_date": "2026-09-08", "decisions": [row]}


def test_a_decision_this_code_wrote_is_marked_as_a_proposal():
    catalog = Catalog.load(year=2026)
    records = normalize_inventory([raw_row()], catalog, "2026-09-08")
    for row in records:
        row["powertrain_candidate"] = catalog.trims[TRIM_ID].powertrain.value
    agent = validate_decisions(_decision(), records, catalog)[0]
    assert (agent["reviewer"], agent["origin"]) == ("agent-proposed", "agent")
    human = validate_decisions(
        _decision(reviewer="vehicle-master-owner"), records, catalog)[0]
    assert human["origin"] == "human"


def test_committed_reference_decisions_are_proposals_not_owner_acceptances():
    """Nothing may sign off in the owner's name on the owner's behalf."""
    status = ingestion_status(snapshot_date=SNAPSHOT_DATE)
    assert status["accepted_existing_trims"] == 0
    assert status["agent_proposed_existing_trims"] == 3
