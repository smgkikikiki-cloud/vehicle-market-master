#!/usr/bin/env python3
"""Discover, download and extract target specs from ECO Sticker brochures.

Examples:
  python tools/ecosticker_brochures.py --car-id 98c1d7de-79db-4581-b332-69abe657a532
  python tools/ecosticker_brochures.py --all --limit 20
  python tools/ecosticker_brochures.py --all --metadata-only

This is a staging tool: it writes candidate JSONL and cached PDFs. It never
creates MarketTrims, changes prices, or mutates DLT registration facts.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from vehreg.brochure_specs import extract_brochure
from vehreg.catalog import Catalog
from vehreg.ecosticker_client import ECOStickerClient, brochure_file_id


def trim_map(catalog: Catalog) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for trim_id, trim in catalog.trims.items():
        for car_id in trim.source_refs.get("ecosticker", ()):
            out.setdefault(str(car_id), []).append(trim_id)
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--car-id", action="append", default=[], help="ECO Sticker car UUID; repeatable")
    parser.add_argument("--all", action="store_true", help="paginate the complete public ECO Sticker vehicle list")
    parser.add_argument("--limit", type=int, default=0, help="stop after N cars (0 = no limit)")
    parser.add_argument("--year", type=int, default=2026, help="Vehicle Master catalog year used for trim matching")
    parser.add_argument("--cache-dir", default=".cache/ecosticker_brochures")
    parser.add_argument("--output", default=".cache/ecosticker_brochure_candidates.jsonl")
    parser.add_argument("--metadata-only", action="store_true", help="discover links but do not download/parse PDFs")
    parser.add_argument("--sleep", type=float, default=0.15, help="polite delay between public-site requests")
    args = parser.parse_args()

    if not args.car_id and not args.all:
        parser.error("provide --car-id or --all")

    client = ECOStickerClient()
    catalog = Catalog.load(year=args.year)
    eco_to_trim = trim_map(catalog)
    cache_dir = Path(args.cache_dir)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)

    ids: list[str] = list(dict.fromkeys(args.car_id))
    list_meta: dict[str, dict] = {}
    if args.all:
        for car in client.iter_cars():
            car_id = str(car.get("id") or "").strip()
            if not car_id or car_id in list_meta:
                continue
            ids.append(car_id)
            list_meta[car_id] = car
            if args.limit and len(ids) >= args.limit:
                break
    elif args.limit:
        ids = ids[: args.limit]

    parsed_by_sha: dict[str, dict] = {}
    counts = {"cars": 0, "brochure": 0, "no_brochure": 0, "parsed": 0, "needs_vision": 0, "errors": 0}

    with output.open("w", encoding="utf-8") as fh:
        for index, car_id in enumerate(ids, 1):
            counts["cars"] += 1
            row: dict = {
                "car_id": car_id,
                "list": list_meta.get(car_id, {}),
                "trim_ids": eco_to_trim.get(car_id, []),
                "match_status": (
                    "MATCHED" if len(eco_to_trim.get(car_id, [])) == 1
                    else "REVIEW" if len(eco_to_trim.get(car_id, [])) > 1
                    else "UNMATCHED"
                ),
            }
            try:
                detail_payload = client.get_market_detail(car_id)
                detail = detail_payload.get("data") or {}
                link = str(detail.get("brochure_link") or "").strip()
                row["market_detail"] = {
                    "brand": detail.get("brand"),
                    "model": detail.get("model"),
                    "cartype_name": detail.get("cartype_name"),
                    "brochure_link": link,
                    "brochure_file_id": brochure_file_id(link),
                }
                if not link:
                    counts["no_brochure"] += 1
                    row["status"] = "NO_BROCHURE"
                else:
                    counts["brochure"] += 1
                    row["status"] = "DISCOVERED"
                    if not args.metadata_only:
                        downloaded = client.download_brochure(car_id, cache_dir)
                        if downloaded is None:
                            row["status"] = "NO_BROCHURE"
                            counts["no_brochure"] += 1
                        else:
                            row["brochure"] = {
                                "file_id": downloaded.file_id,
                                "url": downloaded.url,
                                "final_url": downloaded.final_url,
                                "path": str(downloaded.path),
                                "sha256": downloaded.sha256,
                                "size_bytes": downloaded.size_bytes,
                            }
                            if downloaded.sha256 not in parsed_by_sha:
                                parsed_by_sha[downloaded.sha256] = extract_brochure(downloaded.path).to_dict()
                            extraction = parsed_by_sha[downloaded.sha256]
                            row["extraction"] = extraction
                            row["status"] = "NEEDS_VISION" if extraction["needs_vision"] else "PARSED"
                            if extraction["needs_vision"]:
                                counts["needs_vision"] += 1
                            else:
                                counts["parsed"] += 1
            except Exception as exc:
                counts["errors"] += 1
                row["status"] = "ERROR"
                row["error"] = f"{type(exc).__name__}: {exc}"

            # Price is intentionally absent even if ECO/detail/brochure contains one.
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
            print(f"[{index}/{len(ids)}] {car_id} -> {row['status']}")
            if args.sleep > 0 and index < len(ids):
                time.sleep(args.sleep)

    print(json.dumps({"output": str(output), **counts}, ensure_ascii=False, sort_keys=True))
    return 0 if counts["errors"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
