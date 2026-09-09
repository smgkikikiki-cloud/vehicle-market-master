# Vehicle Market Master retirement manifest

Retired on 2026-09-09. This repository is a historical source only.

## Canonical destination

- Repository: `smgkikikiki-cloud/TDR`
- Vehicle engine: `automotive/vehicle_master/`
- All new vehicle facts, MarketTrim/spec work, fitment, Price Ledger/campaigns, ECO ingestion, DLT resolution, registration joins, release publishing, price harvesting, fixes, tests, workflows, and agent work belong in TDR only.

The production cutover was completed by TDR PR #19 (`Complete Vehicle Master cutover and retire the old repository`). Post-cutover price-feed resilience and embedded-repository guard fixes were subsequently applied directly to TDR.

## Operational retirement

- Legacy GitHub Actions workflows were removed from this repository.
- The 20-minute Price Feed runs from TDR only.
- TDR routing guards reject references that would route active work back here.
- The retired repository has no active implementation route.

The migrated TDR Price Feed was verified by a real scheduled run and an additional cutover smoke run. Harvest, publish policy, embedded-repository price guard, test suite, and the data-only PR step all completed successfully.

## Historical branches

Non-`main` branches in this repository are retained only as historical references. They are not alternate canonical sources and must not be used as active implementation targets.

During final retirement audit:

- major completed feature/fix branches checked were ancestors of the retired `main` and therefore already represented by the canonical migration;
- `audit/final-powertrain-recheck` contained only an old audit workflow beyond its merge base;
- `audit/powertrain-worklist-65` contained no file delta beyond its merge base;
- `data/backfill-2026-jul` / `feature/data-backfill-2026-jul` contained an older compressed staging representation of 2026 DLT backfill data; the usable March-July 2026 monthly data is present in TDR's `automotive/vehicle_master/data/raw_pivot/` and August is present as `pivot_2026-08.csv`;
- `feature/ecosticker-brochure-ingest` contains an unmerged experimental brochure downloader/parser prototype. It was never part of the retired canonical `main`, was not silently promoted during cutover, and must not be cherry-picked or revived automatically. If that capability is wanted later, re-review it as a new TDR feature against the current ECO ingestion architecture.

Do not infer that an unmerged historical branch is missing production work. Any intentional recovery from a historical branch must be reviewed and implemented in TDR, not here.

## Repository-level archive flag

The code and automation are retired regardless of GitHub's repository-level `archived` metadata. If the repository is not yet marked Archived in GitHub, set that final UI flag from repository Settings. No active workflow or agent routing depends on that flag.
