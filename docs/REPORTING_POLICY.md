# Vehicle Market Master — Reporting Policy

## Canonical registration total

For all market analysis produced from this repository, **total vehicle registrations are defined as the sum of registrations assigned to identifiable vehicle models / model rows**.

The reporting denominator is therefore a **model-sum total**, not the DLT published headline / official aggregate total.

This is intentional. In some DLT registration datasets — especially รย.1 — the published overall total does not reconcile exactly with the sum of the model-level rows. The residual may appear as `Other`, an unclassified remainder, or another source-level discrepancy that has little analytical value for model/segment market work.

### Rules

1. **Keep the raw DLT source unchanged.**
   `Other`, residual rows, official totals, and any unmatched source evidence must not be deleted from the raw-data layer. They remain available for provenance, audit, and source-quality checks.

2. **Do not use the DLT official aggregate as the market denominator.**
   Market size, brand share, model share, segment share, growth, powertrain share, body-type share, and similar analytics use the sum of usable identified model registrations.

3. **Exclude `Other` / residual volume from analytical market totals.**
   Residual volume is not redistributed to brands, models, segments, powertrains, or any other facet.

4. **Do not force reconciliation.**
   The system must not create synthetic allocations merely to make the model-sum total equal the DLT official aggregate.

5. **Track the difference as a diagnostic only.**
   When useful, report:

   `reconciliation_gap = DLT official aggregate - model-sum total`

   This gap describes source coverage / classification completeness. It is not vehicle-market volume for downstream analysis.

6. **If a report explicitly shows the DLT official number, label it separately.**
   Use wording such as `DLT official aggregate` so it cannot be confused with the repository's canonical `registration total`.

## Practical meaning

If the DLT official total is 100,000 registrations, identifiable model rows sum to 97,500, and 2,500 sits in `Other` / residual data, then Vehicle Market Master reports **97,500 registrations** as the market total.

The 2,500 remains in the raw/audit layer and may be shown as a 2,500-unit reconciliation gap, but it is not included in market share denominators.

## Status

This policy is canonical for Vehicle Market Master from 2026-09-04 onward and supersedes older wording inherited from `Export-channel` that implied analytical totals must always reconcile to the DLT source aggregate.
