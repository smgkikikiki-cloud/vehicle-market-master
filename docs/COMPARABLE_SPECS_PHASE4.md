# Comparable Specs — Phase 4 C-Crossover pilot

Phase 4 adds an evidence-backed comparison layer without changing registration
grain, retail identity or price authority. The first bounded cohort is exactly
20 models classified as Segment C + BodyType CROSSOVER in the 2026 catalog.

## Delivered boundary

| Layer | Authority |
|---|---|
| `MarketTrim` | retail identity and Phase-1 basic specification |
| `PriceLedger` | current and historical retail price observations |
| Phase-2 ECO snapshot | immutable homologation/source evidence |
| `SpecLedger` | field-level, dated facts attached to an exact `MarketTrim.id` |
| `BattleCardEngine` | generated comparison output; never edited as master data |

The registry contains 48 typed fields and core, safety and comfort profiles.
Every numeric field has one canonical unit. Fields which need context also name
comparison qualifiers: rated range requires the same measurement basis, NCAP
requires the same programme/protocol/market/tested variant, and DC charging time
requires the same state-of-charge window and charger power.

An absent field is `UNKNOWN`; it is never rendered as `false` or as equipment
not fitted. A source omission therefore cannot manufacture a de-specification
event for Phase 5.

## Pilot cohort

The cohort is versioned at
`vehreg/data/2026/product/comparable_specs/cohorts/c_crossover.json`.

| Group | Models |
|---|---|
| Mainstream electrified | Aion V, BYD Atto 3, BYD Sealion 6, Deepal S05, Deepal S07, Geely EX5, Haval H6, Jaecoo 6T EV, Jaecoo 7, Leapmotor C10, MG S5 EV, Toyota bZ4X |
| Multi-powertrain / established | Honda CR-V, Mazda CX-30, MG HS, Nissan X-Trail, Subaru Forester, Toyota Corolla Cross |
| Higher-price reference | Hyundai Ioniq 5, Volvo EX40 |

The immutable 2026-09-08 ECO snapshot yields 80 candidate trim rows and 1,174
candidate comparable values across all 20 models. One representative source
row per model is selected explicitly; it is not inferred from price or file
order.

These rows remain `PROVISIONAL_UNRESOLVED_TRIM`. An ECO homologation record is
evidence that a configuration exists, not sufficient evidence that it is the
current showroom offering. Its recommended price is exposed only as
`ECO_STICKER_PRICE`, with `canonical_retail_price: false`.

## Commands

```bash
python -m vehreg market spec-coverage
python -m vehreg market spec-candidates --representatives-only

python -m vehreg market battle-card \
  --candidate 762c0806-4101-4155-9343-7c2dc815dd3b \
  --candidate ee5085a9-67ca-40f6-9944-550da794d94c \
  --candidate e9901aa9-5f90-406e-a56d-3d19da56b895

python -m vehreg market battle-card \
  --trim brand.model.generation.trim.grade_a \
  --trim brand.model.generation.trim.grade_b \
  --profile c_crossover_core --as-of 2026-09-08

python -m vehreg market spec-import facts.json
python -m vehreg market spec-import facts.json --write
```

Battle cards require two to six distinct subjects. Candidate cards are visibly
provisional. Published cards join current list and active campaign observations
from PriceLedger; prices are never copied into the spec store.

Facts are immutable by `fact_id`. A correction is another dated fact. Equal
start dates with different values in the same comparison context fail closed.
An expired newer fact does not resurrect an obsolete older fact.

## Fact payload

```json
{
  "schema_version": 1,
  "facts": [{
    "fact_id": "oem.example.max.power.2026",
    "trim_id": "brand.model.generation.trim.max",
    "field_key": "powertrain.max_power_kw",
    "value_state": "KNOWN",
    "value": 155,
    "unit": "kW",
    "qualifiers": {"output_scope": "MOTOR", "rating_basis": "PEAK"},
    "effective_from": "2026-01-01",
    "observed_at": "2026-09-08",
    "claim_ids": ["claim.official.example"],
    "verification_status": "VERIFIED",
    "source": "official_oem",
    "source_ref": "https://example.com/specification",
    "source_locator": "Powertrain table / MAX"
  }]
}
```

Price-shaped keys are rejected. List and campaign prices remain in PriceLedger.

## Promotion gate

The pilot stops before writing 20 new MarketTrims. Promotion requires a review
decision for the exact retail grade and current OEM evidence. Once a candidate
is mapped to a reviewed MarketTrim, its ECO dimensions, declared weight, tyre,
battery chemistry, range and consumption can be promoted as field-level facts
without changing registration analytics.

This preserves the Phase-2 rule that machine-proposed mappings are not owner
decisions. Preview mode provides useful comparison output while the canonical
store remains honest.

## Acceptance

Tests cover registry/profile integrity, the 20-model cohort, candidate coverage,
price isolation, cell-level provenance, qualifier incompatibility, unknown vs
explicit false, temporal expiry, conflict handling, idempotent writes, CLI
output and byte-for-byte unchanged registration rows.
