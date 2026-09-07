from pathlib import Path

# ---------- entities.py ----------
path = Path("vehreg/entities.py")
text = path.read_text(encoding="utf-8")

old = '''    id: str                                   # "toyota.alphard.ah40.trim.z_premier"\n    generation_id: str\n    name: str                                 # marketed grade, e.g. "Z Premier"\n    variant_id: Optional[str] = None           # analytical Variant, if known\n    powertrain: Powertrain = Powertrain.UNKNOWN\n'''
new = '''    id: str                                   # "toyota.alphard.ah40.trim.z_premier"\n    generation_id: str\n    name: str                                 # marketed grade, e.g. "Z Premier"\n    # Retail identity must name one real powertrain. Unlike analytical Variant,\n    # MarketTrim cannot represent an unresolved/aggregate UNKNOWN bucket.\n    powertrain: Powertrain\n    variant_id: Optional[str] = None           # analytical Variant, if known\n'''
assert old in text, "MarketTrim field-order anchor changed"
text = text.replace(old, new, 1)

old = '''    def validate(self) -> list[str]:\n        problems: list[str] = []\n        if self.price_thb is not None and self.price_thb < 0:\n'''
new = '''    def validate(self) -> list[str]:\n        problems: list[str] = []\n        # Loader already rejects UNKNOWN, but keep the entity itself honest too:\n        # direct construction in tests/tools must not create an invalid retail SKU.\n        if self.powertrain is Powertrain.UNKNOWN:\n            problems.append("powertrain must be exact; UNKNOWN is not valid for MarketTrim")\n        if self.price_thb is not None and self.price_thb < 0:\n'''
assert old in text, "MarketTrim validate anchor changed"
text = text.replace(old, new, 1)
path.write_text(text, encoding="utf-8")

# ---------- catalog.py ----------
path = Path("vehreg/catalog.py")
text = path.read_text(encoding="utf-8")

old = '''from .entities import (\n    Brand, Generation, MarketTrim, Model, ResolvedVehicle, Variant, cross_check, resolve,\n)\n'''
new = '''from .entities import (\n    Brand, Generation, MarketTrim, Model, ResolvedVehicle, Variant, cross_check, resolve,\n    to_jsonable,\n)\n'''
assert old in text, "entities import anchor changed"
text = text.replace(old, new, 1)

old = '''def _tuple(raw: Any) -> tuple[str, ...]:\n    if not raw:\n        return ()\n    if isinstance(raw, str):\n        return (raw,)\n    return tuple(str(x) for x in raw)\n\n\nclass Catalog:\n'''
new = '''def _tuple(raw: Any) -> tuple[str, ...]:\n    if not raw:\n        return ()\n    if isinstance(raw, str):\n        return (raw,)\n    return tuple(str(x) for x in raw)\n\n\ndef _source_refs(raw: Any) -> dict[str, tuple[str, ...]]:\n    """Canonicalize external source IDs without changing their meaning.\n\n    Source-system IDs are provenance, not vehicle identity. Whitespace-only\n    keys/IDs are discarded and duplicates are removed while preserving order,\n    so repeated ECO imports cannot silently accumulate junk references.\n    """\n    out: dict[str, tuple[str, ...]] = {}\n    for key, value in dict(raw or {}).items():\n        source = str(key).strip()\n        if not source:\n            continue\n        refs: list[str] = []\n        seen: set[str] = set()\n        for item in _tuple(value):\n            ref = item.strip()\n            if not ref or ref in seen:\n                continue\n            seen.add(ref)\n            refs.append(ref)\n        if refs:\n            out[source] = tuple(refs)\n    return out\n\n\nclass Catalog:\n'''
assert old in text, "_tuple anchor changed"
text = text.replace(old, new, 1)

