# ECO ingestion — Phase 2

Phase 2 turns the public ECO Sticker inventory into a reproducible, review-first
input for Vehicle Master. It does not create registration facts, allocate DLT
volume, or silently mutate Model, Generation, Variant, MarketTrim, specs, tyres
or prices.

## How the snapshot is produced

`tools/ecosticker_fetch.py` is the harvester. Two public read-only endpoints:

| Call | Purpose |
|---|---|
| `GET https://api-car.ecosticker.go.th/api/v2/landing-page/cars?page=N` | the paged inventory list, 12 rows per page |
| `POST https://api-car.ecosticker.go.th/api/v2/landing-page/compare` body `{"id": [...]}` | the detail record: dimensions, `wheel_size`, declared `engine_name`, battery, factory, weight |

The compare endpoint refuses fewer than two and more than four IDs per call, so
details go out in batches of four and a lone leftover ID is padded from the
previous batch. `--cache-dir` makes an interrupted run resumable; identical
input produces byte-identical output.

```bash
python tools/ecosticker_fetch.py --out raw.jsonl.gz --cache-dir .eco-cache
```

The first Phase 2 capture reached only the list pages: it called
`v1/eco-sticker/by-car-req`, which is the sticker-image route and answers
"ไม่พบข้อมูลรถยนต์" for a landing-page UUID. The route that carries the
specification is `v2/landing-page/compare`. That capture is superseded and was
replaced in place; its bytes remain in Git history.

## Live inventory snapshot

Captured **2026-09-08** from `https://car.ecosticker.go.th/landing-page`.

| Check | Result |
|---|---:|
| Source rows | 1,640 |
| Unique source IDs | 1,640 |
| Pages | 137 |
| Detail pages harvested | 1,640 / 1,640 |
| Registration analytical rows before/after | 367 / 367, identical |

The source uses two identifier renderings, hyphenated UUIDs and compact
32-character UUIDs. Both are retained as source identifiers. The raw, normalized
and review-queue JSONL artifacts are deterministically gzip-compressed and
committed with the manifest. The snapshot directory is immutable: rerunning the
exact input is idempotent; different input under the same date is rejected.

## Normalization and matching result

| Result | Records |
|---|---:|
| Unique Model match | 1,369 |
| Unique Generation match | 1,366 |
| Catalog models represented | 263 of 322 |
| Ready-for-review trim candidate | 1,335 |
| Needs powertrain review | 31 |
| Needs Model/Generation review | 274 |

Review reasons overlap: 136 ambiguous model matches, 135 unmatched models, 46
unmatched brands, 32 labels with no assertable powertrain and three ambiguous
generations.

### Where a powertrain answer comes from

| Basis | Records |
|---|---:|
| `detail_engine_name` — the record's own declared engine type | 1,286 |
| `detail_cartype` — the coarse ECO class, when engine type is blank | 320 |
| `explicit_label` — decisive wording in the model name | 2 |
| `not_explicit` — no answer; goes to review | 32 |

The declared engine type outranks the model name, because the name is wrong in
both directions. Every Bentley in this capture is named `... HYBRID` and every
one of them is declared `ปลั๊กอินไฮบริด` — a plug-in, not an HEV. An Audi Q3 in
the same capture is declared `ไมล์ดไฮบริด (MHEV)` and is not electrified at all.

So bare `HYBRID` in a model name asserts nothing and sends the row to review.
Mild hybrids fold into `ICE`: the owner's taxonomy has no MHEV bucket, and a
48V belt starter is not an electrified powertrain. `REEV` is reserved for
declared plug-ins whose name says REEV/EREV; Nissan e-Power is `HEV`.

The coarse `cartype_name` is trusted only for `BEV`, `PHEV` and `FCEV`. Its
`ICE` bucket also holds full hybrids — a Vellfire Hybrid is filed there — so it
is never read as a combustion verdict.

## Human review and canonical population

Decisions support three explicit actions: `accept_existing_trim`, `reject` and
`defer`. Acceptance requires a real `MarketTrim.id`, named reviewer, review date,
matching exact powertrain and source UUID. Invalid or duplicate decisions reject
the whole file.

**A decision this code wrote is not a decision the owner made.** Machine-written
rows carry `reviewer: "agent-proposed"`, are stamped `origin: "agent"`, and are
counted by `eco-status` as `agent_proposed_existing_trims` — never as
`accepted_existing_trims`. A person replaces the reviewer with their own name
when they have actually looked at the record.

The three JAECOO 5 reference records are currently in that state:

| ECO record | Proposed MarketTrim | Spec | Tyre |
|---|---|---|---|
| Long Range Dynamic | `jaecoo.jaecoo_5_ev.j5.trim.long_range_dynamic_bev` | linked | 235/55R18 |
| Long Range Max | `jaecoo.jaecoo_5_ev.j5.trim.long_range_max_bev` | linked | 235/55R18 |
| MAX+ | `jaecoo.jaecoo_5_ev.j5.trim.max_plus_bev` | linked | 235/55R18 |

1,384 records now carry a harvested `wheel_size` and all 1,640 carry dimensions,
but only those three are attached to a MarketTrim. Attaching the rest is review
work, not an ingestion step.

## Commands

```bash
python tools/ecosticker_fetch.py --out inventory.jsonl.gz --cache-dir .eco-cache
python -m vehreg market eco-build inventory.jsonl.gz \
  --snapshot-date 2026-09-08 --expected-records 1640
python -m vehreg market eco-build inventory.jsonl.gz \
  --snapshot-date 2026-09-08 --expected-records 1640 --write
python -m vehreg market eco-review decisions.json \
  --snapshot-date 2026-09-08 --write
python -m vehreg market eco-status --snapshot-date 2026-09-08
```

Dry-run is the default for snapshot building and review writes. None of these
commands connects to the registration database.

## What is still open

- 274 records need a Model or Generation decision; 46 brands are unmatched.
- 32 records have no assertable powertrain, mostly `อื่นๆ` with an ICE class.
- 1,637 harvested detail records are staged but attached to no MarketTrim.
- ECO prices stay `ECO_STICKER_PRICE`. That is a declared figure, not retail
  MSRP, and `PriceLedger.current_list_price` will never return one.

Do not auto-promote a ready candidate merely because a powertrain is known. The
declared engine type is enough to propose an identity; it is not enough to
assert that the trim is on sale under that name.
