import json
import requests

IDS = {
    "dynamic": "d744d9f3-d393-4ac3-b441-17a022098fed",
    "long_range_max": "b4529bb4-d813-416b-b272-430b123cc06c",
    "max_plus": "98c1d7de-79db-4581-b332-69abe657a532",
}


def test_probe_ecosticker_j5():
    out = {}
    for name, car_id in IDS.items():
        url = "https://api-car.ecosticker.go.th/api/v1/eco-sticker/public/by-car-id"
        r = requests.get(url, params={"car_id": car_id}, timeout=20)
        out[name] = {"status": r.status_code, "json": r.json()}
    list_url = "https://api-car.ecosticker.go.th/api/v2/landing-page/cars"
    for term in ("JAECOO", "5 EV", "JAECOO 5 EV", "MAX+", "ULTRA"):
        r = requests.get(list_url, params={"page": 1, "row": 100, "search": term, "sort": ""}, timeout=20)
        out[f"search:{term}"] = {"status": r.status_code, "json": r.json()}
    raise AssertionError("ECOSTICKER_PROBE=" + json.dumps(out, ensure_ascii=False, sort_keys=True))
