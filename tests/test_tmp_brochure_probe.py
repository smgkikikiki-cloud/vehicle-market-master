import json
import re
from urllib.parse import urljoin

import requests

CAR_ID = "98c1d7de-79db-4581-b332-69abe657a532"
FILE_ID = "d086cd15-ea65-4b25-ab6f-80ffb2071a31"
DETAIL = f"https://car.ecosticker.go.th/landing-page/detail/{CAR_ID}"
FILE_URL = f"https://api-car.ecosticker.go.th/api/v1/file/data?file_id={FILE_ID}"


def _snips(text, needle, radius=250):
    out = []
    low = text.lower()
    start = 0
    while len(out) < 10:
        i = low.find(needle.lower(), start)
        if i < 0:
            break
        out.append(text[max(0, i-radius): i+len(needle)+radius])
        start = i + len(needle)
    return out


def test_probe_brochure_discovery():
    s = requests.Session()
    s.headers.update({"User-Agent": "Mozilla/5.0"})
    out = {}

    r = s.get(DETAIL, timeout=30)
    out["detail"] = {
        "status": r.status_code,
        "content_type": r.headers.get("content-type"),
        "len": len(r.content),
        "contains_file_id": FILE_ID in r.text,
        "file_data_snips": _snips(r.text, "/api/v1/file/data"),
        "brochure_snips": _snips(r.text, "brochur"),
    }

    scripts = re.findall(r'<script[^>]+src=["\']([^"\']+)', r.text, flags=re.I)
    out["script_count"] = len(scripts)
    hits = []
    for src in scripts:
        url = urljoin(DETAIL, src)
        try:
            js = s.get(url, timeout=30)
        except Exception as exc:
            hits.append({"url": url, "error": repr(exc)})
            continue
        text = js.text
        needles = ["/api/v1/file/data", "brochur", "linkBrochurButton", "file_id"]
        found = {n: _snips(text, n) for n in needles if n.lower() in text.lower()}
        if found:
            hits.append({"url": url, "status": js.status_code, "len": len(js.content), "found": found})
    out["script_hits"] = hits[:20]

    f = s.get(FILE_URL, timeout=30, allow_redirects=False)
    out["file_direct"] = {
        "status": f.status_code,
        "content_type": f.headers.get("content-type"),
        "content_disposition": f.headers.get("content-disposition"),
        "location": f.headers.get("location"),
        "len": len(f.content),
        "first16_hex": f.content[:16].hex(),
    }

    api = s.get(
        "https://api-car.ecosticker.go.th/api/v1/eco-sticker/public/by-car-id",
        params={"car_id": CAR_ID}, timeout=30)
    out["detail_api"] = {
        "status": api.status_code,
        "contains_file_id": FILE_ID in api.text,
        "file_data_snips": _snips(api.text, "/api/v1/file/data"),
        "brochure_snips": _snips(api.text, "brochur"),
        "file_id_snips": _snips(api.text, "file_id"),
    }

    raise AssertionError("BROCHURE_PROBE=" + json.dumps(out, ensure_ascii=False))
