from collections import Counter

from vehreg.catalog import Catalog
from vehreg.taxonomy import BodyType

EXPECTED_OFFROAD = {
    "toyota.land_cruiser_300",
    "lexus.lx",
    "gwm.tank300",
    "gwm.tank500",
    "mercedes_benz.g_class",
    "suzuki.jimny",
    "jeep.wrangler",
}
EXPECTED_PPV = {
    "ford.everest",
    "toyota.fortuner",
    "isuzu.mux",
    "mitsubishi.pajero_sport",
    "nissan.terra",
}

cat = Catalog.load(year=2026)
counts = Counter(m.body_type.value for m in cat.models.values())
offroad = {m.id for m in cat.models.values() if m.body_type is BodyType.OFFROAD}
ppv = {m.id for m in cat.models.values() if m.body_type is BodyType.PPV}

print("BODY_COUNTS_2026", dict(sorted(counts.items())))
print("OFFROAD", sorted(offroad))
print("PPV", sorted(ppv))

assert "SUV" not in counts, counts
assert offroad == EXPECTED_OFFROAD, (offroad, EXPECTED_OFFROAD)
assert ppv == EXPECTED_PPV, (ppv, EXPECTED_PPV)
assert BodyType.parse("SUV") is BodyType.CROSSOVER
assert BodyType.parse("ladder frame suv") is BodyType.OFFROAD
