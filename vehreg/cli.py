"""Command line for the registration warehouse.

    python -m vehreg init
    python -m vehreg ingest data/raw/dlt_2023_2025.csv --wide
    python -m vehreg cube --by segment,powertrain --from 2023-01 --to 2025-12
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any, Optional

from . import allocate as allocate_mod, authoring, cube as cube_mod
from . import dlt as dlt_mod, editor as editor_mod, trimledger
from .catalog import (
    DATA_DIR, DEFAULT_YEAR, Catalog, CatalogError, available_years, fork_year,
)
from .db import connect, loaded_years, rebuild_dimension, unmatched_summary
from . import normalize
from .ingest import ColumnMap, ingest_csv, teach_alias
from .taxonomy import (
    BodyType, BrandSegment, CabType, Drivetrain, ImportType, MarketPosition,
    Powertrain, PowertrainGroup, RegistrationType, Segment, THAI_LABELS,
    PRICE_BAND_EDGES,
)

DEFAULT_DB = Path("data/vehreg.sqlite3")


def _catalog(args) -> Catalog:
    return Catalog.load(args.data_dir, args.year)


def _conn(args):
    Path(args.db).parent.mkdir(parents=True, exist_ok=True)
    return connect(args.db)


def _parse_filters(raw: list[str]) -> dict[str, Any]:
    filters: dict[str, Any] = {}
    for item in raw or []:
        if "=" not in item:
            raise SystemExit(f"--filter expects key=value, got {item!r}")
        key, _, value = item.partition("=")
        values = [v for v in value.split(",") if v]
        filters[key.strip()] = values if len(values) > 1 else (
            values[0] if values else "")
    return filters


def _write_csv(path: str, fieldnames: list[str], rows: list[dict]) -> None:
    with open(path, "w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames,
                                extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


# --------------------------------------------------------------------- verbs
def cmd_facets(args) -> int:
    groups = [
        ("Segment", Segment), ("BodyType", BodyType), ("CabType", CabType),
        ("MarketPosition", MarketPosition), ("Powertrain", Powertrain),
        ("PowertrainGroup", PowertrainGroup), ("ImportType", ImportType),
        ("BrandSegment", BrandSegment), ("Drivetrain", Drivetrain),
        ("RegistrationType", RegistrationType),
    ]
    for name, enum_cls in groups:
        print(f"\n{name}")
        for member in enum_cls:
            print(f"  {member.value:<16} {THAI_LABELS[name].get(member.value, '')}")
    print("\nPrice bands (THB, upper bound exclusive)")
    previous = 0
    for edge, band in PRICE_BAND_EDGES:
        print(f"  {band.value:<16} {previous:>10,} - {edge - 1:>10,}")
        previous = edge
    print(f"  LUXURY           {previous:>10,} +")
    return 0


def cmd_init(args) -> int:
    catalog = _catalog(args)
    problems = catalog.validate()
    if problems and not args.force:
        print(f"catalog has {len(problems)} problems; fix them or pass --force")
        for problem in problems[:20]:
            print(f"  - {problem}")
        return 1
    conn = _conn(args)
    rows = rebuild_dimension(conn, catalog)
    print(f"catalog: {catalog.coverage()}")
    print(f"dimension rows: {rows}")
    print(f"database: {args.db}")
    return 0


def cmd_catalog(args) -> int:
    if args.catalog_cmd == "template":
        print(f"wrote {authoring.template(args.path)}")
        return 0
    if args.catalog_cmd == "years":
        years = available_years(args.data_dir)
        print("catalog years on disk: "
              + (", ".join(map(str, years)) if years else "none"))
        return 0
    if args.catalog_cmd == "fork":
        target = fork_year(args.data_dir, args.year, args.to,
                           overwrite=args.overwrite)
        print(f"copied {args.year} -> {args.to} at {target}")
        print(f"edit it, then: python -m vehreg --year {args.to} init")
        return 0
    if args.catalog_cmd == "import":
        applied, problems, written = authoring.import_csv(
            args.path, args.data_dir, year=args.year, dry_run=args.dry_run)
        print(f"rows applied: {applied}")
        for problem in problems[:40]:
            print(f"  - {problem}")
        if len(problems) > 40:
            print(f"  ... {len(problems) - 40} more")
        if args.dry_run:
            print("dry run: nothing written")
        elif problems:
            print("nothing written: fix the problems above first")
        else:
            for path in written:
                print(f"wrote {path}")
        return 1 if problems else 0

    catalog = _catalog(args)
    if args.catalog_cmd == "stats":
        for key, value in catalog.coverage().items():
            print(f"{key:<12} {value}")
        return 0
    if args.catalog_cmd == "validate":
        problems = catalog.validate()
        for problem in problems:
            print(f"  - {problem}")
        print(f"{len(problems)} problems")
        return 1 if problems else 0
    if args.catalog_cmd == "audit":
        unverified = [
            v for v in catalog.variants.values()
            if v.price_thb is None or "unverified" in (v.price_note or "")
        ]
        for variant in unverified[:args.limit]:
            print(f"  {variant.id} price={variant.price_thb} "
                  f"({variant.price_note or 'no note'})")
        print(f"{len(unverified)} variants in {catalog.year} still need an "
              "owner-confirmed price")
        return 0
    if args.catalog_cmd == "export":
        volumes = None
        if getattr(args, "with_volume", False):
            conn = _conn(args)
            volumes = {r["unit_id"]: r["units"] for r in conn.execute(
                "SELECT unit_id, SUM(units) units FROM fact_registration "
                "WHERE CAST(substr(period, 1, 4) AS INTEGER) = ? "
                "AND grain = 'MODEL' GROUP BY unit_id", (catalog.year,))}
        count = authoring.export_csv(catalog, args.path, volumes)
        print(f"wrote {count} rows to {args.path}"
              + (" (sorted by units)" if volumes else ""))
        return 0
    if args.catalog_cmd == "nameplate":
        plates = catalog.nameplates()
        query = (args.query or "").lower()
        hits = {k: v for k, v in plates.items() if query in k.lower()}
        if not hits:
            print(f"no nameplate matches {args.query!r}")
            return 1
        for plate, model_ids in list(hits.items())[:args.limit]:
            print(f"\n{plate}")
            for model_id in model_ids:
                model = catalog.models[model_id]
                scope = "" if model.market_scope.value == "CORE" \
                    else f"  [{model.market_scope.value}]"
                print(f"  {model.name_en}  ({model.body_type.value}"
                      + (f"/{model.cab_type.value}"
                         if model.cab_type.value != "NOT_APPLICABLE" else "")
                      + f", {model.registration_type.value}){scope}")
                for gen, variants in catalog.succession(model_id):
                    window = f"{(gen.launched or '?')[:7]} -> " \
                             f"{(gen.ended or 'current')[:7]}"
                    print(f"    {gen.code or '-':<8} {window}")
                    for variant in variants:
                        span = ""
                        if variant.price_min_thb and variant.price_max_thb and \
                                variant.price_min_thb != variant.price_max_thb:
                            span = (f"  ({variant.price_min_thb:,.0f}"
                                    f"-{variant.price_max_thb:,.0f})")
                        print(f"      {variant.name:<24} "
                              f"{(variant.price_thb or 0):>10,.0f}{span}")
        return 0
    if args.catalog_cmd == "scope":
        rows = [m for m in catalog.models.values()
                if args.value is None
                or m.market_scope.value == args.value.upper()]
        for model in sorted(rows, key=lambda m: (m.market_scope.value, m.id)):
            print(f"  {model.market_scope.value:<8} {model.id}")
        print(f"{len(rows)} models")
        return 0
    if args.catalog_cmd == "show":
        matches = [vid for vid in catalog.variants if args.query.lower() in vid]
        if not matches:
            print(f"no variant id contains {args.query!r}")
            return 1
        for vid in matches[:args.limit]:
            resolved = catalog.resolve(vid)
            print(f"\n{vid}  (catalog {catalog.year})")
            for key, value in resolved.as_row().items():
                if key in {"variant_id", "year"}:
                    continue
                origin = resolved.provenance.get(key, "-")
                print(f"  {key:<22} {str(value):<28} <- {origin}")
        return 0
    return 1


def cmd_ingest(args) -> int:
    catalog = _catalog(args)
    conn = _conn(args)
    if not conn.execute("SELECT 1 FROM dim_unit LIMIT 1").fetchone():
        rebuild_dimension(conn, catalog)
    colmap = ColumnMap(period=args.col_period, brand=args.col_brand,
                       model=args.col_model, variant=args.col_variant,
                       units=args.col_units, province=args.col_province,
                       registration_type=args.col_regtype)
    if not any(vars(colmap).values()):
        colmap = None
    report = ingest_csv(conn, catalog, args.path, args.source, wide=args.wide,
                        colmap=colmap,
                        default_registration_type=args.registration_type,
                        url=args.url, notes=args.notes)
    print(report.render())
    return 0


def cmd_dlt(args) -> int:
    raw_dir = Path(args.raw_dir)
    if args.dlt_cmd == "list":
        for resource in dlt_mod.list_resources():
            tag = resource.period or (f"ปี {resource.year}" if resource.year
                                      else "?")
            print(f"  {tag:<10} {resource.id}  {resource.name}")
        return 0

    index = dlt_mod.monthly_index()
    if args.month:
        periods = [normalize.period_key(args.month)]
    else:
        year = args.fetch_year or args.year
        periods = dlt_mod.months_of(year, index)
        if not periods:
            print(f"DLT publishes no month for {year}; available years: "
                  + ", ".join(sorted({p[:4] for p in index})))
            return 1

    reports = [dlt_mod.fetch_month(period, raw_dir, resources=index)
               for period in periods]
    for report in reports:
        print(report.render())
        print()

    if args.dlt_cmd == "fetch":
        return 0

    # load = fetch then ingest, with the exact columns the fetcher wrote.
    catalog = _catalog(args)
    conn = _conn(args)
    if not conn.execute("SELECT 1 FROM dim_unit LIMIT 1").fetchone():
        rebuild_dimension(conn, catalog)
    for report in reports:
        ingested = ingest_csv(
            conn, catalog, report.path, f"DLT {report.period}",
            colmap=dlt_mod.column_map(), publisher="DLT",
            url=f"{dlt_mod.CKAN_BASE}/datastore_search"
                f"?resource_id={report.resource_id}",
            notes=f"sha256 {report.sha256}")
        print(f"--- {report.period}")
        print(ingested.render())
        print()
    return 0


def cmd_edit(args) -> int:
    editor_mod.serve(args.data_dir, args.year, args.db, args.host, args.port)
    return 0


def cmd_trim(args) -> int:
    conn = _conn(args)
    if args.trim_cmd == "check":
        problems = trimledger.reconcile(conn)
        for row in problems[:args.limit]:
            print(f"  {row['model_id']:<40} {row['period']}  "
                  f"ledger={row['ledger_units']:,.0f} "
                  f"master={row['master_units']:,.0f} "
                  f"diff={row['difference']:+,.0f}")
        if problems:
            print(f"{len(problems)} model-months disagree")
            return 1
        print("trim ledger and master agree on every model-month")
        return 0

    if args.trim_cmd == "export":
        count = trimledger.export_csv(
            conn, args.path, period_from=getattr(args, "from"),
            period_to=args.to, brand=args.brand)
        print(f"wrote {count} trim rows to {args.path}")
        return 0

    rows = trimledger.rows(conn, period_from=getattr(args, "from"),
                           period_to=args.to, brand=args.brand)
    header = (f"{'brand':<12} {'nameplate':<20} {'trim':<28} "
              f"{'grade':<14} {'km':>5} {'units':>8}")
    print(header)
    print("-" * len(header))
    for row in rows[:args.limit]:
        print(f"{str(row['brand'])[:12]:<12} {str(row['nameplate'])[:20]:<20} "
              f"{str(row['trim_label'] or '(base)')[:28]:<28} "
              f"{str(row['grade'] or '-')[:14]:<14} "
              f"{(row['range_km'] or 0):>5.0f} {row['units']:>8,.0f}")
    print(f"\n{len(rows)} trim rows, {sum(r['units'] for r in rows):,.0f} units")
    return 0


def cmd_review(args) -> int:
    conn = _conn(args)
    if args.map:
        scope, _, rest = args.map.partition(":")
        raw, _, target = rest.rpartition("=")
        if not (scope and raw and target):
            raise SystemExit(
                "--map expects scope:raw label=target_id, e.g. "
                "'model:TOYOTA REVO=toyota.hilux_revo_smart_cab'")
        teach_alias(conn, scope, raw, target, args.reg or "*")
        scope_note = f" for {args.reg}" if args.reg else " for any DLT class"
        print(f"taught {scope}{scope_note}: {raw!r} -> {target}")
        return 0
    print("open review rows by reason:")
    for row in unmatched_summary(conn):
        print(f"  {row['reason']:<20} rows={row['rows']:<6} "
              f"units={(row['units'] or 0):,.0f}")
    print("\ntop unmatched labels:")
    for row in conn.execute(
            "SELECT raw_label, reason, SUM(units) AS units, COUNT(*) AS n "
            "FROM ingest_review WHERE status='open' GROUP BY raw_label, reason "
            "ORDER BY units DESC LIMIT ?", (args.limit,)):
        print(f"  {(row['raw_label'] or '')[:44]:<46} {row['reason']:<18} "
              f"{(row['units'] or 0):,.0f}")
    return 0


def _scopes(raw):
    if not raw:
        return None
    return [s.strip() for s in raw.split(",") if s.strip()]


def cmd_cube(args) -> int:
    conn = _conn(args)
    result = cube_mod.run(
        conn, [d.strip() for d in args.by.split(",") if d.strip()],
        filters=_parse_filters(args.filter), period_from=getattr(args, "from"),
        period_to=args.to, grains=args.grain, scopes=_scopes(args.scope),
        allocate=args.allocate, limit=args.limit)
    if args.json:
        print(json.dumps(result.rows, ensure_ascii=False, indent=2))
    elif args.csv:
        _write_csv(args.csv, result.dimensions + ["units", "share"], result.rows)
        print(f"wrote {len(result.rows)} rows to {args.csv}")
    else:
        print(result.render(limit=args.limit or 40))
    return 0


def cmd_growth(args) -> int:
    conn = _conn(args)
    rows = cube_mod.growth(conn, args.by, base=args.base, compare=args.compare,
                           filters=_parse_filters(args.filter),
                           scopes=_scopes(args.scope), allocate=args.allocate)
    header = f"{args.by:<26} {args.base:>12} {args.compare:>12} {'chg':>10} " \
             f"{'growth':>9} {'share pp':>9}"
    print(header)
    print("-" * len(header))
    for row in rows[:args.limit]:
        growth_pct = "n/a" if row["growth"] is None else f"{row['growth']:.1%}"
        print(f"{str(row[args.by])[:26]:<26} {row['units_base']:>12,.0f} "
              f"{row['units_compare']:>12,.0f} {row['units_change']:>10,.0f} "
              f"{growth_pct:>9} {row['share_change_pp']:>+9.2f}")
    return 0


def cmd_allocate(args) -> int:
    conn = _conn(args)
    covered, total = allocate_mod.derive_weights(conn, fallback=args.fallback)
    print(f"model-periods with a derived trim mix: {covered} / {total}")
    bad = allocate_mod.weight_health(conn)
    if bad:
        print(f"warning: {len(bad)} model-periods do not sum to 1.0")
    print("run `cube --allocate` to split model-grain volume with these weights")
    return 0


def cmd_coverage(args) -> int:
    conn = _conn(args)
    report = cube_mod.coverage_report(conn)
    report["catalog_years_loaded"] = loaded_years(conn)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


# --------------------------------------------------------------------- parser
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="vehreg",
        description="Thai new-vehicle registration intelligence warehouse")
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--data-dir", default=str(DATA_DIR))
    parser.add_argument("--year", type=int, default=DEFAULT_YEAR,
                        help=f"catalog year to work with (default {DEFAULT_YEAR}); "
                             "years are independent, nothing reads across them")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("facets", help="print every facet vocabulary")
    p.set_defaults(func=cmd_facets)

    p = sub.add_parser("init", help="validate the catalog and build the warehouse")
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("catalog", help="inspect or edit the catalog")
    csub = p.add_subparsers(dest="catalog_cmd", required=True)
    csub.add_parser("stats").set_defaults(func=cmd_catalog)
    csub.add_parser("validate").set_defaults(func=cmd_catalog)
    c = csub.add_parser("audit", help="periods with no owner-confirmed price")
    c.add_argument("--limit", type=int, default=30)
    c.set_defaults(func=cmd_catalog)
    c = csub.add_parser("show", help="resolve one variant and show provenance")
    c.add_argument("query")
    c.add_argument("--limit", type=int, default=5)
    c.set_defaults(func=cmd_catalog)
    csub.add_parser("years", help="list catalog years on disk").set_defaults(
        func=cmd_catalog)
    c = csub.add_parser("nameplate",
                        help="roll a nameplate back up: its models, cabs and "
                             "generations in order")
    c.add_argument("query")
    c.add_argument("--limit", type=int, default=5)
    c.set_defaults(func=cmd_catalog)
    c = csub.add_parser("scope", help="list models by market scope")
    c.add_argument("value", nargs="?", choices=["CORE", "NICHE", "GREY",
                                                "UNKNOWN"])
    c.set_defaults(func=cmd_catalog)
    c = csub.add_parser("fork", help="start another year as a copy of --year")
    c.add_argument("--to", type=int, required=True)
    c.add_argument("--overwrite", action="store_true")
    c.set_defaults(func=cmd_catalog)
    c = csub.add_parser("template", help="write a blank authoring CSV")
    c.add_argument("path")
    c.set_defaults(func=cmd_catalog)
    c = csub.add_parser("import", help="merge an authoring CSV into the catalog")
    c.add_argument("path")
    c.add_argument("--dry-run", action="store_true")
    c.set_defaults(func=cmd_catalog)
    c = csub.add_parser("export", help="flatten the catalog to CSV")
    c.add_argument("path")
    c.add_argument("--with-volume", action="store_true",
                   help="add a units column and sort by it, so the rows that "
                        "matter come first")
    c.set_defaults(func=cmd_catalog)

    p = sub.add_parser("ingest", help="load a DLT export")
    p.add_argument("path")
    p.add_argument("--source", help="name for this source (defaults to filename)")
    p.add_argument("--wide", action="store_true",
                   help="months are columns rather than rows")
    p.add_argument("--registration-type", default="RY1")
    p.add_argument("--url", default="")
    p.add_argument("--notes", default="")
    for name in ("period", "brand", "model", "variant", "units", "province"):
        p.add_argument(f"--col-{name}", dest=f"col_{name}")
    p.add_argument("--col-regtype", dest="col_regtype")
    p.set_defaults(func=cmd_ingest)

    p = sub.add_parser("dlt", help="talk to DLT's open-data API")
    dsub = p.add_subparsers(dest="dlt_cmd", required=True)
    for name, helptext in (("list", "show every published resource"),
                           ("fetch", "download months to --raw-dir"),
                           ("load", "download months and ingest them")):
        d = dsub.add_parser(name, help=helptext)
        d.add_argument("--raw-dir", default="data/raw")
        if name != "list":
            d.add_argument("--month", help="YYYY-MM (or Thai/BE, e.g. 2569-01)")
            d.add_argument("--fetch-year", type=int,
                           help="every published month of this year "
                                "(defaults to --year)")
        else:
            d.add_argument("--month", default=None, help=argparse.SUPPRESS)
            d.add_argument("--fetch-year", default=None, help=argparse.SUPPRESS)
        d.set_defaults(func=cmd_dlt)

    p = sub.add_parser("edit", help="open the local editor in a browser")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--host", default="127.0.0.1")
    p.set_defaults(func=cmd_edit)

    p = sub.add_parser("trim", help="the separate trim ledger for the Chinese "
                                    "marques and Tesla")
    tsub = p.add_subparsers(dest="trim_cmd", required=True)
    for name, helptext in (("list", "show trim rows"),
                           ("check", "reconcile the ledger against the master"),
                           ("export", "write the ledger to its own CSV")):
        t = tsub.add_parser(name, help=helptext)
        if name == "export":
            t.add_argument("path")
        t.add_argument("--from", dest="from", help="YYYY-MM")
        t.add_argument("--to", help="YYYY-MM")
        t.add_argument("--brand")
        t.add_argument("--limit", type=int, default=40)
        t.set_defaults(func=cmd_trim)

    p = sub.add_parser("review", help="see and resolve unmatched labels")
    p.add_argument("--limit", type=int, default=25)
    p.add_argument("--map", help="scope:raw label=target_id")
    p.add_argument("--reg", choices=["RY1", "RY2", "RY3"],
                   help="limit the lesson to one DLT class, so the same label "
                        "can mean a double cab in รย.1 and a smart cab in รย.3")
    p.set_defaults(func=cmd_review)

    p = sub.add_parser("cube", help="cross-tab any facets")
    p.add_argument("--by", required=True, help="comma-separated facets")
    p.add_argument("--from", dest="from", help="YYYY-MM")
    p.add_argument("--to", help="YYYY-MM")
    p.add_argument("--filter", action="append", default=[],
                   help="facet=value[,value]")
    p.add_argument("--grain", action="append",
                   choices=["BRAND", "MODEL", "VARIANT"])
    p.add_argument("--allocate", action="store_true",
                   help="split model-grain volume with the loaded weights")
    p.add_argument("--scope", default=None,
                   help="market scopes to count: CORE (default), NICHE, GREY, "
                        "a comma-separated list, or 'all'")
    p.add_argument("--limit", type=int)
    p.add_argument("--csv")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_cube)

    p = sub.add_parser("growth", help="compare two periods on one facet")
    p.add_argument("--by", required=True)
    p.add_argument("--base", required=True, help="YYYY or YYYY-MM")
    p.add_argument("--compare", required=True)
    p.add_argument("--filter", action="append", default=[])
    p.add_argument("--allocate", action="store_true")
    p.add_argument("--scope", default=None)
    p.add_argument("--limit", type=int, default=30)
    p.set_defaults(func=cmd_growth)

    p = sub.add_parser("allocate",
                       help="derive a trim mix from the trim-level rows present")
    p.add_argument("--fallback", choices=list(allocate_mod.FALLBACKS),
                   default="year")
    p.set_defaults(func=cmd_allocate)

    p = sub.add_parser("coverage", help="how much volume is classified how deeply")
    p.set_defaults(func=cmd_coverage)
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (CatalogError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
