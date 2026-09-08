# Fixing a price by hand

The ledger is append-only on purpose: a number that was published has to stay
auditable. Before this there was no supported way to correct one — appending a
second price on the same day was refused with *"conflicting LIST_PRICE; review
required"*, and the only recourse was editing `observations.json` by hand.

Three operations close that gap, and none of them deletes a row.

| What happened | Operation | What it does to the old row |
|---|---|---|
| The price changed | **supersede** | gets `effective_to` = the day before the new one starts, and stays true of the period it covered |
| The row was wrong | **retract** | marked `retracted_at` with its reason; stops counting immediately, still readable |
| The price ended, nothing replaces it | **close** | gets `effective_to`, no new row |

Retracting and superseding are different claims about history, so they are
different commands. A retracted row was never true; a superseded one was.

Every one of the three demands a **reason** and a **reviewer**, both stored on
the row. Dry run is the default.

## From the page

`pages/7_Prices.py` — the **ราคา** page.

- **ราคาปัจจุบัน** — every trim that has price evidence, its current list price,
  and how many campaign options are live today. Pick one for the campaign detail
  and the full history including retracted rows.
- **แก้ราคา** — pick a trim, see the live row, choose one of the three actions.
  The button stays disabled until the reviewer name and the reason are filled
  in, so you are told what is missing before you click rather than after.
- **แคมเปญ** — every campaign with its options and conditions; paste a campaign
  as JSON to add or replace one.
- **คิวรอตรวจ** — the harvester's output: what published, what is provisional
  (one outlet, internal only), what is waiting, and the prices whose car has no
  trim yet.

Campaign options are shown side by side and never ranked. A cash discount and a
0% finance deal are not comparable, and choosing for the reader would be a lie.

## From the command line

```bash
# the price changed on 1 October
python -m vehreg market correct-price toyota.alphard.ah40.trim.hev_premium 4390000 \
  --mode supersede --effective-from 2026-10-01 \
  --reason "MY2027 pricelist" --reviewer "owner" \
  --source official_oem --source-ref https://... --write

# the figure was wrong and never applied
python -m vehreg market correct-price toyota.alphard.ah40.trim.hev_premium 4190000 \
  --mode retract --reason "the outlet corrected it the next day" \
  --reviewer "owner" --write

# the grade is gone; no replacement price
python -m vehreg market close-price toyota.alphard.ah40.trim.hev_premium \
  --ends 2026-09-30 --reason "grade withdrawn" --reviewer "owner" --write

# add or replace a campaign
python -m vehreg market campaign campaign.json --write

# read it back
python -m vehreg market quote toyota.alphard.ah40.trim.hev_premium
```

Add `--price-type CAMPAIGN_PRICE --campaign-id … --option-id …` to work on one
option of a campaign rather than the list price.

## What it refuses, and why

- **No reason, or no reviewer.** A price nobody signed is a price nobody can
  question later.
- **Superseding on the day the price started.** That would give the old row a
  negative life. The error says to use `--mode retract` instead — the row was
  simply wrong.
- **Closing before the price started.**
- **Two live rows for the same price.** It names the amounts and stops rather
  than picking one.
- **Nothing live to change.** A correction never silently becomes an insert; use
  `market append-prices` for a genuinely new price.

## Clearing the review queue from the page

The **คิวรอตรวจ** tab acts on what the harvester found. Every button writes the
owner's name into `pricefeed/review/decisions.json`; a decision the harvester
wrote carries `reviewer: "agent-proposed"` and by design moves nothing.

| The queue says | You do |
|---|---|
| one outlet reported this (`provisional`) | **ยืนยันและเผยแพร่** — you vouch for the single source, and it publishes |
| a campaign price with no campaign | pick the campaign and the option; it becomes provisional, then you vouch |
| the car has no trim yet | open the proposal, confirm model/generation/powertrain, **สร้าง trim แล้วรับราคา** — the trim and the price are one decision |
| wrong, or not a price at all | **ปฏิเสธ** |

**Publish only promotes a provisional price.** The review reasons — no trim, an
implausible amount, a campaign with no conditions, two sources disagreeing —
are structural, and each is answered by fixing the thing rather than overriding
it. Once fixed, the item becomes provisional and can then be vouched for.

Answers **merge**. Reviewing is not one question: you bind a campaign price to
its campaign, and later vouch for the source that reported it, and the second
answer must not erase the first. Rejecting is the exception — it withdraws the
whole answer.

A trim created this way cites the articles that reported it, in
`source_refs.press`. It is a real trim in the catalog from that moment, so the
model/generation/powertrain you confirm are the ones the warehouse will use.
