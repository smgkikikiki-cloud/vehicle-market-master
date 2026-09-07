import unittest

from vehreg.catalog import Catalog, DATA_DIR
from vehreg.powertrain_rules import effective_powertrain_sql


class OwnerCatalogFixTests(unittest.TestCase):
    def test_lexus_is_no_longer_matches_es(self):
        for year in range(2021, 2027):
            cat = Catalog.load(DATA_DIR, year)
            unit_id, _, _ = cat.model_index.lookup("LEXUS IS300h")
            self.assertEqual(unit_id, "lexus.lexus_is", year)
            self.assertEqual(
                {v.powertrain.value for v in cat.variants_of(unit_id)}, {"HEV"})

    def test_lexus_ls_no_longer_matches_lm(self):
        for year in range(2021, 2027):
            cat = Catalog.load(DATA_DIR, year)
            unit_id, _, _ = cat.model_index.lookup("LEXUS LS500H")
            self.assertEqual(unit_id, "lexus.lexus_ls", year)
            self.assertEqual(
                {v.powertrain.value for v in cat.variants_of(unit_id)}, {"HEV"})

    def test_prius_has_a_real_model_target(self):
        for year in range(2021, 2027):
            cat = Catalog.load(DATA_DIR, year)
            for label in ("TOYOTA PRIUS", "TOYOTA PRIUS Z HYBRID",
                          "TOYOTA PRIUS HYBRID Z 2WD"):
                unit_id, _, _ = cat.model_index.lookup(label)
                self.assertEqual(unit_id, "toyota.prius", (year, label))
            self.assertEqual(
                {v.powertrain.value for v in cat.variants_of("toyota.prius")},
                {"HEV"})

    def test_audi_rules_use_canonical_model_names(self):
        sql = effective_powertrain_sql("b")
        self.assertIn("AUDI Q7", sql)
        self.assertIn("AUDI A6", sql)


if __name__ == "__main__":
    unittest.main()
