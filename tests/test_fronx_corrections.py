"""The Fronx: a capped offer that closed early, and an article that did not.

Suzuki published the GL cash price of 599,000 to 30 September 2026 and closed it
on 25 August when the 200-car quota was taken. Headlightmag's article of
1 September still listed it. A calendar-only campaign model would have gone on
quoting a price nobody could buy, and a feed that treats the press as the
authority on a brand's own offer would have published it.
"""

import json
import unittest
from dataclasses import replace
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


class ClosedCampaignEchoTests(unittest.TestCase):
    """Placing a claim against an offer the brand has already closed.

    The first version of this rule matched on trim and amount alone: any claim
    at 599,000 for the GL was "contradicted by a closed campaign", including
    Suzuki's own list price and any future campaign that happened to land on the
    same round number.  Matching a closed offer is not a contradiction.  What
    the offer was doing on the day the article ran is.
    """

    @classmethod
    def setUpClass(cls):
        cls.master = ProductMaster.load()
        cls.catalog = Catalog.load(year=2026)
        cls.sources = pf.load_sources()

    def document(self, published_at, *, source_id="headlightmag"):
        return pf.SourceDocument(
            document_id="sha256:d", source_id=source_id,
            url="https://www.headlightmag.com/special-price-suzuki-fronx-september-2026/"
                if source_id == "headlightmag"
                else "https://www.suzuki.co.th/news/articles/news-999",
            content_hash="d", published_at=published_at)

    def claim(self, *, amount=599_000, price_type=PriceType.CAMPAIGN_PRICE,
              source_id="headlightmag", trim_raw="Fronx 1.5 GL 4AT"):
        return pf.PriceClaim(
            claim_id="c1", document_id="sha256:d", source_id=source_id,
            brand_raw="Suzuki", model_raw="Fronx", trim_raw=trim_raw,
            amount_thb=amount, price_type=price_type,
            reference_price_thb=689_000)

    def reasons(self, *, published_at, day="2026-09-08", **claim_kwargs):
        source_id = claim_kwargs.get("source_id", "headlightmag")
        result = pf.run(
            [self.document(published_at, source_id=source_id)],
            [self.claim(**claim_kwargs)], self.sources, self.catalog,
            campaigns=self.master.prices.campaigns, ledger=self.master.prices,
            as_of=date.fromisoformat(day))
        held = result.offers + result.provisional + result.review
        self.assertEqual(1, len(held), "one claim should produce one item")
        return set(held[0]["reasons"]), held[0]["state"]

    # -- A ------------------------------------------------------------------
    def test_a_a_list_price_at_the_same_amount_is_not_a_closed_campaign(self):
        """Suzuki's own MSRP is not answerable to Suzuki's own expired promo."""
        reasons, state = self.reasons(
            published_at="2026-09-08T00:00:00+00:00",
            price_type=PriceType.LIST_PRICE, source_id="official_oem")
        self.assertNotIn(pf.ReviewReason.CONTRADICTED_BY_CLOSED_CAMPAIGN.value,
                         reasons)
        self.assertEqual("canonical", state)

    # -- B ------------------------------------------------------------------
    def test_b_a_new_official_campaign_may_reuse_the_same_round_number(self):
        reasons, _ = self.reasons(
            published_at="2026-09-08T00:00:00+00:00", source_id="official_oem")
        # Still held, but on the structural rule that a campaign price must
        # name the campaign it belongs to -- not on August's closed offer.
        self.assertEqual({pf.ReviewReason.CAMPAIGN_WITHOUT_CONDITIONS.value},
                         reasons)

    # -- C ------------------------------------------------------------------
    def test_c_an_article_published_after_the_offer_closed_is_stale(self):
        reasons, state = self.reasons(published_at="2026-09-01T03:16:48+00:00")
        self.assertIn(pf.ReviewReason.CONTRADICTED_BY_CLOSED_CAMPAIGN.value,
                      reasons)
        self.assertEqual("review", state)

    # -- D ------------------------------------------------------------------
    def test_d_an_article_published_while_it_was_open_is_history_not_a_lie(self):
        reasons, state = self.reasons(published_at="2026-08-03T04:04:22+00:00")
        self.assertNotIn(pf.ReviewReason.CONTRADICTED_BY_CLOSED_CAMPAIGN.value,
                         reasons)
        self.assertIn(pf.ReviewReason.HISTORICAL_CAMPAIGN_OBSERVATION.value,
                      reasons)
        self.assertEqual("review", state)

    # -- E ------------------------------------------------------------------
    def test_e_a_claim_with_no_publication_date_fails_closed(self):
        reasons, state = self.reasons(published_at=None)
        self.assertIn(pf.ReviewReason.CAMPAIGN_DATE_UNKNOWN.value, reasons)
        self.assertNotIn(pf.ReviewReason.CONTRADICTED_BY_CLOSED_CAMPAIGN.value,
                         reasons)
        self.assertEqual("review", state)

    def test_the_same_article_is_untouched_while_the_offer_is_still_open(self):
        reasons, _ = self.reasons(published_at="2026-08-03T04:04:22+00:00",
                                  day="2026-08-20")
        self.assertEqual(set(), reasons & {
            pf.ReviewReason.CONTRADICTED_BY_CLOSED_CAMPAIGN.value,
            pf.ReviewReason.HISTORICAL_CAMPAIGN_OBSERVATION.value,
            pf.ReviewReason.CAMPAIGN_DATE_UNKNOWN.value})


