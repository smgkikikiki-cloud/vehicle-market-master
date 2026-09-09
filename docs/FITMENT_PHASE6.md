# Fitment expansion — Phase 6 (schema only)

The roadmap calls Phase 6 "Fitment expansion: tyre structured database, wheel,
12V battery." This change adds the schema for that and nothing else — no
fitment value has been written for any trim.

## Why schema first, and stop there

Every field the comparable-spec pipeline has ever populated came from evidence
this repository already ingests: DLT registration, the ECO Sticker snapshot, or
the live price feed. None of those sources reports a wheel's bolt pattern,
offset, load index, speed rating, or a car's 12V starter/accessory battery
group size. The only fitment fact any source has ever stated is a tyre size
string (`225/55R18`), which is already `fitment.tyre_size` / `tyre_front` /
`tyre_rear` from Phase 4.

`vehreg/data/2026/product/comparable_specs/registry.json` and `profiles.json`
now name the rest of what the fitment database needs to hold:

| Field | Type | Unit |
|---|---|---|
| `fitment.wheel_rim_width_front_in` / `_rear_in` | NUMBER | in |
| `fitment.wheel_pcd` | TEXT | — (e.g. `"5x114.3"`) |
| `fitment.wheel_offset_mm` | NUMBER | mm |
| `fitment.tyre_load_index_front` / `_rear` | NUMBER | index |
| `fitment.tyre_speed_rating_front` / `_rear` | ENUM | — (e.g. `"H"`, `"V"`) |
| `fitment.battery_12v_group_size` | TEXT | — (e.g. `"55D23L"`) |
| `fitment.battery_12v_capacity_ah` | NUMBER | Ah |

All ten sit in group `chassis` beside the existing tyre-size fields, and in a
new `c_crossover_fitment` profile so the Compare page can show them as their
own tab without crowding `c_crossover_core`. `SpecRegistry.validate()` passes;
`test_no_fitment_value_has_been_invented_for_any_pilot_trim` (in
`tests/test_comparable_specs_phase4.py`) fails the build if any fact ledger in
the repository ever carries a value against one of these keys without a real
source behind it — the same discipline Phase 4 applied to price and to
unresearched specs.

## What is still needed before this can hold a value

A rim's PCD and offset, a tyre's load index and speed rating, and a 12V
battery's group size are not on an ECO Sticker, a DLT export, or a price
article. They come from either:

- the OEM's own owner's-manual / spec-sheet PDF (per model, per trim — the same
  page-by-page problem Phase 4's `oem_sources.json` already tracks for
  headline specs and found mostly blocked by JS rendering and, for two brands,
  a robots policy that names AI agents), or
- a tyre/battery retailer's fitment lookup (Tyreplus, Kumho, GS Battery and
  similar publish fitment-by-model tables, which is a different shape of
  source than anything this pipeline harvests today — a new adapter, not a
  new field on the existing OEM/media harvester).

Building either evidence pipeline is a Phase-3-sized decision — a new source
tier, a new claim shape, a new review queue — not a follow-on to this schema
change. It is intentionally not started here.
