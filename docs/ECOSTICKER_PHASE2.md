# ECO ingestion — Phase 2

Phase 2 turns the public ECO Sticker inventory into a reproducible, review-first
input for Vehicle Master. It does not create registration facts, allocate DLT
volume, or silently mutate Model, Generation, Variant, MarketTrim, specs, tyres
or prices.

## Live inventory snapshot

The official public inventory was captured on **2026-09-08** from
`https://car.ecosticker.go.th/landing-page`.

| Check | Result |
|---|---:|
| Source rows | 1,640 |
| Unique source IDs | 1,640 |
| Pages | 55 |
| Last-page rows | 20 |
| Raw SHA-256 | `e2cda82b10829cf1dfa796f40332696bcfd6c05188bc3535f8d1e9bd941d12b9` |
| Registration analytical rows before/after | 371 / 371, identical |

The source uses two identifier renderings: 1,331 hyphenated UUIDs and 309
compact 32-character UUIDs. Both are retained as source identifiers. The raw,
normalized and review-queue JSONL artifacts are deterministically gzip-compressed
and committed with the manifest. The snapshot directory is immutable: rerunning
the exact input is idempotent; different input under the same date is rejected.

## Normalization and matching result

| Result | Records |
|---|---:|
| Unique Model match | 1,357 |
| Unique Generation match | 1,354 |
| Catalog models represented | 260 of 326 |
| Explicit powertrain in source label | 369 |
| Ready-for-review trim candidate | 342 |
| Needs powertrain review | 1,012 |
| Needs Model/Generation review | 286 |

Review reasons overlap. The snapshot contains 1,271 labels without an explicit
powertrain, 149 ambiguous model matches, 134 unmatched models, 46 unmatched
brands, 34 brand-alias collisions and three ambiguous generations.

The matcher is conservative by design:

- brand aliases can return multiple owners; `JAECOO` correctly exposes both the
  legacy `jaecoo` catalog branch and the Phase-1 `chery` product branch;
- Model matching is scoped to brand candidates, uses longest whole-token
  surfaces first and keeps cross-brand ties for review;
- a Generation is selected automatically only when the matched Model has one;
- powertrain is inferred only from explicit labels such as EV/BEV, HEV/hybrid,
  PHEV/plug-in/DM-i, REEV/EREV or fuel-cell wording;
- a plain petrol/diesel-looking grade is **not** silently labelled ICE;
- the source price is retained only as `ECO_STICKER_PRICE` candidate evidence.

Every normalized row contains the raw source fields, normalized comparison keys,
all brand/model candidates, score/method, proposed Generation, proposed
powertrain, deterministic trim candidate ID, review status/reasons and provenance.

## Human review and canonical population

Decisions support three explicit actions: `accept_existing_trim`, `reject` and
`defer`. Acceptance requires a real `MarketTrim.id`, named reviewer, review date,
matching exact powertrain and source UUID. Invalid or duplicate decisions reject
the whole file.

The three previously researched JAECOO 5 records are the reference implementation:

| ECO record | Accepted MarketTrim | Spec | Tyre |
|---|---|---|---|
| Long Range Dynamic | `chery.jaecoo_j5.j5.trim.long_range_dynamic_bev` | linked | 235/55R18 |
| Long Range Max | `chery.jaecoo_j5.j5.trim.long_range_max_bev` | linked | 235/55R18 |
| MAX+ | `chery.jaecoo_j5.j5.trim.max_plus_bev` | linked | 235/55R18 |

Those decisions join to the source-backed detail records and MarketTrim source
references already accepted in Phase 1. They demonstrate the complete reviewed
path without duplicating or relabelling evidence.

The current public detail route returned **“ไม่พบข้อมูลรถยนต์”** for both newly
listed UUIDs and the known JAECOO UUID during this capture. Therefore Phase 2
does not invent specs or tyres for the other 1,637 rows. Their list records,
matches and trim candidates are present; canonical promotion remains blocked
until authoritative detail payloads are available and reviewed.

## Commands

```bash
python -m vehreg market eco-build inventory.jsonl \
  --snapshot-date 2026-09-08 --expected-records 1640
python -m vehreg market eco-build inventory.jsonl \
  --snapshot-date 2026-09-08 --expected-records 1640 --write
python -m vehreg market eco-review decisions.json \
  --snapshot-date 2026-09-08 --write
python -m vehreg market eco-status --snapshot-date 2026-09-08
```

Dry-run is the default for snapshot building and review writes. None of these
commands connects to the registration database.

## Recommended continuation choices

1. **Obtain/recover the official ECO detail feed, then backfill the staged UUIDs
   (recommended).** This preserves one authoritative source for homologation,
   specs and tyres and lets the existing review queue resume deterministically.
2. Re-crawl public detail pages after the official site fixes the route. This is
   operationally simple but dependent on the public UI remaining available.
3. Fill missing product specs from official OEM sources. This can improve retail
   coverage, but it is a separate source stream and should retain OEM provenance
   rather than being labelled as ECO-derived.

Do not auto-promote the 342 ready candidates merely because their label includes
a powertrain. A source label is enough to propose an identity, not enough to
assert dimensions, tyre fitment or current sale status.
