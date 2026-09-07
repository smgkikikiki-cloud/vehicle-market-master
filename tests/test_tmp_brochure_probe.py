import json
import requests

MAP_URL = "https://car.ecosticker.go.th/landing-page/static/js/main.f4d375f1.js.map"


def test_probe_brochure_discovery():
    s=requests.Session(); s.headers.update({"User-Agent":"Mozilla/5.0"})
    r=s.get(MAP_URL,timeout=30)
    out={"status":r.status_code,"content_type":r.headers.get("content-type"),"len":len(r.content)}
    try:
        sm=r.json()
    except Exception:
        raise AssertionError("MAP="+json.dumps(out))
    hits=[]
    for name, content in zip(sm.get("sources",[]),sm.get("sourcesContent",[])):
        if not content: continue
        if "brochure_link" in content or "download_brochure" in content or "by-car-id" in content:
            hits.append({"source":name,"content":content[:30000]})
    out["hits"]=hits[:30]
    raise AssertionError("MAP="+json.dumps(out,ensure_ascii=False))
