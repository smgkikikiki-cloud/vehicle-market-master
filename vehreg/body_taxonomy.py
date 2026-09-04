"""Market-facing SUV roll-up for reporting.

Reports expose one reader-facing umbrella with three subtypes:

    SUV -> CROSSOVER | PPV | OFFROAD_SUV

This is deliberately a market/competitive taxonomy, not a tax or chassis
classification. Legal PPV treatment or platform sharing must not move a model
away from the vehicles a buyer would naturally compare it with.
"""

from __future__ import annotations

from .taxonomy import BodyType

SUV_BODY_TYPES = frozenset({BodyType.CROSSOVER, BodyType.PPV, BodyType.SUV})

# Explicit competitive-set exceptions. The legacy catalog used PPV for some
# ladder-frame SUVs and SUV for some ordinary road SUVs, so body_type alone is
# not enough to produce the reader-facing split.
OFFROAD_SUV_MODELS = frozenset({
    "FJ Cruiser",
    "Land Cruiser 300",
    "Tank 300",
    "Tank 500",
    "Wrangler",
    "Defender",
})


def body_family_for(body: BodyType | str) -> str:
    """SUV-like bodies roll up to SUV; other bodies retain their normal label."""
    parsed = BodyType.parse(body)
    return "SUV" if parsed in SUV_BODY_TYPES else parsed.value


def suv_type_for(body: BodyType | str, model: str | None = None) -> str:
    """Return CROSSOVER / PPV / OFFROAD_SUV, or NOT_APPLICABLE.

    The explicit off-road list wins over the legacy body_type. Otherwise
    CROSSOVER remains crossover, PPV remains PPV, and old generic SUV rows are
    treated as road/passenger crossovers by default.
    """
    parsed = BodyType.parse(body)
    if model in OFFROAD_SUV_MODELS:
        return "OFFROAD_SUV"
    if parsed is BodyType.PPV:
        return "PPV"
    if parsed in {BodyType.CROSSOVER, BodyType.SUV}:
        return "CROSSOVER"
    return "NOT_APPLICABLE"


BODY_FAMILY_SQL = (
    "CASE WHEN body_type IN ('CROSSOVER','PPV','SUV') "
    "THEN 'SUV' ELSE body_type END"
)

_OFFROAD_SQL = ", ".join("'" + name.replace("'", "''") + "'"
                         for name in sorted(OFFROAD_SUV_MODELS))
SUV_TYPE_SQL = (
    f"CASE WHEN model IN ({_OFFROAD_SQL}) THEN 'OFFROAD_SUV' "
    "WHEN body_type = 'PPV' THEN 'PPV' "
    "WHEN body_type IN ('CROSSOVER','SUV') THEN 'CROSSOVER' "
    "ELSE 'NOT_APPLICABLE' END"
)
