# TDR Market export — Phase 7, "TDR Market panel"

The roadmap's Phase 7 names three panels; this is the first, and it turned
out to already half-exist. TDR (`smgkikikiki-cloud/tdr`, a separate
repository and a separate Supabase database) already has a `registrations`
table:

```sql
create table if not exists registrations (
  id uuid primary key default gen_random_uuid(),
  period date not null,
  brand_name_raw text not null,
  model_name_raw text not null,
  model_id uuid references models(id) on delete set null,
  registrations integer not null,
  source_id uuid references sources(id) on delete set null,
  unique(period, brand_name_raw, model_name_raw)
);
```

and code that already reads it: a monthly bar chart on every model's own page
(`app/models/[slug]/page.tsx`), and a "reports" page (`app/reports/page.tsx`,
the paywalled "TDR Report" the README mentions) that queries the table's date
range. Both currently have nothing to show — the table is empty. "TDR Market
panel" is that gap, not a page that needs designing.

## What this repository can honestly hand over

`python -m vehreg export-tdr-registrations --csv <path>` writes exactly
TDR's own four columns:

| column | from |
|---|---|
| `period` | this warehouse's `YYYY-MM` fact period, as a SQL date (`YYYY-MM-01`) |
| `brand_name_raw` | `dim_unit.brand` — the catalog-resolved brand name |
| `model_name_raw` | `dim_unit.model` — the catalog-resolved model name |
| `registrations` | summed `fact_registration.units`, MODEL+VARIANT grain, CORE scope by default |

TDR's own column name says "raw"; what it gets is deliberately not
`raw_label` (this warehouse's own copy of DLT's noisy full nameplate string,
e.g. `"AUDI A4 AV 45 TFSI q S line BE"`). TDR does its own brand/model
matching downstream — `model_id` is nullable and filled in separately, the
same way this warehouse never auto-resolves a fuzzy match into a fact. What
serves that matching best is the *clean* brand/model pair this warehouse has
already resolved through its own catalog, not DLT's raw text repeated a
second time.

Volume this warehouse has not itself resolved to a brand and a model — still
sitting in its own review queue — has no name to export it under and is
dropped from the file rather than mislabelled. It is not silently lost:
`export-tdr-registrations` prints the excluded unit count to stderr, and
`cube.tdr_registrations_unresolved_units()` returns it for a caller that
wants the number. As of this writing that is 511 units out of roughly
4.06M — the same review queue every other report in this project already
carries.

## What this is not

This command produces a file. It never opens a connection to TDR's database,
sends a request to it, or handles any of its credentials — not
`SUPABASE_SERVICE_ROLE_KEY`, not any other secret of that project's. Getting
the file's rows into TDR's `registrations` table is TDR's own job, run
locally with TDR's own environment: a `COPY`/upsert against Supabase, or a
small script TDR's own repository would host. That script does not belong
in this repository, and building it was explicitly not asked for here.

## Refresh

There is no schedule wired up. Re-run the export command and re-import
whenever TDR's admin wants the chart and the report page to reflect this
warehouse's latest month. The importing side should upsert on
`(period, brand_name_raw, model_name_raw)` — the same key the table already
declares unique — so a re-run never duplicates a row.

## Still open, in the same roadmap phase

Two more panels are named and neither is started: a Sales/Manager command
panel and a Parts Demand panel. Both need an audience and a home (a page in
this app, a page in TDR, or somewhere neither project owns yet) before
either is buildable — the same kind of call this project's owner reviewed
before Phase 3's price-harvester architecture was built, not a smaller one.
