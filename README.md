# Vehicle Market Master

Thai vehicle product master and registration intelligence workspace.

Vehicle Master is the foundation for retail trims, exact specifications, source
evidence and a separate Price Ledger. Registration analytics is one consumer.
See [Vehicle Master 2.0 — Phase 1](docs/VEHICLE_MASTER_PHASE1.md) for the delivered
contract, JAECOO 5 reference, product API, import/export commands and next choices.

Phase 2 is documented in [ECO ingestion — Phase 2](docs/ECOSTICKER_PHASE2.md).
The repository contains the verified 1,640-record public inventory snapshot,
normalized Model/Generation and trim candidates, a human-review queue and the
reviewed JAECOO 5 reference decisions. ECO staging never writes registration
analytics.

```bash
python -m vehreg market validate
python -m vehreg market list --model chery.jaecoo_j5
```

This repository is the dedicated home for the vehicle-registration (`vehreg`) subsystem previously developed inside `Export-channel`.

Core scope:
- DLT registration raw data and metadata
- Vehicle catalog / model-generation-variant taxonomy
- รย.1 / รย.3 classification and allocation
- Market / segment / body / cab / powertrain facets
- Local classification editor and decision log
- Import/export and cube-building tools
- Vehicle-registration tests and documentation

## Canonical market total

For downstream market analysis, **registration total means the sum of usable identified vehicle-model registrations, not the DLT official aggregate headline**.

`Other`, residual, unmatched aggregate, and reconciliation-gap volume remains preserved in the raw/audit layer but is excluded from market-size and market-share denominators. The system must not redistribute that residual merely to force reconciliation with the official aggregate.

See `docs/REPORTING_POLICY.md` for the full rule.

Source migration baseline: `smgkikikiki-cloud/Export-channel@5b3dfd7407fbc6e5f9919d0d4b1451e05f75b3d7`.
