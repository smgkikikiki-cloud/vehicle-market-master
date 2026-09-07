import json
import re
from urllib.parse import urljoin

import requests

CAR_ID = "98c1d7de-79db-4581-b332-69abe657a532"
FILE_ID = "d086cd15-ea65-4b25-ab6f-80ffb2071a31"
DETAIL = f"https://car.ecosticker.go.th/landing-page/detail/{CAR_ID}"
FILE_URL = f"https://api-car.ecosticker.go.th/api/v1/file/data?file_id={FILE_ID}"


def test_probe_brochure_discovery():
    s = requests.Session()
    s.headers.update({"User-Agent": "Mozilla/5.0"})
    page = s.get(DETAIL, timeout=30)
    scripts = re.findall(r'<script[^>]+src=["\']([^"\']+)', page.text, flags=re.I)
    out = {"detail_status": page.status_code, "scripts": scripts}

    for src in scripts:
        url = urljoin(DETAIL, src)
        js = s.get(url, timeout=30)
        text = js.text
        idx = text.find("brochure_link")
        if idx >= 0:
            lo, hi = max(0, idx - 10000), min(len(text), idx + 10000)
            ctx = text[lo:hi]
            out["bundle"] = url
            out["brochure_context"] = ctx
            out["api_like_strings"] = sorted(set(re.findall(r'["\']([^"\']*(?:api|car)[^"\']*)["\']', ctx, flags=re.I)))[:100]
            out["http_strings"] = sorted(set(re.findall(r'https?://[^"\'\\ ]+', ctx)))[:100]
            break

    f = s.get(FILE_URL, timeout=30, allow_redirects=False)
    out["file_direct"] = {
        "status": f.status_code,
        "location": f.headers.get("location"),
    }
    raise AssertionError("BROCHURE_CONTEXT=" + json.dumps(out, ensure_ascii=False))
