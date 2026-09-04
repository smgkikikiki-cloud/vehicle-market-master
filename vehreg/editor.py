"""A local editor for the judgement calls the catalog cannot make for you.

Most of what this warehouse claims about a car - which segment it sits in,
whether it belongs in the numbers at all, what it costs - is an opinion that
was seeded from one person's memory and is very likely wrong in places. The
only fix is for the owner to look at each row and decide, so this module's job
is to put the evidence in front of them: what the classification currently
says, how much volume rides on it, and which raw DLT labels feed it.

Two surfaces, same rules underneath:

* ``vehreg catalog export --with-volume`` for bulk work in a spreadsheet, now
  sorted by the units at stake rather than alphabetically.
* ``vehreg edit`` for a local web page - stdlib http.server, no pip, no network
  - where one row can be judged and saved at a time.

Every write goes through the same validation the CSV importer uses and is
refused whole if it would break a cross-facet rule, and every change is
appended to a decision log so a classification can be traced to who decided it
and why.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from .catalog import DATA_DIR, DEFAULT_YEAR, Catalog, CatalogError, year_dir
from .taxonomy import (
    BodyType, BrandSegment, CabType, Drivetrain, ImportType, MarketScope,
    Powertrain, RegistrationType, Segment,
)

#: Fields the owner may change, and the vocabulary each one accepts.
MODEL_FIELDS: dict[str, Optional[type]] = {
    "nameplate": None,
    "body_type": BodyType,
    "cab_type": CabType,
    "registration_type": RegistrationType,
    "market_scope": MarketScope,
    "name_th": None,
    "notes": None,
}
GENERATION_FIELDS: dict[str, Optional[type]] = {
    "segment": Segment,
    "seats": int,
    "launched": None,
    "ended": None,
}
VARIANT_FIELDS: dict[str, Optional[type]] = {
    "powertrain": Powertrain,
    "drivetrain": Drivetrain,
    "engine_cc": int,
    "battery_kwh": float,
    "price_thb": float,
    "price_min_thb": float,
    "price_max_thb": float,
    "price_note": None,
}
BRAND_FIELDS: dict[str, Optional[type]] = {
    "brand_segment": BrandSegment,
    "oem_group": None,
    "brand_origin": None,
    "trim_detail": bool,
}


def decisions_path(data_dir: Path | str, year: int) -> Path:
    """The log lives beside the year it describes, so it travels with the
    catalog and diffs next to it in Git."""
    return Path(data_dir) / str(year) / "decisions.jsonl"


def _coerce(value: Any, kind: Optional[type]) -> Any:
    text = "" if value is None else str(value).strip()
    if kind is None:
        return text
    if text == "":
        return None
    if kind is bool:
        return text.lower() in {"1", "true", "yes", "y", "t"}
    if kind in (int, float):
        cleaned = text.replace(",", "")
        return int(float(cleaned)) if kind is int else float(cleaned)
    return kind.parse(text).value          # a facet vocabulary


def edit_catalog(data_dir: Path | str, year: int,
                 mutate: Callable[[dict[str, dict]], list[str]],
                 ) -> tuple[bool, list[str], list[str]]:
    """Apply ``mutate`` to the year's payloads, validate, then write or refuse.

    Returns ``(ok, problems, files_written)``. Nothing reaches disk unless the
    whole catalog still validates, so a bad edit cannot leave the year in a
    state the loader will not read.
    """
    models_dir = year_dir(data_dir, year)
    payloads: dict[str, dict] = {}
    for path in sorted(models_dir.glob("*.json")):
        payloads[json.loads(path.read_text(encoding="utf-8"))["brand"]["id"]] = \
            json.loads(path.read_text(encoding="utf-8"))
    if not payloads:
        raise CatalogError(f"no catalog for {year} at {models_dir}")

    before = {bid: json.dumps(p, sort_keys=True) for bid, p in payloads.items()}
    baseline = set(Catalog.load(data_dir, year).validate())

    problems = list(mutate(payloads))

    probe = Catalog(year)
    for bid, payload in payloads.items():
        probe.add_brand_payload(payload, source=f"<edit {bid}>")
    probe.build_indexes()
    problems += [p for p in probe.validate() if p not in baseline]
    if problems:
        return False, problems, []

    written = []
    for bid, payload in payloads.items():
        if before.get(bid) == json.dumps(payload, sort_keys=True):
            continue
        target = models_dir / f"{bid}.json"
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2)
                          + "\n", encoding="utf-8")
        written.append(str(target))
    return True, [], written


def _find_model(payloads: dict[str, dict], model_id: str) -> tuple[dict, dict]:
    brand_id, _, rest = model_id.partition(".")
    payload = payloads.get(brand_id)
    if payload is None:
        raise CatalogError(f"unknown brand in {model_id!r}")
    for model in payload["models"]:
        if model["id"] == rest:
            return payload, model
    raise CatalogError(f"unknown model {model_id!r}")


def log_decision(data_dir: Path | str, year: int, entry: dict) -> None:
    """Append one judgement to the year's decision log, newest last."""
    path = decisions_path(data_dir, year)
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = dict(entry)
    entry["at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")


