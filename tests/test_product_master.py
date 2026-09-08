from copy import deepcopy
from datetime import date
import json
from pathlib import Path
import shutil

import pytest

from vehreg.catalog import Catalog, CatalogError, DATA_DIR
from vehreg.cli import main
from vehreg.pricing import PriceLedger, PricingError
from vehreg.product import ProductMaster, append_prices, import_trims

TRIM = 'chery.jaecoo_j5.j5.trim.max_plus_bev'
GEN = 'chery.jaecoo_j5.j5'


@pytest.fixture
def local_data(tmp_path):
    shutil.copytree(DATA_DIR / '2026', tmp_path / '2026')
    return tmp_path


def trim_payload(root):
    catalog = Catalog.load(root, 2026)
    brand = catalog.brand_payload('chery')
    gen = next(g for m in brand['models'] for g in m['generations']
               if any(t['id'] == 'max_plus_bev' for t in g['trims']))
    raw = deepcopy(next(t for t in gen['trims'] if t['id'] == 'max_plus_bev'))
    return {'generation_id': GEN, 'trims': [raw]}


def quote(**overrides):
    row = dict(trim_id=TRIM, amount_thb=699000, price_type='LIST_PRICE',
               effective_from='2026-09-01', observed_at='2026-09-08',
               source='official_oem', source_ref='https://example.com/price-list')
    row.update(overrides)
    return row


def file_bytes(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()}


def test_product_query_separates_price_specs_and_source():
    master = ProductMaster.load()
    before = [r.as_row() for r in master.catalog.iter_resolved()]
    detail = master.detail(TRIM, as_of=date(2026, 9, 8))
    assert 'price_thb' not in detail['specs']
    assert detail['current_list_price']['amount_thb'] == 699000
    assert detail['ecosticker_evidence']['battery_supplier'].startswith('Hefei')
    assert detail['specs']['source_refs']['official_omodajaecoo'][0].startswith('https://')
    assert master.detail(TRIM, as_of=date(2026, 9, 7))['current_list_price'] is None
    ultra = master.detail(GEN + '.trim.ultra_bev', as_of=date(2026, 9, 8))
    assert ultra['current_list_price'] is None
    assert ultra['price_history'][0]['price_type'] == 'ESTIMATED_PRICE'
    assert master.validate() == []
    assert [r.as_row() for r in master.catalog.iter_resolved()] == before
    assert len(master.rows(model_id='chery.jaecoo_j5', powertrain='BEV')) == 4
    assert master.coverage()['legacy_embedded_prices'] == 0


def test_trim_authoring_dry_run_then_write_preserves_all_analytics(local_data):
    original = file_bytes(local_data)
    before = [r.as_row() for r in Catalog.load(local_data).iter_resolved()]
    payload = trim_payload(local_data)
    payload['trims'][0]['notes'] = 'Reviewed technical source; price remains separate.'
    assert import_trims(local_data, 2026, payload)['changed']
    assert file_bytes(local_data) == original
    assert import_trims(local_data, 2026, payload, write=True)['written']
    assert not import_trims(local_data, 2026, payload, write=True)['written']
    after = Catalog.load(local_data)
    assert [r.as_row() for r in after.iter_resolved()] == before
    assert len(after.trims) == 4
    changed = [p for p, contents in file_bytes(local_data).items() if contents != original[p]]
    assert changed == ['2026/models/chery.json']


def test_add_new_trim_requires_explicit_identity_and_preserves_siblings(local_data):
    payload = trim_payload(local_data)
    payload['trims'][0]['id'] = 'reference_test_bev'
    payload['trims'][0]['name'] = 'Reference test'
    before = len(Catalog.load(local_data).variants)
    import_trims(local_data, 2026, payload, write=True)
    catalog = Catalog.load(local_data)
    assert len(catalog.trims) == 5
    assert len(catalog.variants) == before
    assert TRIM in catalog.trims


