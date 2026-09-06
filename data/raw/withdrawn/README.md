# Withdrawn DLT exports

Files here are kept as evidence and are **not** loaded: `bootstrap_database`
only globs `data/raw/dlt_????-??.csv`, one directory up. Each was replaced by
the same month read from the DLT pivot workbook, in `data/raw_pivot/`.

## `dlt_2023-12` — the API returned December 2022's payload

Resource `475ade70-243b-4250-bfe2-1bef174436ad` ("ธันวาคม 2566") returned the
same registrations as resource `b6f88d4b-…` ("ธันวาคม 2565"): 453 rows, 47,635
units, 452 of them matching to the character. The two meta files agree down to
the 145,528 motorcycles each filtered out.

The pivot workbook settles which one is wrong. It reports December 2022 at
47,727 — within 0.2% of the export, the same gap every other month shows — and
December 2023 at 42,593, which is 5,026 units below what this file claims. So
the December 2022 export is right and this one is a duplicate of it.

## `dlt_2026-02` — fetched before the month was published

Six rows, eighteen units, because DLT publishes a resource for the current
month before the month is over. The pivot has the finished month at 48,908.

## Re-fetching

Either month can come back here as a normal export if DLT serves it correctly:
drop the corrected file into `data/raw/`, delete the matching
`data/raw_pivot/pivot_YYYY-MM.csv`, and rebuild. The export is the better
source when it is right — it carries the registration class, which the pivot
does not.