def apply_edit(data_dir: Path | str, year: int, target: str, target_id: str,
               changes: dict[str, Any], reason: str = ""
               ) -> tuple[bool, list[str], list[str]]:
    """Change one brand, model, generation or variant and record why."""
    specs = {"brand": BRAND_FIELDS, "model": MODEL_FIELDS,
             "generation": GENERATION_FIELDS, "variant": VARIANT_FIELDS}
    if target not in specs:
        raise CatalogError(f"target must be one of {sorted(specs)}")
    allowed = specs[target]
    unknown = [k for k in changes if k not in allowed]
    if unknown:
        raise CatalogError(f"cannot edit {', '.join(unknown)} on a {target}")

    old: dict[str, Any] = {}

    def mutate(payloads: dict[str, dict]) -> list[str]:
        if target == "brand":
            payload = payloads.get(target_id)
            if payload is None:
                return [f"unknown brand {target_id!r}"]
            node = payload["brand"]
        else:
            model_id = target_id if target == "model" else \
                ".".join(target_id.split(".")[:2])
            _, model = _find_model(payloads, model_id)
            if target == "model":
                node = model
            else:
                gen_slug = target_id.split(".")[2]
                gens = [g for g in model["generations"]
                        if _slugish(g.get("code", "")) == gen_slug]
                if not gens:
                    return [f"unknown generation in {target_id!r}"]
                if target == "generation":
                    node = gens[0]
                else:
                    trim_slug = ".".join(target_id.split(".")[3:])
                    hits = [v for v in gens[0]["variants"]
                            if _slugish(v["name"]) == trim_slug]
                    if not hits:
                        return [f"unknown variant {target_id!r}"]
                    node = hits[0]
        for key, raw in changes.items():
            old[key] = node.get(key)
            node[key] = _coerce(raw, allowed[key])
        return []

    ok, problems, written = edit_catalog(data_dir, year, mutate)
    if ok:
        log_decision(data_dir, year, {
            "target": target, "id": target_id, "changes": changes,
            "previous": old, "reason": reason,
        })
    return ok, problems, written


def _slugish(text: str) -> str:
    from .normalize import slug
    return slug(text)


# --------------------------------------------------------------------------
# Read side: the evidence a judgement needs
# --------------------------------------------------------------------------
def model_rows(catalog: Catalog, conn: Optional[sqlite3.Connection] = None
               ) -> list[dict[str, Any]]:
    """Every model with its classification and the volume riding on it."""
    units: dict[str, float] = {}
    if conn is not None:
        for row in conn.execute(
            "SELECT unit_id, SUM(units) u FROM fact_registration "
            "WHERE CAST(substr(period, 1, 4) AS INTEGER) = ? AND grain = 'MODEL' "
            "GROUP BY unit_id", (catalog.year,)
        ):
            units[row["unit_id"]] = row["u"]

    rows: list[dict[str, Any]] = []
    for model in catalog.models.values():
        brand = catalog.brands[model.brand_id]
        gens = catalog.generations_of(model.id)
        variants = catalog.variants_of(model.id)
        prices = [v.price_thb for v in variants if v.price_thb]
        unverified = sum(1 for v in variants
                         if v.price_thb is None
                         or "unverified" in (v.price_note or ""))
        rows.append({
            "model_id": model.id,
            "brand_id": brand.id,
            "brand": brand.name_en,
            "brand_segment": brand.brand_segment.value,
            "trim_detail": brand.trim_detail,
            "nameplate": model.nameplate or model.name_en,
            "model": model.name_en,
            "name_th": model.name_th,
            "body_type": model.body_type.value,
            "cab_type": model.cab_type.value,
            "registration_type": model.registration_type.value,
            "market_scope": model.market_scope.value,
            "segment": ", ".join(sorted({g.segment.value for g in gens})) or "-",
            "seats": gens[0].seats if gens else None,
            "generation_id": f"{model.id}.{_slugish(gens[0].code)}" if gens else "",
            "powertrain": ", ".join(sorted({v.powertrain.value for v in variants}))
                          or "-",
            "spec_lines": len(variants),
            "price_min": min(prices) if prices else None,
            "price_max": max(prices) if prices else None,
            "unverified": unverified,
            "units": units.get(model.id, 0.0),
            "notes": model.notes,
        })
    rows.sort(key=lambda r: -r["units"])
    return rows


