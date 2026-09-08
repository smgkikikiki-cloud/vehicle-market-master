"""Three nameplates that were describing the wrong car, and the Audi labels.

Each of these was reported as "no ECO evidence", which was a symptom rather than
the problem: one was a duplicate under its Chinese name, one had another car's
specification pasted into it, and one is simply not on sale here.
"""

import gzip
import json
import unittest

from vehreg.catalog import Catalog, DATA_DIR
from vehreg.powertrain_rules import RULES


class GalaxyE5Tests(unittest.TestCase):
    """Galaxy E5 is the Chinese name of the car Thailand receives as the EX5."""

    @classmethod
    def setUpClass(cls):
        cls.catalog = Catalog.load(year=2026)
        cls.catalog.build_indexes()

    def test_there_is_one_nameplate_not_two(self):
        self.assertNotIn("geely.galaxy_e5", self.catalog.models)
        self.assertIn("geely.geely_ex5", self.catalog.models)

    def test_both_names_reach_the_surviving_nameplate(self):
        for label in ("GEELY GALAXY E5", "GALAXY E5", "E5", "EX5", "GEELY EX5"):
            resolved, _, _ = self.catalog.model_index.lookup(label)
            self.assertEqual("geely.geely_ex5", resolved, label)

    def test_the_alias_does_not_reach_across_brands(self):
        """"E5" is short enough to be worth checking against every other model."""
        for year in range(2021, 2027):
            catalog = Catalog.load(year=year)
            catalog.build_indexes()
            brands = {candidate.split(".")[0] for candidate
                      in catalog.model_index.ambiguous_candidates("E5")}
            self.assertLessEqual(len(brands), 1, f"{year}: E5 is ambiguous")


class MgEsTests(unittest.TestCase):
    """The ES is a wagon. The specification here belonged to the S5 crossover."""

    @classmethod
    def setUpClass(cls):
        cls.catalog = Catalog.load(year=2026)
        cls.catalog.build_indexes()

    def test_the_es_is_a_wagon_and_the_s5_is_still_a_crossover(self):
        self.assertEqual("WAGON", self.catalog.models["mg.mg_es"].body_type.value)
        self.assertEqual("CROSSOVER",
                         self.catalog.models["mg.mg_s5_ev"].body_type.value)

    def test_the_es5_aliases_are_gone(self):
        self.assertEqual((), self.catalog.models["mg.mg_es"].aliases)
        for generation in self.catalog.generations_of("mg.mg_es"):
            self.assertNotEqual("ES5", generation.code)

    def test_the_s5_specification_is_no_longer_filed_under_the_es(self):
        variants = [v for v in self.catalog.variants.values()
                    if v.generation_id.startswith("mg.mg_es.")]
        self.assertEqual([51.0], [v.battery_kwh for v in variants])
        self.assertEqual(["UNKNOWN"], [v.drivetrain.value for v in variants])
        self.assertEqual([None], [v.price_thb for v in variants])

    def test_the_two_cars_still_resolve_apart(self):
        self.assertEqual("mg.mg_es",
                         self.catalog.model_index.lookup("MG ES")[0])
        self.assertEqual("mg.mg_s5_ev",
                         self.catalog.model_index.lookup("MG S5 EV")[0])

    def test_a_wagon_drops_out_of_the_crossover_cohort_by_itself(self):
        from vehreg.comparable_specs import ComparableCohort
        self.assertNotIn("mg.mg_es", ComparableCohort.load().model_ids)


