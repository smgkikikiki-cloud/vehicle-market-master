"""Offline tests for the registration warehouse. No network, no paid calls."""

import csv
import json
import re
import tempfile
import unittest
from pathlib import Path

from vehreg import (
    allocate, authoring, cube, db, dlt, editor, normalize, taxonomy, trimledger,
)
from vehreg.catalog import (
    DEFAULT_YEAR, Catalog, CatalogError, available_years, fork_year, year_dir,
)
from vehreg.ingest import Resolver, ingest_csv, teach_alias
from vehreg.taxonomy import (
    BodyType, BrandSegment, CabType, Grain, ImportType, MarketPosition,
    MarketScope, Powertrain, RegistrationType, Segment,
)

YEAR = DEFAULT_YEAR


def tiny_payload():
    """One brand covering the structural rules: a pickup split by cab but rolled
    up under one nameplate, a two-generation succession, a folded spec line, and
    a halo model kept out of the default numbers."""
    return {
        "brand": {"id": "acme", "name_en": "Acme", "name_th": "แอคมี่",
                  "brand_segment": "MASS", "oem_group": "Acme Group",
                  "brand_origin": "TH", "aliases": ["แอคมี่"]},
        "models": [
            {"id": "runner_cab", "name_en": "Runner Cab",
             "name_th": "รันเนอร์ ตอนเดียว/แค็บ", "nameplate": "Runner",
             "body_type": "PICKUP",
             "cab_type": "SINGLE_SMART", "aliases": ["Runner"],
             "generations": [{
                 "code": "R1", "segment": "F", "seats": 4,
                 "launched": "2022-01-01",
                 "variants": [
                     {"name": "2.4 Base", "powertrain": "ICE", "drivetrain": "RWD",
                      "engine_cc": 2400, "price_thb": 480000,
                      "import_type": "CKD", "origin_country": "TH"},
                 ]}]},
            {"id": "runner_double_cab", "name_en": "Runner Double Cab",
             "name_th": "รันเนอร์ 4 ประตู", "nameplate": "Runner",
             "body_type": "PICKUP",
             "cab_type": "DOUBLE_CAB", "aliases": ["Runner"],
             "generations": [{
                 "code": "R1", "segment": "F", "seats": 5,
                 "launched": "2022-01-01",
                 "variants": [
                     {"name": "2.4 4x4", "powertrain": "ICE", "drivetrain": "4WD",
                      "engine_cc": 2400, "price_thb": 1250000,
                      "import_type": "CKD", "origin_country": "TH"},
                 ]}]},
            {"id": "volt", "name_en": "Volt", "name_th": "โวลต์",
             "body_type": "CROSSOVER",
             "generations": [
                 {"code": "V1", "segment": "B", "seats": 5,
                  "launched": "2020-03-01", "ended": "2023-03-01",
                  "variants": [
                      {"name": "1.5 Petrol", "powertrain": "ICE",
                       "drivetrain": "FWD", "engine_cc": 1500,
                       "price_thb": 690000, "import_type": "CKD",
                       "origin_country": "TH"},
                  ]},
                 {"code": "V2", "segment": "B", "seats": 5,
                  "launched": "2023-03-01",
                  "variants": [
                      {"name": "50 kWh BEV", "powertrain": "BEV",
                       "drivetrain": "FWD", "battery_kwh": 50.0,
                       "price_thb": 899000, "import_type": "CKD",
                       "origin_country": "TH"},
                      # Four trims folded into one spec line.
                      {"name": "1.5L ICE", "powertrain": "ICE",
                       "drivetrain": "FWD", "engine_cc": 1500,
                       "price_thb": 749000, "price_min_thb": 749000,
                       "price_max_thb": 829000, "import_type": "CKD",
                       "origin_country": "TH",
                       "aliases": ["1.5 E", "1.5 EL", "1.5 RS"]},
                  ]},
             ]},
            {"id": "sprint", "name_en": "Sprint", "name_th": "สปรินท์",
             "body_type": "CROSSOVER",
             "generations": [{
                 "code": "S1", "segment": "B", "seats": 5,
                 "launched": "2025-01-01",
                 "variants": [
                     {"name": "60 kWh BEV", "powertrain": "BEV",
                      "drivetrain": "RWD", "battery_kwh": 60.0,
                      "price_thb": 899000, "import_type": "CKD",
                      "origin_country": "TH"},
                 ]}]},
            {"id": "meteor", "name_en": "Meteor", "name_th": "มีเทีย",
             "body_type": "COUPE", "market_scope": "NICHE",
             "generations": [{
                 "code": "M1", "segment": "D", "seats": 2,
                 "launched": "2024-01-01",
                 "variants": [
                     {"name": "5.0L ICE", "powertrain": "ICE",
                      "drivetrain": "RWD", "engine_cc": 5000,
                      "price_thb": 9900000, "import_type": "CBU",
                      "origin_country": "DE"},
                 ]}]},
        ],
    }


def tiny_catalog(year=YEAR):
    catalog = Catalog(year)
    catalog.add_brand_payload(tiny_payload(), source="<test>")
    catalog.build_indexes()
    return catalog


class TaxonomyTests(unittest.TestCase):
    def test_price_bands_are_contiguous_and_total(self):
        self.assertIs(taxonomy.market_position_for_price(0), MarketPosition.ENTRY)
        self.assertIs(taxonomy.market_position_for_price(499_999),
                      MarketPosition.ENTRY)
        self.assertIs(taxonomy.market_position_for_price(500_000),
                      MarketPosition.VOLUME)
        self.assertIs(taxonomy.market_position_for_price(1_000_000),
                      MarketPosition.UPPER)
        # The brief's 1.8M-2.0M gap is closed rather than left unclassified.
        self.assertIs(taxonomy.market_position_for_price(1_900_000),
                      MarketPosition.LUXURY)
        self.assertIs(taxonomy.market_position_for_price(None),
                      MarketPosition.UNKNOWN)

    def test_powertrain_rollups(self):
        self.assertIs(taxonomy.powertrain_group(Powertrain.REEV),
                      taxonomy.PowertrainGroup.HYBRID)
        self.assertIs(taxonomy.powertrain_group(Powertrain.parse("MHEV")),
                      taxonomy.PowertrainGroup.COMBUSTION)
        self.assertIs(taxonomy.market_powertrain(Powertrain.HEV),
                      taxonomy.MarketPowertrain.HYBRID)
        self.assertIs(taxonomy.market_powertrain(Powertrain.REEV),
                      taxonomy.MarketPowertrain.REEV)
        self.assertIs(Powertrain.parse("EREV"), Powertrain.REEV)
        with self.assertRaises(ValueError):
            Powertrain.parse("RANGE_EXTENDER")
        self.assertTrue(taxonomy.is_plug_in(Powertrain.PHEV))
        self.assertFalse(taxonomy.is_plug_in(Powertrain.HEV))
        # A mild hybrid is not xEV here: it folds to ICE before it is asked.
        self.assertFalse(taxonomy.is_electrified(Powertrain.parse("MHEV")))

    def test_facets_parse_common_aliases(self):
        self.assertIs(Powertrain.parse("ev"), Powertrain.BEV)
        self.assertIs(BodyType.parse("body on frame suv"), BodyType.PPV)
        self.assertIs(CabType.parse("space cab"), CabType.SMART_CAB)
        self.assertIs(RegistrationType.parse("รย.3"), RegistrationType.RY3)
        with self.assertRaises(ValueError):
            Powertrain.parse("steam")

    def test_double_cab_is_ry1_and_other_cabs_are_ry3(self):
        self.assertIs(taxonomy.registration_type_for(BodyType.PICKUP,
                                                     CabType.SINGLE_SMART),
                      RegistrationType.RY3)
        self.assertIs(taxonomy.registration_type_for(BodyType.PICKUP,
                                                     CabType.DOUBLE_CAB),
                      RegistrationType.RY1)
        self.assertIs(taxonomy.registration_type_for(BodyType.PICKUP,
                                                     CabType.SMART_CAB),
                      RegistrationType.RY3)
        self.assertIs(taxonomy.registration_type_for(BodyType.PICKUP,
                                                     CabType.SINGLE_CAB),
                      RegistrationType.RY3)
        self.assertIs(taxonomy.registration_type_for(BodyType.PPV,
                                                     CabType.NOT_APPLICABLE),
                      RegistrationType.RY1)
        self.assertTrue(taxonomy.check_registration(
            BodyType.PICKUP, CabType.DOUBLE_CAB, RegistrationType.RY3))
        self.assertFalse(taxonomy.check_registration(
            BodyType.PICKUP, CabType.DOUBLE_CAB, RegistrationType.RY1))
        # รย.2 is the owner's call for >7 seats and is never contradicted.
        self.assertFalse(taxonomy.check_registration(
            BodyType.MPV, CabType.NOT_APPLICABLE, RegistrationType.RY2))

    def test_cross_facet_rules_reject_impossible_combinations(self):
        self.assertTrue(taxonomy.check_body_segment(
            BodyType.PICKUP, CabType.NOT_APPLICABLE, Segment.F))
        self.assertTrue(taxonomy.check_body_segment(
            BodyType.SEDAN, CabType.DOUBLE_CAB, Segment.C))
        self.assertFalse(taxonomy.check_body_segment(
            BodyType.PICKUP, CabType.DOUBLE_CAB, Segment.F))
        self.assertTrue(taxonomy.check_powertrain(Powertrain.BEV, 60.0, 1500))
        self.assertTrue(taxonomy.check_origin(ImportType.CKD, "CN"))


