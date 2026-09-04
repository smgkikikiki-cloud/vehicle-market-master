"""vehreg - Thai new-vehicle registration intelligence.

Layers, in the order data moves through them:

    taxonomy   closed vocabularies for every facet the owner listed
    entities   Brand / Model / Generation / Variant + the override resolver
    catalog    load, validate and index one year's on-disk catalog
    authoring  bulk-edit the catalog from a wide CSV
    normalize  fold messy Thai/English labels and match them to the catalog
    db         SQLite: type-2 dimension + fact table + review queue
    ingest     DLT export -> facts, with everything unmatched kept visible
    cube       cross-tab any facet against any other
"""

from .taxonomy import (  # noqa: F401
    BodyType, BrandSegment, CabType, Drivetrain, Grain, ImportType,
    MarketPosition, Powertrain, PowertrainGroup, RegistrationType, Segment,
    market_position_for_price, powertrain_group, registration_type_for,
)
from .entities import (  # noqa: F401
    Brand, Generation, Model, ResolvedVehicle, Variant, resolve,
)
from .catalog import DEFAULT_YEAR, Catalog, available_years, fork_year  # noqa: F401

__version__ = "0.1.0"
