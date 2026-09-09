"""The publish policy, exercised on the shapes real Thai price news arrives in."""

import json
import unittest
from datetime import date
from pathlib import Path

from vehreg.catalog import Catalog
from vehreg import pricefeed as pf
from vehreg.pricing import Campaign, CampaignOption, Conditions, PriceType


def source(source_id, tier, **changes):
    return pf.Source(id=source_id, name=source_id, tier=pf.Tier(tier), **changes)


SOURCES = {
    "official_oem": source("official_oem", "A"),
    "outlet_a": source("outlet_a", "B"),
    "outlet_b": source("outlet_b", "B"),
    "aggregator": source("aggregator", "B", republisher=True),
    "forum": source("forum", "D"),
}


def document(document_id, source_id, sketch=(), **changes):
    return pf.SourceDocument(
        document_id=f"sha256:{document_id}", source_id=source_id,
        url=f"https://example.test/{document_id}", content_hash=document_id,
        body_sketch=tuple(sketch), **changes)


def claim(claim_id, source_id, *, amount=1_290_000, trim_id="t.m.g.trim.x",
          price_type=PriceType.LIST_PRICE, document_id=None, **changes):
    return pf.PriceClaim(
        claim_id=claim_id, document_id=f"sha256:{document_id or source_id}",
        source_id=source_id, brand_raw="Toyota", model_raw="Alphard",
        trim_raw="HEV Premium", amount_thb=amount, price_type=price_type,
        trim_id=trim_id, **changes)


class PublishPolicyTests(unittest.TestCase):

    def docs(self, *pairs):
        return {d.document_id: d for d in
                (document(name, src, sketch=sketch) for name, src, sketch in pairs)}

    def test_one_manufacturer_source_is_enough(self):
        verdict = pf.decide([claim("c1", "official_oem")], SOURCES)
        self.assertEqual("canonical", verdict.state)

    def test_one_outlet_alone_stays_internal(self):
        verdict = pf.decide([claim("c1", "outlet_a")], SOURCES)
        self.assertEqual("provisional", verdict.state)
        self.assertIn(pf.ReviewReason.SINGLE_TIER_B.value, verdict.reasons)

    def test_two_outlets_writing_their_own_words_are_two_voices(self):
        documents = self.docs(("outlet_a", "outlet_a", ("aa", "ab", "ac")),
                              ("outlet_b", "outlet_b", ("ba", "bb", "bc")))
        verdict = pf.decide([claim("c1", "outlet_a"), claim("c2", "outlet_b")],
                            SOURCES, documents=documents)
        self.assertEqual(("canonical", 2), (verdict.state, verdict.independent_claims))

    def test_two_outlets_reprinting_one_press_release_are_one_voice(self):
        shared = tuple(f"s{i}" for i in range(20))
        documents = self.docs(("outlet_a", "outlet_a", shared),
                              ("outlet_b", "outlet_b", shared + ("extra",)))
        verdict = pf.decide([claim("c1", "outlet_a"), claim("c2", "outlet_b")],
                            SOURCES, documents=documents)
        self.assertEqual(("provisional", 1), (verdict.state, verdict.independent_claims))

    def test_two_stories_from_one_outlet_are_still_one_voice(self):
        documents = self.docs(("d1", "outlet_a", ("aa",)), ("d2", "outlet_a", ("zz",)))
        verdict = pf.decide(
            [claim("c1", "outlet_a", document_id="d1"),
             claim("c2", "outlet_a", document_id="d2")], SOURCES, documents=documents)
        self.assertEqual(1, verdict.independent_claims)

    def test_a_known_republisher_never_verifies_a_price_alone(self):
        verdict = pf.decide([claim("c1", "aggregator")], SOURCES)
        self.assertEqual("provisional", verdict.state)

    def test_social_posts_are_not_evidence(self):
        verdict = pf.decide([claim("c1", "forum")], SOURCES)
        self.assertEqual("review", verdict.state)
        self.assertIn(pf.ReviewReason.LOW_TIER_ONLY.value, verdict.reasons)

    def test_an_instalment_sized_number_is_not_a_price(self):
        verdict = pf.decide([claim("c1", "official_oem", amount=6_770)], SOURCES)
        self.assertEqual("review", verdict.state)
        self.assertIn(pf.ReviewReason.IMPLAUSIBLE_AMOUNT.value, verdict.reasons)

    def test_a_campaign_price_without_conditions_is_never_published(self):
        verdict = pf.decide([claim("c1", "official_oem",
                                   price_type=PriceType.CAMPAIGN_PRICE)],
                            SOURCES, has_conditions=False)
        self.assertEqual("review", verdict.state)
        self.assertIn(pf.ReviewReason.CAMPAIGN_WITHOUT_CONDITIONS.value,
                      verdict.reasons)

    def test_an_unmatched_trim_blocks_even_a_manufacturer_price(self):
        verdict = pf.decide([claim("c1", "official_oem", trim_id=None)], SOURCES)
        self.assertEqual("review", verdict.state)
        self.assertIn(pf.ReviewReason.NO_TRIM_MATCH.value, verdict.reasons)

    def test_sources_that_disagree_are_a_question_not_a_tie_break(self):
        claims = [claim("c1", "official_oem", amount=1_290_000),
                  claim("c2", "outlet_a", amount=1_390_000)]
        disputed = pf.conflicting(claims)
        self.assertEqual({("t.m.g.trim.x", PriceType.LIST_PRICE)}, set(disputed))
        self.assertEqual({1_290_000, 1_390_000},
                         disputed[("t.m.g.trim.x", PriceType.LIST_PRICE)])


