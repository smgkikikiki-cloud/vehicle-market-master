import unittest

from vehreg import cube, db
from vehreg.monthly_state import set_state


class CubeMonthlyStateTests(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")
        self.conn.execute(
            "INSERT INTO dim_source(name) VALUES ('test')"
        )
        source_id = self.conn.execute(
            "SELECT source_id FROM dim_source WHERE name='test'"
        ).fetchone()["source_id"]
        self.conn.execute(
            "INSERT INTO dim_unit "
            "(unit_id,catalog_year,grain,brand,model,segment,body_type,market_scope,"
            "price_thb,origin_country,import_type) "
            "VALUES ('x.car',2026,'MODEL','X','Car','C','SEDAN','CORE',"
            "1099000,'CN','CBU')"
        )
        self.conn.execute(
            "INSERT INTO fact_registration "
            "(period,registration_type,province,unit_id,grain,units,source_id,raw_label) "
            "VALUES ('2026-04','RY1','ALL','x.car','MODEL',10,?,'X Car'),"
            "('2026-05','RY1','ALL','x.car','MODEL',20,?,'X Car')",
            (source_id, source_id),
        )

    def test_cube_uses_state_effective_in_each_fact_month(self):
        set_state(
            self.conn, 'x.car', '2026-05', price_thb=999000,
            origin_country='TH', import_type='CKD',
        )
        price = cube.run(self.conn, ['price_band'], scopes='all')
        rows = {r['price_band']: r['units'] for r in price.rows}
        self.assertEqual(rows['1M_TO_2M'], 10)
        self.assertEqual(rows['UNDER_1M'], 20)

        origin = cube.run(self.conn, ['origin_country'], scopes='all')
        rows = {r['origin_country']: r['units'] for r in origin.rows}
        self.assertEqual(rows, {'CN': 10, 'TH': 20})

        route = cube.run(self.conn, ['import_type'], scopes='all')
        rows = {r['import_type']: r['units'] for r in route.rows}
        self.assertEqual(rows, {'CBU': 10, 'CKD': 20})

    def test_default_analysis_grain_excludes_brand_rows(self):
        source_id = self.conn.execute(
            "SELECT source_id FROM dim_source WHERE name='test'"
        ).fetchone()["source_id"]
        self.conn.execute(
            "INSERT INTO dim_unit "
            "(unit_id,catalog_year,grain,brand,market_scope) "
            "VALUES ('x',2026,'BRAND','X','MIXED')"
        )
        self.conn.execute(
            "INSERT INTO fact_registration "
            "(period,registration_type,province,unit_id,grain,units,source_id,raw_label) "
            "VALUES ('2026-05','RY1','ALL','x','BRAND',999,?,'X')",
            (source_id,),
        )
        self.assertEqual(cube.run(self.conn, [], scopes='all').total_units, 30)
        self.assertEqual(
            cube.run(self.conn, [], scopes='all', grains=['BRAND']).total_units,
            999,
        )


if __name__ == '__main__':
    unittest.main()
