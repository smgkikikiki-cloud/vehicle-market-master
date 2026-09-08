"""Manual price maintenance: fixing a price without erasing what was published.

append_prices only adds, so before this there was no supported way to correct a
wrong figure -- the ledger refused a second price on the same day and the only
recourse was hand-editing the JSON. These three operations close that gap, and
none of them deletes a row.
"""

import json
import shutil
import unittest
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

from vehreg.catalog import CatalogError, DATA_DIR
from vehreg.product import (
    ProductMaster, append_prices, close_price, correct_price, find_price_rows,
    save_campaign,
)

TRIM = "jaecoo.jaecoo_5_ev.j5.trim.long_range_dynamic_bev"
TODAY = date(2026, 9, 8)


class EditingTests(unittest.TestCase):

    def setUp(self):
        self.root = Path(self.enterContext(TemporaryDirectory()))
        shutil.copytree(DATA_DIR / "2026", self.root / "2026")
        append_prices(self.root, 2026, {"prices": [{
            "trim_id": TRIM, "amount_thb": 700_000, "price_type": "LIST_PRICE",
            "effective_from": "2026-09-01", "observed_at": "2026-09-01",
            "source": "official_oem", "source_ref": "https://example.test/a",
        }]}, write=True)

    def amount(self, when=TODAY):
        return ProductMaster.load(self.root).prices.current_list_amount(
            TRIM, as_of=when)

    def rows(self, include_retracted=True):
        """List prices only: this trim also carries committed ECO evidence."""
        from vehreg.pricing import PriceType
        return ProductMaster.load(self.root).prices.records_for(
            TRIM, price_type=PriceType.LIST_PRICE,
            include_retracted=include_retracted)

    def fix(self, **changes):
        payload = dict(trim_id=TRIM, price_type="LIST_PRICE", amount_thb=690_000,
                       reason="the outlet corrected it", reviewer="owner",
                       as_of=TODAY, write=True)
        payload.update(changes)
        return correct_price(self.root, 2026, **payload)

    # ------------------------------------------------------------------ modes
    def test_a_retracted_row_stops_counting_but_stays_readable(self):
        self.assertEqual(700_000, self.amount())
        self.fix(mode="retract")
        self.assertEqual(690_000, self.amount())
        retracted = [r for r in self.rows() if r.retracted]
        self.assertEqual([700_000], [r.amount_thb for r in retracted])
        self.assertEqual("the outlet corrected it", retracted[0].retraction_reason)
        self.assertEqual("owner", retracted[0].reviewed_by)

    def test_a_retracted_row_is_hidden_from_normal_reads(self):
        self.fix(mode="retract")
        self.assertEqual([690_000],
                         [r.amount_thb for r in self.rows(include_retracted=False)])

    def test_superseding_keeps_the_old_price_true_of_its_own_period(self):
        self.fix(mode="supersede", effective_from="2026-10-01")
        self.assertEqual(700_000, self.amount(date(2026, 9, 30)))
        self.assertEqual(690_000, self.amount(date(2026, 10, 1)))
        self.assertEqual(2, len(self.rows()))

    def test_closing_ends_a_price_with_no_replacement(self):
        close_price(self.root, 2026, trim_id=TRIM, price_type="LIST_PRICE",
                    ends="2026-09-30", reason="grade withdrawn", reviewer="owner",
                    as_of=TODAY, write=True)
        self.assertEqual(700_000, self.amount(date(2026, 9, 30)))
        self.assertIsNone(self.amount(date(2026, 10, 1)))
        self.assertEqual(1, len(self.rows()))

    # ----------------------------------------------------------------- guards
    def test_a_correction_needs_a_reason_and_a_person(self):
        for changes in ({"reason": ""}, {"reviewer": ""}):
            with self.assertRaises(CatalogError):
                self.fix(**changes)
        self.assertEqual(700_000, self.amount())

    def test_superseding_on_the_day_the_price_started_is_refused(self):
        """That would give the old row a negative life. Retract it instead."""
        with self.assertRaises(CatalogError) as caught:
            self.fix(mode="supersede", effective_from="2026-09-01")
        self.assertIn("retract", str(caught.exception))

    def test_closing_before_the_price_started_is_refused(self):
        with self.assertRaises(CatalogError):
            close_price(self.root, 2026, trim_id=TRIM, price_type="LIST_PRICE",
                        ends="2026-08-01", reason="x", reviewer="owner",
                        as_of=TODAY, write=True)

    def test_nothing_to_correct_is_an_error_not_a_silent_insert(self):
        with self.assertRaises(CatalogError):
            self.fix(price_type="DEALER_PRICE")

    def test_dry_run_leaves_the_file_alone(self):
        before = (self.root / "2026/market/prices/observations.json").read_bytes()
        self.fix(mode="retract", write=False)
        self.assertEqual(before,
                         (self.root / "2026/market/prices/observations.json").read_bytes())

    def test_correcting_to_the_same_number_changes_nothing(self):
        result = self.fix(mode="supersede", amount_thb=700_000)
        self.assertFalse(result["changed"])

    def test_two_live_rows_are_a_question_not_a_guess(self):
        """Never pick one of an ambiguous pair; say which ones and stop."""
        path = self.root / "2026/market/prices/observations.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["prices"].append({**payload["prices"][-1], "amount_thb": 705_000})
        path.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaises(CatalogError) as caught:
            self.fix(mode="retract")
        self.assertIn("705,000", str(caught.exception))

    def test_find_price_rows_reports_which_file_holds_each_row(self):
        found = find_price_rows(self.root, 2026, trim_id=TRIM,
                                price_type="LIST_PRICE", as_of=TODAY)
        self.assertEqual(1, len(found))
        self.assertTrue(found[0]["live"])
        self.assertTrue(str(found[0]["path"]).endswith("observations.json"))


class CampaignAuthoringTests(unittest.TestCase):

    def setUp(self):
        self.root = Path(self.enterContext(TemporaryDirectory()))
        shutil.copytree(DATA_DIR / "2026", self.root / "2026")
        self.payload = {
            "id": "campaign.toyota.test", "brand_id": "toyota", "name": "Test",
            "options": [{"id": "cash", "label": "Cash",
                         "conditions": {"booking_to": "2026-12-31", "text": "x"}}],
        }

    def save(self, payload=None, **changes):
        return save_campaign(self.root, 2026, {**(payload or self.payload), **changes},
                             write=True)

    def test_saving_then_saving_again_replaces_rather_than_duplicates(self):
        self.assertFalse(self.save()["replaced"])
        self.assertTrue(self.save(name="Test 2")["replaced"])
        ledger = ProductMaster.load(self.root).prices
        self.assertEqual("Test 2", ledger.campaigns["campaign.toyota.test"].name)

    def test_a_campaign_needs_at_least_one_option(self):
        with self.assertRaises(Exception):
            self.save(options=[])

    def test_an_unknown_brand_is_refused(self):
        with self.assertRaises(CatalogError):
            self.save(brand_id="not_a_brand")

    def test_a_campaign_that_ends_before_it_starts_is_refused(self):
        with self.assertRaises(Exception):
            self.save(starts="2026-12-01", ends="2026-01-01")

    def test_a_dry_run_writes_nothing(self):
        path = self.root / "2026/market/campaigns/toyota.json"
        save_campaign(self.root, 2026, self.payload, write=False)
        self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