class ResolutionTests(unittest.TestCase):
    def setUp(self):
        self.catalog = tiny_catalog()

    def test_every_facet_resolves_with_provenance(self):
        resolved = self.catalog.resolve("acme.runner_double_cab.r1.2_4_4x4")
        self.assertEqual(resolved["brand"], "Acme")
        self.assertIs(resolved["segment"], Segment.F)
        self.assertIs(resolved["body_type"], BodyType.PICKUP)
        self.assertIs(resolved["cab_type"], CabType.DOUBLE_CAB)
        self.assertIs(resolved["registration_type"], RegistrationType.RY1)
        self.assertIs(resolved["market_position"], MarketPosition.UPPER)
        self.assertIs(resolved["brand_segment"], BrandSegment.MASS)
        self.assertEqual(resolved.year, YEAR)
        self.assertEqual(resolved.provenance["brand_segment"], "brand")
        self.assertEqual(resolved.provenance["body_type"], "model")
        self.assertEqual(resolved.provenance["cab_type"], "model")
        self.assertEqual(resolved.provenance["segment"], "generation")
        self.assertEqual(resolved.provenance["market_position"], "variant")
        self.assertEqual(resolved.provenance["powertrain_group"], "derived")

    def test_lower_layer_overrides_higher_layer(self):
        payload = tiny_payload()
        payload["models"][2]["generations"][1]["variants"][0]["overrides"] = {
            "brand_segment": "PREMIUM_TECH"}
        catalog = Catalog(YEAR)
        catalog.add_brand_payload(payload)
        catalog.build_indexes()
        resolved = catalog.resolve("acme.volt.v2.50_kwh_bev")
        self.assertIs(resolved["brand_segment"], BrandSegment.PREMIUM_TECH)
        self.assertEqual(resolved.provenance["brand_segment"], "variant")

    def test_body_and_cab_cannot_be_overridden_below_the_model(self):
        payload = tiny_payload()
        payload["models"][2]["generations"][1]["variants"][0]["overrides"] = {
            "body_type": "HATCHBACK"}
        catalog = Catalog(YEAR)
        catalog.add_brand_payload(payload)
        catalog.build_indexes()
        problems = catalog.validate()
        self.assertTrue(any("cannot override body_type" in p for p in problems))
        # And the override is ignored rather than silently applied.
        self.assertIs(catalog.resolve("acme.volt.v2.50_kwh_bev")["body_type"],
                      BodyType.CROSSOVER)

    def test_registration_type_defaults_from_body_and_cab(self):
        self.assertIs(self.catalog.models["acme.runner_cab"].registration_type,
                      RegistrationType.RY3)
        self.assertIs(self.catalog.models["acme.runner_double_cab"].registration_type,
                      RegistrationType.RY1)
        self.assertIs(self.catalog.models["acme.volt"].registration_type,
                      RegistrationType.RY1)

    def test_a_pickup_model_must_name_its_cab(self):
        payload = tiny_payload()
        payload["models"][0]["cab_type"] = "NOT_APPLICABLE"
        catalog = Catalog(YEAR)
        catalog.add_brand_payload(payload)
        catalog.build_indexes()
        self.assertTrue(any("must name its cab_type" in p
                            for p in catalog.validate()))

    def test_same_name_and_body_twice_is_a_duplicate_not_a_split(self):
        payload = tiny_payload()
        clone = json.loads(json.dumps(payload["models"][2]))
        clone["id"] = "volt_again"
        payload["models"].append(clone)
        catalog = Catalog(YEAR)
        catalog.add_brand_payload(payload)
        catalog.build_indexes()
        self.assertTrue(any("same name and body" in p
                            for p in catalog.validate()))

    def test_split_models_roll_back_up_under_one_nameplate(self):
        plates = self.catalog.nameplates()
        self.assertEqual(
            sorted(plates["Acme Runner"]),
            ["acme.runner_cab", "acme.runner_double_cab"])
        # A model that was never split is its own nameplate.
        self.assertEqual(plates["Acme Volt"], ["acme.volt"])
        for model_id in plates["Acme Runner"]:
            self.assertEqual(self.catalog.resolve(
                self.catalog.variants_of(model_id)[0].id)["nameplate"], "Runner")

    def test_a_blank_nameplate_falls_back_to_the_base_name(self):
        payload = tiny_payload()
        for model in payload["models"]:
            model.pop("nameplate", None)
        catalog = Catalog(YEAR)
        catalog.add_brand_payload(payload)
        catalog.build_indexes()
        # "Runner Single Cab" -> "Runner" without the owner typing anything.
        self.assertIn("Acme Runner", catalog.nameplates())

    def test_generations_read_as_a_succession(self):
        codes = [gen.code for gen, _ in self.catalog.succession("acme.volt")]
        self.assertEqual(codes, ["V1", "V2"])          # oldest first
        older, newer = self.catalog.generations_of("acme.volt")
        self.assertEqual(older.ended, newer.launched)

    def test_out_of_scope_models_stay_in_the_catalog(self):
        meteor = self.catalog.models["acme.meteor"]
        self.assertIs(meteor.market_scope, MarketScope.NICHE)
        # Still resolvable, so a DLT row naming it does not go to review.
        self.assertIs(self.catalog.resolve("acme.meteor.m1.5_0l_ice")
                      ["market_scope"], MarketScope.NICHE)
        self.assertEqual(self.catalog.coverage()["models_niche"], 1)

    def test_a_folded_line_may_not_straddle_a_price_band(self):
        payload = tiny_payload()
        line = payload["models"][2]["generations"][1]["variants"][1]
        line["price_max_thb"] = 1_200_000        # was 829,000: VOLUME -> UPPER
        catalog = Catalog(YEAR)
        catalog.add_brand_payload(payload)
        catalog.build_indexes()
        self.assertTrue(any("split this line" in p for p in catalog.validate()))

    def test_seeded_catalog_is_internally_consistent(self):
        catalog = Catalog.load()
        self.assertEqual(catalog.year, YEAR)
        self.assertEqual(catalog.validate(), [])
        self.assertGreater(catalog.coverage()["models"], 100)

    def test_every_seeded_pickup_is_split_by_cab(self):
        catalog = Catalog.load()
        pickups = [m for m in catalog.models.values()
                   if m.body_type is BodyType.PICKUP]
        self.assertTrue(pickups)
        for model in pickups:
            self.assertIsNot(model.cab_type, CabType.NOT_APPLICABLE, model.id)
            expected = (RegistrationType.RY1
                        if model.cab_type is CabType.DOUBLE_CAB
                        else RegistrationType.RY3)
            self.assertIs(model.registration_type, expected, model.id)

    def test_every_seeded_pickup_nameplate_resolves_per_dlt_class(self):
        """The whole point of the two-way cab split: DLT prints the bare
        nameplate, and each รย. class must leave exactly one model."""
        catalog = Catalog.load()
        conn = db.connect(":memory:")
        db.rebuild_dimension(conn, catalog)
        resolver = Resolver(catalog, conn)

        # Group by the name DLT actually prints - "HILUX REVO", "HILUX CHAMP"
        # - which is the model name minus its cab suffix, not the wider
        # reporting roll-up that puts every Hilux together.
        plates: dict[tuple[str, str], set[str]] = {}
        for model in catalog.models.values():
            if model.body_type is BodyType.PICKUP:
                plates.setdefault(
                    (model.brand_id, normalize.base_nameplate(model.name_en)),
                    set()).add(model.registration_type.value)

        for (brand_id, plate), classes in plates.items():
            brand = catalog.brands[brand_id]
            for reg in sorted(classes):
                unit_id, grain, _, _, reason = resolver.resolve(
                    brand.name_en, plate, reg=reg)
                self.assertEqual(reason, "", f"{brand.name_en} {plate} {reg}")
                self.assertEqual(grain, Grain.MODEL)
                self.assertEqual(
                    catalog.models[unit_id].registration_type.value, reg)

    def test_a_split_body_never_steals_the_base_nameplate(self):
        """Mazda2 is the sedan and Mazda2 Hatchback is not, the same way City
        is the sedan - so a bare label lands on the base body, not on a tie."""
        catalog = Catalog.load()
        conn = db.connect(":memory:")
        resolver = Resolver(catalog, conn)
        for brand, plate, expected in (("Mazda", "MAZDA 2", "mazda.mazda2"),
                                       ("Honda", "CITY", "honda.city")):
            unit_id, _, _, _, reason = resolver.resolve(brand, plate, reg="RY1")
            self.assertEqual((unit_id, reason), (expected, ""))
        self.assertEqual(
            resolver.resolve("Honda", "CITY HATCHBACK", reg="RY1")[0],
            "honda.city_hatchback")
        self.assertIn("mazda.mazda2_hatchback", catalog.models)

    def test_duplicate_ids_are_rejected(self):
        catalog = Catalog(YEAR)
        catalog.add_brand_payload(tiny_payload())
        with self.assertRaises(CatalogError):
            catalog.add_brand_payload(tiny_payload())


class YearTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dir = Path(self.temp.name)
        target = year_dir(self.dir, YEAR)
        target.mkdir(parents=True)
        (target / "acme.json").write_text(
            json.dumps(tiny_payload(), ensure_ascii=False), encoding="utf-8")

    def test_load_is_scoped_to_one_year(self):
        catalog = Catalog.load(self.dir, YEAR)
        self.assertEqual(catalog.year, YEAR)
        self.assertEqual(available_years(self.dir), [YEAR])
        with self.assertRaises(CatalogError):
            Catalog.load(self.dir, YEAR - 1)

    def test_fork_copies_and_then_diverges(self):
        fork_year(self.dir, YEAR, YEAR + 1)
        self.assertEqual(available_years(self.dir), [YEAR, YEAR + 1])
        with self.assertRaises(CatalogError):
            fork_year(self.dir, YEAR, YEAR + 1)

        path = self.dir / "bump.csv"
        with open(path, "w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(authoring.COLUMNS),
                                    extrasaction="ignore")
            writer.writeheader()
            writer.writerow({"brand": "Acme", "model": "Volt",
                             "generation": "V2", "variant": "50 kWh BEV",
                             "price_thb": "1150000"})
        authoring.import_csv(path, self.dir, year=YEAR + 1)

        this_year = Catalog.load(self.dir, YEAR)
        next_year = Catalog.load(self.dir, YEAR + 1)
        self.assertIs(this_year.resolve("acme.volt.v2.50_kwh_bev")
                      ["market_position"], MarketPosition.VOLUME)
        self.assertIs(next_year.resolve("acme.volt.v2.50_kwh_bev")
                      ["market_position"], MarketPosition.UPPER)


class NormalisationTests(unittest.TestCase):
    def test_period_parsing_handles_thai_and_buddhist_era(self):
        self.assertEqual(normalize.period_key("2026-03"), "2026-03")
        self.assertEqual(normalize.period_key("มี.ค. 2569"), "2026-03")
        self.assertEqual(normalize.period_key("Mar 2026"), "2026-03")
        with self.assertRaises(ValueError):
            normalize.period_key("ไม่ระบุ")

    def test_longest_name_wins_over_a_shorter_prefix(self):
        index = normalize.MatchIndex()
        index.add("yaris", ["Yaris"], priority=1)
        index.add("yaris_ativ", ["Yaris Ativ"], priority=1)
        key, _, how = index.lookup("YARIS ATIV 1.2 SMART")
        self.assertEqual(key, "yaris_ativ")
        self.assertEqual(how, "contains")
        self.assertEqual(index.lookup("YARIS 1.2 PLAY")[0], "yaris")

    def test_a_surface_owned_by_two_keys_is_ambiguous(self):
        index = normalize.MatchIndex()
        index.add("single", ["Runner Single Cab"], priority=1)
        index.add("single", ["Runner"])
        index.add("smart", ["Runner Smart Cab"], priority=1)
        index.add("smart", ["Runner"])
        self.assertEqual(index.lookup("Runner")[2], "ambiguous")
        self.assertEqual(index.ambiguous_candidates("Runner"), ["single", "smart"])
        self.assertEqual(index.lookup("Runner Smart Cab")[0], "smart")

    def test_a_real_name_outranks_another_models_alias(self):
        index = normalize.MatchIndex()
        index.add("city", ["City"], priority=1)
        index.add("city_hatch", ["City Hatchback"], priority=1)
        index.add("city_hatch", ["City"])          # derived from the split
        self.assertEqual(index.lookup("City")[0], "city")
        self.assertEqual(index.lookup("City Hatchback")[0], "city_hatch")


