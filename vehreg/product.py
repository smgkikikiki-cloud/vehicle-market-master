"""Vehicle Master product API. No database connection or registration writes.

Use ProductMaster for joined retail specs/prices and the two authoring functions
for validated, atomic, single-file changes. JSON/Git remains the source of truth.
"""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from dataclasses import fields
from datetime import date, timedelta
import json
import os
from pathlib import Path
import tempfile

from .catalog import Catalog, CatalogError, DATA_DIR, DEFAULT_YEAR, year_dir
from .entities import MarketTrim, to_jsonable
from .homologation import ECOStickerSpecStore
from .normalize import slug
from .pricing import PriceLedger, _iso_date, campaign_dir, price_dir


class ProductMaster:
    def __init__(self, catalog: Catalog, prices: PriceLedger,
                 eco: ECOStickerSpecStore):
        self.catalog, self.prices, self.eco = catalog, prices, eco
        if catalog.year != prices.year or catalog.year != eco.year:
            raise CatalogError("product stores must use the same catalog year")

    @classmethod
    def load(cls, data_dir=DATA_DIR, year=DEFAULT_YEAR):
        catalog = Catalog.load(data_dir, year)
        return cls(catalog, PriceLedger.load(data_dir, year=year, catalog=catalog),
                   ECOStickerSpecStore.load(data_dir, year, catalog=catalog))

    def validate(self):
        return (self.catalog.validate() + self.prices.validate()
                + self.eco.validate_against_catalog(self.catalog))

    def detail(self, trim_id: str, *, as_of: date | None = None):
        if trim_id not in self.catalog.trims:
            raise CatalogError(f"unknown trim_id {trim_id!r}")
        trim = self.catalog.trims[trim_id]
        specs = to_jsonable(trim)
        # Legacy input is never a fallback for canonical retail price.
        specs.pop("price_thb", None)
        current = self.prices.current_list_price(trim_id, as_of=as_of)
        eco = self.eco.get(trim_id)
        return {
            "catalog_year": self.catalog.year,
            "price_as_of": (as_of or date.today()).isoformat(),
            "model_id": self.catalog.model_for_trim(trim_id).id,
            "model": self.catalog.model_for_trim(trim_id).name_en,
            "brand": self.catalog.brand_for_trim(trim_id).name_en,
            "specs": specs,
            "current_list_price": to_jsonable(current) if current else None,
            "price_history": [to_jsonable(r) for r in self.prices.records_for(trim_id)],
            "ecosticker_evidence": to_jsonable(eco) if eco else None,
        }

    def rows(self, *, model_id=None, powertrain=None, as_of=None):
        if model_id is not None and model_id not in self.catalog.models:
            raise CatalogError(f"unknown model_id {model_id!r}")
        return [self.detail(t.id, as_of=as_of)
                for t in sorted(self.catalog.trims.values(), key=lambda t: t.id)
                if (model_id is None or self.catalog.model_for_trim(t.id).id == model_id)
                and (powertrain is None or t.powertrain.value == powertrain)]

    def coverage(self, *, as_of=None):
        trims = list(self.catalog.trims.values())
        return {
            "catalog_year": self.catalog.year,
            "models": len(self.catalog.models),
            "models_with_market_trims": len({self.catalog.model_for_trim(t.id).id for t in trims}),
            **self.catalog.trim_coverage(),
            "with_front_and_rear_tyres": sum(bool(t.tire_front and t.tire_rear) for t in trims),
            "with_basic_specs": sum(bool(t.seats and t.transmission and
                t.drivetrain.value != "UNKNOWN" and
                (t.battery_kwh if t.powertrain.value == "BEV" else t.engine_cc)) for t in trims),
            "with_source_refs": sum(bool(t.source_refs) for t in trims),
            "legacy_embedded_prices": sum(t.price_thb is not None for t in trims),
            "prices": self.prices.coverage(as_of=as_of),
            "ecosticker": self.eco.coverage(),
        }


@contextmanager
def _writer_lock(data_dir, year):
    """Fail fast on concurrent product writers; always release after failure."""
    path = Path(data_dir) / str(year) / ".product-write.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise CatalogError("another product writer holds the lock") from exc
    try:
        os.close(descriptor)
        yield
    finally:
        path.unlink()


