"""Review-first ECO Sticker inventory ingestion for Vehicle Master.

The public inventory is source evidence, not a product authority.  This module
normalizes a complete snapshot, proposes catalog Model/Generation matches and
trim candidates, and writes only to a staging area.  A human decision is
required before a source UUID can be attached to a MarketTrim.

Nothing in this module opens the registration database or changes analytical
Variants.  Recommended prices remain evidence and are explicitly labelled
``ECO_STICKER_PRICE``; they are never promoted to canonical list price.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import gzip
import hashlib
import json
from pathlib import Path
import re
import tempfile
from typing import Iterable, Optional

from .catalog import Catalog, DATA_DIR, DEFAULT_YEAR
from .normalize import fold, similarity, slug
from .taxonomy import Powertrain


SOURCE_NAME = "ecosticker"
SOURCE_LIST_URL = "https://car.ecosticker.go.th/landing-page"
SCHEMA_VERSION = 1
REQUIRED_RAW_FIELDS = {
    "source_id", "source_url", "brand_raw", "model_raw", "price_thb",
    "importer_raw", "list_page",
}
# The live inventory currently carries both hyphenated UUIDs and 32-character
# compact UUIDs. Preserve the source identifier exactly apart from case.
UUID_RE = re.compile(
    r"^(?:[0-9a-f]{32}|[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})$", re.I)


class ECOIngestError(ValueError):
    pass


def snapshot_dir(data_dir: Path | str, year: int, snapshot_date: str) -> Path:
    return (Path(data_dir) / str(year) / "ingest" / SOURCE_NAME /
            "snapshots" / snapshot_date)


def review_dir(data_dir: Path | str, year: int) -> Path:
    return Path(data_dir) / str(year) / "ingest" / SOURCE_NAME / "review"


def _iso_date(raw: object, field: str = "snapshot_date") -> str:
    value = str(raw or "")
    try:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise ValueError(value)
        date.fromisoformat(value)
    except ValueError as exc:
        raise ECOIngestError(f"{field} must be YYYY-MM-DD, got {value!r}") from exc
    return value


def _read_jsonl(path: Path | str) -> list[dict]:
    source = Path(path)
    if source.suffix == ".gz":
        contents = gzip.decompress(source.read_bytes()).decode("utf-8")
    else:
        contents = source.read_text(encoding="utf-8")
    rows: list[dict] = []
    for line_no, line in enumerate(contents.splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ECOIngestError(f"{source}:{line_no}: invalid JSON: {exc}") from exc
        if not isinstance(row, dict):
            raise ECOIngestError(f"{source}:{line_no}: row must be an object")
        rows.append(row)
    return rows


def load_raw_inventory(path: Path | str) -> list[dict]:
    """Load and fail-closed validate a browser-captured inventory snapshot."""
    rows = _read_jsonl(path)
    if not rows:
        raise ECOIngestError("inventory is empty")
    seen: set[str] = set()
    pages: set[int] = set()
    validated: list[dict] = []
    for position, raw in enumerate(rows, 1):
        missing = REQUIRED_RAW_FIELDS - set(raw)
        unknown = set(raw) - REQUIRED_RAW_FIELDS
        if missing or unknown:
            raise ECOIngestError(
                f"row {position}: missing={sorted(missing)} unknown={sorted(unknown)}")
        source_id = str(raw["source_id"] or "").strip().lower()
        if not UUID_RE.fullmatch(source_id):
            raise ECOIngestError(f"row {position}: invalid source_id {source_id!r}")
        if source_id in seen:
            raise ECOIngestError(f"row {position}: duplicate source_id {source_id}")
        seen.add(source_id)
        source_url = str(raw["source_url"] or "").strip()
        if not source_url.endswith("/" + source_id) or not source_url.startswith(
                "https://car.ecosticker.go.th/landing-page/detail/"):
            raise ECOIngestError(f"row {position}: source_url does not match source_id")
        price = raw["price_thb"]
        if type(price) is not int or price <= 0:
            raise ECOIngestError(f"row {position}: price_thb must be a positive integer")
        page = raw["list_page"]
        if type(page) is not int or page <= 0:
            raise ECOIngestError(f"row {position}: list_page must be a positive integer")
        brand = str(raw["brand_raw"] or "").strip()
        model = str(raw["model_raw"] or "").strip()
        importer = str(raw["importer_raw"] or "").strip()
        if not brand or not model or not importer:
            raise ECOIngestError(f"row {position}: brand/model/importer cannot be blank")
        pages.add(page)
        validated.append({
            "source_id": source_id,
            "source_url": source_url,
            "brand_raw": brand,
            "model_raw": model,
            "price_thb": price,
            "importer_raw": importer,
            "list_page": page,
        })
    if pages != set(range(1, max(pages) + 1)):
        raise ECOIngestError("inventory page sequence has gaps")
    return validated


def _brand_candidates(catalog: Catalog, raw: str) -> list[str]:
    key = fold(raw)
    exact: list[str] = []
    for brand in catalog.brands.values():
        surfaces = (brand.name_en, brand.name_th, *brand.aliases)
        if key and key in {fold(surface) for surface in surfaces if surface}:
            exact.append(brand.id)
    if exact:
        # Alias collisions are real ownership questions (for example JAECOO is
        # both a catalog brand and a Chery alias). Never resolve them by order.
        return sorted(set(exact))
    scored = []
    for brand in catalog.brands.values():
        score = max((similarity(raw, surface) for surface in
                     (brand.name_en, brand.name_th, *brand.aliases) if surface),
                    default=0.0)
        if score >= 0.92:
            scored.append((score, brand.id))
    if not scored:
        return []
    best = max(score for score, _ in scored)
    return sorted(brand_id for score, brand_id in scored if score == best)


@dataclass(frozen=True, slots=True)
class _ModelHit:
    model_id: str
    brand_id: str
    surface: str
    score: float
    method: str

    def as_dict(self, catalog: Catalog) -> dict:
        return {
            "model_id": self.model_id,
            "brand_id": self.brand_id,
            "matched_surface": self.surface,
            "score": round(self.score, 4),
            "method": self.method,
            "generation_ids": [g.id for g in catalog.generations_of(self.model_id)],
        }


def _contains_tokens(needle: str, haystack: str) -> bool:
    small, large = fold(needle).split(), fold(haystack).split()
    return bool(small) and any(large[i:i + len(small)] == small
                               for i in range(len(large) - len(small) + 1))


def _model_candidates(catalog: Catalog, brand_ids: Iterable[str], raw: str) -> list[_ModelHit]:
    hits: list[_ModelHit] = []
    for brand_id in brand_ids:
        for model in catalog.models_of(brand_id):
            surfaces = tuple(dict.fromkeys(
                surface for surface in (model.name_en, model.name_th, *model.aliases)
                if surface))
            contained = [surface for surface in surfaces if _contains_tokens(surface, raw)]
            if contained:
                surface = max(contained, key=lambda x: (len(fold(x).split()), len(fold(x))))
                hits.append(_ModelHit(model.id, brand_id, surface,
                                      min(0.99, 0.90 + 0.03 * len(fold(surface).split())),
                                      "contains"))
                continue
            surface, score = max(((surface, similarity(raw, surface))
                                  for surface in surfaces), key=lambda x: x[1])
            if score >= 0.92:
                hits.append(_ModelHit(model.id, brand_id, surface, score, "fuzzy"))
    if not hits:
        return []
    # Longest contained model surface wins within each brand, but equal-quality
    # matches across brands stay visible to review.
    contained = [hit for hit in hits if hit.method == "contains"]
    if contained:
        best_len = max(len(fold(hit.surface).split()) for hit in contained)
        return sorted((hit for hit in contained
                       if len(fold(hit.surface).split()) == best_len),
                      key=lambda hit: hit.model_id)
    best = max(hit.score for hit in hits)
    return sorted((hit for hit in hits if abs(hit.score - best) < 1e-9),
                  key=lambda hit: hit.model_id)


def infer_powertrain(label: str) -> tuple[Optional[str], str]:
    """Return only explicit source-label evidence; do not guess plain ICE."""
    value = " " + fold(label) + " "
    if any(token in value for token in (" phev ", " plug in hybrid ", " dm i ",
                                        " e hybrid ", " super hybrid ", " shs ")):
        return Powertrain.PHEV.value, "explicit_label"
    if any(token in value for token in (" reev ", " erev ")):
        return Powertrain.REEV.value, "explicit_label"
    if any(token in value for token in (" fcev ", " fuel cell ", " hydrogen ")):
        return Powertrain.FCEV.value, "explicit_label"
    if any(token in value for token in (" bev ", " electric ", " ev ")):
        return Powertrain.BEV.value, "explicit_label"
    if any(token in value for token in (" hev ", " hybrid ", " e power ")):
        return Powertrain.HEV.value, "explicit_label"
    return None, "not_explicit"


def normalize_inventory(rows: Iterable[dict], catalog: Catalog,
                        snapshot_date: str) -> list[dict]:
    observed_at = _iso_date(snapshot_date)
    normalized: list[dict] = []
    for raw in rows:
        brand_ids = _brand_candidates(catalog, raw["brand_raw"])
        model_hits = _model_candidates(catalog, brand_ids, raw["model_raw"])
        unique_models = sorted({hit.model_id for hit in model_hits})
        model_id = unique_models[0] if len(unique_models) == 1 else None
        generation_ids = ([g.id for g in catalog.generations_of(model_id)]
                          if model_id else [])
        generation_id = generation_ids[0] if len(generation_ids) == 1 else None
        powertrain, powertrain_basis = infer_powertrain(raw["model_raw"])
        reasons: list[str] = []
        if not brand_ids:
            reasons.append("brand_unmatched")
        elif len(brand_ids) > 1:
            reasons.append("brand_alias_collision")
        if not unique_models:
            reasons.append("model_unmatched")
        elif len(unique_models) > 1:
            reasons.append("model_ambiguous")
        if model_id and not generation_id:
            reasons.append("generation_ambiguous")
        if not powertrain:
            reasons.append("powertrain_not_explicit")
        if not unique_models:
            status = "needs_model_review"
        elif len(unique_models) > 1 or not generation_id:
            status = "needs_model_review"
        elif not powertrain:
            status = "needs_powertrain_review"
        else:
            status = "ready_for_review"
        normalized.append({
            "schema_version": SCHEMA_VERSION,
            "snapshot_date": observed_at,
            "source": SOURCE_NAME,
            "source_id": raw["source_id"],
            "source_url": raw["source_url"],
            "brand_raw": raw["brand_raw"],
            "model_raw": raw["model_raw"],
            "importer_raw": raw["importer_raw"],
            "recommended_price_thb": raw["price_thb"],
            "price_classification": "ECO_STICKER_PRICE",
            "list_page": raw["list_page"],
            "brand_key": fold(raw["brand_raw"]),
            "model_key": fold(raw["model_raw"]),
            "brand_candidates": brand_ids,
            "model_candidates": [hit.as_dict(catalog) for hit in model_hits],
            "matched_model_id": model_id,
            "matched_generation_id": generation_id,
            "powertrain_candidate": powertrain,
            "powertrain_basis": powertrain_basis,
            "trim_candidate": {
                "local_id": slug(raw["model_raw"] + (" " + powertrain if powertrain else "")),
                "name_raw": raw["model_raw"],
                "generation_id": generation_id,
                "powertrain": powertrain,
                "source_refs": {SOURCE_NAME: [raw["source_id"]]},
            },
            "review_status": status,
            "review_reasons": reasons,
        })
    return normalized


def _jsonl_bytes(rows: Iterable[dict]) -> bytes:
    return ("".join(json.dumps(row, ensure_ascii=False, sort_keys=True,
                               separators=(",", ":")) + "\n" for row in rows)
            .encode("utf-8"))


def _atomic_write(path: Path, contents: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(dir=path.parent, prefix=".eco-", delete=False)
    temporary = Path(handle.name)
    try:
        with handle:
            handle.write(contents)
            handle.flush()
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def build_snapshot(raw_path: Path | str, *, data_dir: Path | str = DATA_DIR,
                   year: int = DEFAULT_YEAR, snapshot_date: str,
                   expected_records: Optional[int] = None, write: bool = False) -> dict:
    """Normalize/match one complete snapshot; dry-run unless ``write`` is set."""
    raw_rows = load_raw_inventory(raw_path)
    if expected_records is not None and len(raw_rows) != expected_records:
        raise ECOIngestError(
            f"expected {expected_records} records, received {len(raw_rows)}")
    catalog = Catalog.load(data_dir, year)
    before = [row.as_row() for row in catalog.iter_resolved()]
    normalized = normalize_inventory(raw_rows, catalog, snapshot_date)
    from .homologation import ECOStickerSpecStore
    specs = ECOStickerSpecStore.load(data_dir, year, catalog=catalog)
    known_detail = {record.source_ref: record for record in specs.records.values()}
    for row in normalized:
        detail = known_detail.get(row["source_id"])
        row["detail_status"] = "available" if detail else "unavailable"
        row["spec_evidence_trim_id"] = detail.trim_id if detail else None
        row["tyre_evidence"] = detail.tire_size if detail else None
    if [row.as_row() for row in catalog.iter_resolved()] != before:
        raise ECOIngestError("ECO staging changed registration analytics")
    queue = [row for row in normalized if row["review_status"] != "ready_for_review"]
    raw_bytes = _jsonl_bytes(raw_rows)
    normalized_bytes = _jsonl_bytes(normalized)
    queue_bytes = _jsonl_bytes(queue)
    counts: dict[str, int] = {}
    reason_counts: dict[str, int] = {}
    for row in normalized:
        counts[row["review_status"]] = counts.get(row["review_status"], 0) + 1
        for reason in row["review_reasons"]:
            reason_counts[reason] = reason_counts.get(reason, 0) + 1
    root = snapshot_dir(data_dir, year, _iso_date(snapshot_date))
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "source": SOURCE_NAME,
        "source_url": SOURCE_LIST_URL,
        "snapshot_date": snapshot_date,
        "catalog_year": year,
        "records": len(raw_rows),
        "unique_source_ids": len({row["source_id"] for row in raw_rows}),
        "pages": max(row["list_page"] for row in raw_rows),
        "counts_by_review_status": dict(sorted(counts.items())),
        "counts_by_review_reason": dict(sorted(reason_counts.items())),
        "records_with_unique_model": sum(
            row["matched_model_id"] is not None for row in normalized),
        "records_with_unique_generation": sum(
            row["matched_generation_id"] is not None for row in normalized),
        "records_with_explicit_powertrain": sum(
            row["powertrain_candidate"] is not None for row in normalized),
        "catalog_models_matched": len({
            row["matched_model_id"] for row in normalized if row["matched_model_id"]}),
        "records_with_detail_evidence": sum(
            row["detail_status"] == "available" for row in normalized),
        "records_with_tyre_evidence": sum(bool(row["tyre_evidence"]) for row in normalized),
        "raw_sha256": hashlib.sha256(raw_bytes).hexdigest(),
        "normalized_sha256": hashlib.sha256(normalized_bytes).hexdigest(),
        "registration_rows_unchanged": len(before),
        "files": {
            "raw": "raw.jsonl.gz",
            "normalized": "normalized.jsonl.gz",
            "review_queue": "review_queue.jsonl.gz",
        },
        "storage_encoding": "gzip",
    }
    manifest_bytes = (json.dumps(manifest, ensure_ascii=False, indent=2,
                                 sort_keys=True) + "\n").encode("utf-8")
    if write:
        raw_stored = gzip.compress(raw_bytes, compresslevel=9, mtime=0)
        normalized_stored = gzip.compress(normalized_bytes, compresslevel=9, mtime=0)
        queue_stored = gzip.compress(queue_bytes, compresslevel=9, mtime=0)
        expected_files = {
            root / "raw.jsonl.gz": raw_stored,
            root / "normalized.jsonl.gz": normalized_stored,
            root / "review_queue.jsonl.gz": queue_stored,
            root / "manifest.json": manifest_bytes,
        }
        existing = [path for path in expected_files if path.exists()]
        if existing:
            if len(existing) != len(expected_files) or any(
                    path.read_bytes() != contents
                    for path, contents in expected_files.items() if path.exists()):
                raise ECOIngestError(
                    f"snapshot {snapshot_date} is immutable and already differs on disk")
            return {"written": False, "unchanged": True, "path": str(root), **manifest}
        _atomic_write(root / "raw.jsonl.gz", raw_stored)
        _atomic_write(root / "normalized.jsonl.gz", normalized_stored)
        _atomic_write(root / "review_queue.jsonl.gz", queue_stored)
        _atomic_write(root / "manifest.json", manifest_bytes)
    return {"written": write, "path": str(root), **manifest}


def load_normalized_snapshot(data_dir: Path | str = DATA_DIR,
                             year: int = DEFAULT_YEAR, *,
                             snapshot_date: str) -> list[dict]:
    root = snapshot_dir(data_dir, year, _iso_date(snapshot_date))
    rows = _read_jsonl(root / "normalized.jsonl.gz")
    ids = [row.get("source_id") for row in rows]
    if len(ids) != len(set(ids)):
        raise ECOIngestError("normalized snapshot contains duplicate source IDs")
    return rows


def validate_decisions(payload: dict, records: Iterable[dict], catalog: Catalog) -> list[dict]:
    if not isinstance(payload, dict) or set(payload) != {
            "schema_version", "snapshot_date", "decisions"}:
        raise ECOIngestError("decisions require schema_version, snapshot_date and decisions")
    if payload["schema_version"] != SCHEMA_VERSION:
        raise ECOIngestError("unsupported decision schema_version")
    _iso_date(payload["snapshot_date"])
    if not isinstance(payload["decisions"], list):
        raise ECOIngestError("decisions must be an array")
    by_source = {row["source_id"]: row for row in records}
    seen: set[str] = set()
    checked: list[dict] = []
    allowed = {"source_id", "action", "trim_id", "reviewer", "reviewed_at", "notes"}
    for position, raw in enumerate(payload["decisions"], 1):
        if not isinstance(raw, dict) or set(raw) - allowed:
            raise ECOIngestError(f"decision {position}: invalid fields")
        source_id = str(raw.get("source_id") or "").strip().lower()
        if source_id not in by_source:
            raise ECOIngestError(f"decision {position}: unknown source_id {source_id!r}")
        if source_id in seen:
            raise ECOIngestError(f"decision {position}: duplicate source_id {source_id}")
        seen.add(source_id)
        action = str(raw.get("action") or "").strip()
        if action not in {"accept_existing_trim", "reject", "defer"}:
            raise ECOIngestError(f"decision {position}: invalid action {action!r}")
        trim_id = str(raw.get("trim_id") or "").strip()
        if action == "accept_existing_trim":
            if trim_id not in catalog.trims:
                raise ECOIngestError(f"decision {position}: unknown trim_id {trim_id!r}")
            if catalog.trims[trim_id].powertrain.value != by_source[source_id]["powertrain_candidate"]:
                raise ECOIngestError(
                    f"decision {position}: candidate/trim powertrain conflict")
        elif trim_id:
            raise ECOIngestError(f"decision {position}: trim_id only allowed for acceptance")
        reviewer = str(raw.get("reviewer") or "").strip()
        reviewed_at = _iso_date(raw.get("reviewed_at"), "reviewed_at")
        if not reviewer:
            raise ECOIngestError(f"decision {position}: reviewer is required")
        checked.append({
            "source_id": source_id,
            "action": action,
            "trim_id": trim_id,
            "reviewer": reviewer,
            "reviewed_at": reviewed_at,
            "notes": str(raw.get("notes") or "").strip(),
        })
    return checked


def save_decisions(path: Path | str, *, data_dir: Path | str = DATA_DIR,
                   year: int = DEFAULT_YEAR, snapshot_date: str,
                   write: bool = False) -> dict:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("snapshot_date") != _iso_date(snapshot_date):
        raise ECOIngestError("decision snapshot_date does not match command")
    records = load_normalized_snapshot(data_dir, year, snapshot_date=snapshot_date)
    catalog = Catalog.load(data_dir, year)
    decisions = validate_decisions(payload, records, catalog)
    canonical = {
        "schema_version": SCHEMA_VERSION,
        "snapshot_date": snapshot_date,
        "decisions": decisions,
    }
    destination = review_dir(data_dir, year) / f"{snapshot_date}.json"
    if write:
        _atomic_write(destination, (json.dumps(canonical, ensure_ascii=False,
                                              indent=2, sort_keys=True) + "\n").encode("utf-8"))
    return {"written": write, "path": str(destination), "decisions": len(decisions),
            "accepted": sum(d["action"] == "accept_existing_trim" for d in decisions),
            "rejected": sum(d["action"] == "reject" for d in decisions),
            "deferred": sum(d["action"] == "defer" for d in decisions)}


def ingestion_status(data_dir: Path | str = DATA_DIR, year: int = DEFAULT_YEAR,
                     *, snapshot_date: str) -> dict:
    records = load_normalized_snapshot(data_dir, year, snapshot_date=snapshot_date)
    catalog = Catalog.load(data_dir, year)
    decisions_path = review_dir(data_dir, year) / f"{snapshot_date}.json"
    decisions: list[dict] = []
    if decisions_path.exists():
        payload = json.loads(decisions_path.read_text(encoding="utf-8"))
        decisions = validate_decisions(payload, records, catalog)
    accepted = {d["source_id"]: d for d in decisions
                if d["action"] == "accept_existing_trim"}
    from .homologation import ECOStickerSpecStore
    specs = ECOStickerSpecStore.load(data_dir, year, catalog=catalog)
    spec_by_source = {row.source_ref: row for row in specs.records.values()}
    accepted_with_spec = sum(source_id in spec_by_source for source_id in accepted)
    accepted_with_tyre = sum(
        source_id in spec_by_source and bool(spec_by_source[source_id].tire_size)
        for source_id in accepted)
    attached_refs = {
        ref for trim in catalog.trims.values()
        for ref in trim.source_refs.get(SOURCE_NAME, ())
    }
    counts: dict[str, int] = {}
    reason_counts: dict[str, int] = {}
    for row in records:
        counts[row["review_status"]] = counts.get(row["review_status"], 0) + 1
        for reason in row["review_reasons"]:
            reason_counts[reason] = reason_counts.get(reason, 0) + 1
    return {
        "snapshot_date": snapshot_date,
        "records": len(records),
        "unique_source_ids": len({row["source_id"] for row in records}),
        "counts_by_review_status": dict(sorted(counts.items())),
        "counts_by_review_reason": dict(sorted(reason_counts.items())),
        "records_with_unique_model": sum(
            row["matched_model_id"] is not None for row in records),
        "records_with_unique_generation": sum(
            row["matched_generation_id"] is not None for row in records),
        "records_with_explicit_powertrain": sum(
            row["powertrain_candidate"] is not None for row in records),
        "catalog_models_matched": len({
            row["matched_model_id"] for row in records if row["matched_model_id"]}),
        "decisions": len(decisions),
        "accepted_existing_trims": len(accepted),
        "accepted_with_spec_evidence": accepted_with_spec,
        "accepted_with_tyre_evidence": accepted_with_tyre,
        "source_ids_attached_to_market_trims": len(
            attached_refs & {row["source_id"] for row in records}),
        "unreviewed": len(records) - len(decisions),
        "registration_database_touched": False,
    }