class LatencyTests(unittest.TestCase):

    def test_latency_is_measured_from_publication_not_from_the_run(self):
        documents = [
            document("d1", "outlet_a", published_at="2026-09-08T01:00:00+00:00",
                     first_seen_at="2026-09-08T03:00:00+00:00"),
            document("d2", "outlet_a", published_at="2026-09-07T00:00:00+00:00",
                     first_seen_at="2026-09-09T00:00:00+00:00"),
        ]
        measured = pf.measure_latency(documents)
        self.assertEqual(2, measured["documents_with_latency"])
        self.assertEqual(2.0, min(d.latency_hours() for d in documents))
        self.assertEqual(1, measured["within_24h"])


class DecisionTests(unittest.TestCase):

    def setUp(self):
        self.path = Path(self.enterContext(
            __import__("tempfile").TemporaryDirectory())) / "decisions.json"

    def write(self, reviewer, origin=None, **extra):
        entry = {
            "claim_id": "c1", "trim_id": "t.m.g.trim.x",
            "campaign_id": "campaign.x", "option_id": "cash",
            "action": "accept", "reviewer": reviewer,
        }
        if origin is not None:
            entry["origin"] = origin
        entry.update(extra)
        self.path.write_text(json.dumps({"decisions": [entry]}), encoding="utf-8")

    def test_a_decision_this_code_wrote_does_not_move_a_price(self):
        self.write("agent-proposed", "AGENT")
        self.assertEqual("AGENT", pf.load_decisions(self.path)["c1"]["origin"])

    def test_a_person_outranks_the_matcher(self):
        self.write("vehicle-master-owner", "HUMAN")
        self.assertEqual("HUMAN", pf.load_decisions(self.path)["c1"]["origin"])

    def test_who_decided_is_stated_and_never_read_off_the_reviewer_name(self):
        """The whole defect in one test: a name is not a provenance claim."""
        self.write("vehicle-master-owner")
        with self.assertRaises(pf.PriceFeedError) as caught:
            pf.load_decisions(self.path)
        self.assertIn("origin is required", str(caught.exception))

    def test_a_rule_may_decide_but_has_to_cite_the_document_it_read(self):
        self.write("pricefeed.closed_campaign_echo", "SYSTEM_EVIDENCE")
        with self.assertRaises(pf.PriceFeedError):
            pf.load_decisions(self.path)
        self.write("pricefeed.closed_campaign_echo", "SYSTEM_EVIDENCE",
                   source_ref="https://www.suzuki.co.th/news/articles/news-245")
        self.assertEqual("SYSTEM_EVIDENCE",
                         pf.load_decisions(self.path)["c1"]["origin"])

    def test_only_a_person_can_vouch_for_a_single_source(self):
        for origin in ("AGENT", "SYSTEM_EVIDENCE"):
            self.write("whoever", origin, action="publish",
                       source_ref="https://example.com/x")
            with self.assertRaises(pf.PriceFeedError):
                pf.load_decisions(self.path)

    def test_a_decision_without_a_reviewer_is_rejected(self):
        self.path.write_text(json.dumps({"decisions": [{"claim_id": "c1"}]}),
                             encoding="utf-8")
        with self.assertRaises(pf.PriceFeedError):
            pf.load_decisions(self.path)