def _write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=".product-", delete=False)
    temporary = Path(handle.name)
    try:
        with handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def import_trims(data_dir, year, payload, *, write=False):
    """Upsert full trim objects for ONE existing generation, preserving siblings.

    Explicit local IDs are mandatory. Reusing an existing ID with a different
    powertrain is rejected. New prices must go through append_prices instead.
    Dry run is the default; both paths execute identical cross-store validation.
    """
    with _writer_lock(data_dir, year):
        master = ProductMaster.load(data_dir, year)
        if not isinstance(payload, dict) or set(payload) != {"generation_id", "trims"}:
            raise CatalogError("expected generation_id and trims")
        gen_id = payload["generation_id"]
        generation = master.catalog.generations.get(gen_id)
        if generation is None:
            raise CatalogError(f"unknown generation_id {gen_id!r}")
        if not isinstance(payload["trims"], list) or not payload["trims"]:
            raise CatalogError("trims must be a nonempty array")
        model = master.catalog.models[generation.model_id]
        # Read the original JSON: never round-trip unrelated analytical fields.
        paths = [p for p in year_dir(data_dir, year).glob("*.json")
                 if json.loads(p.read_text(encoding="utf-8"))["brand"]["id"] == model.brand_id]
        if len(paths) != 1:
            raise CatalogError("expected exactly one brand file")
        path = paths[0]
        authored = json.loads(path.read_text(encoding="utf-8"))
        updated = deepcopy(authored)
        raw_model = next(m for m in updated["models"]
                         if slug(m.get("id") or m["name_en"]) == model.id.split(".", 1)[1])
        raw_gen = next(g for g in raw_model["generations"]
                       if slug(g.get("code") or g.get("id") or "gen1") == gen_id.rsplit(".", 1)[1])
        allowed = {f.name for f in fields(MarketTrim)} - {"generation_id", "price_thb"}
        allowed.add("variant")
        seen = set()
        for raw in payload["trims"]:
            if not isinstance(raw, dict):
                raise CatalogError("trim must be an object")
            unknown = set(raw) - allowed
            if unknown:
                raise CatalogError(f"unknown/forbidden trim fields: {sorted(unknown)}; prices belong in PriceLedger")
            local_id = raw.get("id")
            if not isinstance(local_id, str) or not local_id or slug(local_id) != local_id:
                raise CatalogError("trim requires an explicit canonical local id")
            if local_id in seen:
                raise CatalogError(f"duplicate trim id {local_id}")
            seen.add(local_id)
            if not isinstance(raw.get("source_refs"), dict) or not raw["source_refs"]:
                raise CatalogError(f"{local_id}: source_refs required for authored product data")
            for refs in raw["source_refs"].values():
                if not isinstance(refs, (str, list)) or (isinstance(refs, list)
                        and not all(isinstance(ref, str) for ref in refs)):
                    raise CatalogError(f"{local_id}: source_refs values must be strings or string arrays")
            for field_name in ("name", "engine_code", "transmission", "tire_front",
                               "tire_rear", "wheel_front", "wheel_rear", "notes"):
                if field_name in raw and not isinstance(raw[field_name], str):
                    raise CatalogError(f"{local_id}: {field_name} must be text")
            full_id = f"{gen_id}.trim.{local_id}"
            existing = master.catalog.trims.get(full_id)
            if existing and raw.get("powertrain") != existing.powertrain.value:
                raise CatalogError(f"{full_id}: powertrain identity cannot change; create a new trim")
            siblings = raw_gen.setdefault("trims", [])
            for i, sibling in enumerate(siblings):
                sibling_id = slug(sibling.get("id") or f"{sibling['name']} {sibling['powertrain']}")
                if sibling_id == local_id:
                    siblings[i] = deepcopy(raw)
                    break
            else:
                siblings.append(deepcopy(raw))
        probe = Catalog(year)
        for source_path in sorted(year_dir(data_dir, year).glob("*.json")):
            probe.add_brand_payload(updated if source_path == path else
                json.loads(source_path.read_text(encoding="utf-8")), source=str(source_path))
        probe.build_indexes()
        master.prices.catalog = probe
        checked = ProductMaster(probe, master.prices, master.eco)
        problems = checked.validate()
        if problems:
            raise CatalogError("; ".join(problems))
        for local_id in seen:
            if not probe.trims[f"{gen_id}.trim.{local_id}"].source_refs:
                raise CatalogError(f"{local_id}: source_refs must contain nonempty references")
        if [r.as_row() for r in master.catalog.iter_resolved()] != [r.as_row() for r in probe.iter_resolved()]:
            raise CatalogError("product import would change registration classification")
        changed = updated != authored
        if write and changed:
            _write_json(path, updated)
        return {"written": bool(write and changed), "changed": changed,
                "path": str(path), "trim_ids": [f"{gen_id}.trim.{i}" for i in sorted(seen)]}


