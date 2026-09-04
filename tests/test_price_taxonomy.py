import sqlite3
import unittest

from vehreg.price_taxonomy import (
    MIXED, ONE_TO_TWO_M, TWO_M_PLUS, UNDER_1M, UNKNOWN,
    price_band_for_price, price_band_for_range, price_band_sql,
)


class PriceBandTests(unittest.TestCase):
    def test_boundaries_are_simple_and_contiguous(self):
        self.assertEqual(price_band_for_price(0), UNDER_1M)
        self.assertEqual(price_band_for_price(999_999), UNDER_1M)
        self.assertEqual(price_band_for_price(1_000_000), ONE_TO_TWO_M)
        self.assertEqual(price_band_for_price(1_999_999), ONE_TO_TWO_M)
        self.assertEqual(price_band_for_price(2_000_000), TWO_M_PLUS)
        self.assertEqual(price_band_for_price(None), UNKNOWN)

    def test_folded_range_crossing_a_cutoff_is_mixed(self):
        self.assertEqual(price_band_for_range(799_000, 899_000), UNDER_1M)
        self.assertEqual(price_band_for_range(1_100_000, 1_900_000), ONE_TO_TWO_M)
        self.assertEqual(price_band_for_range(1_900_000, 2_100_000), MIXED)

    def test_model_grain_uses_child_variant_consensus(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute(
            "CREATE TABLE dim_unit (unit_id TEXT, catalog_year INTEGER, grain TEXT, "
            "price_thb REAL, price_min_thb REAL, price_max_thb REAL)"
        )
        conn.executemany(
            "INSERT INTO dim_unit VALUES (?,?,?,?,?,?)",
            [
                ("x.car", 2026, "MODEL", None, None, None),
                ("x.car.g1.a", 2026, "VARIANT", 799000, None, None),
                ("x.car.g1.b", 2026, "VARIANT", 899000, None, None),
            ],
        )
        row = conn.execute(
            f"SELECT {price_band_sql('q')} AS price_band FROM dim_unit q "
            "WHERE q.unit_id = 'x.car'"
        ).fetchone()
        self.assertEqual(row["price_band"], UNDER_1M)

        conn.execute(
            "UPDATE dim_unit SET price_thb = 1100000 WHERE unit_id = 'x.car.g1.b'"
        )
        row = conn.execute(
            f"SELECT {price_band_sql('q')} AS price_band FROM dim_unit q "
            "WHERE q.unit_id = 'x.car'"
        ).fetchone()
        self.assertEqual(row["price_band"], MIXED)


if __name__ == "__main__":
    unittest.main()
