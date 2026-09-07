import copy
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