def append_prices(data_dir, year, payload, *, write=False):
    """Validate and append observations idempotently; never erase history."""
    with _writer_lock(data_dir, year):
        master = ProductMaster.load(data_dir, year)
        before = len(master.prices.records)
        master.prices.add_payload(payload)
        problems = master.prices.validate()
        if problems:
            raise CatalogError("; ".join(problems))
        added = master.prices.records[before:]
        for record in added:
            if not record.source or not record.source_ref or not record.observed_at:
                raise CatalogError("new price observations require source, source_ref and observed_at")
        path = price_dir(data_dir, year) / "observations.json"
        current = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"prices": []}
        current["prices"].extend(to_jsonable(r) for r in added)
        if write and added:
            _write_json(path, current)
        return {"written": bool(write and added), "added": len(added), "path": str(path)}


# --------------------------------------------------------------------------
# Manual price maintenance
# --------------------------------------------------------------------------
#
# append_prices only ever adds. These three close the loop for a person who has
# to fix something, without ever erasing what was published:
#
#   supersede  the price changed      -> the old row is given an end date
#   retract    the row was wrong      -> the old row stops counting, and says why
#   close      the price simply ended -> an end date, no replacement
#
# Every one of them demands a reason and a reviewer, and none deletes a row.

def _price_files(data_dir, year):
    folder = price_dir(data_dir, year)
    return sorted(folder.glob("*.json")) if folder.is_dir() else []


def _matches(row, *, trim_id, price_type, campaign_id=None, option_id=None):
    if row.get("trim_id") != trim_id or row.get("price_type") != price_type:
        return False
    if campaign_id is not None and (row.get("campaign_id") or None) != campaign_id:
        return False
    if option_id is not None and (row.get("option_id") or None) != option_id:
        return False
    return not row.get("retracted_at")


def _live_on(row, when):
    start = row.get("effective_from") or row.get("observed_at")
    if start and start > when:
        return False
    end = row.get("effective_to")
    return not (end and end < when)


def find_price_rows(data_dir, year, *, trim_id, price_type,
                    campaign_id=None, option_id=None, as_of=None):
    """Every stored row for one price, with the file and index that holds it."""
    when = (as_of or date.today()).isoformat()
    found = []
    for path in _price_files(data_dir, year):
        payload = json.loads(path.read_text(encoding="utf-8"))
        for index, row in enumerate(payload.get("prices", [])):
            if _matches(row, trim_id=trim_id, price_type=price_type,
                        campaign_id=campaign_id, option_id=option_id):
                found.append({"path": path, "index": index, "row": row,
                              "live": _live_on(row, when)})
    return found


def _one_live_row(data_dir, year, *, trim_id, price_type, campaign_id, option_id,
                  as_of):
    rows = [r for r in find_price_rows(
        data_dir, year, trim_id=trim_id, price_type=price_type,
        campaign_id=campaign_id, option_id=option_id, as_of=as_of) if r["live"]]
    if not rows:
        raise CatalogError(
            f"{trim_id}: no live {price_type} to change on "
            f"{(as_of or date.today()).isoformat()}")
    if len(rows) > 1:
        amounts = ", ".join(f"{r['row']['amount_thb']:,}" for r in rows)
        raise CatalogError(
            f"{trim_id}: {len(rows)} live {price_type} rows ({amounts}); "
            "name the campaign/option, or fix the overlap first")
    return rows[0]


def _apply(edits, *, write):
    """Write each touched file once, atomically, after re-validating the ledger."""
    by_path = {}
    for edit in edits:
        by_path.setdefault(edit["path"], json.loads(
            edit["path"].read_text(encoding="utf-8")))
    for edit in edits:
        payload = by_path[edit["path"]]
        if edit.get("index") is not None:
            payload["prices"][edit["index"]].update(edit["changes"])
        else:
            payload["prices"].append(edit["changes"])
    if write:
        for path, payload in by_path.items():
            _write_json(path, payload)
    return sorted(str(p) for p in by_path)


def _revalidate(data_dir, year):
    problems = ProductMaster.load(data_dir, year).validate()
    if problems:
        raise CatalogError("; ".join(problems))


def _day_before(day: str) -> str:
    return (date.fromisoformat(day) - timedelta(days=1)).isoformat()