class KiaEv6Tests(unittest.TestCase):

    def test_a_car_that_is_not_on_sale_says_so_without_inventing_history(self):
        catalog = Catalog.load(year=2026)
        model = catalog.models["kia.ev6"]
        # Not GREY: that would assert it was never officially sold, which is
        # exactly what has not been established.
        self.assertEqual("UNVERIFIED", model.retail_status.value)
        self.assertEqual("CORE", model.market_scope.value)
        self.assertIn("kia.com/th/en", model.notes)

    def test_no_trim_or_specification_was_invented_for_it(self):
        catalog = Catalog.load(year=2026)
        self.assertEqual([], [t for t in catalog.trims if t.startswith("kia.ev6.")])

    def test_it_has_no_eco_record_and_that_is_not_an_ingestion_fault(self):
        path = (DATA_DIR / "2026/ingest/ecosticker/snapshots/2026-09-08"
                / "normalized.jsonl.gz")
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            matched = {json.loads(line)["matched_model_id"] for line in handle}
        self.assertNotIn("kia.ev6", matched)

    def test_only_current_retail_models_belong_in_a_buyer_comparison(self):
        catalog = Catalog.load(year=2026)
        not_current = {model_id for model_id, model in catalog.models.items()
                       if model.retail_status.value != "CURRENT"}
        from vehreg.comparable_specs import ComparableCohort
        self.assertEqual(set(), not_current & set(ComparableCohort.load().model_ids))


class AudiLabelRuleTests(unittest.TestCase):
    """A trailing "e" is the whole difference, so substring order matters.

    "TFSI" is inside "TFSI e". A combustion rule written first would swallow
    every plug-in Audi in the file, which is why the explicit rules come first
    and the combustion rules say what they are not looking at.
    """

    def rules_for(self, model):
        return [r for r in RULES if r.brand == "Audi" and r.model == model]

    def decide(self, model, label):
        upper = label.upper()
        for rule in self.rules_for(model):
            if rule.raw_any and not any(t in upper for t in rule.raw_any):
                continue
            if any(t in upper for t in rule.raw_none):
                continue
            return rule.powertrain
        return None

    def test_the_plug_in_rule_is_declared_before_the_combustion_rule(self):
        for model in ("Audi Q7", "Audi A6"):
            powertrains = [r.powertrain for r in self.rules_for(model)]
            self.assertEqual("PHEV", powertrains[0], model)
            self.assertNotIn("MIXED", powertrains, model)

    def test_every_label_in_the_warehouse_lands_where_the_owner_said(self):
        cases = [
            ("Audi Q7", "AUDI Q7 60 TFSI e q S line BE", "PHEV"),
            ("Audi Q7", "AUDI Q7 TFSI e q S line edition one", "PHEV"),
            ("Audi Q7", "AUDI Q7 45 TDI q", "ICE"),
            ("Audi Q7", "AUDI Q7 55 TFSI q S line", "ICE"),
            ("Audi Q7", "AUDI Q7 3.0 TDI QUATTRO", "ICE"),
            ("Audi Q7", "AUDI Q7", "ICE"),
            ("Audi A6", "AUDI A6 40 TFSI S line", "ICE"),
            ("Audi A6", "AUDI A6 AV 45 TFSI q S line BE", "ICE"),
            ("Audi A6", "AUDI A6 50 TFSI", "ICE"),
            ("Audi A6", "AUDI A6 2.0 TDI", "ICE"),
            ("Audi A6", "AUDI A6 50 TFSI e", "PHEV"),
            ("Audi A6", "AUDI A6 55 TFSI e quattro", "PHEV"),
            ("Audi A6", "AUDI A6", "ICE"),
        ]
        for model, label, expected in cases:
            self.assertEqual(expected, self.decide(model, label),
                             f"{model}: {label}")

    def test_the_a6_etron_is_a_separate_model_these_rules_never_see(self):
        catalog = Catalog.load(year=2026)
        self.assertEqual("Audi A6 e-tron", catalog.models["audi.a6_etron"].name_en)
        self.assertNotEqual("Audi A6", catalog.models["audi.a6_etron"].name_en)

    def test_both_nameplates_are_marked_owner_reviewed(self):
        catalog = Catalog.load(year=2026)
        for model_id in ("audi.q7", "audi.a6"):
            self.assertTrue(catalog.models[model_id].powertrain_checked, model_id)


if __name__ == "__main__":
    unittest.main()