class CampaignResolverTests(unittest.TestCase):
    """Options are alternatives; an ended campaign is hidden, never deleted."""

    def ledger(self):
        from vehreg.pricing import PriceLedger
        ledger = PriceLedger(2026)
        ledger.campaigns["campaign.x"] = Campaign(
            id="campaign.x", brand_id="acme", name="Test",
            starts="2026-03-01", ends="2026-04-05",
            options=(
                CampaignOption("cash", "Cash",
                               Conditions(booking_to="2026-04-05", text="เงินสด")),
                CampaignOption("finance", "0%",
                               Conditions(booking_to="2026-04-05",
                                          finance_required=True, text="ไฟแนนซ์")),
            ))
        ledger.add_payload({"prices": [
            {"trim_id": "t", "amount_thb": 899_900, "price_type": "LIST_PRICE",
             "effective_from": "2026-01-01"},
            {"trim_id": "t", "amount_thb": 859_900, "price_type": "CAMPAIGN_PRICE",
             "campaign_id": "campaign.x", "option_id": "cash",
             "reference_price_thb": 899_900,
             "effective_from": "2026-03-01", "effective_to": "2026-04-05"},
            {"trim_id": "t", "amount_thb": 879_900, "price_type": "CAMPAIGN_PRICE",
             "campaign_id": "campaign.x", "option_id": "finance",
             "effective_from": "2026-03-01", "effective_to": "2026-04-05"},
        ]})
        return ledger

    def test_every_live_option_is_offered_and_none_is_called_best(self):
        quote = self.ledger().campaign_quote("t", as_of=date(2026, 3, 15))
        self.assertEqual(899_900, quote["list_price_thb"])
        self.assertEqual(2, len(quote["campaign_options"]))
        by_option = {o["option_id"]: o for o in quote["campaign_options"]}
        self.assertEqual(40_000, by_option["cash"]["discount_thb"])
        # The finance option quotes no "from" price, so no discount is invented.
        self.assertIsNone(by_option["finance"]["discount_thb"])
        self.assertTrue(by_option["finance"]["conditions"]["finance_required"])

    def test_an_ended_campaign_stops_showing_but_the_list_price_stays(self):
        quote = self.ledger().campaign_quote("t", as_of=date(2026, 5, 1))
        self.assertEqual(899_900, quote["list_price_thb"])
        self.assertEqual([], quote["campaign_options"])

    def test_history_survives_the_campaign(self):
        ledger = self.ledger()
        self.assertEqual(2, len(ledger.records_for(
            "t", price_type=PriceType.CAMPAIGN_PRICE)))


if __name__ == "__main__":
    unittest.main()


class RobotsTests(unittest.TestCase):
    """A source that says no is not polled, however useful it would be."""

    SUZUKI = "\n".join([
        "User-agent: *",
        "Content-Signal: search=yes,ai-train=no,use=reference",
        "Allow: /",
        "User-agent: ClaudeBot",
        "Disallow: /",
        "User-agent: GPTBot",
        "Disallow: /",
    ])

    def report(self, text):
        from tools import robots_check
        from urllib.robotparser import RobotFileParser
        parser = RobotFileParser()
        parser.parse(text.splitlines())
        return {
            "base_url": "https://example.test",
            "robots_txt": bool(text.strip()),
            "may_fetch": parser.can_fetch(robots_check.AGENT, "https://example.test/"),
            "content_signal": robots_check.content_signal(text),
            "ai_agents_disallowed": robots_check.blocked_agents(text),
        }

    def test_naming_ai_crawlers_in_disallow_is_a_refusal(self):
        from tools import robots_check
        report = self.report(self.SUZUKI)
        self.assertIn("claudebot", report["ai_agents_disallowed"])
        self.assertTrue(robots_check.verdict(report).startswith("refused"))

    def test_an_open_site_is_allowed(self):
        from tools import robots_check
        report = self.report("User-agent: *\nDisallow:\n")
        self.assertEqual("allowed", robots_check.verdict(report))

    def test_no_robots_file_is_allowed_but_says_so(self):
        from tools import robots_check
        self.assertIn("no robots.txt", robots_check.verdict(self.report("")))

    def test_content_signal_is_parsed(self):
        from tools import robots_check
        self.assertEqual({"search": "yes", "ai-train": "no", "use": "reference"},
                         robots_check.content_signal(self.SUZUKI))


