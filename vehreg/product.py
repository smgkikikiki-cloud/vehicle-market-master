"""Vehicle Master product API. No database connection or registration writes.

Use ProductMaster for joined retail specs/prices and the two authoring functions
for validated, atomic, single-file changes. JSON/Git remains the source of truth.
"""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from dataclasses import fields
from datetime import date
import json
import os
from pathlib import Path
import tempfile

from .catalog import Catalog, CatalogError, DATA_DIR, DEFAULT_YEAR, year_dir
from .entities import MarketTrim, to_jsonable
from .homologation import ECOStickerSpecStore
from .normalize import slug
from .pricing import PriceLedger, price_dir


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
