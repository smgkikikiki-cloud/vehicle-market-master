"""Offline tests for the review queue: triage, lessons, and re-reading a file."""

import json
import tempfile
import unittest
from pathlib import Path

from vehreg import db, review
from vehreg.catalog import DEFAULT_YEAR, Catalog, year_dir
from vehreg.ingest import ingest_csv, sources_awaiting_reload, teach_alias

from test_vehreg import tiny_payload

YEAR = DEFAULT_YEAR


def written(payload, directory, year):
    target = year_dir(directory, year)
    target.mkdir(parents=True, exist_ok=True)
    (target / "acme.json").write_text(json.dumps(payload, ensure_ascii=False),
                                      encoding="utf-8")


class ReviewQueueTests(unittest.TestCase):
    """The queue as a plan: what each label needs, not one uniform dropdown."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dir = Path(self.temp.name)
        written(tiny_payload(), self.dir, YEAR)
        self.catalog = Catalog.load(self.dir, YEAR)
        self.catalogs = {YEAR: self.catalog}
        self.conn = db.connect(":memory:")
        db.rebuild_dimension(self.conn, self.catalog)

    def write_csv(self, rows, name="dlt.csv"):
        path = self.dir / name
        lines = ["เดือน,ยี่ห้อ,แบบรถ,รุ่นย่อย,จำนวน,ประเภทรถ"]
        lines += [",".join(str(cell) for cell in row) for row in rows]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8-sig")
        return path

    def test_one_label_is_one_decision_however_many_months_it_spans(self):
        path = self.write_csv([
            (f"{YEAR}-01", "Acme", "Nonesuch", "", "10", "RY1"),
            (f"{YEAR}-02", "Acme", "Nonesuch", "", "30", "RY1"),
            (f"{YEAR}-03", "Acme", "Nonesuch", "", "5", "RY1"),
        ])
        ingest_csv(self.conn, self.catalog, path, "s")
        items = review.queue(self.conn, self.catalogs)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].units, 45.0)
        self.assertEqual(items[0].rows, 3)
        self.assertEqual(len(items[0].periods), 3)

    def test_a_label_with_no_close_model_asks_for_a_catalog_entry(self):
        # "Nonesuch" is not a car Acme makes, and no alias can make it one.
        path = self.write_csv([(f"{YEAR}-01", "Acme", "Nonesuch", "", "10",
                                "RY1")])
        ingest_csv(self.conn, self.catalog, path, "s")
        item = review.queue(self.conn, self.catalogs)[0]
        self.assertEqual(item.needs, review.NEEDS_CATALOG)
        self.assertFalse(item.teachable)
        self.assertIn("catalog", item.blocked)

    def test_a_target_missing_from_an_earlier_year_is_never_offered(self):
        """The trap that made three labels look settleable when none were.

        Each year has its own catalog and a lesson is not scoped by year, so a
        model that exists only in the newer catalog would resolve to a unit_id
        with no dimension row for the older month - a fact with every facet
        NULL, which is worse than the review row it replaced.
        """
        older = dict(tiny_payload())
        older["models"] = [m for m in older["models"] if m["id"] != "sprint"]
        written(older, self.dir, YEAR - 1)
        catalogs = {YEAR - 1: Catalog.load(self.dir, YEAR - 1),
                    YEAR: self.catalog}
        db.rebuild_dimension(self.conn, catalogs[YEAR - 1])

        spanning = [catalogs[YEAR - 1], catalogs[YEAR]]
        current = [catalogs[YEAR]]
        self.assertNotIn("acme.sprint",
                         [c.unit_id for c in review.models_for(spanning,
                                                               "acme")])
        self.assertIn("acme.sprint",
                      [c.unit_id for c in review.models_for(current, "acme")])

    def test_the_manual_list_is_the_brands_models_in_name_order(self):
        """Not a ranking. Nothing in the strings knows what the owner knows."""
        names = [c.unit_id for c in review.models_for([self.catalog], "acme")]
        self.assertEqual(len(names), len(self.catalog.models_of("acme")))
        self.assertEqual(names, sorted(
            names, key=lambda i: review._model_label(self.catalog, i)))
        self.assertEqual(review.models_for([self.catalog], "nobody"), [])

    def test_a_label_needing_a_catalog_entry_still_names_its_brand(self):
        # So the page can offer that brand's models for a manual decision.
        path = self.write_csv([(f"{YEAR}-01", "Acme", "Nonesuch", "", "10",
                                "RY1")])
        ingest_csv(self.conn, self.catalog, path, "s")
        item = review.queue(self.conn, self.catalogs)[0]
        self.assertEqual(item.needs, review.NEEDS_CATALOG)
        self.assertEqual(item.brand_id, "acme")

    def test_a_classless_file_cannot_settle_a_cab_split_by_lesson(self):
        """The pivot workbook has no รย. column, which is why the cabs tie.

        Teaching here would put a month's whole nameplate on one cab when the
        month was a mix of both, so the answer is a better file.
        """
        path = self.write_csv([(f"{YEAR}-01", "Acme", "Runner", "", "500", "*")])
        ingest_csv(self.conn, self.catalog, path, "pivot")
        item = review.queue(self.conn, self.catalogs)[0]
        self.assertEqual(item.reason, "model-ambiguous")
        self.assertEqual(item.needs, review.NEEDS_SOURCE)
        self.assertFalse(item.teachable)
        self.assertIn("รย.", item.note)

    def test_a_classed_file_settles_the_same_split_with_one_scoped_lesson(self):
        # A รย.1 file leaves only the double cab, so the matcher never asks.
        # Force the tie by giving the file a class the split does not resolve.
        path = self.write_csv([(f"{YEAR}-01", "Acme", "Runner", "", "500",
                                "RY12")])
        ingest_csv(self.conn, self.catalog, path, "odd")
        item = review.queue(self.conn, self.catalogs)[0]
        self.assertEqual(item.default_reg, "RY12")
        self.assertEqual(item.needs, review.NEEDS_TEACH)
        self.assertEqual({c.unit_id for c in item.candidates},
                         {"acme.runner_cab", "acme.runner_double_cab"})

    def test_a_trim_string_is_not_mistaken_for_a_factory_code(self):
        """One token is the signal. Stripping spaces first destroyed it.

        The first pass filed "745Le xDrive M Sport", "630i Gran Turismo RHD"
        and "TUNLAND DC 4X2 S PREMIUM" as codes to be dismissed - real cars,
        offered for deletion from the queue - because with the spaces removed
        they are capitals and digits like anything else.
        """
        for name in ("745Le xDrive M Sport", "630i Gran Turismo RHD",
                     "TUNLAND DC 4X2 S PREMIUM", "M2 Coupe RHD MX"):
            with self.subTest(name=name):
                self.assertFalse(review._looks_like_a_code(name))
        for code in ("UVL4RDRE26KHE-----", "UVL4RDRE26KWDMER9E"):
            with self.subTest(code=code):
                self.assertTrue(review._looks_like_a_code(code))

    def test_a_factory_code_is_recognised_and_dismissing_moves_no_units(self):
        path = self.write_csv([(f"{YEAR}-01", "Acme", "UVL4RDRE26KHE-----", "",
                                "70", "RY1")])
        ingest_csv(self.conn, self.catalog, path, "s")
        item = review.queue(self.conn, self.catalogs)[0]
        self.assertEqual(item.needs, review.NEEDS_NOTHING)

        before = self.conn.execute(
            "SELECT SUM(units) AS u FROM fact_registration").fetchone()["u"]
        self.assertEqual(review.dismiss(self.conn, [item]), 1)
        after = self.conn.execute(
            "SELECT SUM(units) AS u FROM fact_registration").fetchone()["u"]
        self.assertEqual(before, after)
        self.assertEqual(review.queue(self.conn, self.catalogs), [])

    def test_the_plan_adds_up_to_the_queue(self):
        path = self.write_csv([
            (f"{YEAR}-01", "Acme", "Nonesuch", "", "10", "RY1"),
            (f"{YEAR}-01", "Acme", "UVL4RDRE26KHE-----", "", "70", "RY1"),
            (f"{YEAR}-01", "Acme", "Runner", "", "500", "*"),
        ])
        ingest_csv(self.conn, self.catalog, path, "s")
        items = review.queue(self.conn, self.catalogs)
        self.assertEqual(sum(row["units"] for row in review.summary(items)),
                         sum(item.units for item in items))
        self.assertEqual({row["needs"] for row in review.summary(items)},
                         {review.NEEDS_CATALOG, review.NEEDS_NOTHING,
                          review.NEEDS_SOURCE})


class LessonTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dir = Path(self.temp.name)
        written(tiny_payload(), self.dir, YEAR)
        self.catalog = Catalog.load(self.dir, YEAR)
        self.conn = db.connect(":memory:")
        db.rebuild_dimension(self.conn, self.catalog)

    def write_csv(self, rows, name="dlt.csv"):
        path = self.dir / name
        lines = ["เดือน,ยี่ห้อ,แบบรถ,รุ่นย่อย,จำนวน,ประเภทรถ"]
        lines += [",".join(str(cell) for cell in row) for row in rows]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8-sig")
        return path

    def test_a_lesson_claims_only_the_label_it_was_taught(self):
        """It used to claim every label containing the taught text.

        "Acme Runner" would mark "Acme Runner Super Duty" mapped, so a label
        nobody had decided anything about left the open queue and the units
        stayed unattributed with no sign of why.
        """
        path = self.write_csv([
            (f"{YEAR}-01", "Acme", "Nonesuch", "", "10", "RY1"),
            (f"{YEAR}-01", "Acme", "Nonesuch Super Duty", "", "20", "RY1"),
        ])
        ingest_csv(self.conn, self.catalog, path, "s")
        teach_alias(self.conn, "model", "Acme Nonesuch", "acme.sprint")
        statuses = {row["raw_model"]: row["status"] for row in self.conn.execute(
            "SELECT raw_model, status FROM ingest_review")}
        self.assertEqual(statuses["Nonesuch"], "mapped")
        self.assertEqual(statuses["Nonesuch Super Duty"], "open")

    def test_a_taught_source_is_listed_until_it_is_read_again(self):
        path = self.write_csv([(f"{YEAR}-01", "Acme", "Nonesuch", "", "10",
                                "RY1")])
        ingest_csv(self.conn, self.catalog, path, "s")
        self.assertEqual(sources_awaiting_reload(self.conn), [])

        teach_alias(self.conn, "model", "Acme Nonesuch", "acme.sprint")
        pending = sources_awaiting_reload(self.conn)
        self.assertEqual([row["name"] for row in pending], ["s"])
        self.assertEqual(pending[0]["units"], 10.0)

        review.reload_source(self.conn, int(pending[0]["source_id"]),
                             data_dir=self.dir)
        self.assertEqual(sources_awaiting_reload(self.conn), [])

    def test_a_lesson_only_pays_off_once_the_file_is_read_again(self):
        path = self.write_csv([(f"{YEAR}-01", "Acme", "Nonesuch", "", "10",
                                "RY1")])
        report = ingest_csv(self.conn, self.catalog, path, "s")
        source_id = report.source_id
        self.assertEqual(self.conn.execute(
            "SELECT unit_id FROM fact_registration").fetchone()["unit_id"],
            "acme")   # placed on the brand, the deepest level that matched

        teach_alias(self.conn, "model", "Acme Nonesuch", "acme.sprint")
        # Still on the brand: matching happens when a file is read.
        self.assertEqual(self.conn.execute(
            "SELECT unit_id FROM fact_registration").fetchone()["unit_id"],
            "acme")

        state = review.reload_source(self.conn, source_id, data_dir=self.dir)
        self.assertEqual(state.moved, 10.0)
        rows = self.conn.execute(
            "SELECT unit_id, units FROM fact_registration").fetchall()
        self.assertEqual([(r["unit_id"], r["units"]) for r in rows],
                         [("acme.sprint", 10.0)])

    def test_re_reading_a_source_replaces_it_rather_than_adding_to_it(self):
        """The bug the upload page shipped with, as a test.

        Both fact tables key on the resolved id, so a row that moves from the
        brand to a model does not overwrite its predecessor - it joins it, and
        the month reads double. Only deleting the source's rows first is safe.
        """
        path = self.write_csv([(f"{YEAR}-01", "Acme", "Nonesuch", "", "10",
                                "RY1")])
        source_id = ingest_csv(self.conn, self.catalog, path, "s").source_id
        teach_alias(self.conn, "model", "Acme Nonesuch", "acme.sprint")
        review.reload_source(self.conn, source_id, data_dir=self.dir)

        total = self.conn.execute(
            "SELECT SUM(units) AS u FROM fact_registration").fetchone()["u"]
        self.assertEqual(total, 10.0)
        self.assertEqual(self.conn.execute(
            "SELECT COUNT(*) AS n FROM fact_registration").fetchone()["n"], 1)

    def test_clearing_a_month_takes_the_trim_ledger_with_it(self):
        path = self.write_csv([(f"{YEAR}-01", "Acme", "Volt", "1.5 EL", "40",
                               "RY1")])
        ingest_csv(self.conn, self.catalog, path, "s")
        db.clear_period(self.conn, f"{YEAR}-01")
        for table in db.SOURCE_TABLES:
            with self.subTest(table=table):
                self.assertEqual(self.conn.execute(
                    f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"], 0)


class KnownModelsTests(unittest.TestCase):
    """The context the catalog tab shows beside an unmatched label."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dir = Path(self.temp.name)
        written(tiny_payload(), self.dir, YEAR)
        self.catalog = Catalog.load(self.dir, YEAR)

    def test_it_lists_the_brands_models_with_their_aliases(self):
        rows = review.known_models(self.catalog, "acme")
        self.assertEqual([row["model"] for row in rows],
                         sorted(row["model"] for row in rows))
        runner = next(r for r in rows if r["id"] == "acme.runner_cab")
        self.assertIn("Runner", str(runner["aliases"]))

    def test_an_unknown_brand_lists_nothing_rather_than_raising(self):
        self.assertEqual(review.known_models(self.catalog, "nobody"), [])


class MigrationTests(unittest.TestCase):
    def test_a_database_built_before_reg_type_gains_the_column(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        path = Path(temp.name) / "old.sqlite3"
        conn = db.connect(path)
        conn.execute("ALTER TABLE ingest_review DROP COLUMN reg_type")
        conn.commit()
        conn.close()

        conn = db.connect(path)
        columns = {row["name"] for row in
                   conn.execute("PRAGMA table_info(ingest_review)")}
        self.assertIn("reg_type", columns)


if __name__ == "__main__":
    unittest.main()
