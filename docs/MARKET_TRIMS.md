# Market trims

Vehicle Master now distinguishes two different grains that used to be forced into one `Variant` object.

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
      "price_thb": 2461000,
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

The first trim schema deliberately focuses on fields useful to the two planned products:

1. market offering: trim name, exact powertrain, price and basic specification;
2. stock prediction / fitment: dimensions, wheelbase, tyre and wheel sizes.

`source_refs` stores only source-system identifiers/provenance. Raw ECO Sticker payloads, consumption, CO2, tax fields and long equipment lists do not belong in this canonical trim object unless a later product explicitly needs them.

## Analytics isolation

`Catalog.iter_resolved()` still iterates only `Variant` objects. `Resolver`, facts and the cube are unchanged. Adding ten trims to a model therefore creates zero additional registration rows and cannot redistribute volume.
