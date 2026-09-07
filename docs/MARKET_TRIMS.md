# Market trims

Vehicle Master distinguishes two different grains that used to be forced into one `Variant` object.

- **Variant** = analytical spec line used by registration classification and the cube. It may fold several retail grades together because DLT often does not publish trim-level volume.
- **MarketTrim** = one actual marketed grade/SKU. It is catalog enrichment only and never receives, splits, or allocates registration volume by itself.

The hierarchy is therefore conceptually:

```text
Brand
└─ Model
   └─ Generation
      ├─ Variant(s)       # analytical registration grain
      └─ MarketTrim(s)    # retail offering / fitment grain
```

A trim can optionally link to an analytical variant with `variant` (local name/id) or `variant_id` (full id). The stable trim id is namespaced so no existing Vehicle Master ids change:

```text
toyota.alphard.ah40.trim.z_premier
```

Powertrain is part of retail identity: two grades both called `Premium` but sold as BEV and PHEV are two different MarketTrim rows. Price, tyre size, battery capacity and other changeable specifications do **not** belong in the trim id.

Example JSON inside a generation:

```json
{
  "code": "AH40",
  "segment": "E",
  "variants": [
    {
      "name": "HEV 2WD",
      "powertrain": "HEV",
      "drivetrain": "FWD"
    }
  ],
  "trims": [
    {
      "name": "Z Premier",
      "variant": "HEV 2WD",
      "powertrain": "HEV",
      "engine_code": "A25A-FXS",
      "engine_cc": 2487,
      "transmission": "e-CVT",
      "seats": 7,
      "length_mm": 4995,
      "width_mm": 1850,
      "height_mm": 1935,
      "wheelbase_mm": 3000,
      "tire_front": "225/60 R18",
      "tire_rear": "225/60 R18",
      "source_refs": {
        "ecosticker": ["a07258c9-0cc4-4233-bbd5-917ede9d676e"]
      }
    }
  ]
}
```

## Scope

The phase-1 trim schema deliberately focuses on fields useful to the two planned products:

1. market offering: trim name, exact powertrain and basic specification;
2. stock prediction / fitment: dimensions, wheelbase, tyre and wheel sizes;
3. provenance: source-system references used to justify the product row.

`source_refs` stores only source-system identifiers/provenance. Raw ECO Sticker payloads, consumption, CO2, tax fields and long equipment lists do not belong in this canonical trim object unless a later product explicitly needs them.

## Price is market state, not vehicle identity

Current retail price is maintained separately in `vehreg/data/<year>/market/prices/*.json` and loaded with `vehreg.pricing.PriceLedger`.

The ledger records the quoted amount, the meaning of that amount (`LIST_PRICE`, `CAMPAIGN_PRICE`, `ECO_STICKER_PRICE`, etc.), effective dates and source evidence. Consumers that want the current canonical MSRP call `PriceLedger.current_list_price()` or `current_list_amount()`; an ECO Sticker recommended price can exist in the ledger without ever becoming current MSRP.

`price_thb` on MarketTrim is retained only as a legacy/backward-compatible field for older authored files. New product data and downstream tools must treat PriceLedger as canonical and must not update trim identity when a price changes.

## Analytics isolation

`Catalog.iter_resolved()` still iterates only `Variant` objects. `Resolver`, facts and the cube are unchanged. Adding ten trims or one hundred price observations therefore creates zero additional registration rows and cannot redistribute volume.
