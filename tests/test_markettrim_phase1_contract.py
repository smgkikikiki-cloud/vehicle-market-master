import unittest

from vehreg.catalog import Catalog, CatalogError
from vehreg.taxonomy import Powertrain


def base_payload():
    return {
        "brand": {"id": "acme", "name_en": "Acme", "name_th": ""},
        "models": [{
            "id": "one",
            "name_en": "One",
            "body_type": "CROSSOVER",
            "generations": [{
                "code": "G1",
                "segment": "C",
                "variants": [
                    {
                        "name": "BEV",
                        "powertrain": "BEV",
                        "drivetrain": "FWD",
                        "battery_kwh": 60,
                        "import_type": "CBU",
                        "origin_country": "CN",
                    },
                    {
                        "name": "PHEV",
                        "powertrain": "PHEV",
                        "drivetrain": "FWD",
                        "engine_cc": 1498,
                        "battery_kwh": 20,
                        "import_type": "CBU",
                        "origin_country": "CN",
                    },
                ],
                "trims": [
                    {
                        "name": "Premium",
                        "variant": "BEV",
                        "powertrain": "BEV",
                        "length_mm": 4500,
                        "width_mm": 1850,
                        "height_mm": 1650,
                        "wheelbase_mm": 2700,
                        "source_refs": {"ecosticker": ["eco-bev"]},
                    },
                    {
                        "name": "Premium",
                        "variant": "PHEV",
                        "powertrain": "PHEV",
                        "length_mm": 4510,
                        "width_mm": 1850,
                        "height_mm": 1650,
                    },
                ],
            }],
        }],
    }


class Phase1MarketTrimContractTests(unittest.TestCase):
    def test_default_identity_includes_exact_powertrain(self):
        c = Catalog(2026)
        c.add_brand_payload(base_payload(), source="<phase1>")
        c.build_indexes()
        self.assertIn("acme.one.g1.trim.premium_bev", c.trims)
        self.assertIn("acme.one.g1.trim.premium_phev", c.trims)
        self.assertIs(c.trims["acme.one.g1.trim.premium_bev"].powertrain,
                      Powertrain.BEV)
        self.assertIs(c.trims["acme.one.g1.trim.premium_phev"].powertrain,
                      Powertrain.PHEV)

    def test_market_trim_refuses_unknown_powertrain(self):
        p = base_payload()
        del p["models"][0]["generations"][0]["trims"][0]["powertrain"]
        c = Catalog(2026)
        with self.assertRaisesRegex(CatalogError, "exact powertrain"):
            c.add_brand_payload(p, source="<phase1>")

    def test_dimension_coverage_is_separate_and_queryable(self):
        c = Catalog(2026)
        c.add_brand_payload(base_payload(), source="<phase1>")
        c.build_indexes()
        coverage = c.trim_coverage()
        self.assertEqual(coverage["trims"], 2)
        self.assertEqual(coverage["exact_powertrain"], 2)
        self.assertEqual(coverage["length_mm"], 2)
        self.assertEqual(coverage["width_mm"], 2)
        self.assertEqual(coverage["height_mm"], 2)
        self.assertEqual(coverage["wheelbase_mm"], 1)
        self.assertEqual(coverage["complete_dimensions"], 1)

    def test_brand_payload_round_trip_preserves_trim_product_fields(self):
        c = Catalog(2026)
        c.add_brand_payload(base_payload(), source="<phase1>")
        c.build_indexes()
        saved = c.brand_payload("acme")
        trims = saved["models"][0]["generations"][0]["trims"]
        self.assertEqual(len(trims), 2)
        bev = next(t for t in trims if t["powertrain"] == "BEV")
        self.assertEqual(bev["id"], "premium_bev")
        self.assertEqual(bev["length_mm"], 4500)
        self.assertEqual(bev["wheelbase_mm"], 2700)
        self.assertEqual(bev["source_refs"]["ecosticker"], ["eco-bev"])

        c2 = Catalog(2026)
        c2.add_brand_payload(saved, source="<phase1-roundtrip>")
        c2.build_indexes()
        rt = c2.trims["acme.one.g1.trim.premium_bev"]
        self.assertIs(rt.powertrain, Powertrain.BEV)
        self.assertEqual(rt.length_mm, 4500)
        self.assertEqual(rt.wheelbase_mm, 2700)

    def test_trims_still_do_not_multiply_registration_rows(self):
        c = Catalog(2026)
        c.add_brand_payload(base_payload(), source="<phase1>")
        c.build_indexes()
        self.assertEqual(len(c.trims), 2)
        self.assertEqual(len(list(c.iter_resolved())), 2)


if __name__ == "__main__":
    unittest.main()
