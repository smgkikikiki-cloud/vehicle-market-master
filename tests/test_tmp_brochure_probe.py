import json
import requests

CAR_ID = "98c1d7de-79db-4581-b332-69abe657a532"
EXPECTED = "https://api-car.ecosticker.go.th/api/v1/file/data?file_id=d086cd15-ea65-4b25-ab6f-80ffb2071a31"


def test_probe_v2_detail():
    url = f"https://api-car.ecosticker.go.th/api/v2/landing-page/{CAR_ID}"
    r = requests.get(url, timeout=30, headers={"User-Agent":"Mozilla/5.0"})
    payload = r.json()
    data = payload.get("data") or {}
    out = {
        "status": r.status_code,
        "brochure_link": data.get("brochure_link"),
        "matches_expected": data.get("brochure_link") == EXPECTED,
        "interesting": {k:data.get(k) for k in [
            "brand","model","cartype_name","battery_capacity","battery_brand","battery_type",
            "nominal_voltage","motor","car_width","car_length","car_height","car_seats",
            "wheel_size","front_wheel","back_wheel","total_weight","driving_range","year","model_year"
        ]},
        "keys": sorted(data.keys()),
    }
    raise AssertionError("V2_DETAIL="+json.dumps(out,ensure_ascii=False,sort_keys=True))
