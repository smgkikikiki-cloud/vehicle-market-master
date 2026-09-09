# Phase A live Supabase verification — 2026-09-09

This addendum closes the live-database uncertainty recorded in `PHASE_A_BASELINE.md`.

The connected TDR Supabase project is reachable and healthy. Read-only SQL inspection confirmed the following live row counts:

| table | rows |
|---|---:|
| `brands` | 62 |
| `models` | 327 |
| `trims` | 0 |
| `registrations` | 0 |

Live `pg_policies` inspection also confirmed that these SELECT policies exist with `qual = true`:

- `public read brands`
- `public read models`
- `public read model_powertrains`
- `public read trims`
- `public read registrations`

Therefore the Phase A finding about `registrations` is confirmed against the running database, not only inferred from migration files: the table is anonymously readable today. It currently contains zero rows, so there is no registration-data leak at this moment. Real market data must not be imported until the entitlement boundary is implemented and the public-read policy is removed/replaced or the data is split into an intentionally public teaser projection.

Live access also removes the credential-access blocker for the object crosswalk. The crosswalk itself is still not done and remains a required migration task before any TDR vehicle object is rewritten or deleted. There are currently 62 TDR brand rows and 327 TDR model rows to inventory against canonical Vehicle Master identities; `trims` is empty, which materially reduces the legacy retail-trim migration burden.

No schema or data mutation was performed during this verification.