def correct_price(data_dir, year, *, trim_id, price_type, amount_thb,
                  reason, reviewer, mode="supersede", effective_from=None,
                  campaign_id=None, option_id=None, source="", source_ref="",
                  reference_price_thb=None, as_of=None, write=False):
    """Replace the live price for one trim, keeping the old row readable.

    ``mode="supersede"`` means the price changed: the old row is given an end
    date and stays true of the period it covered.  ``mode="retract"`` means the
    old row was wrong and was never true, so it is marked retracted with its
    reason rather than being given a history it did not have.
    """
    if mode not in {"supersede", "retract"}:
        raise CatalogError(f"unknown mode {mode!r}")
    if not reason or not reviewer:
        raise CatalogError("a correction requires both a reason and a reviewer")
    today = (as_of or date.today()).isoformat()
    starts = effective_from or today

    with _writer_lock(data_dir, year):
        target = _one_live_row(data_dir, year, trim_id=trim_id,
                               price_type=price_type, campaign_id=campaign_id,
                               option_id=option_id, as_of=as_of)
        old = target["row"]
        if old["amount_thb"] == amount_thb and mode == "supersede":
            return {"written": False, "changed": False,
                    "note": "the live price already says that"}
        old_start = old.get("effective_from") or old.get("observed_at")
        if mode == "supersede" and old_start and old_start >= starts:
            raise CatalogError(
                f"{trim_id}: the live price starts {old_start}, so it cannot end "
                f"before {starts}; use --mode retract if it was simply wrong")
        closing = ({"effective_to": _day_before(starts)} if mode == "supersede"
                   else {"retracted_at": today, "retraction_reason": reason})
        closing["reviewed_by"] = reviewer
        replacement = {
            "trim_id": trim_id, "amount_thb": amount_thb,
            "price_type": price_type, "effective_from": starts,
            "observed_at": today, "source": source or old.get("source", ""),
            "source_ref": source_ref or old.get("source_ref", ""),
            "notes": reason, "reviewed_by": reviewer,
        }
        for name, value in (("campaign_id", campaign_id), ("option_id", option_id),
                            ("reference_price_thb", reference_price_thb)):
            if value is not None:
                replacement[name] = value
        edits = [{"path": target["path"], "index": target["index"], "changes": closing},
                 {"path": price_dir(data_dir, year) / "observations.json",
                  "index": None, "changes": replacement}]
        paths = _apply(edits, write=write)
        if write:
            _revalidate(data_dir, year)
        return {"written": write, "changed": True, "mode": mode,
                "was": old["amount_thb"], "now": amount_thb, "paths": paths}


def close_price(data_dir, year, *, trim_id, price_type, ends, reason, reviewer,
                campaign_id=None, option_id=None, as_of=None, write=False):
    """End a price with no replacement -- the trim stopped being sold at it."""
    if not reason or not reviewer:
        raise CatalogError("closing a price requires both a reason and a reviewer")
    _iso_date(ends, "ends")
    with _writer_lock(data_dir, year):
        target = _one_live_row(data_dir, year, trim_id=trim_id,
                               price_type=price_type, campaign_id=campaign_id,
                               option_id=option_id, as_of=as_of)
        start = target["row"].get("effective_from") or target["row"].get("observed_at")
        if start and start > ends:
            raise CatalogError(
                f"{trim_id}: cannot end on {ends}, the price starts {start}")
        paths = _apply([{"path": target["path"], "index": target["index"],
                         "changes": {"effective_to": ends, "reviewed_by": reviewer,
                                     "notes": reason}}], write=write)
        if write:
            _revalidate(data_dir, year)
        return {"written": write, "changed": True, "ends": ends, "paths": paths}


def save_campaign(data_dir, year, payload, *, write=False):
    """Upsert one campaign into its brand file, options and all.

    Campaigns are small and change as a unit -- an option is added, a date is
    filled in when the brand finally publishes one -- so the whole campaign is
    replaced rather than patched field by field. Prices are untouched: closing a
    campaign hides its offers through the resolver, it does not delete them.
    """
    with _writer_lock(data_dir, year):
        if not isinstance(payload, dict):
            raise CatalogError("expected one campaign object")
        campaign_id = str(payload.get("id") or "").strip()
        brand_id = str(payload.get("brand_id") or "").strip()
        if not campaign_id or not brand_id:
            raise CatalogError("a campaign needs an id and a brand_id")
        catalog = Catalog.load(data_dir, year)
        if brand_id not in catalog.brands:
            raise CatalogError(f"unknown brand_id {brand_id!r}")
        # Parse and validate before touching disk, so a bad option cannot land.
        probe = PriceLedger(year)
        probe.add_campaign_payload({"campaigns": [payload]}, source="<input>")

        path = campaign_dir(data_dir, year) / f"{brand_id}.json"
        current = (json.loads(path.read_text(encoding="utf-8"))
                   if path.exists() else {"campaigns": []})
        kept = [c for c in current["campaigns"] if c.get("id") != campaign_id]
        replaced = len(kept) != len(current["campaigns"])
        current["campaigns"] = sorted(kept + [payload], key=lambda c: c["id"])
        if write:
            _write_json(path, current)
            _revalidate(data_dir, year)
        return {"written": write, "replaced": replaced, "campaign_id": campaign_id,
                "options": [o.get("id") for o in payload.get("options", [])],
                "path": str(path)}
