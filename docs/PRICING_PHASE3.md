# Phase 3 — live retail pricing

**Status: proposal awaiting the owner's approval. No code in this document is
implemented yet.**

The goal the owner set: a distinct price per trim, a separate campaign price
with its real conditions, refreshed within 24 hours of an announcement, resolved
dynamically by date. Coverage is explicitly *not* a goal — a trim with no price
is fine, a trim with a wrong price is not.

This is a review of the design drafted alongside it, and the plan that replaces
it. The three-layer core of that draft — Document / Claim / Offer — is right and
is kept. Seven things are changed.

---

## What is kept

**Document → Claim → Offer.** One fetched page is one `SourceDocument`. Each
number an outlet asserts is a `PriceClaim` against that document. A number the
system is willing to stand behind is a `PriceOffer`. Two outlets reporting the
same launch produce two claims and one offer. This is the same shape Phase 2
uses for ECO records, and it is the reason a retraction can be traced back to
the page that caused it.

**One offer, one trim.** No model-level "529,900–709,900" in the ledger. A range
is a rendering of several offers, never a stored fact.

**Campaign price never overwrites MSRP.** They are two offers on the same trim
with different `price_type`. When a campaign ends, nothing is deleted; the
resolver simply stops selecting it.

**Structured conditions, and options are OR.** A campaign offering "cash
discount" *or* "0% finance" is two options under one campaign. Conditions inside
one option are AND. Never merge the best of both.

**Benefits are not vehicle prices.** Monthly instalment, free insurance,
trade-in bonus, wall charger — none of these become a `CAMPAIGN_PRICE`. A number
becomes a campaign price only when the source states a purchase price.

**Provisional stays internal.** A single Tier-B report is visible in the review
panel and never on the public site.

---

## What changes, and why

### 1. `FUTURE_LIST_PRICE` is deleted. A window already does this.

The draft invents a price type for "529,900 until 30 June, then 579,900". The
ledger built in Phase 1 already resolves that with two ordinary `LIST_PRICE`
rows and no new code:

```
2026-05-15 -> 529900
2026-06-30 -> 529900
2026-07-01 -> 579900
2026-09-08 -> 579900
```

Adding the type makes it *worse*: `current_list_price` filters on
`price_type is LIST_PRICE`, so a `FUTURE_LIST_PRICE` row would be invisible on
1 July and the trim would resolve to no price at all. A type that the resolver
must special-case to undo is a type that should not exist.

The rule: **a price type describes what kind of money it is, never when it
applies.** When it applies is `effective_from` / `effective_to`.

`DEALER_PRICE` is kept from the draft — that one is a genuinely different kind
of money (one dealer's number, not the manufacturer's).

### 2. No `prices/v2/`. The existing ledger grows.

The draft forks a parallel `prices/v2/` tree. Two ledgers means two answers to
"what does this cost", and the older one will not be deleted on schedule.

`PriceOffer` is `PriceRecord` plus five fields: `offer_id`, `campaign_id`,
`option_id`, `reference_price_thb`, `conditions`. Everything already written —
`current_list_price` and its supersession rule, the conflict error, validation,
the ECO price separation, the tests — carries forward. `PriceType.parse` is
fail-closed today, so an unknown type is rejected rather than silently stored;
that stays.

### 3. Structure only the conditions the resolver reads

The draft's `condition_set` has fifteen fields. Code branches on four of them.
The other eleven produce eleven nulls on every row and the appearance of
structure where there is none.

Stored as fields, because the resolver reads them:

| Field | Why code needs it |
|---|---|
| `booking_from` / `booking_to` | decides whether the offer is live today |
| `delivery_by` | a campaign can require delivery inside a window |
| `quota_units` | a campaign can end before its calendar date |
| `finance_required` | separates a cash option from a finance option |

Everything else — eligible colours, customer groups, sales channel, trade-in,
interest rate, down payment — goes in `condition_text` **verbatim in Thai, as
the source wrote it**. It is displayed, not computed. A field earns its place in
the schema by being read by code; until then it is decoration that goes stale.

`quota_units` is stored but never counted down automatically. Nobody publishes
live remaining quota, so a quota campaign shows its cap and its date, and the
system does not pretend to know when the cap was hit.

### 4. Two Tier-B sources are usually one source

Thai car media republish the same manufacturer press release within minutes, in
near-identical wording. Counting that as two-source consensus is counting one
press release twice, and it is exactly how a wrong figure in a press release
becomes "verified".

Consensus requires two **independent** claims. Independence is checked, not
assumed: if two claims' evidence text is near-identical (normalised similarity
above a fixed threshold), they collapse to one for consensus purposes. Both
claims are still stored — the evidence is real — but they do not vote twice.

An outlet that only ever republishes verbatim will therefore never produce a
verified price on its own, which is the correct outcome.

### 5. The trim-must-exist rule defeats the 24-hour goal

This is the largest gap in the draft. It says a claim that cannot be matched to
a `MarketTrim` is queued and no price is published. On launch day the trim does
not exist yet — that is what a launch is. So the single most valuable case, the
one the 24-hour target exists for, is guaranteed to miss it.

A launch claim therefore carries a **bundled trim proposal**: the price claim
and the trim it implies (brand, model, trim name, powertrain if stated) go into
the review queue together as one decision. The owner accepts once and both the
trim and its price appear. Accepting a price still cannot create a trim silently
— but it stops being two separate pieces of work a week apart.

