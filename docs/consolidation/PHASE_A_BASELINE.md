# Consolidation Phase A — baseline, ownership, and what was found

Scope is exactly [Phase A of the masterplan](MASTERPLAN.md): document canonical
ownership, inventory and diff the two systems, map duplicated TDR
fields/tables to a migration action, sketch the route-removal map, and record
a baseline. No UI rewrite, no data move, no write path changed. Everything
below is read-only inspection of both repositories as they stand on
2026-09-09.

## Ownership, declared

| Domain | Canonical owner from this point forward |
|---|---|
| Brand / Model / Generation / Variant / MarketTrim identity | `vehicle-market-master` (`vehreg.entities`, `vehreg.catalog`) |
| Price (list / campaign / finance / ECO sticker) | `vehreg.pricing` — Price Ledger |
| Comparable specs (powertrain, dimensions, fitment, battery…) | `vehreg.comparable_specs` — SpecRegistry / SpecLedger |
| DLT registration resolution and analytics | `vehreg.db` / `vehreg.cube` — the registration warehouse |
| DLT Trim Ledger (Chinese-marque / Tesla detail) | `vehreg.trimledger` |
| Production programs, plants, local content, MiT | Stays TDR's own domain (`production_programs`, `plants`, `local_content_declarations`, `mit_approvals`) — masterplan §9 keeps this out of the automotive engine |
| Editorial (news, images, featured, report copy) | Stays TDR's own domain |

`TDR` is the declared long-term main repository (masterplan §2). This
warehouse is the declared canonical vehicle engine until Phase B moves it.

## vehreg baseline (2026-09-09, `main` @ `f9c6abe`)

```
registrations         4,064,148 units / 35,212 fact rows / 68 periods (2021-01..2026-08)
trim ledger            reconciles at 0 against the master
review queue           1,081 units open with no best_guess (raw-label ambiguity, pre-match)
export gap             511 units have a fact row but no dim_unit join (post-match, pre-catalog)
tests                   544 passed, 4,334 subtests
comparable specs        60 registry fields, 4 profiles (core/safety/comfort/fitment)
                        20 pilot models published, 11 in backlog, 0 published facts,
                        0 pilot models with current OEM evidence
price ledger            Suzuki Fronx campaign corrections + closed-campaign rule live
                        (see PR #15's three-defect fix)
```

These two "unresolved" numbers are different pipeline stages and must not be
summed: 1,081 units never matched a catalog row at all; 511 matched a
`unit_id` that has since disappeared from the current catalog year's dimension
(a stale reference, not an unmatched label). Both are visible, neither is
invented.

## TDR schema inventory

Read from `supabase/schema_v11_full.sql` (the consolidated fresh-install
script) plus the incremental `migration_v*.sql` files, not from a live
connection — no credential was available for this pass.