def model_detail(catalog: Catalog, conn: Optional[sqlite3.Connection],
                 model_id: str) -> dict[str, Any]:
    """Spec lines plus the raw DLT labels that actually landed on this model."""
    model = catalog.models[model_id]
    lines = []
    for gen in catalog.generations_of(model_id):
        for variant in catalog.variants.values():
            if variant.generation_id != gen.id:
                continue
            lines.append({
                "variant_id": variant.id,
                "generation_id": gen.id,
                "generation": gen.code,
                "name": variant.name,
                "powertrain": variant.powertrain.value,
                "drivetrain": variant.drivetrain.value,
                "engine_cc": variant.engine_cc,
                "battery_kwh": variant.battery_kwh,
                "price_thb": variant.price_thb,
                "price_min_thb": variant.price_min_thb,
                "price_max_thb": variant.price_max_thb,
                "price_note": variant.price_note,
                "import_type": variant.import_type.value,
                "origin_country": variant.origin_country,
                "aliases": list(variant.aliases),
            })

    labels: list[dict[str, Any]] = []
    if conn is not None:
        variant_ids = [v.id for v in catalog.variants_of(model_id)]
        placeholders = ",".join("?" for _ in ([model_id] + variant_ids))
        labels = [dict(r) for r in conn.execute(
            f"SELECT raw_label, registration_type, SUM(units) units, "
            f"COUNT(DISTINCT period) months FROM fact_registration "
            f"WHERE unit_id IN ({placeholders}) "
            f"AND CAST(substr(period, 1, 4) AS INTEGER) = ? "
            f"GROUP BY raw_label, registration_type ORDER BY units DESC LIMIT 25",
            [model_id, *variant_ids, catalog.year])]

    gens = catalog.generations_of(model_id)
    return {
        "model_id": model_id,
        "model": model.name_en,
        "generations": [{"generation_id": f"{model_id}.{_slugish(g.code)}",
                         "code": g.code, "segment": g.segment.value,
                         "seats": g.seats, "launched": g.launched,
                         "ended": g.ended} for g in gens],
        "spec_lines": lines,
        "labels": labels,
        "aliases": list(model.aliases),
    }


def review_rows(conn: sqlite3.Connection, year: int, limit: int = 200
                ) -> list[dict[str, Any]]:
    return [dict(r) for r in conn.execute(
        "SELECT raw_label, raw_brand, reason, SUM(units) units, "
        "COUNT(DISTINCT period) months FROM ingest_review "
        "WHERE status = 'open' AND CAST(substr(period, 1, 4) AS INTEGER) = ? "
        "GROUP BY raw_label, reason ORDER BY units DESC LIMIT ?", (year, limit))]


def vocabularies() -> dict[str, list[str]]:
    return {
        "body_type": [m.value for m in BodyType],
        "cab_type": [m.value for m in CabType],
        "registration_type": [m.value for m in RegistrationType],
        "market_scope": [m.value for m in MarketScope],
        "segment": [m.value for m in Segment],
        "powertrain": [m.value for m in Powertrain],
        "drivetrain": [m.value for m in Drivetrain],
        "import_type": [m.value for m in ImportType],
        "brand_segment": [m.value for m in BrandSegment],
    }


# --------------------------------------------------------------------------
# The local page. stdlib http.server, bound to localhost, no network calls.
# --------------------------------------------------------------------------
class _State:
    def __init__(self, data_dir: Path, year: int, db: Path) -> None:
        self.data_dir = data_dir
        self.year = year
        self.db = db
        self._catalog: Optional[Catalog] = None

    @property
    def catalog(self) -> Catalog:
        if self._catalog is None:
            self._catalog = Catalog.load(self.data_dir, self.year)
        return self._catalog

    def invalidate(self) -> None:
        self._catalog = None

    def connect(self) -> Optional[sqlite3.Connection]:
        if not Path(self.db).exists():
            return None
        conn = sqlite3.connect(str(self.db))
        conn.row_factory = sqlite3.Row
        return conn