class WarehouseTests(unittest.TestCase):
    def setUp(self):
        self.catalog = tiny_catalog()
        self.conn = db.connect(":memory:")
        db.rebuild_dimension(self.conn, self.catalog)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dir = Path(self.temp.name)

    def write_csv(self, rows, name="dlt.csv",
                  header=("เดือน", "ยี่ห้อ", "แบบรถ", "รุ่นย่อย", "จำนวน")):
        path = self.dir / name
        with open(path, "w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.writer(handle)
            writer.writerow(header)
            writer.writerows(rows)
        return path

    def test_dimension_has_one_row_per_unit_per_year(self):
        rows = self.conn.execute(
            "SELECT catalog_year, market_position, registration_type "
            "FROM dim_unit WHERE unit_id = 'acme.runner_double_cab.r1.2_4_4x4'"
        ).fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["catalog_year"], YEAR)
        self.assertEqual(rows[0]["registration_type"], "RY1")
        self.assertEqual(db.loaded_years(self.conn), [YEAR])

    def test_model_grain_row_reports_mixed_only_where_trims_disagree(self):
        row = self.conn.execute(
            "SELECT * FROM dim_unit WHERE unit_id = 'acme.volt' "
            "AND grain = 'MODEL'").fetchone()
        self.assertEqual(row["body_type"], "CROSSOVER")   # both trims agree
        self.assertEqual(row["segment"], "B")
        self.assertEqual(row["powertrain"], db.MIXED)     # BEV vs ICE

    def test_ingest_matches_and_preserves_totals(self):
        path = self.write_csv([
            (f"{YEAR}-02", "Acme", "Runner Double Cab", "2.4 4x4", "120"),
            (f"{YEAR}-02", "แอคมี่", "Volt", "", "300"),
            (f"ก.พ. {YEAR + 543}", "Acme", "Volt", "50 kWh BEV", "80"),
            (f"{YEAR}-02", "Nonexist", "Ghost", "", "45"),
        ])
        report = ingest_csv(self.conn, self.catalog, path, "test")
        self.assertEqual(report.rows_read, 4)
        self.assertEqual(report.units_matched, 500.0)
        self.assertEqual(report.units_review, 45.0)
        self.assertEqual(report.by_grain["VARIANT"], 2)
        self.assertEqual(report.by_grain["MODEL"], 1)

    def test_a_year_with_no_catalog_is_queued_not_classified(self):
        path = self.write_csv([("2019-05", "Acme", "Volt", "", "500")])
        report = ingest_csv(self.conn, self.catalog, path, "old")
        self.assertEqual(report.units_matched, 0.0)
        self.assertEqual(report.units_review, 500.0)
        reason = self.conn.execute(
            "SELECT reason FROM ingest_review").fetchone()["reason"]
        self.assertEqual(reason, "no-catalog-for-year")

    def test_reingesting_the_same_file_does_not_double_count(self):
        path = self.write_csv([(f"{YEAR}-02", "Acme", "Volt", "", "300")])
        ingest_csv(self.conn, self.catalog, path, "test")
        ingest_csv(self.conn, self.catalog, path, "test")
        total = self.conn.execute(
            "SELECT SUM(units) AS u FROM fact_registration").fetchone()["u"]
        self.assertEqual(total, 300.0)

    def test_unmatched_rows_are_queued_never_guessed(self):
        path = self.write_csv([(f"{YEAR}-02", "Nonexist", "Ghost", "", "45")])
        ingest_csv(self.conn, self.catalog, path, "test")
        row = self.conn.execute(
            "SELECT raw_label, reason, units FROM ingest_review").fetchone()
        self.assertEqual(row["reason"], "brand-not-found")
        self.assertEqual(row["units"], 45.0)
        self.assertIsNone(self.conn.execute(
            "SELECT SUM(units) AS u FROM fact_registration").fetchone()["u"])

    def test_the_dlt_class_disambiguates_a_split_pickup(self):
        resolver = Resolver(self.catalog, self.conn)
        # รย.1 leaves only the double cab in scope.
        unit_id, grain, _, _, reason = resolver.resolve("Acme", "Runner",
                                                        reg="RY1")
        self.assertEqual(unit_id, "acme.runner_double_cab")
        self.assertEqual(reason, "")
        # รย.3 leaves exactly one model too, because a nameplate is split the
        # two ways the registration data actually distinguishes.
        unit_id, _, _, _, reason = resolver.resolve("Acme", "Runner", reg="RY3")
        self.assertEqual(unit_id, "acme.runner_cab")
        self.assertEqual(reason, "")
        # A รย.2 pickup is a passenger conversion, so it follows the รย.1 body.
        self.assertEqual(resolver.resolve("Acme", "Runner", reg="RY2")[0],
                         "acme.runner_double_cab")

    def test_a_lesson_can_be_limited_to_one_dlt_class(self):
        rows = [(f"{YEAR}-02", "Acme", "Runner", "", "90")]
        path = self.write_csv(rows)
        # Taught lessons override the class tie-break, and only for that class.
        teach_alias(self.conn, "model", "Acme Runner",
                    "acme.runner_double_cab", reg="RY3")
        report = ingest_csv(self.conn, self.catalog, path, "taught",
                            default_registration_type="RY3")
        self.assertEqual(report.by_grain, {"MODEL": 1})
        self.assertEqual(report.units_matched, 90.0)
        unit_id = self.conn.execute(
            "SELECT unit_id FROM fact_registration").fetchone()["unit_id"]
        self.assertEqual(unit_id, "acme.runner_double_cab")
        # The lesson is scoped: รย.1 still resolves to the double cab.
        resolver = Resolver(self.catalog, self.conn)
        self.assertEqual(resolver.resolve("Acme", "Runner", reg="RY1")[0],
                         "acme.runner_double_cab")

    def test_a_bare_model_label_never_claims_trim_grain(self):
        # DLT publishes no trim-level volume. A label that only names the model
        # must not match a folded line just because one of its aliases matches.
        path = self.write_csv([(f"{YEAR}-03", "Acme", "Volt", "", "260")],
                              name="bare.csv")
        report = ingest_csv(self.conn, self.catalog, path, "bare")
        self.assertEqual(report.by_grain, {"MODEL": 1})
        # A label that does say more still resolves to the spec line.
        path = self.write_csv([(f"{YEAR}-03", "Acme", "Volt", "1.5 EL", "40")],
                              name="trim.csv")
        report = ingest_csv(self.conn, self.catalog, path, "trim")
        self.assertEqual(report.by_grain, {"VARIANT": 1})

    def test_brand_scoping_stops_a_cross_brand_match(self):
        resolver = Resolver(self.catalog, self.conn)
        self.assertEqual(resolver.resolve("Acme", "Volt")[0], "acme.volt")
        self.assertIsNone(resolver.resolve("Nonexist", "Volt")[0])

    def test_wide_layout_is_unpivoted(self):
        path = self.dir / "wide.csv"
        with open(path, "w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.writer(handle)
            writer.writerow(["ยี่ห้อ", "แบบรถ", f"ม.ค. {YEAR + 543}",
                             f"ก.พ. {YEAR + 543}"])
            writer.writerow(["Acme", "Volt", "100", "150"])
        report = ingest_csv(self.conn, self.catalog, path, "wide", wide=True)
        self.assertEqual(report.units_matched, 250.0)
        periods = [r["period"] for r in self.conn.execute(
            "SELECT DISTINCT period FROM fact_registration ORDER BY period")]
        self.assertEqual(periods, [f"{YEAR}-01", f"{YEAR}-02"])


class CubeTests(unittest.TestCase):
    def setUp(self):
        self.catalog = tiny_catalog()
        self.conn = db.connect(":memory:")
        db.rebuild_dimension(self.conn, self.catalog)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        path = Path(self.temp.name) / "facts.csv"
        with open(path, "w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.writer(handle)
            writer.writerow(["เดือน", "ยี่ห้อ", "แบบรถ", "รุ่นย่อย", "จำนวน"])
            writer.writerows([
                (f"{YEAR}-05", "Acme", "Runner Cab", "2.4 Base", "300"),
                (f"{YEAR}-05", "Acme", "Runner Double Cab", "2.4 4x4", "100"),
                (f"{YEAR}-05", "Acme", "Volt", "", "200"),
                (f"{YEAR}-09", "Acme", "Runner Cab", "2.4 Base", "400"),
                (f"{YEAR}-09", "Acme", "Volt", "50 kWh BEV", "150"),
                (f"{YEAR}-09", "Acme", "Volt", "1.5 EL", "50"),
                (f"{YEAR}-09", "Acme", "Meteor", "", "30"),
            ])
        ingest_csv(self.conn, self.catalog, path, "facts")

    def test_any_facet_crosses_any_other(self):
        result = cube.run(self.conn, ["body_type", "market_position"])
        self.assertEqual(result.total_units, 1200.0)
        keys = {(r["body_type"], r["market_position"]) for r in result.rows}
        self.assertIn(("PICKUP", "ENTRY"), keys)
        self.assertIn(("PICKUP", "UPPER"), keys)

    def test_cab_and_registration_class_cross_cleanly(self):
        result = cube.run(self.conn, ["cab_type", "registration_type"],
                          filters={"body_type": "PICKUP"})
        rows = {(r["cab_type"], r["registration_type"]): r["units"]
                for r in result.rows}
        self.assertEqual(rows[("SINGLE_SMART", "RY3")], 700.0)
        self.assertEqual(rows[("DOUBLE_CAB", "RY1")], 100.0)

    def test_model_grain_volume_shows_as_mixed_not_as_a_guess(self):
        result = cube.run(self.conn, ["powertrain"], period_to=f"{YEAR}-06")
        mixed = [r for r in result.rows if r["powertrain"] == db.MIXED]
        self.assertEqual(mixed[0]["units"], 200.0)
        self.assertEqual(result.mixed_units, 200.0)

    def test_allocation_splits_mixed_and_conserves_the_total(self):
        allocate.derive_weights(self.conn, fallback="all")
        plain = cube.run(self.conn, ["powertrain"])
        split = cube.run(self.conn, ["powertrain"], allocate=True)
        self.assertAlmostEqual(plain.total_units, split.total_units)
        self.assertEqual(split.mixed_units, 0.0)
        self.assertGreater(split.estimated_units, 0.0)
        bev = next(r for r in split.rows if r["powertrain"] == "BEV")
        # 150 reported + 3/4 of the 200 model-grain row (150 BEV : 50 ICE).
        self.assertAlmostEqual(bev["units"], 300.0)

    def test_reports_default_to_core_and_say_what_they_left_out(self):
        core = cube.run(self.conn, ["brand"])
        everything = cube.run(self.conn, ["brand"], scopes="all")
        self.assertLess(core.total_units, everything.total_units)
        self.assertEqual(core.excluded_by_scope, {"NICHE": 30.0})
        self.assertAlmostEqual(core.total_units + core.excluded_units,
                               everything.total_units)
        self.assertEqual(everything.excluded_by_scope, {})
        widened = cube.run(self.conn, ["brand"], scopes=["CORE", "NICHE"])
        self.assertAlmostEqual(widened.total_units, everything.total_units)

    def test_nameplate_rolls_the_split_pickup_models_together(self):
        result = cube.run(self.conn, ["nameplate"],
                          filters={"body_type": "PICKUP"})
        rows = {r["nameplate"]: r["units"] for r in result.rows}
        self.assertEqual(rows["Runner"], 800.0)     # 300 + 100 + 400

    def test_unknown_group_by_is_rejected(self):
        with self.assertRaises(ValueError):
            cube.run(self.conn, ["colour"])
        with self.assertRaises(ValueError):
            cube.run(self.conn, ["brand"], filters={"1=1; DROP TABLE x": 1})

    def test_pivot_reshapes_without_losing_units(self):
        result = cube.run(self.conn, ["body_type", "powertrain"])
        _, rows = cube.pivot(result, "powertrain")
        self.assertAlmostEqual(sum(r["total"] for r in rows), result.total_units)

    def test_coverage_names_the_years_present(self):
        report = cube.coverage_report(self.conn)
        self.assertEqual(report["fact_years"], [YEAR])
        self.assertEqual(report["units_without_dimension_row"], 0)


class DltFeedTests(unittest.TestCase):
    """Parsing of the DLT open-data feed. No network: these are pure shape tests."""

    def test_resource_names_yield_their_period(self):
        monthly = "รถจดทะเบียนครั้งแรก (รถยนต์)-จำแนกตามยี่ห้อและรุ่น มกราคม 2569"
        yearly = "รถจดทะเบียนครั้งแรก (รถยนต์)-จำแนกตามยี่ห้อและรุ่น ปี 2568"
        self.assertEqual(dlt._classify_resource(monthly), ("2026-01", 2026))
        self.assertEqual(dlt._classify_resource(yearly), (None, 2025))

    def test_only_the_three_car_classes_become_facts(self):
        records = [
            {"ประเภทรถ": "รถยนต์นั่งส่วนบุคคลไม่เกิน 7 คน", "ยี่ห้อ": "TOYOTA",
             "รุ่น": "YARIS ATIV", "จำนวน": 4213},
            {"ประเภทรถ": "รถยนต์บรรทุกส่วนบุคคล", "ยี่ห้อ": "TOYOTA",
             "รุ่น": "HILUX REVO", "จำนวน": 2500},
            {"ประเภทรถ": "รถยนต์นั่งส่วนบุคคลเกิน 7 คน", "ยี่ห้อ": "TOYOTA",
             "รุ่น": "COMMUTER", "จำนวน": 600},
            {"ประเภทรถ": "รถจักรยานยนต์", "ยี่ห้อ": "HONDA", "รุ่น": "WAVE",
             "จำนวน": 154124},
            {"ประเภทรถ": "รถแทร็กเตอร์", "ยี่ห้อ": "KUBOTA", "รุ่น": "M",
             "จำนวน": 3380},
        ]
        rows, skipped, units = dlt._to_rows(records, "2026-01")
        self.assertEqual([r["ประเภท"] for r in rows], ["RY1", "RY3", "RY2"])
        self.assertEqual(units, 7313)
        # Skipped classes are counted, never silently dropped.
        self.assertEqual(skipped,
                         {"รถจักรยานยนต์": 154124, "รถแทร็กเตอร์": 3380})

    def test_the_same_nameplate_appears_under_several_classes(self):
        # This is why the DLT class has to disambiguate a split pickup: DLT
        # prints "HILUX REVO" for the double cab and for the other cabs alike.
        records = [
            {"ประเภทรถ": "รถยนต์นั่งส่วนบุคคลไม่เกิน 7 คน", "ยี่ห้อ": "TOYOTA",
             "รุ่น": "HILUX REVO", "จำนวน": 23057},
            {"ประเภทรถ": "รถยนต์บรรทุกส่วนบุคคล", "ยี่ห้อ": "TOYOTA",
             "รุ่น": "HILUX REVO", "จำนวน": 35314},
        ]
        rows, _, _ = dlt._to_rows(records, "2026-01")
        self.assertEqual({r["ประเภท"] for r in rows}, {"RY1", "RY3"})
        self.assertEqual({r["แบบรถ"] for r in rows}, {"HILUX REVO"})

    def test_unreadable_counts_do_not_crash_the_load(self):
        rows, _, units = dlt._to_rows(
            [{"ประเภทรถ": "รถยนต์นั่งส่วนบุคคลไม่เกิน 7 คน", "ยี่ห้อ": "X",
              "รุ่น": "Y", "จำนวน": "-"}], "2026-01")
        self.assertEqual((len(rows), units), (1, 0))

    def test_the_written_columns_match_the_declared_column_map(self):
        mapping = dlt.column_map()
        for column in (mapping.period, mapping.brand, mapping.model,
                       mapping.units, mapping.registration_type):
            self.assertIn(column, dlt.CSV_HEADER)
        self.assertEqual(mapping.missing(), [])


class TrimLedgerTests(unittest.TestCase):
    """The second set of books: split for the marques that publish trim,
    while the master stays folded for every brand."""

    def setUp(self):
        payload = tiny_payload()
        # Acme now behaves like a Chinese marque: DLT prints trim in its
        # รุ่น field.
        payload["brand"]["trim_detail"] = True
        self.catalog = Catalog(YEAR)
        self.catalog.add_brand_payload(payload)
        self.catalog.build_indexes()
        self.conn = db.connect(":memory:")
        db.rebuild_dimension(self.conn, self.catalog)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dir = Path(self.temp.name)

    def load(self, rows, name="dlt.csv"):
        path = self.dir / name
        with open(path, "w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.writer(handle)
            writer.writerow(["เดือน", "ยี่ห้อ", "แบบรถ", "จำนวน"])
            writer.writerows(rows)
        return ingest_csv(self.conn, self.catalog, path, name)

    def test_parse_pulls_grade_range_drive_and_powertrain(self):
        spec = trimledger.parse_trim("(410KM-PREMIUM)")
        self.assertEqual((spec.grade, spec.range_km), ("PREMIUM", 410.0))
        spec = trimledger.parse_trim("V23 4WD PEAK")
        self.assertEqual((spec.grade, spec.drive), ("PEAK", "4WD"))
        spec = trimledger.parse_trim("S05 REEV MAX")
        self.assertEqual((spec.grade, spec.powertrain_hint), ("MAX", "REEV"))
        spec = trimledger.parse_trim("5 EV Long Range Max")
        self.assertEqual(spec.grade, "LONG RANGE MAX")
        self.assertEqual(spec.powertrain_hint, "BEV")
        blank = trimledger.parse_trim("")
        self.assertEqual((blank.grade, blank.range_km), (None, None))

    def test_the_trim_label_is_what_the_source_added(self):
        label = trimledger.residual_trim(self.catalog, "acme.sprint",
                                         "Acme Sprint (500KM-PREMIUM)")
        self.assertEqual(label, "500KM-PREMIUM")
        # Nothing beyond the names means no trim was published.
        self.assertEqual(
            trimledger.residual_trim(self.catalog, "acme.sprint", "Acme Sprint"),
            "")

    def test_master_folds_the_trims_and_the_ledger_splits_them(self):
        report = self.load([
            (f"{YEAR}-01", "Acme", "Sprint (400KM-STD)", "100"),
            (f"{YEAR}-01", "Acme", "Sprint (500KM-PREMIUM)", "60"),
        ])
        self.assertEqual(report.by_grain, {"MODEL": 2})     # master folded
        master = cube.run(self.conn, ["model"], filters={"model": "Sprint"})
        self.assertEqual(master.total_units, 160.0)
        self.assertEqual(len(master.rows), 1)               # one row, one model

        ledger = trimledger.rows(self.conn)
        self.assertEqual({r["trim_label"] for r in ledger},
                         {"400KM-STD", "500KM-PREMIUM"})
        self.assertEqual(sum(r["units"] for r in ledger), 160.0)
        self.assertEqual({r["grade"] for r in ledger}, {"STD", "PREMIUM"})
        self.assertEqual(trimledger.reconcile(self.conn), [])

    def test_the_ledger_carries_the_master_facets_for_cross_tabs(self):
        self.load([(f"{YEAR}-01", "Acme", "Sprint (500KM-PREMIUM)", "60")])
        row = trimledger.rows(self.conn)[0]
        self.assertEqual(row["segment"], "B")
        self.assertEqual(row["body_type"], "CROSSOVER")
        self.assertEqual(row["powertrain"], "BEV")
        self.assertEqual(row["market_position"], "VOLUME")

    def test_brands_that_do_not_publish_trim_are_left_out(self):
        payload = tiny_payload()          # trim_detail defaults to False
        catalog = Catalog(YEAR)
        catalog.add_brand_payload(payload)
        catalog.build_indexes()
        conn = db.connect(":memory:")
        db.rebuild_dimension(conn, catalog)
        path = self.dir / "plain.csv"
        with open(path, "w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.writer(handle)
            writer.writerow(["เดือน", "ยี่ห้อ", "แบบรถ", "จำนวน"])
            writer.writerow([f"{YEAR}-01", "Acme", "Sprint", "60"])
        report = ingest_csv(conn, catalog, path, "plain")
        self.assertEqual(report.trim_rows, 0)
        self.assertEqual(trimledger.rows(conn), [])

    def test_a_mismatch_between_the_two_books_is_reported(self):
        self.load([(f"{YEAR}-01", "Acme", "Sprint (400KM-STD)", "100")])
        self.assertEqual(trimledger.reconcile(self.conn), [])
        with self.conn:
            self.conn.execute(
                "UPDATE fact_registration SET units = 90 "
                "WHERE unit_id = 'acme.sprint'")
        problems = trimledger.reconcile(self.conn)
        self.assertEqual(len(problems), 1)
        self.assertEqual(problems[0]["difference"], 10.0)

    def test_reconcile_does_not_fan_out_across_years(self):
        """dim_trim is keyed by (trim_id, catalog_year), so a trim that exists
        in several years must still be counted once per fact."""
        self.load([(f"{YEAR}-01", "Acme", "Sprint (400KM-STD)", "100")])
        # Same catalog, next year, same trim id.
        next_year = Catalog(YEAR + 1)
        payload = tiny_payload()
        payload["brand"]["trim_detail"] = True
        next_year.add_brand_payload(payload)
        next_year.build_indexes()
        db.rebuild_dimension(self.conn, next_year)
        path = self.dir / "next.csv"
        with open(path, "w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.writer(handle)
            writer.writerow(["เดือน", "ยี่ห้อ", "แบบรถ", "จำนวน"])
            writer.writerow([f"{YEAR + 1}-01", "Acme", "Sprint (400KM-STD)", "70"])
        ingest_csv(self.conn, next_year, path, "next")

        years = self.conn.execute(
            "SELECT COUNT(DISTINCT catalog_year) n FROM dim_trim").fetchone()["n"]
        self.assertEqual(years, 2)
        self.assertEqual(trimledger.reconcile(self.conn), [])
        totals = {r["period"]: r["units"] for r in trimledger.rows(self.conn)}
        self.assertEqual(totals, {f"{YEAR}-01": 100.0, f"{YEAR + 1}-01": 70.0})

    def test_export_writes_its_own_file(self):
        self.load([(f"{YEAR}-01", "Acme", "Sprint (400KM-STD)", "100")])
        out = self.dir / "trims.csv"
        count = trimledger.export_csv(self.conn, out)
        self.assertEqual(count, 1)
        with open(out, encoding="utf-8-sig") as handle:
            written = list(csv.DictReader(handle))
        self.assertEqual(written[0]["trim_label"], "400KM-STD")
        self.assertEqual(written[0]["units"], "100.0")


class EditorTests(unittest.TestCase):
    """Manual re-classification: the edits must land, and a bad one must not."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dir = Path(self.temp.name)
        target = year_dir(self.dir, YEAR)
        target.mkdir(parents=True)
        (target / "acme.json").write_text(
            json.dumps(tiny_payload(), ensure_ascii=False), encoding="utf-8")

    def test_an_edit_is_written_and_logged_with_its_previous_value(self):
        ok, problems, written = editor.apply_edit(
            self.dir, YEAR, "generation", "acme.volt.v2",
            {"segment": "C"}, reason="ตัดสินใหม่")
        self.assertEqual((ok, problems), (True, []))
        self.assertTrue(written)
        catalog = Catalog.load(self.dir, YEAR)
        self.assertIs(catalog.generations["acme.volt.v2"].segment, Segment.C)

        log = editor.decisions_path(self.dir, YEAR).read_text(encoding="utf-8")
        entry = json.loads(log.strip().splitlines()[-1])
        self.assertEqual(entry["changes"], {"segment": "C"})
        self.assertEqual(entry["previous"], {"segment": "B"})
        self.assertEqual(entry["reason"], "ตัดสินใหม่")
        self.assertIn("at", entry)

    def test_an_edit_that_breaks_a_rule_is_refused_whole(self):
        ok, problems, written = editor.apply_edit(
            self.dir, YEAR, "model", "acme.runner_double_cab",
            {"registration_type": "RY3"})
        self.assertFalse(ok)
        self.assertTrue(any("is registered RY1" in p for p in problems))
        self.assertEqual(written, [])
        # Nothing reached disk, so the catalog still loads and still validates.
        catalog = Catalog.load(self.dir, YEAR)
        self.assertIs(catalog.models["acme.runner_double_cab"].registration_type,
                      RegistrationType.RY1)
        self.assertEqual(catalog.validate(), [])
        self.assertFalse(editor.decisions_path(self.dir, YEAR).exists())

    def test_only_declared_fields_may_be_edited(self):
        with self.assertRaises(CatalogError):
            editor.apply_edit(self.dir, YEAR, "model", "acme.volt",
                              {"units": "9999"})
        with self.assertRaises(CatalogError):
            editor.apply_edit(self.dir, YEAR, "nonsense", "acme.volt",
                              {"segment": "C"})

    def test_price_edits_move_the_band_and_clear_the_flag(self):
        catalog = Catalog.load(self.dir, YEAR)
        variant = catalog.variants["acme.volt.v2.1_5l_ice"]
        self.assertIs(catalog.resolve(variant.id)["market_position"],
                      MarketPosition.VOLUME)
        ok, problems, _ = editor.apply_edit(
            self.dir, YEAR, "variant", variant.id,
            {"price_thb": "1,250,000", "price_min_thb": "1250000",
             "price_max_thb": "1250000", "price_note": "ยืนยันจากใบราคา"})
        self.assertEqual((ok, problems), (True, []))
        after = Catalog.load(self.dir, YEAR)
        self.assertIs(after.resolve(variant.id)["market_position"],
                      MarketPosition.UPPER)
        self.assertEqual(after.variants[variant.id].price_note, "ยืนยันจากใบราคา")

    def test_rows_carry_the_volume_that_makes_a_row_worth_judging(self):
        catalog = Catalog.load(self.dir, YEAR)
        conn = db.connect(":memory:")
        db.rebuild_dimension(conn, catalog)
        path = self.dir / "facts.csv"
        with open(path, "w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.writer(handle)
            writer.writerow(["เดือน", "ยี่ห้อ", "แบบรถ", "จำนวน"])
            writer.writerow([f"{YEAR}-01", "Acme", "Volt", "700"])
            writer.writerow([f"{YEAR}-01", "Acme", "Meteor", "3"])
        ingest_csv(conn, catalog, path, "facts")

        rows = editor.model_rows(catalog, conn)
        self.assertEqual(rows[0]["model_id"], "acme.volt")   # sorted by units
        self.assertEqual(rows[0]["units"], 700.0)
        self.assertEqual(rows[0]["unverified"], 0)     # every price is filled in

        # Clearing a price is what makes a row show as needing attention.
        editor.apply_edit(self.dir, YEAR, "variant", "acme.volt.v2.1_5l_ice",
                          {"price_thb": ""})
        again = editor.model_rows(Catalog.load(self.dir, YEAR), conn)
        self.assertEqual(next(r for r in again
                              if r["model_id"] == "acme.volt")["unverified"], 1)

        detail = editor.model_detail(catalog, conn, "acme.volt")
        self.assertEqual([l["raw_label"] for l in detail["labels"]],
                         ["Acme Volt"])
        self.assertEqual(len(detail["spec_lines"]), 3)

    def test_export_with_volume_puts_the_big_rows_first(self):
        catalog = Catalog.load(self.dir, YEAR)
        out = self.dir / "flat.csv"
        authoring.export_csv(catalog, out, {"acme.meteor": 900.0,
                                            "acme.volt": 10.0})
        with open(out, encoding="utf-8-sig") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(rows[0]["model"], "Meteor")
        self.assertEqual(rows[0]["units"], "900")
        # The extra column must not break a re-import.
        applied, problems, _ = authoring.import_csv(out, self.dir, year=YEAR)
        self.assertEqual(problems, [])
        self.assertGreater(applied, 0)


class AuthoringTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dir = Path(self.temp.name)
        target = year_dir(self.dir, YEAR)
        target.mkdir(parents=True)
        (target / "acme.json").write_text(
            json.dumps(tiny_payload(), ensure_ascii=False), encoding="utf-8")

    def write_rows(self, rows):
        path = self.dir / "add.csv"
        with open(path, "w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(authoring.COLUMNS),
                                    extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        return path

    def test_csv_import_creates_the_whole_nesting(self):
        path = self.write_rows([{
            "brand": "Zeta", "model": "Comet", "generation": "C1",
            "variant": "Long Range", "brand_segment": "PREMIUM_TECH",
            "brand_origin": "CN", "body_type": "SEDAN", "segment": "D",
            "seats": "5", "launched": "2026-02-01", "powertrain": "BEV",
            "drivetrain": "RWD", "battery_kwh": "80", "price_thb": "1990000",
            "import_type": "CBU", "origin_country": "CN",
        }])
        applied, problems, written = authoring.import_csv(path, self.dir,
                                                          year=YEAR)
        self.assertEqual(applied, 1)
        self.assertEqual(problems, [])
        self.assertTrue(written)
        catalog = Catalog.load(self.dir, YEAR)
        resolved = catalog.resolve("zeta.comet.c1.long_range")
        self.assertIs(resolved["market_position"], MarketPosition.LUXURY)
        self.assertIs(resolved["brand_segment"], BrandSegment.PREMIUM_TECH)

    def test_a_second_body_for_one_nameplate_is_refused(self):
        path = self.write_rows([
            {"brand": "Zeta", "model": "Comet", "variant": "1.5",
             "body_type": "SEDAN", "segment": "C", "powertrain": "ICE",
             "engine_cc": "1500", "price_thb": "800000",
             "import_type": "CKD", "origin_country": "TH"},
            {"brand": "Zeta", "model": "Comet", "variant": "1.5 HB",
             "body_type": "HATCHBACK", "segment": "C", "powertrain": "ICE",
             "engine_cc": "1500", "price_thb": "850000",
             "import_type": "CKD", "origin_country": "TH"},
        ])
        applied, problems, written = authoring.import_csv(path, self.dir,
                                                          year=YEAR)
        self.assertEqual(applied, 1)
        self.assertTrue(any("separate model" in p for p in problems))
        self.assertEqual(written, [])

    def test_registration_type_is_left_to_the_cab(self):
        path = self.write_rows([{
            "brand": "Zeta", "model": "Hauler Double Cab", "variant": "2.0",
            "body_type": "PICKUP", "cab_type": "DOUBLE_CAB", "segment": "F",
            "powertrain": "ICE", "engine_cc": "2000", "price_thb": "950000",
            "import_type": "CKD", "origin_country": "TH",
        }])
        applied, problems, _ = authoring.import_csv(path, self.dir, year=YEAR)
        self.assertEqual((applied, problems), (1, []))
        catalog = Catalog.load(self.dir, YEAR)
        self.assertIs(catalog.models["zeta.hauler_double_cab"].registration_type,
                      RegistrationType.RY1)

    def test_a_row_that_would_break_the_catalog_is_not_written(self):
        path = self.write_rows([{
            "brand": "Acme", "model": "Volt", "generation": "V2",
            "variant": "Broken", "powertrain": "BEV", "engine_cc": "1500",
            "price_thb": "900000", "import_type": "CKD", "origin_country": "TH",
        }])
        applied, problems, written = authoring.import_csv(path, self.dir,
                                                          year=YEAR)
        self.assertTrue(any("must not declare engine_cc" in p for p in problems))
        self.assertEqual(written, [])
        catalog = Catalog.load(self.dir, YEAR)
        self.assertNotIn("acme.volt.v2.broken", catalog.variants)

    def test_round_trip_export_import_is_stable(self):
        catalog = Catalog.load(self.dir, YEAR)
        out = self.dir / "flat.csv"
        authoring.export_csv(catalog, out)
        authoring.import_csv(out, self.dir, year=YEAR)
        after = Catalog.load(self.dir, YEAR)
        self.assertEqual(sorted(after.variants), sorted(catalog.variants))
        self.assertEqual(sorted(after.models), sorted(catalog.models))
        self.assertEqual(after.validate(), [])


if __name__ == "__main__":
    unittest.main()


class MarketPowertrainTests(unittest.TestCase):
    """Reader-facing buckets keep HEV and maker-labelled REEV distinct."""

    def test_a_mild_hybrid_is_a_petrol_car_everywhere(self):
        """MHEV is not a value this warehouse can hold.

        Neither layer of the site has a column for it and nobody cross-shops a
        mild hybrid against a Corolla Cross HEV, so it folds at parse rather
        than at display - a catalog file that spells MHEV still loads and lands
        on ICE, and no future edit can reintroduce the category.
        """
        self.assertFalse(hasattr(Powertrain, "MHEV"))
        for spelling in ("MHEV", "MILD HYBRID", "mild-hybrid", "48V",
                         "EQ BOOST"):
            with self.subTest(spelling=spelling):
                self.assertIs(Powertrain.parse(spelling), Powertrain.ICE)
        self.assertIs(taxonomy.market_powertrain(Powertrain.ICE),
                      taxonomy.MarketPowertrain.FUEL)

    def test_reev_stays_separate_from_hev(self):
        self.assertIs(taxonomy.market_powertrain(Powertrain.REEV),
                      taxonomy.MarketPowertrain.REEV)
        self.assertIs(taxonomy.market_powertrain(Powertrain.HEV),
                      taxonomy.MarketPowertrain.HYBRID)

    def test_a_plug_keeps_its_own_bucket(self):
        # The coarser PowertrainGroup puts a Prius and an Outlander PHEV
        # together, which is the distinction a buyer is actually shopping.
        self.assertIs(taxonomy.powertrain_group(Powertrain.HEV),
                      taxonomy.powertrain_group(Powertrain.PHEV))
        self.assertIsNot(taxonomy.market_powertrain(Powertrain.HEV),
                         taxonomy.market_powertrain(Powertrain.PHEV))

    def test_every_powertrain_has_a_bucket_and_a_thai_label(self):
        for pt in Powertrain:
            bucket = taxonomy.market_powertrain(pt)
            self.assertIn(bucket.value, taxonomy.MARKET_POWERTRAIN_TH)

    def test_e_power_is_not_a_plug_in_car(self):
        """A Nissan e-Power battery is only ever charged by its own engine.

        Filing it REEV made all 21,863 of its units read as plug-ins and put
        the only occupant in a category of its own; it is HEV in this catalog.
        """
        self.assertFalse(taxonomy.is_plug_in(Powertrain.HEV))
        self.assertTrue(taxonomy.is_electrified(Powertrain.HEV))
        # REEV keeps its meaning for a car that really has a socket.
        self.assertTrue(taxonomy.is_plug_in(Powertrain.REEV))


class GeneratedViewTests(unittest.TestCase):
    def test_a_new_facet_reaches_the_reading_view(self):
        """The views are generated from DIM_FACETS and must not go stale.

        ``CREATE VIEW IF NOT EXISTS`` leaves an existing definition alone, so
        adding market_powertrain left every warehouse built before it querying
        a view without the column - "no such column: market_powertrain" on the
        dashboard's first chart.
        """
        conn = db.connect(":memory:")
        conn.execute("DROP VIEW fact_classified")
        conn.execute("CREATE VIEW fact_classified AS SELECT 1 AS stale")
        conn.commit()
        conn.close()

        conn = db.connect(":memory:")
        columns = {row["name"] for row in
                   conn.execute("PRAGMA table_info(fact_classified)")}
        for facet in db.DIM_FACETS:
            with self.subTest(facet=facet):
                self.assertIn(facet, columns)


class ReevIsForPlugInsTests(unittest.TestCase):
    """REEV means a socket. Without that it collects anything unusual."""

    def test_a_range_extender_plugs_in_and_is_electrified(self):
        self.assertTrue(taxonomy.is_plug_in(Powertrain.REEV))
        self.assertTrue(taxonomy.is_electrified(Powertrain.REEV))

    def test_the_catalog_only_files_real_range_extenders_as_reev(self):
        """Nissan e-Power was REEV and has no socket at all.

        Every REEV unit in the warehouse was then a car that cannot be plugged
        in, and the plug-in total carried 21,863 units that never charged.
        """
        from vehreg.catalog import DATA_DIR, Catalog, available_years

        offenders: list[str] = []
        for year in available_years(DATA_DIR):
            catalog = Catalog.load(DATA_DIR, year)
            for model in catalog.models.values():
                for variant in catalog.variants_of(model.id):
                    if variant.powertrain is Powertrain.REEV:
                        offenders.append(f"{year} {model.id}")
        # Anything here has to be a car that charges from a socket.
        self.assertEqual(sorted({o.split()[1] for o in offenders}),
                         ["deepal.deepal_s05", "jaecoo.jaecoo_6t_reev"])


class BmwModelSplitTests(unittest.TestCase):
    """The owner's rule for BMW, pinned so a later edit cannot drift off it.

    One nameplate holds its combustion and plug-in halves together - a 3 Series
    is a 3 Series whether it is a 320d or a 330e - and every i car is its own
    model, because an i5 is not a 5 Series with a different engine.
    """

    def setUp(self):
        from vehreg.catalog import DATA_DIR, Catalog, available_years
        self.catalogs = {year: Catalog.load(DATA_DIR, year)
                         for year in available_years(DATA_DIR)}

    def test_every_i_car_is_its_own_model(self):
        for year, catalog in self.catalogs.items():
            for model in catalog.models_of("bmw"):
                name = model.name_en.lower()
                if not name.startswith("i") or name.startswith("ix1"):
                    continue
                with self.subTest(year=year, model=model.id):
                    # An i model never shares a row with a combustion nameplate.
                    powertrains = {v.powertrain for v in
                                   catalog.variants_of(model.id)}
                    self.assertTrue(
                        powertrains <= {Powertrain.BEV, Powertrain.PHEV},
                        f"{model.id} carries {powertrains}")

    def test_an_i_badge_never_lands_on_a_combustion_nameplate(self):
        """The iX2 sat inside the iX, and the i7 inside the 7 Series."""
        for year, catalog in self.catalogs.items():
            for model in catalog.models_of("bmw"):
                if model.name_en.lower().startswith("i"):
                    continue
                for alias in model.aliases:
                    with self.subTest(year=year, model=model.id, alias=alias):
                        self.assertFalse(
                            alias.lower().lstrip().startswith("i")
                            and any(ch.isdigit() for ch in alias),
                            f"{model.id} claims the i-car alias {alias!r}")

    def test_a_nameplate_sold_both_ways_holds_both(self):
        catalog = self.catalogs[max(self.catalogs)]
        for model_id in ("bmw.bmw_3", "bmw.bmw_5", "bmw.7_series", "bmw.x5"):
            with self.subTest(model=model_id):
                powertrains = {v.powertrain for v in
                               catalog.variants_of(model_id)}
                self.assertEqual(powertrains, {Powertrain.ICE, Powertrain.PHEV})


class IncompleteVariantTests(unittest.TestCase):
    """A nameplate can be researched on one side and not the other."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dir = Path(self.temp.name)
        target = year_dir(self.dir, YEAR)
        target.mkdir(parents=True)
        payload = tiny_payload()
        # The Volt gains a plug-in whose battery and engine nobody has looked
        # up - the BMW X1 xDrive30e case. Without a way to say so, either the
        # trim is left out and its registrations read as petrol, or the whole
        # model is called incomplete, which is false.
        payload["models"][2]["generations"][1]["variants"].append({
            "name": "1.5 PHEV", "powertrain": "PHEV", "drivetrain": "FWD",
            "import_type": "CKD", "origin_country": "TH", "incomplete": True,
        })
        (target / "acme.json").write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        self.catalog = Catalog.load(self.dir, YEAR)

    def test_a_declared_gap_is_not_a_validation_problem(self):
        self.assertEqual(
            [p for p in self.catalog.validate() if "1_5_phev" in p], [])

    def test_it_is_reported_as_a_gap_instead(self):
        gaps = [g for g in self.catalog.incomplete_models() if "1_5_phev" in g]
        self.assertEqual(len(gaps), 1)
        self.assertIn("battery_kwh", gaps[0])
        self.assertIn("engine_cc", gaps[0])
        self.assertTrue(gaps[0].startswith("variant "))

    def test_the_model_itself_is_not_called_incomplete(self):
        self.assertFalse(self.catalog.models["acme.volt"].incomplete)
        self.assertEqual(
            [g for g in self.catalog.incomplete_models()
             if g.startswith("model acme.volt")], [])

    def test_the_nameplate_now_reads_mixed(self):
        rows = {r["unit_id"]: r for r in db.build_dimension(self.catalog)}
        self.assertEqual(rows["acme.volt"]["powertrain"], db.MIXED)

    def test_saving_the_brand_keeps_the_marker(self):
        payload = self.catalog.brand_payload("acme")
        variants = [v for m in payload["models"] for g in m["generations"]
                    for v in g["variants"] if v["name"] == "1.5 PHEV"]
        self.assertEqual(len(variants), 1)
        self.assertTrue(variants[0]["incomplete"])


class TrailingNumberGuardTests(unittest.TestCase):
    """A nameplate's number is the nameplate, not noise on the end of it."""

    def setUp(self):
        self.index = normalize.MatchIndex()
        self.index.add("geely.ex5", ["Geely EX5"], priority=1)
        self.index.add("geely.ex2", ["Geely EX2"], priority=1)

    def test_a_neighbouring_number_is_not_a_near_miss(self):
        """EX2 scored 0.90 against EX5 and took 8,731 registrations with it."""
        self.assertGreater(
            normalize.similarity(normalize.fold("GEELY EX2"),
                                 normalize.fold("Geely EX5")),
            normalize.MATCH_FLOOR)
        self.assertEqual(self.index.lookup("GEELY EX2")[0], "geely.ex2")
        self.assertEqual(self.index.lookup("GEELY EX5")[0], "geely.ex5")

    def test_an_unknown_number_matches_nothing_rather_than_its_neighbour(self):
        lonely = normalize.MatchIndex()
        lonely.add("geely.ex5", ["Geely EX5"], priority=1)
        key, _score, how = lonely.lookup("GEELY EX2")
        self.assertIsNone(key)
        self.assertEqual(how, "none")

    def test_the_guard_stays_out_of_the_way_of_a_trim_code(self):
        """A trim code differs from its nameplate in digits, for a reason.

        "BMW 330e Sport" reaches the 3 Series on the alias the catalog carries
        for it, not on fuzzy - it scores 0.59 against the bare name. The guard
        must not interfere with that path, and must not fire on the pair at
        all, or every BMW would fall to brand grain.
        """
        index = normalize.MatchIndex()
        index.add("bmw.3", ["BMW 3 Series"], priority=1)
        index.add("bmw.3", ["330e", "320d"])
        self.assertEqual(index.lookup("BMW 330e Sport")[0], "bmw.3")
        self.assertFalse(normalize._numbers_disagree(
            normalize.fold("BMW 330e Sport"), normalize.fold("BMW 3 Series")))

    def test_it_only_applies_when_both_names_end_in_a_number(self):
        self.assertTrue(normalize._numbers_disagree("geely ex 2", "geely ex 5"))
        self.assertFalse(normalize._numbers_disagree("bmw 330 e sport",
                                                     "bmw 3 series"))
        self.assertFalse(normalize._numbers_disagree("geely ex 5",
                                                     "geely ex 5"))


class OwnerConfirmedPowertrainTests(unittest.TestCase):
    """Calls the owner made about what is actually sold, pinned as tests.

    They are market facts, not derivable from any file, so the only thing that
    keeps a later edit from quietly undoing them is a test that names them.
    """

    def setUp(self):
        from vehreg.catalog import DATA_DIR, Catalog
        self.catalog = Catalog.load(DATA_DIR, 2026)

    def test_the_pickups_are_diesel_and_say_they_were_checked(self):
        for model_id in ("toyota.hilux_revo_cab", "toyota.hilux_revo_double_cab",
                         "isuzu.dmax_cab", "isuzu.dmax_double_cab",
                         "mitsubishi.triton_cab", "nissan.navara_cab"):
            with self.subTest(model=model_id):
                model = self.catalog.models[model_id]
                self.assertTrue(model.powertrain_checked)
                self.assertEqual(
                    {v.powertrain for v in self.catalog.variants_of(model_id)},
                    {Powertrain.ICE})

    def test_the_yaris_ativ_is_mixed_because_dlt_cannot_split_it(self):
        """It gained a hybrid and DLT files both under one bare label.

        MIXED is the honest reading: 251,114 units that nothing can attribute
        to one side or the other.
        """
        self.assertEqual(
            {v.powertrain for v in
             self.catalog.variants_of("toyota.yaris_ativ")},
            {Powertrain.ICE, Powertrain.HEV})

    def test_an_e_tron_badge_belongs_to_an_e_tron_model(self):
        """The Q8 e-tron was inside the petrol Q8, on the Q8's own alias list."""
        for model in self.catalog.models_of("audi"):
            if "etron" in model.id:
                self.assertEqual(
                    {v.powertrain for v in self.catalog.variants_of(model.id)},
                    {Powertrain.BEV}, model.id)
                continue
            for alias in model.aliases:
                with self.subTest(model=model.id, alias=alias):
                    self.assertNotIn("tron", alias.lower())

    def test_a_nameplate_and_its_ev_twin_stay_apart(self):
        """MG ZS and MG ZS EV are two cars and DLT files them apart.

        The pattern that went wrong for the Audi Q8 - the battery car sitting
        on the petrol nameplate's alias list - so it is worth a test where it
        is right.
        """
        zs = self.catalog.models["mg.mg_zs"]
        zs_ev = self.catalog.models["mg.mg_zs_ev"]
        self.assertEqual({v.powertrain for v in
                          self.catalog.variants_of(zs.id)}, {Powertrain.ICE})
        self.assertEqual({v.powertrain for v in
                          self.catalog.variants_of(zs_ev.id)}, {Powertrain.BEV})
        for alias in zs.aliases:
            with self.subTest(alias=alias):
                self.assertNotIn("ev", alias.lower().split())

    def test_the_bmw_plug_ins_no_longer_declare_a_gap(self):
        for model_id in ("bmw.bmw_x1", "bmw.bmw_x3"):
            plugin = [v for v in self.catalog.variants_of(model_id)
                      if v.powertrain is Powertrain.PHEV]
            self.assertEqual(len(plugin), 1, model_id)
            with self.subTest(model=model_id):
                self.assertFalse(plugin[0].incomplete)
                self.assertTrue(plugin[0].engine_cc)
                self.assertTrue(plugin[0].battery_kwh)


class AliasMustNotSwallowAPowertrainWordTests(unittest.TestCase):
    """A model alias holding a powertrain word hides it from the trim ledger.

    "TANK 300 HYBRID" was a harmless second spelling while the Tank was hybrid
    only. Once the 2.4 diesel arrived in 2025 it became the thing that made the
    two indistinguishable: residual_trim treats every token of every model alias
    as part of the name, so HYBRID was stripped and the ledger recorded an empty
    trim and no hint for all 1,374 of them. The Alphard had the same alias and
    the same problem, live, with a hybrid and a plug-in on sale.

    The rule compares against the model's own name, so a nameplate that IS its
    powertrain - Kia EV6, MG ZS EV, MG4 Electric - is untouched.
    """

    PT_TOKEN = re.compile(
        r"^(hybrid|hev|phev|bev|ev|reev|diesel|dmi|epower)$", re.I)

    def _powertrain_tokens(self, text: str) -> set:
        return {t for t in normalize.fold(text).split()
                if self.PT_TOKEN.match(t)}

    def test_no_alias_adds_a_powertrain_word_the_name_lacks(self):
        from vehreg.catalog import DATA_DIR, Catalog, available_years

        for year in available_years(DATA_DIR):
            catalog = Catalog.load(DATA_DIR, year)
            for model in catalog.models.values():
                own = (self._powertrain_tokens(model.name_en)
                       | self._powertrain_tokens(model.name_th)
                       | self._powertrain_tokens(model.nameplate))
                for alias in model.aliases:
                    with self.subTest(year=year, model=model.id, alias=alias):
                        self.assertEqual(
                            self._powertrain_tokens(alias) - own, set())

    def test_the_word_reaches_the_ledger_once_the_alias_is_gone(self):
        from vehreg.catalog import DATA_DIR, Catalog

        catalog = Catalog.load(DATA_DIR, 2026)
        for model_id, label, expected in (
                ("gwm.tank300", "GWM TANK 300 HYBRID", "HEV"),
                ("gwm.tank300", "GWM GWM TANK 300", None),
                ("toyota.alphard", "TOYOTA ALPHARD 2.5 HYBRID G", "HEV")):
            with self.subTest(label=label):
                residual = trimledger.residual_trim(catalog, model_id, label)
                self.assertEqual(
                    trimledger.parse_trim(residual).powertrain_hint, expected)
