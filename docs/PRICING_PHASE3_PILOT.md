# Phase 3 pilot — steps 1 to 6 on ten models

What was built, what it produced against the live sources on 2026-09-08, and
what the run showed that the design got wrong.

The design is `docs/PRICING_PHASE3.md`. This is the record of running it.

## The ten models

Trims were needed before any price could land on anything. They were generated
from the Phase 2 ECO Sticker snapshot rather than typed by hand, so every one
carries the manufacturer's homologation UUID and nothing was invented:

| Model | Trims | Model | Trims |
|---|---:|---|---:|
| `toyota.alphard` | 52 | `ford.ranger_double_cab` | 19 |
| `toyota.vellfire` | 23 | `toyota.hilux_revo_double_cab` | 19 |
| `mazda.mazda2` | 24 | `isuzu.dmax_cab` | 18 |
| `mitsubishi.triton_double_cab` | 21 | `nissan.kicks` | 16 |
| `nissan.almera` | 14 | `suzuki.fronx` | 1 |

207 trims, all with `source_refs.ecosticker`, dimensions and wheel size copied
from the ECO record. `tools/eco_trim_proposals.py` produces the payload;
`market import-trims` applies it after validation.

## What the pipeline produced

One harvest over both Tier-B sources, everything modified since 2026-06-01:

```
posts listed            563
skipped, no known brand 112
skipped, foreign market  75
skipped, no price line  191
documents kept           62
claims extracted        157
```

Then matching, independence, consensus:

```
canonical  4     two independent outlets, matched trim, no conflict
provisional 4    one outlet only; internal review panel, never public
review     96    93 of them because the trim does not exist yet
```

The four canonical offers, written to the ledger by `market price-run --write`:

| Trim | Price |
|---|---:|
| `toyota.alphard.ah40.trim.hev_smart` | 3,590,000 |
| `toyota.alphard.ah40.trim.hev_premium` | 4,290,000 |
| `toyota.vellfire.gen1.trim.hev_premium` | 4,290,000 |
| `toyota.alphard.ah40.trim.hev_premium_luxury` | 4,590,000 |

Registration analytics before and after: 4,064,148 units / 35,212 rows /
68 months / trim ledger reconciles at 0. Identical.

## Five things the run found that the design did not

**1. A struck-through price is still a price to a regex.** Both outlets write a
discount as `<del>689,000 บาท</del> 599,000 บาท`. Stripping tags leaves 689,000
first on the line, and the harvester would have published the price the car is
no longer sold at — on every discounted car. The extractor now rewrites a
struck-through figure into the "was" position before reading the line.

**2. One article prices two nameplates.** A single Alphard/Vellfire price table
lists both. Taking the model from the headline filed a Vellfire price on an
Alphard trim. The grade line is now matched before the headline, and the two
nameplates separate correctly.

**3. Comparing claim text collapsed independent reports into one.** The design
said two Tier-B claims whose evidence text is near-identical should count once.
But a price table row reads the same however independently it was typed —
"Alphard HEV Premium 4,290,000 บาท" — so *every* honest agreement was being
thrown away and nothing could ever reach canonical. Independence is now a
property of the **article**, compared with a min-hash sketch of the whole body.
The four canonical offers exist only because of this fix.

**4. The republication premise was not supported by the data.** With
document-level comparison, **zero** cross-outlet pairs in 62 documents scored
above 0.15 overlap. These two outlets cover the same press releases and write
their own copy. The check is cheap insurance and it correctly stayed out of the
way, but its threshold has not yet been tested against a real reprint — only
against a synthetic one in the tests. Treat 0.55 as unvalidated.

**5. Two outlets, two table layouts.** One writes `Grade : price บาท`, the other
`Grade  price บาท` with no colon at all. The colon-only rule silently produced
zero grades for the second outlet, which is why its claims first appeared to
have no trim.

## What the SLA measurement actually says

Nothing yet. The harvest deliberately backfilled three months, so the
`published_at → first_seen_at` median of 571 hours measures how far back the
window reached, not how fast the system is. A real number needs the schedule
running forward. What exists is the instrument: every document records
`published_at`, `first_seen_at` and `fetched_at`, and `measure_latency` reports
median, max and the count within 24 hours on every run.

## Step 6: Tier-A adapters are blocked by permission, not by code

`tools/robots_check.py` asks each source whether it may be polled, and the
harvester now skips any source that says no.

- Headlightmag: no directives, no content signal — allowed, polled gently.
- AutoLife Thailand: `Disallow:` empty, sitemap published — allowed.
- **suzuki.co.th: `Disallow: /` for ClaudeBot, GPTBot, CCBot, Google-Extended
  and five more, plus `Content-Signal: ai-train=no, use=reference`.** That is a
  refusal of the fetch itself. No Suzuki adapter will be written.
- toyota.co.th: no robots.txt at all.

So Tier A stays the manual path — the owner or a dealer pricelist entered
through `market append-prices`, which already carries the JAECOO MAX+ official
price. Automated OEM adapters are per-brand and gated on each brand's own
robots file, not on a single decision.

## Commands

```bash
python tools/robots_check.py
python tools/pricefeed_harvest.py --since 2026-09-08T00:00:00 --out batch.json
python -m vehreg market price-run batch.json --decisions .../decisions.json
python -m vehreg market price-run batch.json --decisions .../decisions.json --write
python -m vehreg market quote toyota.alphard.ah40.trim.hev_premium
python tools/pricefeed_guard.py --base origin/main
python tools/eco_trim_proposals.py --model nissan.kicks --out trims.json
```

`.github/workflows/pricefeed.yml` runs the first four every 20 minutes and opens
a data-only PR. `pricefeed_guard.py` refuses that PR if it touches anything
outside `market/`, moves more than 25 list prices at once, moves any single list
price by more than 25%, or removes a price a trim already had.

## Still open

- **The campaign path is proven but unpublished.** The real Suzuki Fronx
  September campaign is authored with its four genuine options (SUZUKI FAMILY
  cash / 0% finance, open-customer cash / 0% finance). Its 599,000 claim is
  attached to `family_cash` by an `agent-proposed` decision, which by design
  does **not** move a price: with that decision marked agent it stays in review;
  marked human it becomes provisional. The owner has to sign it.
- The campaign has no end date because the source states none. It was left open
  rather than guessed.
- 93 review items are prices for cars with no trim yet, each carrying a bundled
  trim proposal. Land Cruiser FJ, IONIQ 5 N Line, BYD Sealion 7, Xpeng L03 and
  Mazda 6e are the volume there.
- `official_oem` is registered Tier A but has no adapter; it is manual entry.
- 112 posts named no brand the catalog knows. Some are genuinely off-topic;
  some are brands missing from the catalog.