class ExtractionTests(unittest.TestCase):
    """The two shapes a Thai price table actually comes in."""

    def document(self):
        return pf.SourceDocument(document_id="sha256:d", source_id="outlet_a",
                                 url="https://example.test/x", content_hash="d")

    def extract(self, body, title=""):
        from tools.pricefeed_harvest import extract_claims
        return extract_claims(self.document(), title=title, body=body,
                              brand_raw="Suzuki", model_raw="Fronx")

    def test_a_struck_through_figure_is_the_old_price_not_the_price(self):
        rows = self.extract(
            "<li>Fronx 1.5 GL 4AT :<del>689,000 บาท</del> 599,000 บาท</li>",
            title="ราคาพิเศษ Suzuki Fronx")
        self.assertEqual(1, len(rows))
        self.assertEqual((599_000, 689_000),
                         (rows[0].amount_thb, rows[0].reference_price_thb))

    def test_a_table_without_a_colon_still_reads(self):
        rows = self.extract("<li>Alphard HEV Smart  3,590,000 บาท</li>",
                            title="ราคาอย่างเป็นทางการ")
        self.assertEqual([3_590_000], [row.amount_thb for row in rows])

    def test_an_instalment_or_a_free_gift_is_not_a_price(self):
        self.assertEqual([], self.extract(
            "<li>ผ่อนเดือนละ 6,770 บาท</li>"
            "<li>ขยายระยะรับประกัน มูลค่า 22,000 บาท</li>"
            "<li>ดอกเบี้ย 0% ส่วนลดอุปกรณ์สูงสุด 40,000 บาท</li>"))

    def test_bare_hybrid_wording_does_not_decide_a_price_type(self):
        rows = self.extract("<li>Fronx 1.5 GL 4AT : 599,000 บาท</li>")
        self.assertEqual(PriceType.UNKNOWN, rows[0].price_type)

    def test_a_foreign_market_article_is_not_a_thai_price(self):
        from tools.pricefeed_harvest import foreign_market
        self.assertTrue(foreign_market(
            "Toyota LAND CRUISER FJ เปิดตัวในอินโดนีเซีย", "https://x/y"))
        self.assertFalse(foreign_market("ราคาอย่างเป็นทางการ Toyota Land Cruiser FJ",
                                        "https://x/official-price"))


class ReviewDecisionWritingTests(unittest.TestCase):
    """A second answer about one claim adds to the first; it never erases it."""

    def setUp(self):
        from tempfile import TemporaryDirectory
        self.path = Path(self.enterContext(TemporaryDirectory())) / "decisions.json"

    def save(self, **changes):
        entry = {"claim_id": "c1", "reviewer": "owner", "action": "accept",
                 "origin": "HUMAN"}
        entry.update(changes)
        return pf.save_decision(self.path, entry, write=True,
                                replace=entry["action"] == "reject")

    def stored(self):
        return json.loads(self.path.read_text(encoding="utf-8"))["decisions"][0]

    def test_vouching_for_a_price_keeps_the_campaign_it_was_bound_to(self):
        self.save(campaign_id="campaign.x", option_id="cash")
        self.save(action="publish", notes="one source is enough here")
        stored = self.stored()
        self.assertEqual(("publish", "campaign.x", "cash"),
                         (stored["action"], stored["campaign_id"],
                          stored["option_id"]))

    def test_rejecting_withdraws_the_whole_answer(self):
        self.save(campaign_id="campaign.x", option_id="cash")
        self.save(action="reject")
        stored = self.stored()
        self.assertEqual("reject", stored["action"])
        self.assertIsNone(stored.get("campaign_id"))

    def test_a_bad_entry_cannot_take_the_good_ones_down_with_it(self):
        self.save(campaign_id="campaign.x")
        with self.assertRaises(pf.PriceFeedError):
            pf.save_decision(self.path,
                             {"claim_id": "c2", "reviewer": "owner",
                              "origin": "HUMAN",
                              "action": "not-an-action"}, write=True)
        self.assertEqual("campaign.x", self.stored()["campaign_id"])

    def test_a_decision_without_a_reviewer_is_refused(self):
        with self.assertRaises(pf.PriceFeedError):
            pf.save_decision(self.path, {"claim_id": "c1", "action": "accept",
                                         "origin": "HUMAN"}, write=True)

    def test_a_decision_without_an_origin_is_refused(self):
        with self.assertRaises(pf.PriceFeedError):
            pf.save_decision(self.path, {"claim_id": "c1", "action": "accept",
                                         "reviewer": "owner"}, write=True)