| TDR table | Target domain (masterplan §2) | Migration action |
|---|---|---|
| `brands` | Automotive — Brand | Superseded by canonical `Brand`; keep `logo_url`, `status` as TDR-served display fields |
| `models` | Automotive — Model/Generation, mixed with TDR-only fields | Split: identity/powertrain/launch fields superseded by canonical `Model`/`Generation`; `featured`, `image_url`, `consumer_description`, `unconfirmed_fields` stay TDR-owned per §13 |
| `model_powertrains` | Automotive — powertrain/spec | Superseded by `SpecRegistry`/`SpecLedger` (`powertrain.*`, `battery.*`, `engine.*` field keys already cover every column here) |
| `trims` | Automotive — MarketTrim | Superseded by `MarketTrim`; **`trims.price_baht` is exactly the field masterplan §4 forbids as a source of truth** — current price must come from `PriceLedger.current_list_price()` |
| `trim_powertrains` | Automotive — MarketTrim↔powertrain join | Superseded by `MarketTrim`'s own powertrain reference |
| `registrations` | Automotive — registration serving projection | This is the table `export-tdr-registrations` (PR #18) feeds. See the RLS finding below before wiring it up |
| `plants` | Industry — stays TDR's own | No migration; masterplan §9 keeps this domain in TDR |
| `production_programs` | Industry — stays TDR's own | No migration |
| `model_plants` | Industry — stays TDR's own | No migration |
| `local_content_declarations` | Industry — stays TDR's own | No migration |
| `mit_approvals` | Industry — stays TDR's own | No migration |
| `companies` | Editorial/backend — stays TDR's own | Masterplan §12: not a main-nav section unless a use case appears |
| `events` | Editorial — stays TDR's own | No migration |
| `sources` / `entity_sources` | Editorial/provenance — stays TDR's own | Distinct from vehreg's own `dim_source`/`SourceDocument` provenance; not the same evidence system and not merged by this plan |

Nothing here required a live database connection — this is a read of committed
migrations, so it describes what *should* be true of a fresh install, not
necessarily verified against the running production project (see below).

## Route removal map (masterplan §10, §12)

Confirmed present in `app/`: `production/`, `production/[slug]/`, `plants/`,
`plants/[slug]/` — exactly the four routes masterplan §10 names for removal.

`components/Footer.tsx` links all of them from main navigation today:

```
"ผลิตในไทย" section  → /production, /production?view=model
"บริษัท"            → /companies
```

`/upcoming` is already a dead redirect to `/models` (`export default function
Upcoming(){redirect("/models")}`) despite still being linked from the footer
— the README's claim that the upcoming category was removed is accurate for
the page; the footer link pointing at a redirect stub was missed and is a
one-line cleanup whenever Phase F touches this file.

`components/Header.tsx` has no `/production`/`/plants` links — only a search
placeholder that mentions "โรงงาน" as an example query, which is copy, not a
route.

## Finding: `registrations` is already anon-readable, independent of this work

`supabase/migration_v08_catalog_industry.sql` (carried into
`schema_v11_full.sql`) adds:

```sql
-- Consumer model pages may show registration figures. Raw import/admin remain write-protected.
create policy "public read registrations" on registrations for select using (true);
```

This is a real, committed policy from V0.8 — well before this consolidation
was proposed — and it grants anonymous `SELECT` on the whole table. It
contradicts an earlier comment in the same file ("registrations remain
private to the service-role/admin layer by default"), which describes the
table's state before this later migration ran.

The table reads empty today (`app/models/[slug]/page.tsx`'s own comment: "the
registrations table can be empty, and an empty map simply means..."), and
`app/models/[slug]/page.tsx` has zero auth/entitlement code anywhere in it —
so right now this is a policy gap with nothing behind it, not a live leak.

This matters directly for masterplan §18 and §25.17: registration/sales
visualizations are target **paid** content, and activating `publish_market`
before the entitlement boundary (Phase D) is explicitly forbidden. **Importing
the `export-tdr-registrations` CSV (PR #18) into this table now would be the
first real data to flow through an already-open anon-read policy** — the
export tool itself opens no connection and is fine as a tool, but the import
step should wait for Phase D, and Phase D's own migration will need to either
replace this policy with an entitlement-checked one or drop it in favour of
a dedicated public teaser projection (masterplan §18's suggested
`public_model_market_teaser`).

Per masterplan §D's own instruction, this needs verifying against the actual
running Supabase project, not only the migration file — a manually-applied
change could differ from what's committed. That check needs `anon` access;
see below.

## ID crosswalk — not started, needs access

Masterplan §16 requires inventorying both systems' objects and building a
verified `TDR object ID → canonical object ID` crosswalk before any object is
touched. That means reading TDR's actual live `brands`/`models`/`trims` rows
(not just their schema) and matching each to a `vehreg` `brand_id`/`model_id`.

`brands` and `models` carry `create policy "public read ... for select using
(true)"` in the committed schema, so this is exactly the kind of read the
`NEXT_PUBLIC_SUPABASE_URL`/`NEXT_PUBLIC_SUPABASE_ANON_KEY` pair is meant for —
no service-role key needed, and none was requested. This section is a stub
until those two values are supplied; nothing here should be read as "the
crosswalk is done."

## Explicitly not done in this pass

- No TDR file was edited. No Supabase migration was run or drafted.
- No object was matched by name — masterplan §16 forbids that, and no
  verified crosswalk exists yet to match any other way.
- No registration data was imported into TDR's `registrations` table.
- Phases B onward (moving the Python engine into TDR, canonical write
  pipeline, entitlement boundary, serving projections) are untouched.

## Open questions for Phase A to close

1. Confirm the `public read registrations` policy's actual state on the
   live Supabase project (the migration file is strong evidence but
   masterplan §D itself says not to trust the file alone).
2. Decide whether that policy is closed now (before any data is imported) or
   left open until Phase D replaces it with an entitlement-checked one or a
   dedicated teaser projection — either is defensible, but leaving it open
   with real data behind it is not, per masterplan §25.17.
3. `entity_sources`/`sources` (TDR's own provenance tables) vs. vehreg's
   `dim_source`/`SourceDocument` — masterplan doesn't call for merging these,
   and this document doesn't recommend it; flagged only so Phase C's
   canonical write pipeline design accounts for two provenance systems
   existing side by side.
