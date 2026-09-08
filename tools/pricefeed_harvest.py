#!/usr/bin/env python3
"""Discover price news and read price claims off it. Read-only by default.

Discovery uses the WordPress REST API rather than RSS or HTML:

    /wp-json/wp/v2/posts?modified_after=<last_poll>&per_page=100&_fields=...

Three reasons.  It returns the delta as small JSON.  ``modified`` changes when an
outlet *edits a published price*, which RSS and sitemaps cannot report and which
is exactly the event that must not be missed.  And a feed holds only its most
recent items, so a busy afternoon can hide a launch before the next poll --
``modified_after`` has no such window.

The harvester writes a batch file of documents and claims.  It never writes to
the price ledger, the catalog or the warehouse; :mod:`vehreg.pricefeed` decides
what a claim is worth, and a person decides what gets published.

    python tools/pricefeed_harvest.py --since 2026-09-01 --out batch.json
    python tools/pricefeed_harvest.py --since 2026-09-01 --measure-only
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from typing import Iterable, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vehreg.pricefeed import (  # noqa: E402
    PriceClaim, PriceFeedError, SourceDocument, body_sketch, content_id,
    load_sources, to_dict,
)
from vehreg.pricing import PriceType  # noqa: E402
from tools import robots_check  # noqa: E402

USER_AGENT = ("vehicle-market-master price watcher "
              "(+https://github.com/smgkikikiki-cloud/vehicle-market-master)")

# Thai price wording. A number is a price only next to one of these.
BAHT = r"(?:บาท|฿)"
AMOUNT = r"(\d{1,3}(?:,\d{3})+|\d{6,8})"
# "<grade> : 1,449,000 บาท" is one outlet's price table...
PRICE_LINE = re.compile(rf"^(.{{0,90}}?)\s*[:：]\s*{AMOUNT}\s*{BAHT}")
# ...and the other writes "Alphard HEV Smart  3,590,000 บาท" with no colon at
# all. Requiring a Latin opening keeps this off Thai prose lines.
PRICE_LINE_BARE = re.compile(rf"^([A-Za-z][^:：]{{0,70}}?)\s+{AMOUNT}\s*{BAHT}")
# "จาก 899,900 บาท เหลือ 859,900 บาท"
FROM_TO = re.compile(rf"จาก\s*{AMOUNT}\s*{BAHT}?\s*(?:เหลือ|ลดเหลือ)\s*{AMOUNT}\s*{BAHT}")
# "1,449,000 บาท จากราคาปกติ 1,699,000 บาท" -- the discount is quoted first.
NOW_WAS = re.compile(
    rf"{AMOUNT}\s*{BAHT}\s*จากราคา(?:ปกติ|เต็ม)\s*{AMOUNT}\s*{BAHT}")
QUOTA = re.compile(r"(?:คันที่|จำนวน|เพียง)\s*\d[\d,]*\s*[–\-]?\s*(\d[\d,]*)\s*คัน")

CAMPAIGN_WORDS = ("แคมเปญ", "โปรโมชั่น", "ข้อเสนอ", "motor show", "motor expo",
                  "ส่วนลด", "ลดราคา", "ราคาพิเศษ")

# This is a master of the Thai market. A price quoted for another country is a
# different car at a different tax rate, and must never reach a Thai trim.
FOREIGN_MARKET = (
    "อินโดนีเซีย", "มาเลเซีย", "สิงคโปร์", "เวียดนาม", "ฟิลิปปินส์", "ญี่ปุ่น",
    "เกาหลี", "ยุโรป", "อังกฤษ", "ออสเตรเลีย", "อเมริกา", "อินเดีย", "ไต้หวัน",
    "ในจีน", "ตลาดจีน", "indonesia", "malaysia", "vietnam", "japan", "korea",
    "europe", "australia", "usa", "india", "china",
)

# A grade column that is really a headline fragment. Better no trim than a
# wrong one: the claim still reaches review, just without a false identity.
NOT_A_GRADE = ("ราคา", "ภาพ", "ผลทดสอบ", "เทียบสเป็ค", "รีวิว", "สเป็ค",
               "เปิดตัว", "ส่วนลด", "โปรโมชั่น", "แคมเปญ")
INTRO_WORDS = ("ราคาเปิดตัว", "ราคาแนะนำพิเศษ", "ราคาพิเศษช่วงเปิดตัว")

# Words that mean the number is not the price of the car.
NOT_A_PRICE = ("ผ่อน", "งวด", "เดือนละ", "ดาวน์", "มัดจำ", "จอง", "ประกัน",
               "ดอกเบี้ย", "ค่าบำรุง", "ส่วนลดดอกเบี้ย", "มูลค่า", "รับประกัน",
               "ค่าแรง", "ส่วนลดค่า", "เงินคืน", "ผ่อนนาน")


class HarvestError(RuntimeError):
    pass


def _get(url: str, *, timeout: float = 45.0, attempts: int = 3,
         pause: float = 2.0) -> object:
    headers = {"Accept": "application/json", "User-Agent": USER_AGENT}
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            request = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code == 400:      # WordPress answers 400 for "no more pages"
                return []
            if exc.code == 429:
                time.sleep(pause * (2 ** attempt) * 4)
            elif exc.code < 500:
                raise HarvestError(f"{url}: HTTP {exc.code}") from exc
            last = HarvestError(f"{url}: HTTP {exc.code}")
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            last = HarvestError(f"{url}: {exc}")
        if attempt + 1 < attempts:
            time.sleep(pause * (2 ** attempt))
    raise last or HarvestError(url)


def list_posts(base_url: str, *, since: str, limit: int = 100,
               delay: float = 1.0, log=lambda *_: None) -> list[dict]:
    """Posts created or edited since ``since``, newest first."""
    fields = "id,date,date_gmt,modified,modified_gmt,link,title"
    posts: list[dict] = []
    page = 1
    while len(posts) < limit:
        query = urllib.parse.urlencode({
            "modified_after": since, "per_page": min(100, limit - len(posts)),
            "page": page, "_fields": fields, "orderby": "modified", "order": "desc",
        })
        batch = _get(f"{base_url.rstrip('/')}/wp-json/wp/v2/posts?{query}")
        if not isinstance(batch, list) or not batch:
            break
        posts.extend(batch)
        log(f"  page {page}: {len(batch)} posts (total {len(posts)})")
        if len(batch) < 100:
            break
        page += 1
        time.sleep(delay)
    return posts[:limit]


def fetch_content(base_url: str, post_id: int) -> dict:
    payload = _get(f"{base_url.rstrip('/')}/wp-json/wp/v2/posts/{post_id}"
                   f"?_fields=id,link,title,content,date_gmt,modified_gmt")
    if not isinstance(payload, dict):
        raise HarvestError(f"post {post_id}: unexpected payload")
    return payload


# A discounted price is written as struck-through old price then new price:
#   <del>689,000 บาท</del> 599,000 บาท
# Dropping the tag silently would leave 689,000 sitting first on the line, and
# the harvester would publish the price the car is no longer sold at.
STRUCK = re.compile(r"<(?:del|s|strike)\b[^>]*>(.*?)</(?:del|s|strike)>",
                    flags=re.S | re.I)


def strip_html(raw: str) -> str:
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", raw or "", flags=re.S)
    # Rewrite into the "B บาท จากราคาปกติ A บาท" shape the extractor understands,
    # so the struck-through figure becomes the reference and not the price.
    text = STRUCK.sub(lambda m: " ||was:" + re.sub(r"<[^>]+>", " ", m.group(1)) + "|| ",
                      text)
    text = re.sub(r"<br\s*/?>|</p>|</div>|</li>|</tr>|</h[1-6]>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = unescape(text).replace("\xa0", " ")
    return _fold_struck(text)


def _fold_struck(text: str) -> str:
    """``A ||was:X|| B`` -> ``A B จากราคาปกติ X``, one line at a time."""
    out: list[str] = []
    for line in text.splitlines():
        marks = re.findall(r"\|\|was:(.*?)\|\|", line)
        if marks:
            line = re.sub(r"\|\|was:.*?\|\|", " ", line)
            line = " ".join(line.split()) + " จากราคาปกติ " + " ".join(
                " ".join(m.split()) for m in marks)
        out.append(line)
    return "\n".join(out)


def _amount(raw: str) -> int:
    return int(raw.replace(",", ""))


def classify(line: str, title: str) -> PriceType:
    haystack = (line + " " + title).lower()
    if any(word in haystack for word in INTRO_WORDS):
        return PriceType.INTRODUCTORY_PRICE
    if any(word in haystack for word in CAMPAIGN_WORDS):
        return PriceType.CAMPAIGN_PRICE
    if "ราคาอย่างเป็นทางการ" in haystack or "ตารางราคา" in haystack:
        return PriceType.LIST_PRICE
    return PriceType.UNKNOWN


def extract_claims(document: SourceDocument, *, title: str, body: str,
                   brand_raw: str, model_raw: str) -> list[PriceClaim]:
    """Read price lines off one article. Rule-based and deliberately literal.

    A number becomes a claim only when it sits on a line that names a grade and
    says baht, and only when the line is not talking about an instalment, a
    deposit, a warranty value or an interest discount.  Everything ambiguous is
    left out: this queue is judged on precision, not on how full it is.
    """
    claims: list[PriceClaim] = []
    seen: set[tuple] = set()
    for raw_line in strip_html(body).splitlines():
        line = " ".join(raw_line.split())
        if not line or "บาท" not in line:
            continue
        if any(word in line for word in NOT_A_PRICE):
            continue
        was = NOW_WAS.search(line) or FROM_TO.search(line)
        match = PRICE_LINE.search(line) or PRICE_LINE_BARE.search(line)
        if not match and not was:
            continue
        # A "was/now" pair states a discount on its own and needs no grade
        # column; without a grade the claim still surfaces, for review.
        trim_raw = match.group(1).strip(" -–—•*.") if match else ""
        if any(word in trim_raw for word in NOT_A_GRADE):
            trim_raw = ""
        amount = _amount(match.group(2)) if match else 0
        reference: Optional[int] = None
        if was:
            first, second = _amount(was.group(1)), _amount(was.group(2))
            # "จาก A เหลือ B" gives A as reference; "B จากราคาปกติ A" gives A too.
            amount, reference = (second, first) if first > second else (first, second)
        price_type = classify(line, title)
        key = (trim_raw.lower(), amount, price_type)
        if key in seen:
            continue
        seen.add(key)
        claims.append(PriceClaim(
            claim_id=content_id(f"{document.document_id}|{trim_raw}|{amount}"
                                f"|{price_type.value}")[7:23],
            document_id=document.document_id,
            source_id=document.source_id,
            brand_raw=brand_raw,
            model_raw=model_raw,
            trim_raw=trim_raw,
            amount_thb=amount,
            price_type=price_type,
            # A short internal quote for the review panel. Never republished.
            evidence_text=line[:200],
            reference_price_thb=reference,
        ))
    return claims


def identify(title: str, catalog) -> tuple[str, str]:
    """Pull ``(brand, model)`` out of a headline using the catalog's own names.

    Returns empty strings when no known brand appears, which keeps unrelated
    posts -- reviews, motorsport, overseas news -- out of the claim ledger.
    """
    catalog.build_indexes()
    plain = " ".join(strip_html(title).split())
    lowered = plain.lower()
    best = ""
    for brand in catalog.brands.values():
        for name in [brand.name_en, brand.id.replace("_", " "), *brand.aliases]:
            token = str(name or "").strip().lower()
            if len(token) > 1 and token in lowered and len(token) > len(best):
                best = token
    if not best:
        return "", ""
    start = lowered.index(best)
    tail = plain[start + len(best):].strip(" :–—-")
    # Stop at the first punctuation that ends the car's name in a headline.
    model = re.split(r"[:：(\[|/]|\s[–—]\s", tail)[0].strip()
    model = re.sub(r"\s*(ราคา|เปิดตัว|ใหม่|อย่างเป็นทางการ).*$", "", model).strip()
    # Thai headlines write model names in Latin script. A tail with no Latin
    # letter or digit is prose ("ประเทศไทย"), not a car.
    if not re.search(r"[A-Za-z0-9]", model):
        return "", ""
    return plain[start:start + len(best)], model


def foreign_market(title: str, url: str) -> bool:
    haystack = (title + " " + url).lower()
    return any(word in haystack for word in FOREIGN_MARKET)


def harvest(sources, *, since: str, catalog, limit_per_source: int = 100,
            delay: float = 1.0, want_content: bool = True,
            log=lambda *_: None) -> dict:
    documents: list[SourceDocument] = []
    claims: list[PriceClaim] = []
    skipped = {"no_brand": 0, "foreign_market": 0, "no_claims": 0,
               "refused_by_robots": 0}
    now = datetime.now(timezone.utc).isoformat()
    for source in sources:
        if not source.base_url:
            continue
        # A source that says no is not polled, however useful it would be.
        permission = robots_check.audit(source.base_url)
        if not robots_check.verdict(permission).startswith("allowed"):
            log(f"{source.id}: {robots_check.verdict(permission)} -- skipping")
            skipped["refused_by_robots"] = skipped.get("refused_by_robots", 0) + 1
            continue
        log(f"{source.id}: listing posts modified since {since}")
        posts = list_posts(source.base_url, since=since, limit=limit_per_source,
                           delay=delay, log=log)
        log(f"{source.id}: {len(posts)} posts")
        for post in posts:
            title = strip_html((post.get("title") or {}).get("rendered", ""))
            brand_raw, model_raw = identify(title, catalog)
            if not brand_raw:
                skipped["no_brand"] += 1
                continue
            if foreign_market(title, post.get("link") or ""):
                skipped["foreign_market"] += 1
                continue
            if not want_content:
                continue
            time.sleep(delay)
            full = fetch_content(source.base_url, post["id"])
            body = (full.get("content") or {}).get("rendered", "")
            document = SourceDocument(
                document_id=content_id(body),
                source_id=source.id,
                url=post.get("link") or full.get("link", ""),
                content_hash=content_id(body),
                published_at=_utc(post.get("date_gmt") or full.get("date_gmt")),
                modified_at=_utc(post.get("modified_gmt") or full.get("modified_gmt")),
                first_seen_at=now,
                fetched_at=now,
                title=title,
                body_sketch=body_sketch(strip_html(body)),
            )
            found = extract_claims(document, title=title, body=body,
                                   brand_raw=brand_raw, model_raw=model_raw)
            if not found:
                skipped["no_claims"] += 1
                continue
            documents.append(document)
            claims.extend(found)
            log(f"  {len(found):>2} claim(s)  {title[:70]}")
    return {
        "schema_version": 1,
        "harvested_at": now,
        "since": since,
        "documents": [to_dict(d) for d in documents],
        "claims": [to_dict(c) for c in claims],
        "skipped": skipped,
    }


def _utc(raw: object) -> Optional[str]:
    """WordPress *_gmt fields carry no offset; say so explicitly."""
    if not raw:
        return None
    text = str(raw)
    return text if text.endswith("+00:00") else text + "+00:00"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--since", required=True,
                        help="ISO date/time; posts modified after this")
    parser.add_argument("--out", type=Path, default=None,
                        help="write the batch file here")
    parser.add_argument("--data-dir", type=Path, default=None)
    parser.add_argument("--year", type=int, default=None)
    parser.add_argument("--source", action="append", default=None,
                        help="limit to these source ids")
    parser.add_argument("--limit", type=int, default=100,
                        help="max posts per source")
    parser.add_argument("--delay", type=float, default=1.0)
    parser.add_argument("--measure-only", action="store_true",
                        help="list and identify, but fetch no article bodies")
    args = parser.parse_args(argv)

    from vehreg.catalog import Catalog, DATA_DIR, DEFAULT_YEAR
    data_dir = args.data_dir or DATA_DIR
    year = args.year or DEFAULT_YEAR
    catalog = Catalog.load(data_dir, year)
    registry = load_sources(data_dir, year)
    if not registry:
        raise HarvestError("no sources.json; nothing to poll")
    wanted = [s for s in registry.values()
              if (not args.source or s.id in args.source) and s.adapter == "wordpress"]
    batch = harvest(wanted, since=args.since, catalog=catalog,
                    limit_per_source=args.limit, delay=args.delay,
                    want_content=not args.measure_only,
                    log=lambda message: print(message, file=sys.stderr))
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(batch, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8")
    print(json.dumps({"documents": len(batch["documents"]),
                      "claims": len(batch["claims"]),
                      "skipped": batch["skipped"],
                      "out": str(args.out) if args.out else None},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
