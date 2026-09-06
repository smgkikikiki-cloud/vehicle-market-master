"""The 2026 models added as stubs, and the shape a stub has to keep.

These exist because the failure they guard against is silent: an alias removed
or an id renamed does not break anything, it just quietly sends a few thousand
registrations a month back to the review queue and drops the model out of every
ranking.
"""

from __future__ import annotations

import pytest

from vehreg.catalog import DATA_DIR, Catalog
from vehreg.ingest import Resolver
from vehreg.db import connect, rebuild_dimension

#: raw DLT label -> the model id it must reach. Every one of these was sitting
#: in review before the stub was added.
LABELS = {
    ("BYD", "BYD ATTO 2 PREMIUM"): "atto2",
    ("BYD", "BYD ATTO 1 PREMIUM"): "atto1",
    ("BYD", "BYD SEALION5 DM-i PREMIUM"): "sealion5",
    ("MG", "MG URBAN"): "mg_urban",
    ("MG", "MG IM5"): "mg_im5",
    ("CHANGAN", "CHANGAN NEVO Q05"): "nevo_q05",
    ("WULING", "WULING DARION EV"): "wuling_darion",
    ("WULING", "WULING PORTA EV"): "wuling_porta",
    ("GWM", "WEY G9 PLUG-IN HYBRID"): "wey_g9",
    ("AVATR", "AVATR 07 MAX"): "avatr_07",
    ("KIA", "PV5 CARGO"): "kia_pv5",
    ("MERCEDES BENZ", "CLA 250+ electric"): "cla",
    ("MINI", "JCW E"): "jcw_e",
    ("CHERY", "TIGGO8 PHEV 4WD ELITE"): "tiggo8",
    ("HONDA", "e:N2"): "en2",
}

STUB_IDS = sorted(set(LABELS.values()))


@pytest.fixture(scope="module")
def catalog():
    cat = Catalog.load(DATA_DIR, 2026)
    cat.build_indexes()
    return cat


class TestTheStubsExist:
    @pytest.mark.parametrize("model_id", STUB_IDS)
    def test_the_model_is_in_the_2026_catalog(self, catalog, model_id):
        # Catalog keys are "<brand>.<model>".
        assert any(key.split(".", 1)[1] == model_id for key in catalog.models)


@pytest.fixture(scope="module")
def resolver(tmp_path_factory):
    cat = Catalog.load(DATA_DIR, 2026)
    cat.build_indexes()
    conn = connect(tmp_path_factory.mktemp("db") / "db.sqlite3")
    rebuild_dimension(conn, cat)
    return Resolver(cat, conn)


class TestTheLabelsStillReach:

    @pytest.mark.parametrize("label,model_id", sorted(LABELS.items()))
    def test_a_real_dlt_label_resolves_to_its_model(self, resolver, label, model_id):
        brand, model = label
        unit_id, grain, _how, _score, problem = resolver.resolve(brand, model)
        assert problem == "", f"{brand} {model} -> {problem}"
        assert grain.value in {"MODEL", "VARIANT"}, f"{brand} {model} -> {grain}"
        assert model_id in unit_id, f"{brand} {model} -> {unit_id}"


class TestAStubStaysHonest:
    """A stub says what DLT said and nothing else. If someone fills a price in,
    they must drop the marker with it."""

    @pytest.mark.parametrize("model_id", STUB_IDS)
    def test_no_price_is_claimed_without_dropping_the_marker(self, catalog, model_id):
        for variant in catalog.variants.values():
            if variant.id.split(".")[1] != model_id:
                continue
            if variant.price_thb is not None:
                assert variant.price_note != "not-researched", (
                    f"{model_id} has a price but is still marked not-researched")

    @pytest.mark.parametrize("model_id", STUB_IDS)
    def test_a_stub_carries_at_least_one_alias(self, catalog, model_id):
        # The alias is the whole mechanism: without it the DLT label finds
        # nothing and the volume goes straight back to review.
        model = next(m for key, m in catalog.models.items()
                     if key.split(".", 1)[1] == model_id)
        assert model.aliases, f"{model_id} has no alias to match a DLT label on"


class TestDeclaredIncompleteness:
    """"The catalog is complete" has to keep meaning something."""

    def test_every_year_validates_clean(self):
        from vehreg.catalog import available_years

        for year in available_years(DATA_DIR):
            cat = Catalog.load(DATA_DIR, year)
            cat.build_indexes()
            assert cat.validate() == [], f"{year} has unexplained problems"

    def test_the_stubs_are_reported_as_holes_rather_than_hidden(self, catalog):
        reported = catalog.incomplete_models()
        assert len(reported) == len(STUB_IDS)
        for model_id in STUB_IDS:
            assert any(model_id in line for line in reported), model_id

    def test_each_hole_names_what_is_missing(self, catalog):
        # A stub with nothing missing is a stub someone finished and forgot to
        # unmark; the report says so rather than staying silent.
        for line in catalog.incomplete_models():
            assert "incomplete (" in line, line

    def test_a_finished_model_is_not_marked_incomplete(self, catalog):
        finished = next(m for k, m in catalog.models.items()
                        if k.split(".", 1)[1] == "atto3")
        assert finished.incomplete is False

    def test_the_marker_survives_a_save_round_trip(self, catalog):
        payload = catalog.brand_payload("byd")
        stub = next(m for m in payload["models"] if m["id"] == "atto2")
        assert stub.get("incomplete") is True

        rebuilt = Catalog(catalog.year)
        rebuilt.add_brand_payload(payload)
        rebuilt.build_indexes()
        assert rebuilt.models["byd.atto2"].incomplete is True
        assert rebuilt.validate() == []