def _handler(state: _State):
    from http.server import BaseHTTPRequestHandler
    from urllib.parse import parse_qs, urlparse

    page = Path(__file__).with_name("editor.html")

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):        # keep the terminal readable
            pass

        def _send(self, payload: Any, status: int = 200,
                  content_type: str = "application/json") -> None:
            body = (payload if isinstance(payload, bytes)
                    else json.dumps(payload, ensure_ascii=False,
                                    default=str).encode("utf-8"))
            self.send_response(status)
            self.send_header("Content-Type", f"{content_type}; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:                     # noqa: N802
            route = urlparse(self.path)
            query = parse_qs(route.query)
            try:
                if route.path in ("/", "/index.html"):
                    return self._send(page.read_bytes(), content_type="text/html")
                if route.path == "/api/state":
                    from .catalog import available_years
                    conn = state.connect()
                    counts = {}
                    if conn:
                        counts = dict(conn.execute(
                            "SELECT COUNT(*), COALESCE(SUM(units), 0) "
                            "FROM fact_registration WHERE "
                            "CAST(substr(period,1,4) AS INTEGER) = ?",
                            (state.year,)).fetchone())
                    return self._send({
                        "year": state.year,
                        "years": available_years(state.data_dir),
                        "vocab": vocabularies(),
                        "models": len(state.catalog.models),
                        "has_warehouse": conn is not None,
                        "counts": counts,
                    })
                if route.path == "/api/models":
                    conn = state.connect()
                    return self._send(model_rows(state.catalog, conn))
                if route.path == "/api/model":
                    conn = state.connect()
                    return self._send(model_detail(state.catalog, conn,
                                                   query["id"][0]))
                if route.path == "/api/review":
                    conn = state.connect()
                    if conn is None:
                        return self._send([])
                    return self._send(review_rows(conn, state.year))
                return self._send({"error": "not found"}, 404)
            except (CatalogError, KeyError, ValueError) as exc:
                return self._send({"error": str(exc)}, 400)

        def do_POST(self) -> None:                    # noqa: N802
            route = urlparse(self.path)
            length = int(self.headers.get("Content-Length", 0))
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError:
                return self._send({"error": "bad json"}, 400)
            try:
                if route.path == "/api/year":
                    state.year = int(body["year"])
                    state.invalidate()
                    return self._send({"ok": True, "year": state.year})
                if route.path == "/api/edit":
                    ok, problems, written = apply_edit(
                        state.data_dir, state.year, body["target"], body["id"],
                        body.get("changes", {}), body.get("reason", ""))
                    if ok:
                        state.invalidate()
                    return self._send({"ok": ok, "problems": problems,
                                       "written": written})
                if route.path == "/api/teach":
                    conn = state.connect()
                    if conn is None:
                        return self._send({"error": "no warehouse yet"}, 400)
                    from .ingest import teach_alias
                    teach_alias(conn, body.get("scope", "model"), body["raw"],
                                body["target_id"], body.get("reg", "*"))
                    log_decision(state.data_dir, state.year, {
                        "target": "alias", "id": body["target_id"],
                        "changes": {"raw": body["raw"],
                                    "reg": body.get("reg", "*")},
                        "previous": None, "reason": body.get("reason", "")})
                    return self._send({"ok": True})
                if route.path == "/api/rebuild":
                    conn = state.connect()
                    if conn is None:
                        return self._send({"error": "no warehouse yet"}, 400)
                    from .db import rebuild_dimension
                    rows = rebuild_dimension(conn, state.catalog)
                    return self._send({"ok": True, "dimension_rows": rows})
                return self._send({"error": "not found"}, 404)
            except (CatalogError, KeyError, ValueError) as exc:
                return self._send({"error": str(exc)}, 400)

    return Handler


def serve(data_dir: Path | str = DATA_DIR, year: int = DEFAULT_YEAR,
          db: Path | str = "data/vehreg.sqlite3", host: str = "127.0.0.1",
          port: int = 8765) -> None:
    from http.server import ThreadingHTTPServer

    state = _State(Path(data_dir), year, Path(db))
    state.catalog                                   # fail early on a bad catalog
    server = ThreadingHTTPServer((host, port), _handler(state))
    print(f"vehreg editor: http://{host}:{port}   (catalog {year}, Ctrl-C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        server.server_close()
