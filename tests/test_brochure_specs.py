from vehreg.brochure_specs import BrochureExtraction, _extract_direct, clean_text


J5_PAGE2 = """
รองรับผู้โดยสารจํานวน 5 ที่นั่ง
จอแสดงผลมาตรวัดขนาด 8 นิ้ว
จอแสดงผลแบบสัมผัสบริเวณคอนโซลกลาง ขนาด 13.2 นิ้ว
เครื่องเสียงพร้อมลําโพง 8 ตําแหน่ง
ฟังก์ชันชาร์จโทรศัพท์มือถือแบบไร้สาย 50 วัตต์
หลังคาพาโนรามิคซันรูฟ (Panoramic Fixed Glass Roof)
ระบบปิดบานประตูท้ายด้วยระบบไฟฟ้า
เบาะนั่งผู้ขับขี่พร้อมฟังก์ชันระบายอากาศ
กล้องแสดงภาพรอบทิศทางแบบ 540 องศา
ระบบช่วยเบรกฉุกเฉินอัตโนมัติ AEB
ระบบควบคุมความเร็วอัตโนมัติ ACC
ระบบเตือนการชนด้านหน้า FCW
ระบบเตือนการออกนอกเลน LDW
ระบบตรวจสอบจุดอับสายตา BSD
ระบบเตือนจุดอับสายตาขณะถอยหลัง RCTA
รูปแบบการขับเคลื่อน                     ขับเคลื่อนล้อหน้า
จํานวนมอเตอร์ไฟฟ้า                     1
กําลังมอเตอร์ไฟฟ้าสูงสุด (กิโลวัตต์ (แรงม้า)) 155 (211)
แรงบิดสูงสุดจากมอเตอร์ไฟฟ้า (นิวตันเมตร) 288
ความจุพลังงานแบตเตอรี่ไฟฟ้าแรงสูง (กิโลวัตต์-ชั่วโมง) 50.6
ระยะทางการขับเคลื่อน (กม.) (มาตรฐาน NEDC) 405
รองรับการชาร์จกระแสสลับ AC สูงสุด (กิโลวัตต์) 6.6
รองรับการชาร์จกระแสตรง DC สูงสุด (กิโลวัตต์) 130
อัตราเร่ง 0-100 กม./ชม. (วินาที) 7.7
ความเร็วสูงสุดโดยประมาณ (กม./ชม.) 175
พื้นที่บรรทุกสัมภาระด้านหน้า (ลิตร) 35
พื้นที่บรรทุกสัมภาระด้านหลัง (ลิตร) 480 - 1,284
มิติตัวถัง (กว้าง x ยาว x สูง) (มม.) 1,860 x 4,380 x 1,650
ระยะฐานล้อ (มม.) 2,620
ระยะต่ําสุดจากพื้น (มม.) 174
ขนาดล้อและยาง - หน้าและหลัง 235/55 R18
"""


def test_targeted_extractor_gets_j5_phase1_fields_without_price():
    result = BrochureExtraction()
    _extract_direct(clean_text(J5_PAGE2), result, 2)
    values = {k: v.value for k, v in result.fields.items()}

    assert values["drivetrain"] == "FWD"
    assert values["motor_count"] == 1
    assert values["power_kw"] == 155
    assert values["power_hp"] == 211
    assert values["torque_nm"] == 288
    assert values["battery_kwh"] == 50.6
    assert values["range_km"] == 405
    assert values["range_standard"] == "NEDC"
    assert values["ac_charge_kw"] == 6.6
    assert values["dc_charge_kw"] == 130
    assert values["acceleration_0_100_s"] == 7.7
    assert values["top_speed_kmh"] == 175
    assert values["width_mm"] == 1860
    assert values["length_mm"] == 4380
    assert values["height_mm"] == 1650
    assert values["wheelbase_mm"] == 2620
    assert values["ground_clearance_mm"] == 174
    assert values["tire_front"] == "235/55 R18"
    assert values["tire_rear"] == "235/55 R18"
    assert values["seats"] == 5
    assert values["instrument_screen_in"] == 8
    assert values["infotainment_screen_in"] == 13.2
    assert values["speaker_count"] == 8
    assert values["wireless_charge_w"] == 50
    assert values["panoramic_roof"] is True
    assert values["power_tailgate"] is True
    assert values["ventilated_front_seats"] is True
    assert values["camera_degrees"] == 540
    assert {"AEB", "ACC", "FCW", "LDW", "BSD", "RCTA"}.issubset(result.adas)
    assert not any("price" in key.lower() for key in values)


def test_missing_brochure_fields_stay_missing_not_false_or_zero():
    result = BrochureExtraction()
    _extract_direct("Model X\nBattery electric vehicle", result, 1)
    assert "battery_kwh" not in result.fields
    assert "panoramic_roof" not in result.fields
    assert "hud" not in result.fields