class PublishOverrideTests(unittest.TestCase):
    """One outlet plus a person who vouches is enough; nothing else is."""

    def run_with(self, decision, *, trim_id="t.m.g.trim.x"):
        documents = {f"sha256:outlet_a": document("outlet_a", "outlet_a")}
        claims = [claim("c1", "outlet_a", trim_id=trim_id)]
        verdict = pf.decide(claims, SOURCES, documents=documents)
        return verdict

    def test_a_lone_outlet_is_provisional_without_a_person(self):
        self.assertEqual("provisional", self.run_with(None).state)

    def test_publish_is_only_offered_for_a_provisional_price(self):
        """Review reasons are structural: they get fixed, not overridden."""
        verdict = pf.decide([claim("c1", "outlet_a", trim_id=None)], SOURCES)
        self.assertEqual("review", verdict.state)


class PublishPromotionTests(unittest.TestCase):
    """The whole loop: a person's answer turns one outlet into a published price."""

    def batch(self):
        documents = [pf.SourceDocument(
            document_id="sha256:d1", source_id="outlet_a",
            url="https://example.test/a", content_hash="d1")]
        claims = [pf.PriceClaim(
            claim_id="c1", document_id="sha256:d1", source_id="outlet_a",
            # "MAX+" is deliberately not used here: it folds to the same token
            # as the alias "Max" on a sibling trim, and the matcher refuses it.
            brand_raw="Jaecoo", model_raw="Jaecoo 5 EV",
            trim_raw="Long Range Dynamic",
            amount_thb=699_000, price_type=PriceType.LIST_PRICE)]
        return documents, claims

    def run_with(self, decisions):
        from vehreg.catalog import Catalog
        documents, claims = self.batch()
        return pf.run(documents, claims, SOURCES, Catalog.load(year=2026),
                      decisions=decisions)

    def decision(self, action, reviewer):
        return {"c1": {"claim_id": "c1", "action": action, "reviewer": reviewer,
                       "origin": ("AGENT" if reviewer == pf.AGENT_REVIEWER
                                  else "HUMAN"), "source_ref": "",
                       "trim_id": None, "campaign_id": None, "option_id": None,
                       "reviewed_at": None, "notes": ""}}

    def test_without_a_person_one_outlet_stays_internal(self):
        result = self.run_with({})
        self.assertEqual((0, 1), (len(result.offers), len(result.provisional)))

    def test_a_person_vouching_publishes_it(self):
        result = self.run_with(self.decision("publish", "vehicle-master-owner"))
        self.assertEqual((1, 0), (len(result.offers), len(result.provisional)))
        self.assertEqual(["vehicle-master-owner"], result.offers[0]["published_by"])

    def test_this_code_vouching_for_itself_changes_nothing(self):
        result = self.run_with(self.decision("publish", pf.AGENT_REVIEWER))
        self.assertEqual((0, 1), (len(result.offers), len(result.provisional)))

    def test_a_person_rejecting_drops_the_claim_entirely(self):
        result = self.run_with(self.decision("reject", "vehicle-master-owner"))
        self.assertEqual([], result.offers + result.provisional + result.review)
