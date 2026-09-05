"""Reader-facing price bands for Thai-market reporting.

Price is deliberately independent from vehicle segment. A large D-segment car
may sit below one million baht, while a C-segment premium model may sit above
two million. Reports therefore use three simple Thai buyer-budget bands:

* UNDER_1M  -- below 1,000,000 THB
* 1M_TO_2M -- 1,000,000 through 1,999,999 THB
* 2M_PLUS   -- 2,000,000 THB and above

The catalog still stores the actual price. ``price_band`` is derived at query
time so a price edit automatically moves the vehicle without duplicating data.
"""

from __future__ import annotations

from typing import Optional

UNDER_1M = "UNDER_1M"
ONE_TO_TWO_M = "1M_TO_2M"
TWO_M_PLUS = "2M_PLUS"
UNKNOWN = "UNKNOWN"
MIXED = "MIXED"


def price_band_for_price(price_thb: Optional[float]) -> str:
    """Return the canonical reporting band for one THB price."""
    if price_thb is None:
        return UNKNOWN
    if price_thb < 0:
        raise ValueError("price_thb must not be negative")
    if price_thb < 1_000_000:
        return UNDER_1M
    if price_thb < 2_000_000:
        return ONE_TO_TWO_M
    return TWO_M_PLUS


def price_band_for_range(price_min_thb: Optional[float],
                         price_max_thb: Optional[float],
                         price_thb: Optional[float] = None) -> str:
    """Band a folded trim range; crossing a boundary is honestly ``MIXED``."""
    low = price_min_thb if price_min_thb is not None else price_thb
    high = price_max_thb if price_max_thb is not None else price_thb
    if low is None and high is None:
        return UNKNOWN
    if low is None:
        low = high
    if high is None:
        high = low
    assert low is not None and high is not None
    if low < 0 or high < 0:
        raise ValueError("price range must not be negative")
    if low > high:
        raise ValueError("price_min_thb must not exceed price_max_thb")
    low_band = price_band_for_price(low)
    high_band = price_band_for_price(high)
    return low_band if low_band == high_band else MIXED


def _variant_band_sql(alias: str) -> str:
    low = f"COALESCE({alias}.price_min_thb, {alias}.price_thb)"
    high = f"COALESCE({alias}.price_max_thb, {alias}.price_thb)"
    return (
        "CASE "
        f"WHEN {low} IS NULL AND {high} IS NULL THEN '{UNKNOWN}' "
        f"WHEN {low} < 1000000 AND {high} < 1000000 THEN '{UNDER_1M}' "
        f"WHEN {low} >= 1000000 AND {high} < 2000000 THEN '{ONE_TO_TWO_M}' "
        f"WHEN {low} >= 2000000 THEN '{TWO_M_PLUS}' "
        f"ELSE '{MIXED}' END"
    )


def price_band_sql(outer_alias: str = "q") -> str:
    """SQLite expression for cube rows at VARIANT, MODEL or BRAND grain.

    Model/brand facts do not pretend to know a trim. Instead, their band is the
    consensus of all child variant bands in ``dim_unit`` for the same catalog
    year. Thus two differently priced trims that both sit below 1M still roll up
    to UNDER_1M, while a model straddling 1M or 2M becomes MIXED.

    A folded row with no variant children falls back to its own price rather
    than reporting UNKNOWN: the price is right there on the row, and a model
    carried at MODEL grain on purpose is the normal case in this catalog, not
    an incomplete one. With no price either, the fallback is UNKNOWN as before.
    """
    direct = _variant_band_sql(outer_alias)
    child = _variant_band_sql("pbv")
    where = (
        "pbv.grain = 'VARIANT' "
        f"AND pbv.catalog_year = {outer_alias}.catalog_year "
        f"AND pbv.unit_id LIKE {outer_alias}.unit_id || '.%'"
    )
    return (
        "CASE "
        f"WHEN {outer_alias}.grain = 'VARIANT' THEN ({direct}) "
        f"WHEN {outer_alias}.grain IN ('MODEL', 'BRAND') THEN CASE "
        f"WHEN (SELECT COUNT(*) FROM dim_unit pbv WHERE {where}) = 0 "
        f"THEN ({direct}) "
        f"WHEN (SELECT COUNT(DISTINCT ({child})) FROM dim_unit pbv WHERE {where}) = 1 "
        f"THEN (SELECT ({child}) FROM dim_unit pbv WHERE {where} LIMIT 1) "
        f"ELSE '{MIXED}' END "
        f"ELSE '{UNKNOWN}' END"
    )
