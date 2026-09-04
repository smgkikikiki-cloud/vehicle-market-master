"""Loading, validating and querying one year's vehicle catalog.

The catalog is plain JSON on disk, one file per brand under a per-year folder,
so the owner can extend it in a text editor or with
``python -m vehreg catalog import`` and diff it in Git:

    vehreg/data/2026/models/toyota.json
    vehreg/data/2027/models/toyota.json    (created by `catalog fork`)

Years are independent on purpose. Nothing reads across them: 2026 volume is
classified by the 2026 catalog and that is the end of it. When a car is
repriced or repositioned for the next year, that is an edit to the next year's
folder, and the year already published never moves.

Inside a year file the layers nest exactly as ``entities.py`` describes them:

    brand -> models[] -> generations[] -> variants[]

IDs are composed from the path, so nothing in the file repeats a parent key and
no two brands can collide.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, Iterator, Optional

from .entities import (
    Brand, Generation, Model, ResolvedVehicle, Variant, cross_check, resolve,
)
from .normalize import MatchIndex, base_nameplate, slug
from .taxonomy import (
    BodyType, BrandSegment, CabType, Drivetrain, ImportType, MarketScope,
    Powertrain, RegistrationType, Segment, registration_type_for,
)

DATA_DIR = Path(__file__).with_name("data")

#: The year this tool is being run for. Older years are not consulted at all.
DEFAULT_YEAR = 2026


class CatalogError(ValueError):
    pass


def year_dir(data_dir: Path | str, year: int) -> Path:
    return Path(data_dir) / str(year) / "models"


def available_years(data_dir: Path | str = DATA_DIR) -> list[int]:
    out = []
    for child in sorted(Path(data_dir).glob("[0-9][0-9][0-9][0-9]")):
        if (child / "models").is_dir():
            out.append(int(child.name))
    return out


def _facet(cls, raw, default):
    if raw in (None, ""):
        return default
    return cls.parse(raw)


#: Override values arriving from JSON are plain strings; parse the ones that
#: name a closed vocabulary so downstream code always sees the enum.
_OVERRIDE_PARSERS = {
    "body_type": BodyType, "cab_type": CabType, "segment": Segment,
    "powertrain": Powertrain, "drivetrain": Drivetrain,
    "import_type": ImportType, "brand_segment": BrandSegment,
    "registration_type": RegistrationType, "market_scope": MarketScope,
}


def _overrides(raw: Any) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in dict(raw or {}).items():
        parser = _OVERRIDE_PARSERS.get(key)
        out[key] = parser.parse(value) if parser and value not in (None, "") else value
    return out


def _tuple(raw: Any) -> tuple[str, ...]:
    if not raw:
        return ()
    if isinstance(raw, str):
        return (raw,)
    return tuple(str(x) for x in raw)


class Catalog:
    """One year of catalog, in memory, with the indexes ingest needs."""

    def __init__(self, year: int = DEFAULT_YEAR) -> None:
        self.year = year
        self.brands: dict[str, Brand] = {}
        self.models: dict[str, Model] = {}
        self.generations: dict[str, Generation] = {}
        self.variants: dict[str, Variant] = {}
        self.brand_index = MatchIndex()
        self.model_index = MatchIndex()
        self.variant_index = MatchIndex()
        self._models_by_brand: dict[str, list[str]] = {}
        self._variants_by_model: dict[str, list[str]] = {}

    # ---------------------------------------------------------------- load
    @classmethod
    def load(cls, data_dir: Path | str = DATA_DIR,
             year: int = DEFAULT_YEAR) -> "Catalog":
        catalog = cls(year)
        models_dir = year_dir(data_dir, year)
        model_files = sorted(models_dir.glob("*.json"))
        if not model_files:
            years = available_years(data_dir)
            raise CatalogError(
                f"no brand files under {models_dir}"
                + (f"; years present: {', '.join(map(str, years))}" if years
                   else ""))
        for path in model_files:
            catalog.load_brand_file(path)
        catalog.build_indexes()
        return catalog

    def load_brand_file(self, path: Path) -> None:
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise CatalogError(f"{path}: invalid JSON: {exc}") from exc
        self.add_brand_payload(payload, source=str(path))

    def add_brand_payload(self, payload: dict, source: str = "<memory>") -> None:
        raw_brand = payload.get("brand")
        if not raw_brand:
            raise CatalogError(f"{source}: missing 'brand'")
        brand_id = slug(raw_brand.get("id") or raw_brand["name_en"])
        if brand_id in self.brands:
            raise CatalogError(f"{source}: duplicate brand id {brand_id!r}")
        self.brands[brand_id] = Brand(
            id=brand_id,
            name_en=raw_brand["name_en"],
            name_th=raw_brand.get("name_th", ""),
            brand_segment=_facet(BrandSegment, raw_brand.get("brand_segment"),
                                 BrandSegment.UNKNOWN),
            oem_group=raw_brand.get("oem_group", "UNKNOWN"),
            brand_origin=raw_brand.get("brand_origin", "UNKNOWN"),
            trim_detail=bool(raw_brand.get("trim_detail", False)),
            aliases=_tuple(raw_brand.get("aliases")),
            overrides=_overrides(raw_brand.get("overrides")),
        )
        self._models_by_brand[brand_id] = []
        for raw_model in payload.get("models", []):
            self._add_model(brand_id, raw_model, source)

    def _add_model(self, brand_id: str, raw: dict, source: str) -> None:
        model_id = f"{brand_id}.{slug(raw.get('id') or raw['name_en'])}"
        if model_id in self.models:
            raise CatalogError(f"{source}: duplicate model id {model_id!r}")
        body = _facet(BodyType, raw.get("body_type"), BodyType.OTHER)
        cab = _facet(CabType, raw.get("cab_type"), CabType.NOT_APPLICABLE)
        model = Model(
            id=model_id,
            brand_id=brand_id,
            name_en=raw["name_en"],
            name_th=raw.get("name_th", ""),
            # A blank nameplate falls back to the model name with its split
            # suffix removed, so Mazda2 Sedan rolls up to Mazda2 without the
            # owner typing anything. Hilux says "Hilux" explicitly, because
            # Revo and Champ are one nameplate but not one base name.
            nameplate=raw.get("nameplate") or base_nameplate(raw["name_en"]),
            body_type=body,
            cab_type=cab,
            # A blank registration_type follows from body and cab, which is
            # what puts double cabs in รย.1 and the other cabs in รย.3.
            registration_type=_facet(RegistrationType,
                                     raw.get("registration_type"),
                                     registration_type_for(body, cab)),
            market_scope=_facet(MarketScope, raw.get("market_scope"),
                                MarketScope.CORE),
            aliases=_tuple(raw.get("aliases")),
            notes=raw.get("notes", ""),
            overrides=_overrides(raw.get("overrides")),
        )
        self.models[model_id] = model
        self._models_by_brand[brand_id].append(model_id)
        self._variants_by_model[model_id] = []

        generations = raw.get("generations")
        if not generations:
            raise CatalogError(f"{source}: model {model_id} has no generations")
        for raw_gen in generations:
            self._add_generation(model_id, raw_gen, source)

    def _add_generation(self, model_id: str, raw: dict, source: str) -> None:
        code = raw.get("code") or raw.get("id") or "gen1"
        gen_id = f"{model_id}.{slug(code)}"
        if gen_id in self.generations:
            raise CatalogError(f"{source}: duplicate generation id {gen_id!r}")
        self.generations[gen_id] = Generation(
            id=gen_id,
            model_id=model_id,
            code=raw.get("code", ""),
            segment=_facet(Segment, raw.get("segment"), Segment.UNKNOWN),
            seats=raw.get("seats"),
            launched=raw.get("launched"),
            ended=raw.get("ended"),
            overrides=_overrides(raw.get("overrides")),
        )
        for raw_variant in raw.get("variants", []):
            self._add_variant(gen_id, model_id, raw_variant, source)

    def _add_variant(self, gen_id: str, model_id: str, raw: dict,
                     source: str) -> None:
        variant_id = f"{gen_id}.{slug(raw.get('id') or raw['name'])}"
        if variant_id in self.variants:
            raise CatalogError(f"{source}: duplicate variant id {variant_id!r}")
        self.variants[variant_id] = Variant(
            id=variant_id,
            generation_id=gen_id,
            name=raw["name"],
            powertrain=_facet(Powertrain, raw.get("powertrain"),
                              Powertrain.UNKNOWN),
            drivetrain=_facet(Drivetrain, raw.get("drivetrain"),
                              Drivetrain.UNKNOWN),
            engine_cc=raw.get("engine_cc"),
            battery_kwh=raw.get("battery_kwh"),
            price_thb=raw.get("price_thb"),
            price_min_thb=raw.get("price_min_thb"),
            price_max_thb=raw.get("price_max_thb"),
            import_type=_facet(ImportType, raw.get("import_type"),
                               ImportType.UNKNOWN),
            origin_country=raw.get("origin_country", "UNKNOWN"),
            price_note=raw.get("price_note", ""),
            aliases=_tuple(raw.get("aliases")),
            overrides=_overrides(raw.get("overrides")),
        )
        self._variants_by_model[model_id].append(variant_id)

    # -------------------------------------------------------------- indexes
    def build_indexes(self) -> None:
        self.brand_index = MatchIndex()
        self.model_index = MatchIndex()
        self.variant_index = MatchIndex()
        for brand in self.brands.values():
            self.brand_index.add(brand.id, [brand.name_en, brand.name_th,
                                            brand.id], priority=1)
            self.brand_index.add(brand.id, list(brand.aliases))
        for model in self.models.values():
            brand = self.brands[model.brand_id]
            for priority, names in ((1, [model.name_en, model.name_th]),
                                    (0, list(model.aliases))):
                # Both bare and brand-prefixed spellings appear in DLT exports.
                surfaces = [n for n in names if n]
                surfaces += [f"{brand.name_en} {n}" for n in surfaces]
                if brand.name_th:
                    surfaces += [f"{brand.name_th} {n}" for n in names if n]
                self.model_index.add(model.id, surfaces, priority=priority)
        for variant in self.variants.values():
            model = self.model_for_variant(variant.id)
            surfaces = [variant.name, *variant.aliases]
            surfaces += [f"{model.name_en} {s}" for s in surfaces if s]
            self.variant_index.add(variant.id, [s for s in surfaces if s])

    # ------------------------------------------------------------ traversal
    def generation_for_variant(self, variant_id: str) -> Generation:
        return self.generations[self.variants[variant_id].generation_id]

    def model_for_variant(self, variant_id: str) -> Model:
        return self.models[self.generation_for_variant(variant_id).model_id]

    def brand_for_variant(self, variant_id: str) -> Brand:
        return self.brands[self.model_for_variant(variant_id).brand_id]

    def models_of(self, brand_id: str) -> list[Model]:
        return [self.models[m] for m in self._models_by_brand.get(brand_id, [])]

    def variants_of(self, model_id: str) -> list[Variant]:
        return [self.variants[v] for v in self._variants_by_model.get(model_id, [])]

    def generations_of(self, model_id: str) -> list[Generation]:
        """Oldest first, so a nameplate's โฉม read as a succession."""
        return sorted((g for g in self.generations.values()
                       if g.model_id == model_id),
                      key=lambda g: (g.launched or "", g.code))

    def trim_detail_brands(self) -> list[str]:
        """Brands whose DLT รุ่น field carries trim, so the ledger tracks them."""
        return sorted(b.id for b in self.brands.values() if b.trim_detail)

    def nameplates(self) -> dict[str, list[str]]:
        """``{"Toyota Hilux": [model_id, ...]}`` - the reporting roll-up."""
        out: dict[str, list[str]] = {}
        for model in self.models.values():
            brand = self.brands[model.brand_id]
            key = f"{brand.name_en} {model.nameplate or model.name_en}"
            out.setdefault(key, []).append(model.id)
        return dict(sorted(out.items()))

    def succession(self, model_id: str) -> list[tuple[Generation, list[Variant]]]:
        """Generations of one model, oldest first, with their variants."""
        return [(gen, [v for v in self.variants.values()
                       if v.generation_id == gen.id])
                for gen in self.generations_of(model_id)]

    # ------------------------------------------------------------- resolve
    def resolve(self, variant_id: str) -> ResolvedVehicle:
        variant = self.variants[variant_id]
        generation = self.generations[variant.generation_id]
        model = self.models[generation.model_id]
        brand = self.brands[model.brand_id]
        return resolve(brand, model, generation, variant, self.year)

    def iter_resolved(self) -> Iterator[ResolvedVehicle]:
        for variant_id in self.variants:
            yield self.resolve(variant_id)

    # ------------------------------------------------------------ validate
    def validate(self) -> list[str]:
        problems: list[str] = []
        for model in self.models.values():
            problems += model.validate()
            if model.body_type is BodyType.OTHER:
                problems.append(f"model {model.id}: body_type not set")
            if not self.variants_of(model.id):
                problems.append(f"model {model.id}: no variants")
        for variant in self.variants.values():
            problems += variant.validate()
        problems += self.duplicate_body_warnings()
        for resolved in self.iter_resolved():
            problems += cross_check(resolved)
        return problems

    def duplicate_body_warnings(self) -> list[str]:
        """One nameplate must not appear twice in the same body under a brand.

        Splitting by body is the rule; two model rows that end up with the same
        name *and* the same body are a duplicate, not a split.
        """
        seen: dict[tuple[str, str, str, str], str] = {}
        problems: list[str] = []
        for model in self.models.values():
            key = (model.brand_id, slug(model.name_en), model.body_type.value,
                   model.cab_type.value)
            if key in seen:
                problems.append(
                    f"model {model.id}: same name and body as {seen[key]}")
            seen[key] = model.id
        return problems

    def coverage(self) -> dict[str, int]:
        scopes: dict[str, int] = {}
        for model in self.models.values():
            key = model.market_scope.value
            scopes[key] = scopes.get(key, 0) + 1
        return {
            "year": self.year,
            "brands": len(self.brands),
            "nameplates": len(self.nameplates()),
            "models": len(self.models),
            "generations": len(self.generations),
            "variants": len(self.variants),
            **{f"models_{k.lower()}": v for k, v in sorted(scopes.items())},
        }

    # ------------------------------------------------------------- writing
    def brand_payload(self, brand_id: str) -> dict:
        """Round-trip a brand back to the on-disk JSON shape."""
        brand = self.brands[brand_id]
        payload: dict[str, Any] = {
            "brand": {
                "id": brand.id, "name_en": brand.name_en, "name_th": brand.name_th,
                "brand_segment": brand.brand_segment.value,
                "oem_group": brand.oem_group, "brand_origin": brand.brand_origin,
                "trim_detail": brand.trim_detail,
                "aliases": list(brand.aliases),
            },
            "models": [],
        }
        for model in self.models_of(brand_id):
            model_payload: dict[str, Any] = {
                "id": model.id.split(".", 1)[1], "name_en": model.name_en,
                "name_th": model.name_th, "nameplate": model.nameplate,
                "body_type": model.body_type.value,
                "cab_type": model.cab_type.value,
                "registration_type": model.registration_type.value,
                "market_scope": model.market_scope.value,
                "aliases": list(model.aliases), "generations": [],
            }
            for gen in self.generations_of(model.id):
                gen_payload: dict[str, Any] = {
                    "code": gen.code, "segment": gen.segment.value,
                    "seats": gen.seats, "launched": gen.launched,
                    "ended": gen.ended, "variants": [],
                }
                for variant in self.variants.values():
                    if variant.generation_id != gen.id:
                        continue
                    gen_payload["variants"].append({
                        "name": variant.name,
                        "powertrain": variant.powertrain.value,
                        "drivetrain": variant.drivetrain.value,
                        "engine_cc": variant.engine_cc,
                        "battery_kwh": variant.battery_kwh,
                        "price_thb": variant.price_thb,
                        "price_min_thb": variant.price_min_thb,
                        "price_max_thb": variant.price_max_thb,
                        "import_type": variant.import_type.value,
                        "origin_country": variant.origin_country,
                        "price_note": variant.price_note,
                        "aliases": list(variant.aliases),
                    })
                model_payload["generations"].append(gen_payload)
            payload["models"].append(model_payload)
        return payload

    def save_brand(self, brand_id: str, data_dir: Path | str = DATA_DIR) -> Path:
        path = year_dir(data_dir, self.year) / f"{brand_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.brand_payload(brand_id), ensure_ascii=False, indent=2)
            + "\n", encoding="utf-8")
        return path


def fork_year(data_dir: Path | str, source_year: int, target_year: int, *,
              overwrite: bool = False) -> Path:
    """Start next year's catalog as a copy of this year's.

    The copy is a starting point to edit, not a link: changing 2027 never
    touches 2026.
    """
    src = year_dir(data_dir, source_year)
    dst = year_dir(data_dir, target_year)
    if not src.is_dir():
        raise CatalogError(f"no catalog for {source_year} at {src}")
    if dst.exists() and any(dst.glob("*.json")) and not overwrite:
        raise CatalogError(
            f"{target_year} already exists at {dst}; pass overwrite to replace it")
    dst.mkdir(parents=True, exist_ok=True)
    for path in sorted(src.glob("*.json")):
        shutil.copy2(path, dst / path.name)
    return dst
