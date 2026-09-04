"""Market-facing SUV roll-up for reporting.

The catalog keeps the long-standing ``BodyType`` values for compatibility, but
reports expose a simpler reader-facing hierarchy:

    SUV -> CROSSOVER | PPV | OFFROAD_SUV

This is a market taxonomy, not a tax or chassis taxonomy:

* CROSSOVER   - road/passenger SUV (CR-V, CX-8, X5, etc.)
* PPV         - pickup-derived mainstream SUV (Fortuner, MU-X, Everest, etc.)
* OFFROAD_SUV - traditional/off-road-oriented SUV (FJ Cruiser, Tank 300, etc.)

Legacy ``BodyType.SUV`` rows default to CROSSOVER because that old bucket was
used for many ordinary passenger SUVs. A model that belongs in OFFROAD_SUV can
override ``suv_type`` at model level. Legal PPV treatment or platform sharing
never overrides the reader-facing competitive set.
"""

from __future__ import annotations

from .taxonomy import BodyType

SUV_BODY_TYPES = frozenset({BodyType.CROSSOVER, BodyType.PPV, BodyType.SUV})

SUV_TYPE_BY_BODY: dict[BodyType, str] = {
    BodyType.CROSSOVER: "CROSSOVER",
    BodyType.PPV: "PPV",
    BodyType.SUV: "CROSSOVER",  # legacy SUV bucket; explicit off-road rows override
}


def body_family_for(body: BodyType | str) -> str:
    """Return the reader-facing umbrella category."""
    parsed = BodyType.parse(body)
    return "SUV" if parsed in SUV_BODY_TYPES else parsed.value


def suv_type_for(body: BodyType | str) -> str:
    """Return CROSSOVER / PPV / OFFROAD_SUV, or NOT_APPLICABLE."""
    parsed = BodyType.parse(body)
    return SUV_TYPE_BY_BODY.get(parsed, "NOT_APPLICABLE")
