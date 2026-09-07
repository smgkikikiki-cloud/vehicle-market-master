# Handover: where the warehouse stands and what the rules are

Written so the next person or agent can pick this up without reading the whole
history. Everything below is on `main` and reproducible from the repo.

## State

```
registrations   4,064,148 units across 35,212 fact rows, 68 months (2021-01 … 2026-08)
open review        20,045 units (0.49%)
trim ledger        reconciles at 0 against the master
tests                 284
```

Where the powertrain reading comes from:

| source | units | |
|---|---:|---|
| the file said so (variant grain) | 72,538 | evidence |
| the catalog admits MIXED | 753,829 | honest |
| asserted from the variant list | 3,214,767 | 94 nameplates still unverified |
| brand only, no model | 23,014 | in the review queue |

71 nameplates have been checked against what is actually sold and carry
`powertrain_checked`. Run `python tools/powertrain_worklist.py` for the rest.

## Rules the owner set — do not undo these without asking

**Powertrain vocabulary.** There is no MHEV. A mild hybrid is a petrol car:
`Powertrain.parse` folds `MHEV`, `MILD_HYBRID`, `EQ_BOOST` and `48V` to ICE, so
the category cannot re-enter through a catalog edit or a new export. REEV means
a car charged from a socket — a Deepal S05 REEV, a Jaecoo 6T REEV — and **not**
Nissan e-Power, whose battery is only ever charged by its own engine; e-Power is
HEV, which is also how Thai excise treats it.

**Reader-facing powertrain buckets.** `market_powertrain` is
FUEL / HYBRID / PLUGIN / REEV / ELECTRIC. HEV includes Nissan e-Power;
REEV stays separate and is used when the manufacturer markets the vehicle as
REEV/EREV. Do not infer REEV from the generic phrase "range extender". The
seven-code `powertrain` stays for analysis.

**One nameplate per model, except the electric twin.** A 3 Series holds its
petrol, diesel and plug-in trims together. An i5 is not a 5 Series with a
different engine, so every i car is its own model — i3, i4, i5, i7, iX, iX1,
iX2, iX3. The same call was made for the Audi e-trons, the BYD Seal 5 DM-i, the
Jaecoo 6T REEV and the MG ZS EV. Two tests enforce it.

**A model alias must never carry a powertrain word the model's own name lacks.**
`TANK 300 HYBRID` as an alias made `residual_trim` treat HYBRID as part of the
nameplate, so the trim ledger recorded an empty trim for all 1,374 of them and
could not tell a hybrid Tank from a diesel one. A nameplate that *is* its
powertrain — Kia EV6, MG ZS EV, MG4 Electric — is fine. Tested across every year
catalog.

**A trailing number is the nameplate, not noise.** `GEELY EX2` fuzzy-matched
`Geely EX5` at 0.90 and 8,731 registrations were filed as the wrong car. Fuzzy
candidates whose trailing bare number disagrees are now refused.

**Never invent a spec.** `Model.incomplete` says a whole nameplate is
unresearched; `Variant.incomplete` says one trim is. Both are reported by
`Catalog.incomplete_models()` rather than by `validate()`, so a declared hole
stays countable instead of disappearing into a clean bill of health.

## Owner-reviewed fact-level powertrain rules

`vehreg/powertrain_rules.py` is the versioned exception layer for decisions that
annual variant consensus cannot represent honestly: month cut-offs (Camry XV80,
CR-V, Accord, HR-V, Corolla Cross, CLA), trim-rich model labels that DLT leaves
at MODEL grain (Deepal S05, Denza D9, Haval H6), and owner-reviewed bare-label
defaults. Rules never split or redistribute units; they only classify the fact
that DLT actually reported. First matching rule wins, source-explicit labels are
listed before bare-nameplate defaults, and MIXED remains a valid deliberate
answer.

A model covered by this rulebook is also considered owner-reviewed by the
powertrain worklist. `powertrain_checked` in the annual catalog still works and
remains the right flag for ordinary catalog-only reviews.

## How to change data safely

Matching happens when a file is read, so a catalog edit or a taught alias
changes nothing until the source is re-read:

```python
from vehreg.db import connect, rebuild_dimension
from vehreg import review
conn = connect("data/vehreg.sqlite3")
for catalog in review.load_catalogs().values():
    rebuild_dimension(conn, catalog)
review.reload_source(conn, source_id)      # clears the source first, then re-ingests
```

`reload_source` deletes everything the source wrote — `fact_registration`,
`fact_trim` and `ingest_review` — before re-reading. Do not skip that: both fact
tables key on the resolved id, so a row that moves from the brand to a model
joins its predecessor instead of replacing it and the month reads double. That
happened once, to 2026-07's trim ledger.

After any data change, check all three:

```
python -m pytest -q
python -c "from vehreg.db import connect; from vehreg import trimledger; \
           print(len(trimledger.reconcile(connect('data/vehreg.sqlite3'))))"   # must be 0
```

and confirm the total moved only by what you meant to move.

## Open work

**94 nameplates still assert a powertrain nobody verified** (533,930 units).
`python tools/powertrain_worklist.py` ranks them; CONFLICT first, where DLT's own
labels contradict the catalog. Top of the unverified list: Honda CR-V 37,834,
Mitsubishi Attrage 22,416, Mirage 18,869, Nissan Kicks e-Power 18,010.
Confirming one is a market fact, not something any file can settle — ask the
owner, then set `powertrain_checked` and say so in the commit.

**Audi Q7 and A6 disagree with the owner.** The owner said Q7 = ICE and
A6 = PHEV. The file carries 58 units of `Q7 60 TFSI e` (Audi's trailing e is the
plug-in) and 99 units of A6 `40/45 TFSI` (petrol). Both nameplates hold both
sides and read MIXED, and neither is marked checked. Settle it with the owner.

**~1,200 labels still need a catalog entry**, worth about 6,700 units. The
review queue page groups them by brand with the existing models beside them;
most are one alias on a model that already exists rather than a new nameplate.

**2026-08 is a pivot-workbook month** with no รย. class, so its pickups cannot
be split by cab and about 11,400 units read MIXED. It is fixed by loading the
DLT long sheet for that month through the upload page, not by editing anything.

## Pages

`app.py` dashboard · `pages/2` Chinese EV trims · `pages/3` analyst deck ·
`pages/4` regional · `pages/5` upload a month from a DLT workbook, with a dry
run before anything is written · `pages/6` the review queue, which says what
each stuck label actually needs.
