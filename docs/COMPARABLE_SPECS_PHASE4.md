# Comparable Specs — Phase 4 C-Crossover pilot

Phase 4 adds an evidence-backed comparison layer without changing registration
grain, retail identity or price authority. The first cohort is the C-segment
crossovers: **every** 2026-catalog model whose body type is CROSSOVER and which
has a Segment C generation, and which has at least one ECO Sticker detail record
with a declared powertrain. That is 31 models. It is a rule, not a list —
`tests/test_comparable_specs_phase4.py` recomputes it from the catalog and the
snapshot and fails if the file drifts from it.

Three eligible models have no ECO detail evidence yet and are therefore out:
`geely.galaxy_e5`, `kia.ev6`, `mg.mg_es`.

## Delivered boundary

| Layer | Authority |
|---|---|
| `MarketTrim` | retail identity and Phase-1 basic specification |
| `PriceLedger` | current and historical retail price observations |
| Phase-2 ECO snapshot | immutable homologation/source evidence |
| `SpecLedger` | field-level, dated facts attached to an exact `MarketTrim.id` |
| `BattleCardEngine` | generated comparison output; never edited as master data |

The registry contains 50 typed fields and core, safety and comfort profiles.
Every numeric field has one canonical unit. Fields which need context also name
comparison qualifiers: rated range requires the same measurement basis, NCAP
requires the same programme/protocol/market/tested variant, and DC charging time
requires the same state-of-charge window and charger power.

Four silences, and they do not mean the same thing:

| State | Means |
|---|---|
| `KNOWN` with `false` | the source says the equipment is not fitted |
| `UNKNOWN` | nobody has looked |
| `NOT_AVAILABLE` | the source looked and did not say |
| `NOT_APPLICABLE` | the question does not arise — a BEV has no engine displacement |

None of them is ever rendered as `false`, so a source omission cannot
manufacture a de-specification event for Phase 5. `NOT_APPLICABLE` matters for
honesty as much as for Phase 5: reporting "this BEV has no engine capacity" as
missing research is a statement about our files disguised as one about the car.

## Cohort

The cohort is versioned at
`vehreg/data/2026/product/comparable_specs/cohorts/c_crossover.json`, with the
selection rule written into the file beside the members.

The immutable 2026-09-08 ECO snapshot yields 118 candidate trim rows and 1,842
candidate comparable values across the 31 models.

One representative source row per model is chosen explicitly; it is never
inferred from price or file order. **20 of the 31 have one so far.** A model
without a representative stays in the cohort and is reported as
`models_without_representative` — dropping it would hide a whole car and still
call the result the segment. Currently awaiting a choice: Audi Q3, BMW X1, iX1,
iX2, Lexus UX, Mercedes-Benz EQB and GLB, MINI Countryman, Peugeot 3008,
Volvo EC40 and XC40.

These rows remain `PROVISIONAL_UNRESOLVED_TRIM`. An ECO homologation record is
evidence that a configuration exists, not sufficient evidence that it is the
current showroom offering. Its recommended price is exposed only as
`ECO_STICKER_PRICE`, with `canonical_retail_price: false`.

## What the card refuses to compare

A comparison that ranks incomparable things is worse than no comparison, so a
row can come back saying it will not pick a winner, and why:

| Status | When |
|---|---|
| `COMPARABLE` | every subject has a value in the same context |
| `COMPARABLE_WITH_GAPS` | some do; the winner is among those that do |
| `NOT_COMPARABLE_ACROSS_POWERTRAIN` | a ranked field that names its powertrains, with subjects in more than one of them |
| `NOT_APPLICABLE_TO_OTHERS` | fewer than two subjects even have the thing |
| `CONTEXT_NOT_SHARED` | the subjects were not measured the same way, so the field splits into rows and one of them holds a single car |
| `INSUFFICIENT_DATA` | genuinely too few values |
| `INFORMATION_ONLY` | the field is not a contest |

Three specific traps this closes:

**A plug-in hybrid's electric range is not a short BEV range.** 150 km on the
battery and 500 km in total are different quantities, so `ev.rated_range_km`
carries a `range_scope` qualifier (`ELECTRIC_ONLY` / `FULL`) and the two land in
separate rows. Energy consumption splits the same way.

**A plug-in hybrid's smaller battery is not a worse battery.** Any ranked field
that declares `applicable_powertrains` is ranked only among subjects sharing one
powertrain — range, consumption, battery capacity, charging.

**Zero tailpipe CO2 is a definition, not an advantage.** `emissions.co2_g_km`
declares its powertrains so a BEV's 0 g/km cannot beat a hybrid's 10 g/km.

## One thing written one way

The ECO register writes a single battery chemistry a dozen ways — `LFP`,
`LiFePO4`, `Lithium iron phosphate/graphite`, `lithium-phosphate (LFP)` — and
the gearbox as Thai prose. `battery.chemistry` and `powertrain.transmission` are
canonical enums; the source's own wording is kept beside them in
`battery.chemistry_as_declared` and `powertrain.transmission_as_declared`.

## The page

`pages/8_Compare.py` — **เทียบสเปค**. Pick two to six cars from the cohort, pick
a profile, and every cell carries its source. The comparison statuses above are
shown in Thai, so a row that declines to rank says why in the reader's language
rather than printing an enum at them. Models still waiting for a representative
are listed in the sidebar, not hidden.

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

**A price cannot enter the spec store, and the guard is in the registry.**
Checking the payload's own dict keys caught nothing — `SpecFact` has no price
field, so such a key is already refused as unknown, while a fact naming a
*registered* price key sailed straight through. The registry now refuses to hold
a field whose key or canonical unit is price-shaped, which is the only way one
could ever have got in. List and campaign prices remain in PriceLedger.

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

Tests cover registry/profile integrity, the cohort recomputed from its own rule,
candidate coverage,
price isolation, cell-level provenance, qualifier incompatibility, unknown vs
explicit false, temporal expiry, conflict handling, idempotent writes, CLI
output and byte-for-byte unchanged registration rows. They also pin the three
refusals above: a plug-in hybrid is not ranked against BEVs on range or battery,
zero tailpipe CO2 wins nothing, a car with no engine is not reported as missing
research, and a price field cannot be registered.
