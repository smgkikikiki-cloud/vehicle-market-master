import json
import re
from urllib.parse import urljoin

import requests

CAR_ID = "98c1d7de-79db-4581-b332-69abe657a532"
DETAIL = f"https://car.ecosticker.go.th/landing-page/detail/{CAR_ID}"


def _snips_all(text, needle, radius=700):
    out = []
    start = 0
    while len(out) < 20:
        i = text.find(needle, start)
        if i < 0:
            break
        out.append(text[max(0, i-radius):min(len(text), i+len(needle)+radius)])
        start = i + len(needle)
    return out


def test_probe_brochure_discovery():
    s = requests.Session()
    s.headers.update({"User-Agent": "Mozilla/5.0"})
    page = s.get(DETAIL, timeout=30)
    scripts = re.findall(r'<script[^>]+src=["\']([^"\']+)', page.text, flags=re.I)
    out = {"detail_status": page.status_code}

    for src in scripts:
        url = urljoin(DETAIL, src)
        js = s.get(url, timeout=30)
        text = js.text
        if "brochure_link" not in text:
            continue
        out["bundle"] = url
        out["brochure_link_count"] = text.count("brochure_link")
        out["brochure_link_snips"] = _snips_all(text, "brochure_link")
        # The app's endpoint literals are more useful than de-minifying the full
        # React component. Keep only short strings containing /api/.
        candidates = set()
        for m in re.finditer(r"/api/", text):
            lo = max(0, m.start()-160)
            hi = min(len(text), m.start()+300)
            frag = text[lo:hi]
            for x in re.findall(r"[A-Za-z0-9_?&=./:{}$+-]{4,}", frag):
                if "/api/" in x and len(x) < 240:
                    candidates.add(x)
        out["api_candidates"] = sorted(candidates)[:400]
        out["equip_factory_snips"] = _snips_all(text, "car_equip_factory", radius=1200)
        break

    raise AssertionError("BROCHURE_APIS=" + json.dumps(out, ensure_ascii=False))
