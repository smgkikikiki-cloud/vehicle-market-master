# ECO Sticker Phase-1 enrichment

The first live enrichment target is **JAECOO 5 EV**. Vehicle Master uses the public backend calls made by the ECO Sticker website as source evidence; these endpoints are not treated as a documented third-party developer API.

## What Phase 1 keeps

For an ECO-backed retail trim, the normalized source-evidence store can retain:

- exact powertrain reported by the source;
- seats;
- tyre size;
- chassis/carriage code;
- battery chemistry, supplier and declared voltage;
- the source's `total_weight` value, conservatively named `declared_total_weight_kg` rather than guessing that it means curb weight;
- factory text;
- rated EV range;
- approval timestamp and ECO Sticker UUID for provenance.

The records live under `vehreg/data/<year>/product/specs/ecosticker/` and are keyed by stable `MarketTrim.id`. `ECOStickerSpecStore.validate_against_catalog()` checks ECO powertrain, seats, tyre size and source UUID against the canonical MarketTrim without rewriting it.

## Price is deliberately excluded

No price field is permitted in this store. The loader fails closed if a key containing `price` appears. ECO Sticker recommended prices, when retained as evidence, belong only in the separate `PriceLedger` as `ECO_STICKER_PRICE`; they never become canonical MSRP through spec enrichment.

## JAECOO 5 result from the live public-site backend

Three records were discoverable and their detail calls returned successfully:

- Long Range Dynamic — ECO UUID `d744d9f3-d393-4ac3-b441-17a022098fed`
- Long Range Max — ECO UUID `b4529bb4-d813-416b-b272-430b123cc06c`
- MAX+ — ECO UUID `98c1d7de-79db-4581-b332-69abe657a532`

No JAECOO 5 **ULTRA** ECO Sticker record was found in the live search used for this first enrichment, so Vehicle Master does not invent ECO-only facts for ULTRA.

A source caveat discovered during the probe: the public list search is not reliable as ordinary full-text search. Searching `JAECOO 5` / `JAECOO 5 EV` could return no rows while the broader `5 EV` search exposed the three records above. A later bulk importer must therefore not depend on one exact model-name search string.

The JAECOO detail payload did **not** provide exterior dimensions or battery capacity in kWh. Those existing MarketTrim fields remain backed by the separate official OMODA/JAECOO evidence already attached to the vehicle and are not relabelled as ECO-derived.

Long factory-equipment lists and energy-consumption fields are intentionally not promoted in Phase 1; comparable equipment/spec battle cards remain a later product layer.
