"""Market-facing SUV roll-up for reporting.

The raw catalog keeps the long-standing ``BodyType`` values because they are
already used across the warehouse. Reporting needs a simpler human-facing view:
all CROSSOVER / PPV / SUV rows belong to one SUV umbrella, then split into three
competitive subtypes.

This is deliberately a market taxonomy, not a tax or chassis taxonomy:

* CROSSOVER   - road/passenger SUV (CR-V, CX-8, etc.)
* PPV         - pickup-derived mainstream SUV (Fortuner, MU-X, Everest, etc.)
* OFFROAD_SUV - traditional/off-road-oriented SUV (FJ Cruiser, Tank 300, etc.)

``BodyType.SUV`` is therefore treated as the legacy storage key for
``OFFROAD_SUV``. Whether a vehicle is legally taxed as a PPV or uses a particular
frame/platform does not override the market-facing competitive set.
"""

from __future__ import annotations

from .taxonomy import BodyType

SUV_BODY_TYPES = frozenset({BodyType.CROSSOVER, BodyType.PPV, BodyType.SUV})

SUV_TYPE_BY_BODY: dict[BodyType, str] = {
    BodyType.CROSSOVER: "CROSSOVER",
    BodyType.PPV: "PPV",
    BodyType.SUV: "OFFROAD_SUV",
}


def body_family_for(body: BodyType | str) -> str:
    """Return the reader-facing umbrella category.

    SUV-like bodies roll up to ``SUV``. Other bodies keep their normal body
    label so the function is safe to use as a general reporting dimension.
    """
    parsed = BodyType.parse(body)
    return "SUV" if parsed in SUV_BODY_TYPES else parsed.value


def suv_type_for(body: BodyType | str) -> str:
    """Return CROSSOVER / PPV / OFFROAD_SUV, or NOT_APPLICABLE."""
    parsed = BodyType.parse(body)
    return SUV_TYPE_BY_BODY.get(parsed, "NOT_APPLICABLE")


# SQLite expressions used by the cube. Keeping them next to the Python mapping
# prevents the dashboard taxonomy from drifting away from catalog logic.
BODY_FAMILY_SQL = (
    "CASE WHEN body_type IN ('CROSSOVER','PPV','SUV') "
    "THEN 'SUV' ELSE body_type END"
)

SUV_TYPE_SQL = (
    "CASE body_type "
    "WHEN 'CROSSOVER' THEN 'CROSSOVER' "
    "WHEN 'PPV' THEN 'PPV' "
    "WHEN 'SUV' THEN 'OFFROAD_SUV' "
    "ELSE 'NOT_APPLICABLE' END"
)
