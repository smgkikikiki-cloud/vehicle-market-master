"""The Fronx: a capped offer that closed early, and an article that did not.

Suzuki published the GL cash price of 599,000 to 30 September 2026 and closed it
on 25 August when the 200-car quota was taken. Headlightmag's article of
1 September still listed it. A calendar-only campaign model would have gone on
quoting a price nobody could buy, and a feed that treats the press as the
authority on a brand's own offer would have published it.
"""

import json
import unittest
from datetime import date
from pathlib import Path

from vehreg.catalog import Catalog, DATA_DIR
from vehreg.pricing import OfferStatus, PriceType
from vehreg.product import ProductMaster
from vehreg import pricefeed as pf

GL = "suzuki.fronx.frx.trim.gl_1_5l_4at"
GLX = "suzuki.fronx.frx.trim.glx_1_5l_mhev_6at"
GLX_PLUS = "suzuki.fronx.frx.trim.glx_plus_1_5l_mhev_6at"
HISTORICAL = "campaign.suzuki.fronx_gl_aug_2026"
CURRENT = "campaign.suzuki.fronx_sep_oct_2026"


class FronxQuoteTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.master = ProductMaster.load()

    def quote(self, trim_id, day):
        return self.master.prices.campaign_quote(
            trim_id, as_of=date.fromisoformat(day))

    def options(self, trim_id, day):
        return {o["option_id"]: o["amount_thb"]
                for o in self.quote(trim_id, day)["campaign_options"]}

    def test_the_gl_offer_is_live_while_the_quota_lasts(self):
        self.assertEqual({"family_cash": 599_000},
                         self.options(GL, "2026-08-20"))
        self.assertEqual(689_000, self.quote(GL, "2026-08-20")["list_price_thb"])

    def test_the_gl_offer_ends_the_day_it_sold_out_not_the_day_it_said(self):
        """This is the whole point of closed_at living beside ends."""
        option = self.master.prices.campaigns[HISTORICAL].option("family_cash")
        self.assertEqual(("2026-09-30", "2026-08-25", OfferStatus.SOLD_OUT),
                         (option.ends, option.closed_at, option.status))
        self.assertEqual({}, self.options(GL, "2026-08-26"))

    def test_the_gl_price_is_not_quoted_in_september(self):
        quote = self.quote(GL, "2026-09-08")
        self.assertEqual(689_000, quote["list_price_thb"])
        self.assertEqual([], quote["campaign_options"])
        self.assertNotIn(
            599_000, [o["amount_thb"] for o in quote["campaign_options"]])

    def test_the_september_campaign_covers_glx_and_glx_plus_only(self):
        self.assertEqual({"family_cash": 649_000, "open_cash": 669_000},
                         self.options(GLX, "2026-09-08"))
        self.assertEqual({"family_cash": 699_000, "open_cash": 719_000},
                         self.options(GLX_PLUS, "2026-09-08"))
        self.assertEqual([], self.quote(GL, "2026-09-08")["campaign_options"])

    def test_cash_and_finance_are_alternatives_and_finance_quotes_no_price(self):
        campaign = self.master.prices.campaigns[CURRENT]
        finance = [o for o in campaign.options if o.conditions.finance_required]
        self.assertEqual({"family_finance", "open_finance"},
                         {o.id for o in finance})
        priced = {r.option_id for r in self.master.prices.records_for(
            GLX, price_type=PriceType.CAMPAIGN_PRICE)}
        self.assertEqual({"family_cash", "open_cash"}, priced)

    def test_the_closed_campaign_is_kept_as_history_not_deleted(self):
        rows = self.master.prices.records_for(
            GL, price_type=PriceType.CAMPAIGN_PRICE)
        self.assertEqual([599_000], [r.amount_thb for r in rows])
        self.assertEqual("2026-08-25", rows[0].effective_to)

    def test_no_campaign_is_left_open_ended(self):
        for campaign in self.master.prices.campaigns.values():
            if campaign.brand_id != "suzuki":
                continue
            self.assertIsNotNone(campaign.ends, f"{campaign.id} has no end date")


