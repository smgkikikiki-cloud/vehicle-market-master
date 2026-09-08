"""The harvester, exercised offline against a stubbed transport.

Phase 2's snapshot used to be an opaque file with no way to reproduce it. These
tests pin the two things that make it reproducible: the request shape the ECO
service actually accepts, and byte-identical output for identical input.
"""

import gzip
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools import ecosticker_fetch as fetch
from vehreg.ecosticker_ingest import load_raw_inventory


def _uuid(n):
    return f"{n:08d}-0000-4000-8000-000000000000"


def _list_page(page, total_pages, ids):
    return {"data": {"info": {"current_page": page, "total_pages": total_pages,
                              "total_rows": total_pages * len(ids)},
                     "car_list": [{"id": i, "brand": "JAECOO", "model": "5 EV MAX+",
                                   "recomend_retail_price": 699000,
                                   "company_name": "OMODA & JAECOO (THAILAND)"}
                                  for i in ids]}}


class HarvestTests(unittest.TestCase):

    def setUp(self):
        self.ids = [_uuid(n) for n in range(1, 7)]
        self.calls = []

    def _transport(self, url, *, payload=None, **_):
        self.calls.append((url, payload))
        if payload is None:
            page = int(url.rsplit("page=", 1)[1])
            start = (page - 1) * 3
            return _list_page(page, 2, self.ids[start:start + 3])
        return {"data": [{"id": i, "wheel_size": "235/55R18", "car_length": "4380",
                          "engine_name": "", "cartype_name": "BEV",
                          "logo_link": "https://signed.example/x"}
                         for i in payload["id"]]}

    def test_harvest_writes_a_snapshot_the_ingester_accepts(self):
        with mock.patch.object(fetch, "_request", self._transport):
            with mock.patch.object(fetch.time, "sleep"):
                out = Path(self.enterContext(
                    __import__("tempfile").TemporaryDirectory())) / "raw.jsonl.gz"
                summary = fetch.harvest(out=out, cache_dir=None, delay=0,
                                        limit=None, want_detail=True)
        self.assertEqual({"records": 6, "records_with_detail": 6,
                          "output": str(out)}, summary)
        rows = load_raw_inventory(out)
        self.assertEqual(6, len(rows))
        self.assertEqual("235/55R18", rows[0]["detail"]["wheel_size"])
        # Signed image URLs churn between runs and are not evidence.
        self.assertNotIn("logo_link", rows[0]["detail"])

    def test_detail_batches_never_break_the_two_to_four_id_window(self):
        with mock.patch.object(fetch, "_request", self._transport):
            with mock.patch.object(fetch.time, "sleep"):
                fetch.fetch_details(self.ids, cache_dir=None, delay=0)
        posts = [payload["id"] for url, payload in self.calls if payload]
        self.assertTrue(posts)
        for batch in posts:
            self.assertTrue(fetch.COMPARE_MIN <= len(batch) <= fetch.COMPARE_MAX,
                            f"batch of {len(batch)} ids")

    def test_a_single_leftover_id_is_padded_rather_than_dropped(self):
        ids = [_uuid(n) for n in range(1, 6)]  # 4 + 1
        with mock.patch.object(fetch, "_request", self._transport):
            with mock.patch.object(fetch.time, "sleep"):
                details = fetch.fetch_details(ids, cache_dir=None, delay=0)
        self.assertEqual(set(ids), set(details))

    def test_identical_input_produces_identical_bytes(self):
        rows = [{"source_id": _uuid(1), "brand_raw": "A", "detail": {"b": 1}}]
        directory = Path(self.enterContext(
            __import__("tempfile").TemporaryDirectory()))
        first, second = directory / "a.gz", directory / "b.gz"
        fetch.write_raw(rows, first)
        fetch.write_raw(rows, second)
        self.assertEqual(first.read_bytes(), second.read_bytes())
        self.assertEqual(rows, [json.loads(line) for line
                                in gzip.decompress(first.read_bytes()).splitlines()])


if __name__ == "__main__":
    unittest.main()
