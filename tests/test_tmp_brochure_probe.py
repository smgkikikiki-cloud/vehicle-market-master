import json
import re
from urllib.parse import urljoin

import requests

DETAIL = "https://car.ecosticker.go.th/landing-page/detail/98c1d7de-79db-4581-b332-69abe657a532"


def snips(text, needle, radius=3000):
    out=[]; pos=0
    while len(out)<20:
        i=text.find(needle,pos)
        if i<0: break
        out.append(text[max(0,i-radius):min(len(text),i+len(needle)+radius)])
        pos=i+len(needle)
    return out


def test_probe_brochure_discovery():
    s=requests.Session(); s.headers.update({"User-Agent":"Mozilla/5.0"})
    html=s.get(DETAIL,timeout=30).text
    scripts=re.findall(r'<script[^>]+src=["\']([^"\']+)',html,flags=re.I)
    js=""
    for src in scripts:
        u=urljoin(DETAIL,src)
        if "main." in u:
            js=s.get(u,timeout=30).text
            break
    out={
      "known_detail": snips(js,"public/by-car-id",5000),
      "known_list": snips(js,"landing-page/cars",5000),
      "base_api": snips(js,"api-car.ecosticker.go.th/api",2500),
      "brochure": snips(js,"brochure_link",5000),
    }
    raise AssertionError("TRACE="+json.dumps(out,ensure_ascii=False))