class ClosedCampaignBeatsTheArticleTests(unittest.TestCase):
    """Tier-A evidence that an offer is over outranks a Tier-B report of it."""

    def setUp(self):
        self.master = ProductMaster.load()
        self.documents = [pf.SourceDocument(
            document_id="sha256:d", source_id="headlightmag",
            url="https://www.headlightmag.com/special-price-suzuki-fronx-september-2026/",
            content_hash="d")]
        self.sources = pf.load_sources()

    def claim(self, amount, trim_raw):
        return pf.PriceClaim(
            claim_id="c1", document_id="sha256:d", source_id="headlightmag",
            brand_raw="Suzuki", model_raw="Fronx", trim_raw=trim_raw,
            amount_thb=amount, price_type=PriceType.CAMPAIGN_PRICE,
            reference_price_thb=689_000)

    def run_on(self, amount, trim_raw, day):
        return pf.run(
            self.documents, [self.claim(amount, trim_raw)], self.sources,
            Catalog.load(year=2026), campaigns=self.master.prices.campaigns,
            ledger=self.master.prices, as_of=date.fromisoformat(day))

    def test_a_september_article_cannot_republish_the_closed_august_price(self):
        result = self.run_on(599_000, "Fronx 1.5 GL 4AT", "2026-09-08")
        self.assertEqual([], result.offers)
        self.assertEqual([], result.provisional)
        self.assertIn(pf.ReviewReason.CONTRADICTED_BY_CLOSED_CAMPAIGN.value,
                      result.review[0]["reasons"])

    def test_the_same_article_was_right_while_the_offer_was_open(self):
        result = self.run_on(599_000, "Fronx 1.5 GL 4AT", "2026-08-20")
        held = result.offers + result.provisional + result.review
        self.assertNotIn(pf.ReviewReason.CONTRADICTED_BY_CLOSED_CAMPAIGN.value,
                         held[0]["reasons"])

    def test_the_owner_rejected_the_stale_claim_in_the_committed_decisions(self):
        decisions = pf.load_decisions(
            DATA_DIR / "2026/market/pricefeed/review/decisions.json")
        stale = decisions["45b1b1dbc600ffdc"]
        self.assertEqual(("reject", "human"), (stale["action"], stale["origin"]))
        self.assertIn("2026-08-25", stale["notes"])


class FronxCatalogTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.catalog = Catalog.load(year=2026)

    def test_the_generation_is_dated_and_sourced_from_indonesia(self):
        generation = self.catalog.generations["suzuki.fronx.frx"]
        self.assertEqual("2025-09-25", generation.launched)
        origins = {v.origin_country for v in self.catalog.variants.values()
                   if v.generation_id == "suzuki.fronx.frx"}
        self.assertEqual({"ID"}, origins)

    def test_the_glx_alias_is_not_parked_on_the_four_speed_petrol_line(self):
        variants = {v.name: v for v in self.catalog.variants.values()
                    if v.generation_id == "suzuki.fronx.frx"}
        self.assertEqual({"1.5L K15B 4AT", "1.5L K15C SHVS 6AT"}, set(variants))
        self.assertNotIn("1.5 glx",
                         [a.lower() for a in variants["1.5L K15B 4AT"].aliases])
        self.assertIn("1.5 glx",
                      [a.lower() for a in variants["1.5L K15C SHVS 6AT"].aliases])

    def test_the_mild_hybrid_is_declared_technology_not_a_powertrain(self):
        """A 12V belt starter does not make the car electrified."""
        trims = {t.id: t for t in self.catalog.trims.values()
                 if t.id.startswith("suzuki.fronx.")}
        self.assertEqual({GL, GLX, GLX_PLUS}, set(trims))
        for trim_id in (GLX, GLX_PLUS):
            self.assertEqual("ICE", trims[trim_id].powertrain.value)
            self.assertEqual("K15C", trims[trim_id].engine_code)
            self.assertIn("SHVS", trims[trim_id].notes)
        self.assertEqual("K15B", trims[GL].engine_code)
        self.assertEqual(("4AT", "6AT", "6AT"),
                         (trims[GL].transmission, trims[GLX].transmission,
                          trims[GLX_PLUS].transmission))
        self.assertEqual({"FWD"}, {t.drivetrain.value for t in trims.values()})


if __name__ == "__main__":
    unittest.main()
