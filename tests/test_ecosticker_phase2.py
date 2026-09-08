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
)
from vehreg.product import ProductMaster


SOURCE_ID = "98c1d7de-79db-4581-b332-69abe657a532"
TRIM_ID = "chery.jaecoo_j5.j5.trim.max_plus_bev"


def raw_row(**changes):
    row = {
        "source_id": SOURCE_ID,
        "source_url": f"https://car.ecosticker.go.th/landing-page/detail/{SOURCE_ID}",
        "brand_raw": "JAECOO",
        "model_raw": "5 EV MAX+",
        "price_thb": 699000,
        "importer_raw": "บริษัท โอโมดา แอนด์ เจคู (ประเทศไทย) จำกัด",
        "list_page": 1,
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


def test_normalizer_exposes_jaecoo_catalog_collision_instead_of_guessing():
    catalog = Catalog.load(year=2026)
    row = normalize_inventory([raw_row()], catalog, "2026-09-08")[0]
    assert row["brand_candidates"] == ["chery", "jaecoo"]
    assert {candidate["model_id"] for candidate in row["model_candidates"]} == {
        "chery.jaecoo_j5", "jaecoo.jaecoo_5_ev",
    }
    assert row["matched_model_id"] is None
    assert row["matched_generation_id"] is None
    assert row["powertrain_candidate"] == "BEV"
    assert row["review_status"] == "needs_model_review"
    assert "brand_alias_collision" in row["review_reasons"]
    assert row["price_classification"] == "ECO_STICKER_PRICE"


@pytest.mark.parametrize(("label", "expected"), [
    ("SEALION 6 DM-i PREMIUM", "PHEV"),
    ("6T REEV 4WD", "REEV"),
    ("MODEL 3 EV LONG RANGE", "BEV"),
    ("CAMRY HEV PREMIUM", "HEV"),
    ("MIRAI FUEL CELL", "FCEV"),
    ("COROLLA ALTIS 1.8 SPORT", None),
])
def test_powertrain_inference_requires_explicit_label(label, expected):
    assert infer_powertrain(label)[0] == expected


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
            "trim_id": "chery.jaecoo_j5.j5.trim.max_plus_bev",
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
    assert manifest["pages"] == 55
    assert sum(row["list_page"] == 55 for row in raw) == 20
    assert hashlib.sha256(raw_bytes).hexdigest() == manifest["raw_sha256"]
    assert hashlib.sha256(normalized_bytes).hexdigest() == manifest["normalized_sha256"]
    assert manifest["counts_by_review_status"] == {
        "needs_model_review": 286,
        "needs_powertrain_review": 1012,
        "ready_for_review": 342,
    }
    assert manifest["records_with_unique_model"] == 1357
    assert manifest["records_with_unique_generation"] == 1354
    assert manifest["catalog_models_matched"] == 260
    status = ingestion_status(snapshot_date="2026-09-08")
    assert status["accepted_existing_trims"] == 3
    assert status["accepted_with_spec_evidence"] == 3
    assert status["accepted_with_tyre_evidence"] == 3
    # Staging all 1,640 public prices does not append them to the retail ledger.
    assert ProductMaster.load().prices.coverage()["eco_sticker_price_records"] == 3
    assert len(list(Catalog.load(year=2026).iter_resolved())) == 371