old = '''    def add_brand_payload(self, payload: dict, source: str = "<memory>") -> None:\n        raw_brand = payload.get("brand")\n        if not raw_brand:\n            raise CatalogError(f"{source}: missing 'brand'")\n        brand_id = slug(raw_brand.get("id") or raw_brand["name_en"])\n        if brand_id in self.brands:\n            raise CatalogError(f"{source}: duplicate brand id {brand_id!r}")\n        self.brands[brand_id] = Brand(\n            id=brand_id,\n            name_en=raw_brand["name_en"],\n            name_th=raw_brand.get("name_th", ""),\n            brand_segment=_facet(BrandSegment, raw_brand.get("brand_segment"),\n                                 BrandSegment.UNKNOWN),\n            oem_group=raw_brand.get("oem_group", "UNKNOWN"),\n            brand_origin=raw_brand.get("brand_origin", "UNKNOWN"),\n            trim_detail=bool(raw_brand.get("trim_detail", False)),\n            aliases=_tuple(raw_brand.get("aliases")),\n            overrides=_overrides(raw_brand.get("overrides")),\n        )\n        self._models_by_brand[brand_id] = []\n        for raw_model in payload.get("models", []):\n            self._add_model(brand_id, raw_model, source)\n'''
new = '''    def add_brand_payload(self, payload: dict, source: str = "<memory>") -> None:\n        """Atomically add one brand payload.\n\n        Parsing used to mutate the live Catalog as it descended the payload. A\n        bad late trim therefore left a half-added brand/models/variants behind\n        after raising CatalogError. Stage the whole brand in an isolated Catalog\n        first, then merge only after every nested object was accepted.\n        """\n        raw_brand = payload.get("brand")\n        if not raw_brand:\n            raise CatalogError(f"{source}: missing 'brand'")\n        brand_id = slug(raw_brand.get("id") or raw_brand["name_en"])\n        if brand_id in self.brands:\n            raise CatalogError(f"{source}: duplicate brand id {brand_id!r}")\n\n        staged = Catalog(self.year)\n        staged._add_brand_payload_inplace(payload, source)\n        self.brands.update(staged.brands)\n        self.models.update(staged.models)\n        self.generations.update(staged.generations)\n        self.variants.update(staged.variants)\n        self.trims.update(staged.trims)\n        self._models_by_brand.update(staged._models_by_brand)\n        self._variants_by_model.update(staged._variants_by_model)\n        self._trims_by_generation.update(staged._trims_by_generation)\n        self._trims_by_variant.update(staged._trims_by_variant)\n\n    def _add_brand_payload_inplace(self, payload: dict, source: str) -> None:\n        raw_brand = payload.get("brand")\n        if not raw_brand:\n            raise CatalogError(f"{source}: missing 'brand'")\n        brand_id = slug(raw_brand.get("id") or raw_brand["name_en"])\n        if brand_id in self.brands:\n            raise CatalogError(f"{source}: duplicate brand id {brand_id!r}")\n        self.brands[brand_id] = Brand(\n            id=brand_id,\n            name_en=raw_brand["name_en"],\n            name_th=raw_brand.get("name_th", ""),\n            brand_segment=_facet(BrandSegment, raw_brand.get("brand_segment"),\n                                 BrandSegment.UNKNOWN),\n            oem_group=raw_brand.get("oem_group", "UNKNOWN"),\n            brand_origin=raw_brand.get("brand_origin", "UNKNOWN"),\n            trim_detail=bool(raw_brand.get("trim_detail", False)),\n            aliases=_tuple(raw_brand.get("aliases")),\n            overrides=_overrides(raw_brand.get("overrides")),\n        )\n        self._models_by_brand[brand_id] = []\n        for raw_model in payload.get("models", []):\n            self._add_model(brand_id, raw_model, source)\n'''
assert old in text, "add_brand_payload anchor changed"
text = text.replace(old, new, 1)

old = '''        source_refs = {\n            str(key): _tuple(value)\n            for key, value in dict(raw.get("source_refs") or {}).items()\n            if str(key).strip()\n        }\n'''
new = '''        source_refs = _source_refs(raw.get("source_refs"))\n'''
assert old in text, "source_refs anchor changed"
text = text.replace(old, new, 1)

