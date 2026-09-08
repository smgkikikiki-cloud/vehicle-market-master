# Vehicle Master 2.0 — Phase 1 delivery

Vehicle Master is the product foundation for market offerings, price history,
comparable specifications and future fitment demand. Registration analytics is
one consumer; it does not define the retail product identity.

## Delivered contract

| Requirement | Implementation | Acceptance |
|---|---|---|
| MarketTrim | Existing Brand → Model → Generation → MarketTrim hierarchy | Stable explicit IDs; same-name BEV/PHEV can coexist; optional analytical Variant link |
| Exact powertrain | Mandatory trim powertrain; identity guard in authoring | UNKNOWN and powertrain changes to an existing ID rejected |
| Dimensions | length/width/height/wheelbase in integer mm | Positive finite values; wheelbase shorter than length |
| Tyre | Separate front/rear tyre and wheel strings | Preserved in round trips; ECO mismatch blocks authoring |
| Basic specs | drivetrain, engine code/cc, battery kWh, transmission, seats | Typed validation; BEV cannot acquire a combustion engine |
| Source references | Source-system IDs and navigable OEM URLs | Nonempty provenance required for new authored trims |
| Price Ledger | Separate classified, dated observations | No embedded price in authored product rows or product query output |
| JAECOO 5 reference | 4 trims, 3 ECO records, 5 price observations | Cross-store validation and complete analytical-row equality tests |
| Operational access | `ProductMaster` API and `vehreg market` CLI | Read, filter, export JSON, validate, dry-run/upsert trims, append prices |

The base commit `385dba5` already contained the MarketTrim schema, JAECOO seed,
ECO spec store and an initial PriceLedger. This change completes their use as a
product subsystem: removes three duplicate trim prices, fixes price selection
and validation, adds guarded authoring and joined read APIs, and documents the
reference evidence. Existing analytical Variant prices remain historical
classification inputs; retail consumers must use PriceLedger.

## Run and inspect

```bash
python -m vehreg market validate
python -m vehreg market coverage --as-of 2026-09-08
python -m vehreg market list --model chery.jaecoo_j5 --powertrain BEV
python -m vehreg market show chery.jaecoo_j5.j5.trim.max_plus_bev --as-of 2026-09-08
python -m vehreg market list > vehicle-products.json
```

`--year` and `--data-dir` precede `market`. These commands never connect to or
create the registration database. `--as-of` selects **price validity**, not a
historical spec snapshot. The response includes the full ledger history for the
selected catalog year, including observations after the requested price date.
All specs remain the selected year's authored snapshot. Phase 5 will add spec
snapshot comparison; no historical spec accuracy is implied here.

```python
from datetime import date
from vehreg.product import ProductMaster

master = ProductMaster.load(year=2026)
rows = master.rows(model_id="chery.jaecoo_j5", as_of=date(2026, 9, 8))
assert master.validate() == []
```

## Author trims

Create a JSON payload with exactly `generation_id` and a nonempty `trims` array.
Each item is a **full replacement** of the named retail trim; omitted optional
fields become unknown. Unmentioned sibling trims remain unchanged. An explicit
local `id`, exact `powertrain`, name and nonempty `source_refs` are required.
Use a new ID for a different powertrain. Do not put `price_thb` in this payload.

```json
{
  "generation_id": "brand.model.generation",
  "trims": [{
    "id": "premium_bev",
    "name": "Premium",
    "powertrain": "BEV",
    "source_refs": {"official_oem": ["https://example.com/specifications"]}
  }]
}
```

The placeholder generation must first exist in the catalog. Use the real
source's values for optional spec fields; omission is preferable to invented
values. Phase 1 authoring attaches trims to existing generations; Model and
Generation creation continue through existing catalog tools.

```bash
python -m vehreg market import-trims trims.json
python -m vehreg market import-trims trims.json --write
```

Both paths run the same validation against catalog, ECO evidence and ledger.
The write is an atomic replacement of one brand file after validation. Full
resolved analytical rows are compared before/after; a difference blocks writing.
Unknown fields fail rather than being silently dropped. Product writers share
an exclusive per-year lock. Other editors must not write the same JSON files
concurrently. If a process dies while holding `.product-write.lock`, verify that
no product writer is running before removing that stale lock.

## Append prices

```json
{
  "prices": [{
    "trim_id": "brand.model.generation.trim.premium_bev",
    "amount_thb": 999000,
    "price_type": "LIST_PRICE",
    "effective_from": "2026-09-01",
    "observed_at": "2026-09-08",
    "source": "official_oem",
    "source_ref": "https://example.com/price-list",
    "notes": "Use a real source and its actual effective date."
  }]
}
```

```bash
python -m vehreg market append-prices prices.json
python -m vehreg market append-prices prices.json --write
```

New observations require source, reference and observation date. They append to
`vehreg/data/<year>/market/prices/observations.json`; existing rows are retained.
Exact duplicate records are skipped, including across files and repeated runs.
An invalid final row rejects the entire batch. Prices must be positive integer
baht; fractional amounts and booleans are rejected rather than truncated.

