"""One nameplate, one home.

Volume lands on whichever entry DLT's brand column resolves to, so a nameplate
duplicated under its parent group silently splits a model in two: one copy
carries every registration, the other carries the product data and reads as a
zero-volume car.  That is how Phase 1's JAECOO 5 work ended up attached to
``chery.jaecoo_j5`` while all 21,670 units sat on ``jaecoo.jaecoo_5_ev``.

These checks run against the real committed catalogs, every year.
"""

import collections
import json
import unittest

from vehreg.catalog import Catalog, DATA_DIR, year_dir

YEARS = range(2021, 2027)


def _brand_payloads(year):
    for path in sorted((year_dir(DATA_DIR, year) / "models").glob("*.json")):
        yield path, json.loads(path.read_text(encoding="utf-8"))


class ShadowNameplateTests(unittest.TestCase):

    def test_no_nameplate_name_is_claimed_by_two_brands(self):
        for year in YEARS:
            owners = collections.defaultdict(list)
            for _, payload in _brand_payloads(year):
                brand_id = payload["brand"]["id"]
                for model in payload["models"]:
                    owners[model["name_en"].strip().lower()].append(
                        f"{brand_id}.{model['id']}")
            duplicates = {name: sorted(ids)
                          for name, ids in owners.items() if len(ids) > 1}
            self.assertEqual({}, duplicates, f"{year}: duplicate nameplates")

    def test_no_brand_alias_names_another_brand_that_has_its_own_file(self):
        for year in YEARS:
            payloads = dict(
                (payload["brand"]["id"], payload)
                for _, payload in _brand_payloads(year))
            own_names = {}
            for brand_id, payload in payloads.items():
                own_names[brand_id.replace("_", " ")] = brand_id
                own_names[payload["brand"]["name_en"].strip().lower()] = brand_id
            for brand_id, payload in payloads.items():
                for alias in payload["brand"].get("aliases") or []:
                    owner = own_names.get(alias.strip().lower())
                    self.assertIn(
                        owner, (None, brand_id),
                        f"{year}: {brand_id} claims alias {alias!r}, "
                        f"but {owner} is a brand of its own")

    def test_no_model_alias_is_ambiguous_across_two_brands(self):
        """Same-brand ambiguity is a grain split the review queue settles.

        Cross-brand ambiguity is a duplicated nameplate, and it costs volume:
        the label never reaches a fact table at all.
        """
        for year in YEARS:
            catalog = Catalog.load(year=year)
            catalog.build_indexes()
            index = catalog.model_index
            for model_id, model in catalog.models.items():
                for alias in list(model.aliases) + [model.name_en]:
                    resolved, _, _ = index.lookup(alias)
                    if resolved is not None:
                        self.assertEqual(
                            model_id, resolved,
                            f"{year}: alias {alias!r} of {model_id} resolves "
                            f"to {resolved!r}")
                        continue
                    brands = {candidate.split(".")[0]
                              for candidate in index.ambiguous_candidates(alias)}
                    self.assertLessEqual(
                        len(brands), 1,
                        f"{year}: alias {alias!r} of {model_id} is ambiguous "
                        f"across brands {sorted(brands)}")

if __name__ == "__main__":
    unittest.main()