old = '''        payload: dict[str, Any] = {\n            "brand": {\n                "id": brand.id, "name_en": brand.name_en, "name_th": brand.name_th,\n                "brand_segment": brand.brand_segment.value,\n                "oem_group": brand.oem_group, "brand_origin": brand.brand_origin,\n                "trim_detail": brand.trim_detail,\n                "aliases": list(brand.aliases),\n            },\n            "models": [],\n        }\n'''
new = '''        payload: dict[str, Any] = {\n            "brand": {\n                "id": brand.id, "name_en": brand.name_en, "name_th": brand.name_th,\n                "brand_segment": brand.brand_segment.value,\n                "oem_group": brand.oem_group, "brand_origin": brand.brand_origin,\n                "trim_detail": brand.trim_detail,\n                "aliases": list(brand.aliases),\n            },\n            "models": [],\n        }\n        if brand.overrides:\n            payload["brand"]["overrides"] = to_jsonable(brand.overrides)\n'''
assert old in text, "brand payload anchor changed"
text = text.replace(old, new, 1)

old = '''            # Without this, saving a brand from the editor would silently clear\n            # the marker and the model would start reading as a finished one.\n            if model.incomplete:\n'''
new = '''            if model.overrides:\n                model_payload["overrides"] = to_jsonable(model.overrides)\n            # Without this, saving a brand from the editor would silently clear\n            # the marker and the model would start reading as a finished one.\n            if model.incomplete:\n'''
assert old in text, "model payload anchor changed"
text = text.replace(old, new, 1)

old = '''                gen_payload: dict[str, Any] = {\n                    "code": gen.code, "segment": gen.segment.value,\n                    "seats": gen.seats, "launched": gen.launched,\n                    "ended": gen.ended, "variants": [], "trims": [],\n                }\n'''
new = '''                gen_payload: dict[str, Any] = {\n                    # Preserve the canonical local ID even when `code` is blank.\n                    # Otherwise a generation authored with only `id` reloads as\n                    # `gen1` after an editor/save round-trip.\n                    "id": gen.id[len(model.id) + 1:],\n                    "code": gen.code, "segment": gen.segment.value,\n                    "seats": gen.seats, "launched": gen.launched,\n                    "ended": gen.ended, "variants": [], "trims": [],\n                }\n                if gen.overrides:\n                    gen_payload["overrides"] = to_jsonable(gen.overrides)\n'''
assert old in text, "generation payload anchor changed"
text = text.replace(old, new, 1)

old = '''                    variant_payload = {\n                        "name": variant.name,\n                        "powertrain": variant.powertrain.value,\n'''
new = '''                    variant_payload = {\n                        # Variant IDs are referenced by MarketTrim. Saving only\n                        # the display name could rename the analytical parent and\n                        # strand every trim link on the next load.\n                        "id": variant.id[len(gen.id) + 1:],\n                        "name": variant.name,\n                        "powertrain": variant.powertrain.value,\n'''
assert old in text, "variant payload anchor changed"
text = text.replace(old, new, 1)

old = '''                    # Same reason as the model flag: saving from the editor\n                    # must not quietly clear the marker and turn a declared\n                    # gap back into a finished trim.\n                    if variant.incomplete:\n'''
new = '''                    if variant.overrides:\n                        variant_payload["overrides"] = to_jsonable(variant.overrides)\n                    # Same reason as the model flag: saving from the editor\n                    # must not quietly clear the marker and turn a declared\n                    # gap back into a finished trim.\n                    if variant.incomplete:\n'''
assert old in text, "variant overrides anchor changed"
text = text.replace(old, new, 1)

path.write_text(text, encoding="utf-8")

