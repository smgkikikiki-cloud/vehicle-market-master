import unittest

from vehreg.catalog import Catalog, CatalogError
from vehreg.taxonomy import Powertrain


def payload():
    return {
        "brand": {
            "id": "acme",
            "name_en": "Acme",
            "name_th": "แอคมี่",
            "brand_segment": "MASS",
            "oem_group": "Acme Group",
            "brand_origin": "TH",
        },
        "models": [{
            "id": "echo",
            "name_en": "Echo",
            "body_type": "CROSSOVER",
            "generations": [{
                "code": "E1",
                "segment": "C",
                "seats": 5,
                "variants": [
                    {
                        "name": "BEV",
                        "powertrain": "BEV",
                        "drivetrain": "FWD",
                        "battery_kwh": 60,
                        "price_thb": 999000,
                        "import_type": "CKD",
                        "origin_country": "TH",
                    },
                    {
                        "name": "PHEV",
                        "powertrain": "PHEV",
                        "drivetrain": "FWD",
                        "engine_cc": 1498,
                        "battery_kwh": 18.3,
                        "price_thb": 1099000,
                        "import_type": "CKD",
                        "origin_country": "TH",
                    },
                ],
                "trims": [
                    {
                        "id": "long_range",
                        "name": "Long Range",
                        "variant": "BEV",
                        "powertrain": "BEV",
                        "price_thb": 1099000,
                        "drivetrain": "FWD",
                        "battery_kwh": 60,
                        "transmission": "single-speed",
                        "length_mm": 4650,
                        "width_mm": 1880,
                        "height_mm": 1650,
                        "wheelbase_mm": 2750,
                        "tire_front": "235/50 R19",
                        "tire_rear": "235/50 R19",
                        "wheel_front": "19x7.5J",
                        "wheel_rear": "19x7.5J",
                        "source_refs": {"ecosticker": ["eco-bev-001"]},
                    },
                    {
                        "name": "Premium PHEV",
                        "variant": "PHEV",
                        "powertrain": "PHEV",
                        "price_thb": 1199000,
                        "engine_code": "A15T",
                        "engine_cc": 1498,
                        "battery_kwh": 18.3,
                        "tire_front": "225/55 R18",
                        "tire_rear": "225/55 R18",
                        "source_refs": {"ecosticker": "eco-phev-001"},
                    },
                ],
            }],
        }],
    }


class MarketTrimTests(unittest.TestCase):
    def catalog(self):
        c = Catalog(2026)
        c.add_brand_payload(payload(), source="<trim-test>")
        c.build_indexes()
        return c

    def test_trims_get_stable_ids_and_parent_links(self):
        c = self.catalog()
        self.assertEqual(len(c.variants), 2)
        self.assertEqual(len(c.trims), 2)

        trim_id = "acme.echo.e1.trim.long_range"
        trim = c.trims[trim_id]
        self.assertEqual(trim.name, "Long Range")
        self.assertEqual(trim.variant_id, "acme.echo.e1.bev")
        self.assertIs(trim.powertrain, Powertrain.BEV)
        self.assertEqual(trim.wheelbase_mm, 2750)
        self.assertEqual(trim.tire_front, "235/50 R19")
        self.assertEqual(trim.source_refs["ecosticker"], ("eco-bev-001",))
        self.assertEqual(c.variant_for_trim(trim_id).id, "acme.echo.e1.bev")
        self.assertEqual(c.model_for_trim(trim_id).id, "acme.echo")
        self.assertEqual(len(c.trims_of_variant("acme.echo.e1.bev")), 1)
        self.assertEqual(len(c.trims_of("acme.echo")), 2)

    def test_trims_never_multiply_analytical_rows(self):
        c = self.catalog()
        # Registration analytics continue to resolve analytical variants only.
        self.assertEqual(len(list(c.iter_resolved())), 2)
        self.assertEqual(len(c.variants), 2)
        self.assertEqual(len(c.trims), 2)

    def test_trim_index_exists_but_is_not_the_variant_index(self):
        c = self.catalog()
        trim_key, _score, _how = c.trim_index.lookup("Echo Long Range")
        variant_key, _score, _how = c.variant_index.lookup("Echo Long Range")
        self.assertEqual(trim_key, "acme.echo.e1.trim.long_range")
        self.assertNotEqual(variant_key, "acme.echo.e1.trim.long_range")

    def test_missing_analytical_variant_reference_fails_closed(self):
        p = payload()
        p["models"][0]["generations"][0]["trims"][0]["variant"] = "NO SUCH LINE"
        c = Catalog(2026)
        with self.assertRaises(CatalogError):
            c.add_brand_payload(p, source="<trim-test>")

    def test_trim_powertrain_mismatch_is_validation_problem_not_analytics_rewrite(self):
        p = payload()
        p["models"][0]["generations"][0]["trims"][0]["powertrain"] = "PHEV"
        c = Catalog(2026)
        c.add_brand_payload(p, source="<trim-test>")
        c.build_indexes()
        problems = c.validate()
        self.assertTrue(any("does not match analytical variant" in x for x in problems))
        # Parent analytical line remains BEV: retail data cannot rewrite it.
        self.assertIs(c.resolve("acme.echo.e1.bev")["powertrain"], Powertrain.BEV)


if __name__ == "__main__":
    unittest.main()
