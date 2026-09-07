# 2021 catalog

Forked from 2022 rather than authored. DLT publishes 2021 registrations and
this warehouse can read them, but the model master did not go back that far,
so every 2021 row would have queued for review instead of classifying.

Measured against the fork before it was committed: 99.9% of the year's
734,373 registrations classify, 1.0% of what classifies lands on the brand
rather than a model, and 7,860 units queue for review. Those leftovers are
real: they are cars that stopped selling before the 2022 catalog was written —
Chevrolet Colorado and Captiva (Chevrolet left Thailand in 2020), Honda
Mobilio, Toyota Avanza, Hyundai Grand Starex.

## What a fork gets wrong

A model's attributes here are its 2022 attributes. Prices, powertrain
availability and import type are all as of 2022, applied to 2021 volume. Where
that matters, the month-effective state editor is the place to correct it: a
change point set at a 2021 month overrides the catalog for that month onward
without touching the file.

## Adding the missing models

Nothing here needs deleting. A 2021-only model can be added to its brand file
in `models/` and it will pick up the volume currently sitting in review; the
review rows name the labels, largest first.