Existing-trim price changes still publish automatically under the rules below.

### 6. Discovery: the WordPress REST API, not RSS or scraping

Both Tier-B sources run WordPress, and both expose `/wp-json/wp/v2/posts`. That
endpoint is better than every alternative in the draft:

```
/wp-json/wp/v2/posts?modified_after=<last_poll>&per_page=100&_fields=id,date,modified,link,title
```

- returns the delta as JSON, a few KB per poll, no HTML parsing;
- `modified` changes when an outlet **edits a published price** — RSS and
  sitemaps cannot tell you that, and a corrected price is exactly the thing that
  must not be missed;
- `_fields` keeps the poll tiny; article body is fetched only for posts that
  look like price news.

Measured today: Headlightmag's RSS feed holds only **10 items**, so a busy
afternoon can push a launch off the feed before a poll sees it. The REST
endpoint has no such window. Headlightmag published 12 posts in the last day —
the volume is small, so politeness costs nothing.

`robots.txt`, checked today: AutoLife allows all and publishes a sitemap index.
Headlightmag's file contains only the content-signal preamble with no directives
and no signal set, which by its own wording neither grants nor restricts. So:
identify the crawler honestly, one request at a time, back off on any 429, and
**never republish source text**. `evidence_text` is a short internal quote for
the review panel; the public site shows the number, the outlet name and a link
back — never their sentences.

### 7. Cadence, and what the SLA actually rests on

The draft's 10–15 minute polling assumes GitHub's scheduled workflows fire on
time. They are best-effort: runs are delayed under load and can be dropped, so
the schedule cannot by itself carry a hard deadline.

| Job | Every |
|---|---|
| Tier-B `modified_after` poll | 20 min |
| OEM newsroom / pricelist adapters | 1 hour |
| OEM promotion pages | 6 hours |
| Expiry + future-window resolver | 1 hour |
| Full reconciliation | daily |

The 24-hour target is met because a missed run costs 20 minutes and the next run
catches everything via `modified_after` — not because any single run is
punctual. What is measured and reported is the truth of it:
`published_at → first_seen_at → verified_at`, per source, so the owner can see
where the system is actually slow rather than trusting a target.

Politeness budget: roughly 72 polls per site per day, each a few KB.

---

## Publish policy

Canonical (public) requires all of:

- one Tier-A source (OEM pricelist, press release, official promotion page)
  stating trim, amount and type; **or** two *independent* Tier-B claims agreeing
  on all three;
- exactly one matching `MarketTrim`;
- no contradicting claim;
- for a campaign: a stated purchase price and at least a booking window.

Provisional (internal only): one Tier-B claim, clear trim and amount, no second
source yet.

Review queue: several possible trims; "ราคาเริ่มต้น" with no trim named; unclear
whether MSRP or campaign; headline and body disagree; two sources give different
numbers; campaign with no conditions; **a trim that does not exist yet**.

Never resolved automatically: the highest number, the lowest number, or the
newest article. A conflict is a question for the owner, not a tie-break.

---

## Storage

Canonical stays JSON in Git, as in Phase 1 and 2.

```
vehreg/data/2026/market/
├── prices/<brand>.json          offers, extended PriceRecord
├── campaigns/<brand>.json       campaign + options + conditions
└── pricefeed/
    ├── sources.json             tier, base URL, adapter, poll interval
    ├── claims/<YYYY-MM>.jsonl.gz
    ├── snapshots/<sha256>.html.gz
    └── review/{pending.jsonl.gz,decisions.json}
```

Snapshots are kept only for documents that produced a claim the system acted on.
Everything else keeps URL, hashes, timestamps and the extraction result. A
gzip blob cannot be delta-compressed by Git, so snapshotting every changed page
every 20 minutes would grow the repository without bound.

## Automation, with a brake

The harvester opens a data-only PR. CI enforces: schema valid, ledger validates,
`current_list_price` unchanged for every trim the PR does not touch, no file
outside `market/` modified, and **no more than a fixed number of offers changed
in one PR**. A run that wants to rewrite fifty prices has a broken extractor, not
fifty announcements; it stops and waits for a person.

Auto-merge only for Tier-A exact or independent Tier-B consensus. Anything else
stays open.

Decisions written by the harvester carry `reviewer: "agent-proposed"`, exactly as
Phase 2's ECO decisions now do.

## Boundaries

- Phase 3 does not touch registration analytics, `dim_unit`, `fact_registration`
  or `fact_trim`.
- `ECO_STICKER_PRICE` remains a declared tax figure and is never promoted to a
  retail price, in the ledger or on the public site.
- No price is invented, rounded, converted or interpolated. A number that no
  source stated does not exist.

## Order of work

1. Extend `PriceRecord` → `PriceOffer`, add `Campaign`/`Option`/`Conditions`,
   `current_campaign_offers(as_of)`. Offline, no network. Existing tests must
   pass unchanged.
2. Source registry, document store, claim extraction, snapshot discipline.
   Offline against fixtures.
3. WordPress adapter for the two Tier-B sources; run it read-only and measure
   real `published_at → first_seen_at` before anything publishes.
4. Matching, independence check, consensus, publish policy, review queue with
   bundled trim proposals.
5. Scheduled workflow and the data-only PR with its CI brake.
6. OEM Tier-A adapters, one brand at a time.

Steps 1 and 2 are useful on their own: they let prices be entered by hand, with
provenance, before any harvester exists.