class CommittedDecisionsTests(unittest.TestCase):
    """What the repository says about who decided, and on what grounds."""

    @classmethod
    def setUpClass(cls):
        cls.decisions = pf.load_decisions(
            DATA_DIR / "2026/market/pricefeed/review/decisions.json")

    def test_the_stale_september_article_is_rejected_on_the_brands_own_page(self):
        stale = self.decisions["45b1b1dbc600ffdc"]
        self.assertEqual(("reject", "SYSTEM_EVIDENCE"),
                         (stale["action"], stale["origin"]))
        self.assertIn("news-245", stale["source_ref"])
        self.assertIn("2026-08-25", stale["notes"])

    def test_the_august_article_is_filed_as_history_and_never_called_stale(self):
        historical = self.decisions["63d4da6e34bb0e87"]
        self.assertEqual(("archive", "SYSTEM_EVIDENCE"),
                         (historical["action"], historical["origin"]))
        self.assertIn("Historical", historical["notes"])
        self.assertNotIn("Stale", historical["notes"])

    def test_no_committed_decision_claims_a_person_who_did_not_act(self):
        """The defect this replaces: a rule signing the owner's name."""
        for decision in self.decisions.values():
            if decision["origin"] == pf.DecisionOrigin.HUMAN.value:
                continue
            self.assertNotIn("owner", decision["reviewer"].lower())


class FronxTemporalStatusTests(unittest.TestCase):
    """What the offer was on the quoted day, and what it is now, are two facts."""

    @classmethod
    def setUpClass(cls):
        cls.master = ProductMaster.load()

    def option(self, trim_id, day):
        return self.master.prices.campaign_quote(
            trim_id, as_of=date.fromisoformat(day))["campaign_options"]

    def test_a_quote_from_before_it_sold_out_reads_active_for_that_day(self):
        [offer] = self.option(GL, "2026-08-20")
        self.assertEqual("ACTIVE", offer["status_as_of"])
        self.assertEqual("SOLD_OUT", offer["current_status"])
        self.assertEqual("2026-08-25", offer["closed_at"])

    def test_after_it_sold_out_there_is_no_option_to_report_a_status_for(self):
        self.assertEqual([], self.option(GL, "2026-08-26"))

    def test_a_running_offer_reads_active_in_both_fields(self):
        offers = {o["option_id"]: o for o in self.option(GLX, "2026-09-08")}
        for offer in offers.values():
            self.assertEqual(("ACTIVE", "ACTIVE"),
                             (offer["status_as_of"], offer["current_status"]))
            self.assertIsNone(offer["closed_at"])


class SharedQuotaTests(unittest.TestCase):
    """499 cars for the campaign, not 499 for each way of buying one."""

    @classmethod
    def setUpClass(cls):
        cls.master = ProductMaster.load()

    def test_the_cap_is_written_once_on_the_campaign(self):
        campaign = self.master.prices.campaigns[CURRENT]
        self.assertEqual(499, campaign.quota_units)
        self.assertEqual({None}, {o.conditions.quota_units
                                  for o in campaign.options})

    def test_every_option_reports_the_pool_it_draws_from(self):
        offers = self.master.prices.campaign_quote(
            GLX, as_of=date(2026, 9, 8))["campaign_options"]
        self.assertEqual([(499, "CAMPAIGN")] * len(offers),
                         [(o["quota_units"], o["quota_scope"]) for o in offers])

    def test_an_option_may_not_restate_the_campaign_cap_as_its_own(self):
        campaign = self.master.prices.campaigns[CURRENT]
        clashing = replace(campaign, options=(
            replace(campaign.options[0], conditions=replace(
                campaign.options[0].conditions, quota_units=499)),))
        self.assertTrue(any("restates the campaign quota" in problem
                            for problem in clashing.validate()))

    def test_the_august_cap_really_was_that_options_own(self):
        campaign = self.master.prices.campaigns[HISTORICAL]
        self.assertIsNone(campaign.quota_units)
        self.assertEqual(200, campaign.option("family_cash").conditions.quota_units)


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