Only `LIST_PRICE` is eligible for canonical list price. If the source does not
publish an effective date, leave `effective_from` absent: the first known date
is `observed_at`, and queries before that date return no value. This does not
claim the price originally started on the observation date. An explicit
`effective_from` represents validity even if the evidence was collected later.

A newer list supersedes an older open-ended list. After the newer list expires,
the old list must not reappear. Conflicting amounts at the same start date stop
canonical selection for review; file order and the highest amount never decide
the answer. Campaign, finance, introductory, estimated and ECO prices remain
separate evidence. Automated harvesting/classification is Phase 3.

## JAECOO 5 evidence and actual coverage

Catalog year 2026 currently has **326 model rows**, but only **one researched
MarketTrim reference model**. This is not 326 fully populated retail catalogs.
The stable reference ID is `chery.jaecoo_j5`; the pre-existing
`jaecoo.jaecoo_5_ev` model is not remapped by this phase, because that would touch
registration identity. Phase 2 matching must present these competing identities
for review before attaching an ECO candidate.

| Retail trim | Battery kWh in existing seed | Tyres front/rear | ECO evidence | Price evidence at 2026-09-08 |
|---|---:|---|---|---|
| Long Range Dynamic | 58.9 | 235/55 R18 | Present | ECO 629,000; no canonical current list |
| Long Range Max | 58.9 | 235/55 R18 | Present | ECO 679,000; no canonical current list |
| MAX+ | 50.6 | 235/55 R18 | Present | OEM list 699,000 and separate ECO 699,000 |
| ULTRA | 60.93 | 235/55 R18 | Not found in prior probe | OEM **estimated** 809,000; no canonical current list |

All four seed trims have FWD, single-speed transmission, five seats and
4,380 × 1,860 × 1,650 mm exterior dimensions with a 2,620 mm wheelbase.

Evidence reviewed in this implementation:

- [OEM English homepage](https://www.omodajaecoo.co.th/en), observed 2026-09-08:
  explicitly displays MAX+ price 699,000 and ULTRA **estimated** price 809,000;
  provides the dimensions/wheelbase for those two grades. No effective date is
  stated, so both new ledger records preserve observation date only.
- [OEM MAX+ product page](https://www.omodajaecoo.co.th/th/model/jaecoo-5-ev)
  and [OEM ULTRA product page](https://www.omodajaecoo.co.th/en/model/en-jaecoo-5-ev-ultra),
  opened 2026-09-08: confirm the named products and provide navigable source refs.
- Existing ECO observations and UUIDs were inherited from `385dba5`, documented
  in [ECOSTICKER_PHASE1.md](ECOSTICKER_PHASE1.md). This implementation did not
  repeat the live ECO backend probe or promote a source weight to curb weight.
- Battery capacities and other seed specifications are carried forward from
  that base, **not claimed as newly reverified** by opening today's OEM pages.
  The currently extracted pages do not expose every numeric seed field. ULTRA
  still has no ECO record; this is an explicit evidence gap, not a fake UUID.

The four records are **known marketed grades**, not a claim that all four remain
orderable today. Sale-window/stock availability needs dated evidence. Wheel
strings currently identify 18-inch diameter only; rim width, PCD, offset,
load/speed rating and 12V battery fitment remain Phase 6, with no inferred values.

## Acceptance and rollback

```bash
python -m compileall -q vehreg pages tests
python -m pytest -q
python -m vehreg market validate
```

Tests exercise atomic failure, duplicate imports, ECO conflicts, identity
changes, malformed quantities/dates, expiry, price conflicts, and unchanged
analytical rows. Raw DLT files, facts, matching rules, ranking/cube code and
published historical catalogs are unchanged. No registration reload is needed.
Rollback is a normal Git revert of this feature; no database migration is involved.

Local acceptance on 2026-09-08: **361 tests and 4,390 subtests passed**; compile
and cross-store validation passed. All **371 resolved analytical rows** match
base commit `385dba5` exactly, including values (not just IDs). Their serialized
SHA-256 is `353d10454026e8ce769a1d9e62daa6545e3e26dca13708c127d57c79b26860e3`.

## Selected next-step options

| Option | Result | Assessment |
|---|---|---|
| **Keep JSON/Git as canonical; stage Phase 2 ECO intake separately** | Reproducible reviewable batches; accepted candidates alone populate product stores | **Recommended now**: reuse the working foundation; no new service cost |
| Add a dedicated SQLite product store before ECO intake | Indexed local queries and transactional multi-row review | Useful when the reviewer UI and ingestion need it; requires a defined JSON/database authority |
| Move product storage to a hosted relational service now | Multiuser editing and service APIs | Save for actual concurrent editors/productization; adds migration and operating work before bulk mapping is proven |

Recommended Phase 2: fetch/stage the requested ECO inventory, reconcile actual
source count rather than hard-code 1,640 as success, normalize, run a small
reviewed batch first, then promote the remaining unambiguous records. Keep raw
ECO records and ambiguous candidates outside canonical MarketTrim. Registration
analytics must remain isolated. No Phase 2–7 jobs or UI panels were built here.
