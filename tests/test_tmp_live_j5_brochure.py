from vehreg.brochure_specs import extract_brochure
from vehreg.ecosticker_client import ECOStickerClient

CAR_ID = "98c1d7de-79db-4581-b332-69abe657a532"
EXPECTED_LINK = "https://api-car.ecosticker.go.th/api/v1/file/data?file_id=d086cd15-ea65-4b25-ab6f-80ffb2071a31"


def test_live_j5_brochure_chain(tmp_path):
    client = ECOStickerClient(timeout=30)
    assert client.get_brochure_link(CAR_ID) == EXPECTED_LINK
    downloaded = client.download_brochure(CAR_ID, tmp_path)
    assert downloaded is not None
    assert downloaded.size_bytes > 1000
    extraction = extract_brochure(downloaded.path)
    values = {k: v.value for k, v in extraction.fields.items()}
    print("LIVE_J5_EXTRACTION", extraction.to_dict())
    assert extraction.needs_vision is False
    assert values["battery_kwh"] == 50.6
    assert values["power_kw"] == 155
    assert values["torque_nm"] == 288
    assert values["range_km"] == 405
    assert values["dc_charge_kw"] == 130
    assert values["width_mm"] == 1860
    assert values["length_mm"] == 4380
    assert values["height_mm"] == 1650
    assert values["wheelbase_mm"] == 2620
    assert values["tire_front"] == "235/55 R18"
    assert "AEB" in extraction.adas