# ---------- tests ----------
Path("tests/test_catalog_structural_integrity.py").write_text(r'''import copy
import unittest

from vehreg.catalog import Catalog, CatalogError
from vehreg.entities import MarketTrim
from vehreg.taxonomy import Powertrain


BASE = {
    "brand": {
        "id": "acme",
        "name_en": "Acme",
        "name_th": "",
        "overrides": {"source_tag": "brand"},
    },
    "models": [{
        "id": "one",
        "name_en": "One",
        "body_type": "CROSSOVER",
        "overrides": {"source_tag": "model"},
        "generations": [{
            "id": "custom-generation",
            "segment": "C",
            "overrides": {"source_tag": "generation"},
            "variants": [
                {
                    "id": "bev-main",
                    "name": "Long Range BEV",
                    "powertrain": "BEV",
                    "drivetrain": "FWD",
                    "battery_kwh": 60,
                    "import_type": "CBU",
                    "origin_country": "CN",
                    "overrides": {"drivetrain": "AWD"},
                }
            ],
            "trims": [
                {
                    "id": "premium",
                    "name": "Premium",
                    "variant": "bev-main",
                    "powertrain": "BEV",
                    "length_mm": 4500,
                    "width_mm": 1850,
                    "height_mm": 1650,
                    "wheelbase_mm": 2700,
                    "source_refs": {
                        " ecosticker ": [" eco-1 ", "eco-1", "", " eco-2 "],
                    },
                }
            ],
        }],
    }],
}


class CatalogStructuralIntegrityTests(unittest.TestCase):
    def test_failed_brand_add_is_atomic(self):
        bad = copy.deepcopy(BASE)
        del bad["models"][0]["generations"][0]["trims"][0]["powertrain"]
        c = Catalog(2026)
        with self.assertRaisesRegex(CatalogError, "exact powertrain"):
            c.add_brand_payload(bad, source="<atomic>")

        self.assertEqual(c.brands, {})
        self.assertEqual(c.models, {})
        self.assertEqual(c.generations, {})
        self.assertEqual(c.variants, {})
        self.assertEqual(c.trims, {})

        # The same brand can be added cleanly after the failed attempt; no ghost
        # duplicate IDs were left behind by the rejected payload.
        c.add_brand_payload(copy.deepcopy(BASE), source="<atomic-retry>")
        self.assertIn("acme", c.brands)

    def test_roundtrip_preserves_canonical_ids_overrides_and_links(self):
        c = Catalog(2026)
        c.add_brand_payload(copy.deepcopy(BASE), source="<roundtrip>")
        c.build_indexes()

        saved = c.brand_payload("acme")
        model = saved["models"][0]
        gen = model["generations"][0]
        variant = gen["variants"][0]
        trim = gen["trims"][0]

        self.assertEqual(saved["brand"]["overrides"]["source_tag"], "brand")
        self.assertEqual(model["overrides"]["source_tag"], "model")
        self.assertEqual(gen["id"], "custom_generation")
        self.assertEqual(gen["overrides"]["source_tag"], "generation")
        self.assertEqual(variant["id"], "bev_main")
        self.assertEqual(variant["overrides"]["drivetrain"], "AWD")
        self.assertEqual(trim["variant_id"], "acme.one.custom_generation.bev_main")

        c2 = Catalog(2026)
        c2.add_brand_payload(saved, source="<roundtrip-2>")
        c2.build_indexes()
        self.assertIn("acme.one.custom_generation", c2.generations)
        self.assertIn("acme.one.custom_generation.bev_main", c2.variants)
        rt = c2.trims["acme.one.custom_generation.trim.premium"]
        self.assertEqual(rt.variant_id, "acme.one.custom_generation.bev_main")

    def test_source_refs_are_normalized_and_deduplicated(self):
        c = Catalog(2026)
        c.add_brand_payload(copy.deepcopy(BASE), source="<refs>")
        trim = c.trims["acme.one.custom_generation.trim.premium"]
        self.assertEqual(trim.source_refs, {"ecosticker": ("eco-1", "eco-2")})

    def test_entity_validation_rejects_unknown_powertrain_too(self):
        trim = MarketTrim(
            id="acme.one.g1.trim.bad",
            generation_id="acme.one.g1",
            name="Bad",
            powertrain=Powertrain.UNKNOWN,
        )
        problems = trim.validate()
        self.assertTrue(any("powertrain must be exact" in p for p in problems))


if __name__ == "__main__":
    unittest.main()
''', encoding="utf-8")
