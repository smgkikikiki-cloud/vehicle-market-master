import sqlite3
import unittest

from vehreg import db
from vehreg.monthly_state import audit_log, effective_state, history, set_state


class MonthlyStateTests(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")
        self.conn.execute(
            "INSERT INTO dim_unit "
            "(unit_id,catalog_year,grain,price_thb,origin_country,import_type) "
            "VALUES ('x.car',2026,'MODEL',1099000,'CN','CBU')"
        )

    def test_sparse_changes_roll_forward(self):
        set_state(self.conn, "x.car", "2026-05", price_thb=999000,
                  origin_country="TH", import_type="CKD", reason="local production")
        april = effective_state(self.conn, "x.car", "2026-04")
        may = effective_state(self.conn, "x.car", "2026-05")
        august = effective_state(self.conn, "x.car", "2026-08")
        self.assertEqual((april["price_thb"], april["origin_country"], april["import_type"]),
                         (1099000, "CN", "CBU"))
        self.assertEqual((may["price_thb"], may["origin_country"], may["import_type"]),
                         (999000, "TH", "CKD"))
        self.assertEqual((august["price_thb"], august["origin_country"], august["import_type"]),
                         (999000, "TH", "CKD"))

    def test_fields_can_change_independently(self):
        set_state(self.conn, "x.car", "2026-03", price_thb=999000)
        set_state(self.conn, "x.car", "2026-06", import_type="CKD", origin_country="TH")
        may = effective_state(self.conn, "x.car", "2026-05")
        july = effective_state(self.conn, "x.car", "2026-07")
        self.assertEqual((may["price_thb"], may["origin_country"], may["import_type"]),
                         (999000, "CN", "CBU"))
        self.assertEqual((july["price_thb"], july["origin_country"], july["import_type"]),
                         (999000, "TH", "CKD"))

    def test_editing_a_change_point_keeps_an_audit_trail(self):
        set_state(self.conn, "x.car", "2026-05", import_type="CKD",
                  reason="initial evidence")
        set_state(self.conn, "x.car", "2026-05", import_type="SKD",
                  reason="corrected source")
        self.assertEqual(history(self.conn, "x.car")[0]["import_type"], "SKD")
        log = [r for r in audit_log(self.conn, "x.car") if r["field"] == "import_type"]
        self.assertEqual([(r["old_value"], r["new_value"]) for r in log],
                         [(None, "CKD"), ("CKD", "SKD")])
        self.assertEqual(log[-1]["reason"], "corrected source")

    def test_invalid_month_and_import_type_are_rejected(self):
        with self.assertRaises(ValueError):
            set_state(self.conn, "x.car", "2026-13", price_thb=900000)
        with self.assertRaises(ValueError):
            set_state(self.conn, "x.car", "2026-05", import_type="MAGIC")


if __name__ == "__main__":
    unittest.main()
