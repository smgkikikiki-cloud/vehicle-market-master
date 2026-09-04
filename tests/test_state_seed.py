from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from vehreg import db
from vehreg.monthly_state import audit_log, effective_state
from vehreg.state_seed import load_seed_csv


class StateSeedTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = db.connect(":memory:")
        self.conn.execute(
            "INSERT INTO dim_unit "
            "(unit_id,catalog_year,grain,origin_country,import_type) "
            "VALUES ('x.car',2024,'MODEL','CN','CBU')"
        )

    def _seed(self) -> Path:
        handle = tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="", delete=False)
        handle.write(
            "unit_id,grain,effective_month,origin_country,import_type,source_url,evidence\n"
            "x.car,MODEL,2024-07,TH,CKD,https://example.test/source,local production\n"
        )
        handle.close()
        return Path(handle.name)

    def test_seed_is_idempotent_and_audited(self) -> None:
        path = self._seed()
        try:
            first = load_seed_csv(self.conn, path)
            second = load_seed_csv(self.conn, path)
        finally:
            path.unlink(missing_ok=True)

        self.assertEqual(first["applied"], 1)
        self.assertEqual(second["unchanged"], 1)
        self.assertEqual(first["errors"], [])
        self.assertEqual(second["errors"], [])

        june = effective_state(self.conn, "x.car", "2024-06")
        july = effective_state(self.conn, "x.car", "2024-07")
        self.assertEqual((june["origin_country"], june["import_type"]), ("CN", "CBU"))
        self.assertEqual((july["origin_country"], july["import_type"]), ("TH", "CKD"))

        fields = [row["field"] for row in audit_log(self.conn, "x.car")]
        self.assertEqual(fields.count("origin_country"), 1)
        self.assertEqual(fields.count("import_type"), 1)
        self.assertEqual(fields.count("note"), 1)


if __name__ == "__main__":
    unittest.main()