@pytest.mark.parametrize('changes', [
    {'powertrain': 'PHEV'}, {'powertrain': 'UNKNOWN'}, {'price_thb': 100},
    {'length_mm': -10}, {'length_mm': '4380'}, {'battery_kwh': float('nan')},
    {'seats': True}, {'wheelbase_mm': 9000}, {'engine_cc': 1500},
    {'source_refs': {}}, {'source_refs': {'official': [' ']}}, {'typo_mm': 4},
])
def test_bad_trim_never_writes_partial_data(local_data, changes):
    before = file_bytes(local_data)
    payload = trim_payload(local_data)
    payload['trims'][0].update(changes)
    with pytest.raises((CatalogError, ValueError)):
        import_trims(local_data, 2026, payload, write=True)
    assert file_bytes(local_data) == before


def test_ecosticker_conflict_blocks_trim_update(local_data):
    payload = trim_payload(local_data)
    payload['trims'][0]['tire_front'] = '215/55 R18'
    with pytest.raises(CatalogError, match='ECO tyre'):
        import_trims(local_data, 2026, payload, write=True)


@pytest.mark.parametrize('amount', [True, 123.8, -1, 0, float('nan'), '1e5'])
def test_price_does_not_truncate_or_accept_invalid_amount(amount):
    ledger = PriceLedger()
    with pytest.raises(PricingError):
        ledger.add_payload({'prices': [quote(amount_thb=amount)]})
    assert ledger.records == []


def test_price_batch_is_atomic_and_deduplicates():
    ledger = PriceLedger()
    with pytest.raises(PricingError):
        ledger.add_payload({'prices': [quote(), quote(effective_from='20260902')]})
    assert ledger.records == []
    ledger.add_payload({'prices': [quote(), quote()]})
    ledger.add_payload({'prices': [quote()]})
    assert len(ledger.records) == 1


def test_conflicting_same_date_prices_are_not_resolved_by_highest_amount():
    ledger = PriceLedger()
    ledger.add_payload({'prices': [quote(), quote(amount_thb=999000)]})
    assert ledger.validate()
    with pytest.raises(PricingError, match='conflicting LIST_PRICE'):
        ledger.current_list_price(TRIM, as_of=date(2026, 9, 8))


def test_expired_new_list_does_not_resurrect_superseded_price():
    ledger = PriceLedger()
    ledger.add_payload({'prices': [quote(effective_from='2026-01-01'),
        quote(amount_thb=649000, effective_from='2026-06-01', effective_to='2026-06-30')]})
    assert ledger.current_list_amount(TRIM, as_of=date(2026, 6, 15)) == 649000
    assert ledger.current_list_amount(TRIM, as_of=date(2026, 7, 1)) is None
    assert ledger.coverage(as_of=date(2026, 7, 1))['trims_with_current_list_price'] == 0


def test_price_append_dry_run_repeat_and_bad_batch(local_data):
    before = file_bytes(local_data)
    row = quote(price_type='CAMPAIGN_PRICE', amount_thb=599000, effective_to='2026-09-30')
    assert append_prices(local_data, 2026, {'prices': [row]})['added'] == 1
    assert file_bytes(local_data) == before
    assert append_prices(local_data, 2026, {'prices': [row]}, write=True)['written']
    assert append_prices(local_data, 2026, {'prices': [row]}, write=True)['added'] == 0
    after = file_bytes(local_data)
    with pytest.raises(CatalogError):
        append_prices(local_data, 2026, {'prices': [quote(source_ref='')]}, write=True)
    assert file_bytes(local_data) == after
    assert ProductMaster.load(local_data).detail(TRIM)['current_list_price']['amount_thb'] == 699000


def test_product_writer_lock_refuses_concurrent_write(local_data):
    lock = local_data / '2026/.product-write.lock'
    lock.touch()
    with pytest.raises(CatalogError, match='another product writer'):
        append_prices(local_data, 2026, {'prices': [quote()]}, write=True)
    assert lock.exists()


def test_cli_product_read_does_not_create_database(tmp_path, capsys):
    db = tmp_path / 'must-not-exist.sqlite3'
    assert main(['--db', str(db), 'market', 'show', TRIM, '--as-of', '2026-09-08']) == 0
    assert json.loads(capsys.readouterr().out)['current_list_price']['amount_thb'] == 699000
    assert not db.exists()
    assert main(['market', 'show', 'missing']) == 2
    assert 'unknown trim_id' in capsys.readouterr().err
