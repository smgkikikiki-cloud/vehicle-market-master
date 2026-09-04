# Derived trim rankings

This directory is for **derived/exported trim-level reporting**, separate from
the canonical vehicle-market facts.

Rules:

- `fact_registration` remains the canonical market ledger.
- Ordinary grades, ranges and drivetrains of the same model remain folded in
  the master model total.
- If the same market model has different powertrains (for example BEV and REEV)
  and the DLT label distinguishes them, reporting treats those powertrains as
  separate market models.
- `fact_trim` / `dim_trim` retain Chinese-marque trim detail. The Chinese EV trim
  ranking reads those tables only; it never feeds trim rows back into the master
  ledger and therefore cannot double-count registrations.
- If DLT does not split a model's trim in a month, the exported ranking uses
  `DLT_UNSPLIT`. Never allocate an unpublished 400/500/600, Standard/Extended,
  RWD/AWD, etc. mix by assumption.

The historical root file `data/trims_2022_2026.csv` is intentionally left in
place for backward compatibility. New explicit exports may be written here.
