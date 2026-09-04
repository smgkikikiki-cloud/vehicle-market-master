#!/usr/bin/env python3
"""Fill the 2026 catalog from what January's real DLT load could not place.

Every model here was taken from an actual unmatched label in
``data/raw/dlt_2026-01.csv``, not from memory. Prices and segments are still
seed values - they carry price_note="seed-unverified" and show up in
``vehreg catalog audit``.

Writes data/catalog/2026_additions.csv, which is then imported with
``python -m vehreg catalog import``. Keeping it as a CSV means the additions are
reviewable as a diff and re-runnable.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from vehreg import authoring                      # noqa: E402
from vehreg.catalog import Catalog                # noqa: E402

OUT = ROOT / "data" / "catalog" / "2026_additions.csv"

#: Brands whose DLT รุ่น field carries trim. Chinese marques plus Tesla.
TRIM_DETAIL_EXISTING = ["mg", "byd", "gwm", "neta", "changan", "aion", "chery",
                        "zeekr", "xpeng", "tesla"]

rows: list[dict] = []


def R(brand, model, variant, **kw):
    row = {"brand": brand, "model": model, "variant": variant,
           "price_note": "seed-unverified"}
    row.update(kw)
    rows.append(row)
    return row


def brand_defaults(**kw):
    """Fields repeated on every row of one brand."""
    return kw


# --------------------------------------------------------------- new brands
CN = dict(brand_origin="CN", trim_detail="true", brand_segment="MASS")

# Deepal and Jaecoo are their own ยี่ห้อ in the DLT feed, not sub-brands.
DEEPAL = dict(CN, brand_th="ดีพัล", oem_group="Changan")
R("Deepal", "Deepal S05", "51 kWh BEV", **DEEPAL, model_th="ดีพัล เอส05",
  body_type="CROSSOVER", segment="B", seats="5", launched="2025-06-01",
  powertrain="BEV", drivetrain="RWD", battery_kwh="51.5", price_thb="799000",
  import_type="CKD", origin_country="TH", model_aliases="s05")
R("Deepal", "Deepal S05", "1.5L REEV", **DEEPAL, powertrain="REEV",
  drivetrain="RWD", engine_cc="1500", battery_kwh="28.4", price_thb="899000",
  import_type="CKD", origin_country="TH")
R("Deepal", "Deepal S07", "80 kWh BEV", **DEEPAL, model_th="ดีพัล เอส07",
  body_type="CROSSOVER", segment="C", seats="5", launched="2024-03-01",
  powertrain="BEV", drivetrain="RWD", battery_kwh="79.9", price_thb="1359000",
  import_type="CKD", origin_country="TH", model_aliases="s07")
R("Deepal", "Deepal L07", "80 kWh BEV", **DEEPAL, model_th="ดีพัล แอล07",
  body_type="SEDAN", segment="D", seats="5", launched="2024-06-01",
  powertrain="BEV", drivetrain="RWD", battery_kwh="79.9", price_thb="1099000",
  import_type="CKD", origin_country="TH", model_aliases="l07")
R("Deepal", "Deepal E07", "89 kWh BEV", **DEEPAL, model_th="ดีพัล อี07",
  body_type="SUV", segment="D", seats="5", launched="2025-01-01",
  powertrain="BEV", drivetrain="AWD", battery_kwh="88.9", price_thb="1999000",
  import_type="CBU", origin_country="CN", model_aliases="e07")
R("Deepal", "Deepal Hunter K50", "1.5L PHEV", **DEEPAL,
  model_th="ดีพัล ฮันเตอร์", body_type="PICKUP", cab_type="DOUBLE_CAB",
  segment="F", seats="5", launched="2025-09-01", powertrain="PHEV",
  drivetrain="AWD", engine_cc="1500", battery_kwh="31.7", price_thb="1199000",
  import_type="CBU", origin_country="CN", model_aliases="hunter k50|hunter")

JAECOO = dict(CN, brand_th="เจคู", oem_group="Chery")
R("Jaecoo", "Jaecoo 5 EV", "61 kWh BEV", **JAECOO, model_th="เจคู 5",
  body_type="CROSSOVER", segment="B", seats="5", launched="2025-09-01",
  powertrain="BEV", drivetrain="FWD", battery_kwh="60.9", price_thb="799000",
  import_type="CKD", origin_country="TH", model_aliases="5 ev|jaecoo 5")
R("Jaecoo", "Jaecoo 6 EV", "69 kWh BEV", **JAECOO, model_th="เจคู 6",
  body_type="CROSSOVER", segment="B", seats="5", launched="2025-11-01",
  powertrain="BEV", drivetrain="FWD", battery_kwh="69.0", price_thb="999000",
  import_type="CKD", origin_country="TH", model_aliases="6 ev|jaecoo 6")
R("Jaecoo", "Jaecoo 6T EV", "69 kWh BEV AWD", **JAECOO, model_th="เจคู 6ที",
  body_type="CROSSOVER", segment="C", seats="5", launched="2025-11-01",
  powertrain="BEV", drivetrain="AWD", battery_kwh="69.0", price_thb="1099000",
  import_type="CKD", origin_country="TH", model_aliases="6t ev|jaecoo 6t")
R("Jaecoo", "Jaecoo 7", "1.5L PHEV", **JAECOO, model_th="เจคู 7",
  body_type="CROSSOVER", segment="C", seats="5", launched="2024-09-01",
  powertrain="PHEV", drivetrain="FWD", engine_cc="1500", battery_kwh="18.3",
  price_thb="1099000", import_type="CKD", origin_country="TH",
  model_aliases="7 shs|jaecoo 7|j7")

GEELY = dict(CN, brand_th="จีลี่", oem_group="Geely")
R("Geely", "Geely EX5", "60 kWh BEV", **GEELY, model_th="จีลี่ อีเอ็กซ์5",
  body_type="CROSSOVER", segment="C", seats="5", launched="2025-08-01",
  powertrain="BEV", drivetrain="FWD", battery_kwh="60.2", price_thb="949000",
  import_type="CKD", origin_country="TH", model_aliases="ex5")

DENZA = dict(CN, brand_th="เด็นซ่า", oem_group="BYD",
             brand_segment="PREMIUM_LUXURY")
R("Denza", "Denza D9", "1.5L PHEV", **DENZA, model_th="เด็นซ่า ดี9",
  body_type="MPV", segment="E", seats="7", launched="2025-06-01",
  powertrain="PHEV", drivetrain="FWD", engine_cc="1500", battery_kwh="18.3",
  price_thb="1899000", import_type="CBU", origin_country="CN",
  model_aliases="d9|denza d9")
R("Denza", "Denza D9", "103 kWh BEV AWD", **DENZA, powertrain="BEV",
  drivetrain="AWD", battery_kwh="103.0", price_thb="2399000",
  import_type="CBU", origin_country="CN")

WULING = dict(CN, brand_th="หวูหลิง", oem_group="SAIC-GM-Wuling",
              brand_segment="BUDGET")
R("Wuling", "Wuling Bingo", "32 kWh BEV", **WULING, model_th="หวูหลิง บิงโก",
  body_type="HATCHBACK", segment="A", seats="5", launched="2024-06-01",
  powertrain="BEV", drivetrain="FWD", battery_kwh="31.9", price_thb="499000",
  import_type="CKD", origin_country="TH",
  model_aliases="bingo|binguo|bingou")
R("Wuling", "Wuling Air EV", "27 kWh BEV", **WULING, model_th="หวูหลิง แอร์ อีวี",
  body_type="HATCHBACK", segment="A", seats="4", launched="2022-08-01",
  powertrain="BEV", drivetrain="RWD", battery_kwh="26.7", price_thb="399000",
  import_type="CKD", origin_country="TH", model_aliases="air ev")

AVATR = dict(CN, brand_th="อาวาตาร์", oem_group="Changan",
             brand_segment="PREMIUM_TECH")
R("Avatr", "Avatr 11", "90 kWh BEV", **AVATR, model_th="อาวาตาร์ 11",
  body_type="CROSSOVER", segment="D", seats="5", launched="2024-06-01",
  powertrain="BEV", drivetrain="AWD", battery_kwh="90.4", price_thb="2599000",
  import_type="CBU", origin_country="CN", model_aliases="avatr 11|11")

GAC = dict(CN, brand_th="จีเอซี", oem_group="GAC")
R("GAC", "GAC M8", "2.0L PHEV", **GAC, model_th="จีเอซี เอ็ม8",
  body_type="MPV", segment="E", seats="7", launched="2025-01-01",
  powertrain="PHEV", drivetrain="FWD", engine_cc="1998", battery_kwh="25.6",
  price_thb="2399000", import_type="CBU", origin_country="CN",
  model_aliases="m8")

LEAP = dict(CN, brand_th="ลีปมอเตอร์", oem_group="Leapmotor")
R("Leapmotor", "Leapmotor B10", "67 kWh BEV", **LEAP, model_th="ลีปมอเตอร์ บี10",
  body_type="CROSSOVER", segment="B", seats="5", launched="2025-10-01",
  powertrain="BEV", drivetrain="RWD", battery_kwh="67.1", price_thb="899000",
  import_type="CKD", origin_country="TH", model_aliases="b10")
R("Leapmotor", "Leapmotor C10", "70 kWh BEV", **LEAP, model_th="ลีปมอเตอร์ ซี10",
  body_type="CROSSOVER", segment="C", seats="5", launched="2025-03-01",
  powertrain="BEV", drivetrain="RWD", battery_kwh="69.9", price_thb="1199000",
  import_type="CKD", origin_country="TH", model_aliases="c10")

RIDDARA = dict(CN, brand_th="ริดดารา", oem_group="Geely")
R("Riddara", "Riddara RD6 Double Cab", "86 kWh BEV", **RIDDARA,
  model_th="ริดดารา อาร์ดี6", nameplate="RD6", body_type="PICKUP",
  cab_type="DOUBLE_CAB", segment="F", seats="5", launched="2024-09-01",
  powertrain="BEV", drivetrain="RWD", battery_kwh="86.0", price_thb="1299000",
  import_type="CBU", origin_country="CN", model_aliases="rd6")
R("Riddara", "Riddara Horizon Double Cab", "88 kWh BEV AWD", **RIDDARA,
  model_th="ริดดารา ฮอไรซัน", nameplate="Horizon", body_type="PICKUP",
  cab_type="DOUBLE_CAB", segment="F", seats="5", launched="2025-11-01",
  powertrain="BEV", drivetrain="AWD", battery_kwh="88.0", price_thb="1399000",
  import_type="CBU", origin_country="CN", model_aliases="horizon")

# ------------------------------------------- new models for existing brands
R("MG", "MG S5 EV", "62 kWh BEV", model_th="เอ็มจี เอส5", body_type="CROSSOVER",
  segment="C", seats="5", launched="2025-06-01", powertrain="BEV",
  drivetrain="RWD", battery_kwh="62.0", price_thb="899000", import_type="CKD",
  origin_country="TH", model_aliases="s5 ev|s5")
R("MG", "MG IM6", "100 kWh BEV", model_th="เอ็มจี ไอเอ็ม6", body_type="CROSSOVER",
  segment="D", seats="5", launched="2025-09-01", powertrain="BEV",
  drivetrain="RWD", battery_kwh="100.0", price_thb="1899000",
  import_type="CBU", origin_country="CN", model_aliases="im6")
R("MG", "MG EP", "50 kWh BEV", model_th="เอ็มจี อีพี", body_type="WAGON",
  segment="B", seats="5", launched="2020-01-01", powertrain="BEV",
  drivetrain="FWD", battery_kwh="50.3", price_thb="799000", import_type="CKD",
  origin_country="TH", model_aliases="ep")
R("MG", "MG Maxus 7", "2.0L ICE", model_th="เอ็มจี แม็กซัส 7", body_type="MPV",
  segment="D", seats="7", launched="2025-01-01", powertrain="ICE",
  drivetrain="RWD", engine_cc="1996", price_thb="1399000", import_type="CBU",
  origin_country="CN", model_aliases="maxus 7")
R("MG", "MG Cyberster", "77 kWh BEV", model_th="เอ็มจี ไซเบอร์สเตอร์",
  body_type="COUPE", segment="D", seats="2", launched="2024-11-01",
  market_scope="NICHE", powertrain="BEV", drivetrain="AWD",
  battery_kwh="77.0", price_thb="3599000", import_type="CBU",
  origin_country="CN", model_aliases="cyberster")

R("Aion", "Aion UT", "44 kWh BEV", model_th="ไอออน ยูที", body_type="HATCHBACK",
  segment="B", seats="5", launched="2025-11-01", powertrain="BEV",
  drivetrain="FWD", battery_kwh="44.2", price_thb="459000", import_type="CKD",
  origin_country="TH", model_aliases="ut|aion ut")
R("Aion", "Aion UT", "53 kWh BEV", powertrain="BEV", drivetrain="FWD",
  battery_kwh="52.9", price_thb="559000", import_type="CKD",
  origin_country="TH")
R("Aion", "Hyptec HT", "77 kWh BEV", model_th="ไฮเทค เอชที",
  body_type="CROSSOVER", segment="D", seats="5", launched="2025-06-01",
  powertrain="BEV", drivetrain="RWD", battery_kwh="76.8", price_thb="1299000",
  import_type="CBU", origin_country="CN", model_aliases="hyptec ht|hyptec")

R("Chery", "Chery V23", "60 kWh BEV", model_th="เชอรี่ วี23", body_type="SUV",
  segment="B", seats="5", launched="2025-10-01", powertrain="BEV",
  drivetrain="RWD", battery_kwh="60.0", price_thb="799000", import_type="CKD",
  origin_country="TH", model_aliases="v23")
R("Chery", "Chery V23", "60 kWh BEV AWD", powertrain="BEV", drivetrain="AWD",
  battery_kwh="60.0", price_thb="899000", import_type="CKD",
  origin_country="TH")

R("Changan", "Changan Lumin", "33 kWh BEV", model_th="ฉางอาน ลูมิน",
  body_type="HATCHBACK", segment="A", seats="4", launched="2025-01-01",
  powertrain="BEV", drivetrain="FWD", battery_kwh="32.8", price_thb="479000",
  import_type="CKD", origin_country="TH", model_aliases="lumin")

# ----------------------------------------------------- Toyota: Hilux Travo
# A separate nameplate from Revo, so it splits the same two ways - double cab
# is รย.1, everything else รย.3 - and rolls up under the same Hilux nameplate.
for name, cab, cab_th, seats, price, extra in (
    ("Hilux Travo Cab", "SINGLE_SMART", "ตอนเดียว/แค็บ", "4", "599000",
     "travo cab|travo ตอนเดียว|travo แค็บ"),
    ("Hilux Travo Double Cab", "DOUBLE_CAB", "4 ประตู", "5", "799000",
     "travo double cab|travo 4 ประตู"),
):
    R("Toyota", name, "2.4L ICE", nameplate="Hilux",
      model_th=f"ไฮลักซ์ ทราโว่ {cab_th}", body_type="PICKUP", cab_type=cab,
      segment="F", seats=seats, launched="2025-07-01", powertrain="ICE",
      drivetrain="RWD", engine_cc="2393", price_thb=price, import_type="CKD",
      origin_country="TH", model_aliases=f"Hilux Travo|travo|{extra}")

# ------------------------------------------------- fleet vans and trucks
R("Toyota", "Commuter", "2.8L ICE", model_th="คอมมิวเตอร์", body_type="VAN",
  registration_type="RY2", market_scope="COMMERCIAL", segment="E", seats="15",
  launched="2019-01-01", powertrain="ICE", drivetrain="RWD", engine_cc="2755",
  price_thb="1398000", import_type="CKD", origin_country="TH",
  model_aliases="commuter")
R("Toyota", "Hiace", "2.8L ICE", model_th="ไฮเอซ", body_type="VAN",
  registration_type="RY2", market_scope="COMMERCIAL", segment="E", seats="11",
  launched="2019-01-01", powertrain="ICE", drivetrain="RWD", engine_cc="2755",
  price_thb="1299000", import_type="CBU", origin_country="JP",
  model_aliases="hiace")
R("Toyota", "Hiace Majesty", "2.8L ICE", model_th="ไฮเอซ มาเจสตี้",
  body_type="VAN", registration_type="RY2", market_scope="NICHE", segment="E",
  seats="9", launched="2022-01-01", powertrain="ICE", drivetrain="RWD",
  engine_cc="2755", price_thb="2299000", import_type="CBU",
  origin_country="JP", model_aliases="hiace majesty|majesty")
R("Toyota", "Vellfire", "2.5L HEV", model_th="เวลไฟร์", body_type="MPV",
  market_scope="NICHE", segment="E", seats="7", launched="2023-09-01",
  powertrain="HEV", drivetrain="AWD", engine_cc="2487", battery_kwh="1.0",
  price_thb="4299000", import_type="CBU", origin_country="JP",
  model_aliases="vellfire")

# Grey-market Toyotas: real registrations, not the official line-up.
for name, th, body, seg, seats in (
    ("Crown", "คราวน์", "SEDAN", "E", "5"),
    ("Harrier", "แฮริเออร์", "CROSSOVER", "D", "5"),
    ("Voxy", "วอกซี่", "MPV", "C", "7"),
    ("Noah", "โนอาห์", "MPV", "C", "7"),
    ("C-HR", "ซี-เอชอาร์", "CROSSOVER", "B", "5"),
):
    R("Toyota", name, "grey import", model_th=th, body_type=body,
      market_scope="GREY", segment=seg, seats=seats, launched="2023-01-01",
      powertrain="UNKNOWN", price_note="grey import, spec not tracked")
for name, th in (("GR86", "จีอาร์86"), ("GR Supra", "จีอาร์ ซูปร้า")):
    R("Toyota", name, "coupe", model_th=th, body_type="COUPE",
      market_scope="NICHE", segment="D", seats="4", launched="2022-01-01",
      powertrain="ICE", drivetrain="RWD", engine_cc="2387",
      price_thb="2599000", import_type="CBU", origin_country="JP",
      model_aliases=name.replace(" ", ""))

R("Isuzu", "Isuzu Elf", "3.0L ICE", model_th="อีซูซุ เอลฟ์", body_type="TRUCK",
  market_scope="COMMERCIAL", segment="UNKNOWN", seats="3",
  launched="2019-01-01", powertrain="ICE", drivetrain="RWD", engine_cc="2999",
  price_thb="1050000", import_type="CKD", origin_country="TH",
  model_aliases="NLR|NPR|NMR|NKR|elf")
R("Isuzu", "Isuzu F-Series", "7.8L ICE", model_th="อีซูซุ เอฟ-ซีรีส์",
  body_type="TRUCK", market_scope="COMMERCIAL", segment="UNKNOWN", seats="3",
  launched="2019-01-01", powertrain="ICE", drivetrain="RWD", engine_cc="7790",
  price_thb="2500000", import_type="CKD", origin_country="TH",
  model_aliases="FTR|FVZ|FRR|FXZ|FVM|GVR")
R("Suzuki", "Suzuki Carry", "1.5L ICE", model_th="ซูซูกิ แครี่",
  body_type="TRUCK", market_scope="COMMERCIAL", segment="UNKNOWN", seats="2",
  launched="2019-01-01", powertrain="ICE", drivetrain="RWD", engine_cc="1462",
  price_thb="399000", import_type="CKD", origin_country="TH",
  model_aliases="carry")

TRUCKS = dict(body_type="TRUCK", market_scope="COMMERCIAL", segment="UNKNOWN",
              seats="3", launched="2020-01-01", powertrain="ICE",
              drivetrain="RWD", engine_cc="5193", import_type="CKD",
              origin_country="TH", price_thb="1500000")
R("Hino", "Hino Truck", "diesel", brand_th="ฮีโน่", brand_segment="MASS",
  oem_group="Toyota Group", brand_origin="JP", model_th="ฮีโน่ ทรัค",
  model_aliases="XZU|FG|FM|FC|FL|FS|SG", **TRUCKS)
R("Foton", "Foton Truck", "diesel", brand_th="โฟตอน", brand_segment="BUDGET",
  oem_group="Foton", brand_origin="CN", model_th="โฟตอน ทรัค",
  model_aliases="BJ", **TRUCKS)
R("JAC", "JAC Truck", "electric", brand_th="เจเอซี", brand_segment="BUDGET",
  oem_group="JAC", brand_origin="CN", model_th="เจเอซี ทรัค",
  model_aliases="HFC", **dict(TRUCKS, powertrain="BEV", engine_cc="",
                              battery_kwh="80"))
R("Tata", "Tata Super Ace", "diesel", brand_th="ทาทา", brand_segment="BUDGET",
  oem_group="Tata", brand_origin="IN", model_th="ทาทา ซูเปอร์เอซ",
  model_aliases="super ace", **dict(TRUCKS, engine_cc="1396",
                                    price_thb="459000"))
R("UD Trucks", "UD Truck", "diesel", brand_th="ยูดี", brand_segment="MASS",
  oem_group="Volvo Group", brand_origin="JP", model_th="ยูดี ทรัค",
  model_aliases="CWE|PKE|GKE|QKE", **TRUCKS)

# --------------------------------------------------- other volume additions
R("Nissan", "Serena", "1.4L REEV", model_th="เซเรน่า", body_type="MPV",
  market_scope="GREY", segment="C", seats="8", launched="2023-01-01",
  powertrain="REEV", drivetrain="FWD", engine_cc="1433", battery_kwh="1.8",
  price_note="grey import", model_aliases="serena")
R("Nissan", "X-Trail", "1.5L REEV", model_th="เอ็กซ์-เทรล",
  body_type="CROSSOVER", segment="C", seats="5", launched="2023-01-01",
  powertrain="REEV", drivetrain="FWD", engine_cc="1497", battery_kwh="2.1",
  price_thb="1599000", import_type="CBU", origin_country="JP",
  model_aliases="x-trail|xtrail|x trial|x-trial")
R("Hyundai", "Santa Fe", "1.6L HEV", model_th="ซานตาเฟ", body_type="CROSSOVER",
  segment="D", seats="7", launched="2024-06-01", powertrain="HEV",
  drivetrain="AWD", engine_cc="1598", battery_kwh="1.5", price_thb="2299000",
  import_type="CBU", origin_country="KR", model_aliases="santa fe")
R("Hyundai", "Palisade", "2.2L ICE", model_th="พาลิเสด", body_type="SUV",
  segment="E", seats="7", launched="2025-06-01", powertrain="ICE",
  drivetrain="AWD", engine_cc="2199", price_thb="2799000", import_type="CBU",
  origin_country="KR", model_aliases="palisade")
R("Hyundai", "H-1", "2.5L ICE", model_th="เอช-1", body_type="VAN",
  registration_type="RY2", market_scope="COMMERCIAL", segment="E", seats="11",
  launched="2018-01-01", powertrain="ICE", drivetrain="RWD", engine_cc="2497",
  price_thb="1799000", import_type="CBU", origin_country="KR",
  model_aliases="h-1|h1")
R("Kia", "EV5", "88 kWh BEV", model_th="อีวี5", body_type="CROSSOVER",
  segment="D", seats="5", launched="2025-09-01", powertrain="BEV",
  drivetrain="FWD", battery_kwh="88.1", price_thb="1899000",
  import_type="CBU", origin_country="CN", model_aliases="ev5")
R("Kia", "Sorento", "1.6L HEV", model_th="โซเรนโต", body_type="SUV",
  segment="D", seats="7", launched="2024-01-01", powertrain="HEV",
  drivetrain="AWD", engine_cc="1598", battery_kwh="1.5", price_thb="2399000",
  import_type="CBU", origin_country="KR", model_aliases="sorento")

for name, th, body, seg, pt, kwh, cc, price in (
    ("EX40", "อีเอ็กซ์40", "CROSSOVER", "C", "BEV", "78", "", "2190000"),
    ("EC40", "อีซี40", "CROSSOVER", "C", "BEV", "78", "", "2290000"),
    ("EX90", "อีเอ็กซ์90", "SUV", "E", "BEV", "111", "", "4990000"),
    ("S60", "เอส60", "SEDAN", "D", "PHEV", "18.8", "1969", "2590000"),
    ("S90", "เอส90", "SEDAN", "E", "PHEV", "18.8", "1969", "3490000"),
    ("V60", "วี60", "WAGON", "D", "PHEV", "18.8", "1969", "2790000"),
):
    R("Volvo", name, "spec", model_th=th, body_type=body, segment=seg,
      seats="5", launched="2024-01-01", powertrain=pt,
      drivetrain="AWD" if pt == "PHEV" else "RWD", engine_cc=cc,
      battery_kwh=kwh, price_thb=price, import_type="CKD",
      origin_country="TH", model_aliases=name)

R("MINI", "Aceman", "54 kWh BEV", model_th="เอซแมน", body_type="CROSSOVER",
  segment="B", seats="5", launched="2024-09-01", powertrain="BEV",
  drivetrain="FWD", battery_kwh="54.2", price_thb="2399000",
  import_type="CBU", origin_country="CN", model_aliases="aceman|jcw aceman")
R("Peugeot", "Peugeot 2008", "1.2L ICE", brand_th="เปอโยต์",
  brand_segment="MASS", oem_group="Stellantis", brand_origin="FR",
  model_th="เปอโยต์ 2008", body_type="CROSSOVER", segment="B", seats="5",
  launched="2021-01-01", powertrain="ICE", drivetrain="FWD", engine_cc="1199",
  price_thb="1099000", import_type="CBU", origin_country="FR",
  model_aliases="2008")
R("Peugeot", "Peugeot 3008", "1.6L PHEV", model_th="เปอโยต์ 3008",
  body_type="CROSSOVER", segment="C", seats="5", launched="2021-01-01",
  powertrain="PHEV", drivetrain="FWD", engine_cc="1598", battery_kwh="13.2",
  price_thb="1899000", import_type="CBU", origin_country="FR",
  model_aliases="3008")
R("Mine Mobility", "Mine MTS", "30 kWh BEV", brand_th="มายน์",
  brand_segment="BUDGET", oem_group="EA", brand_origin="TH",
  model_th="มายน์ เอ็มทีเอส", body_type="MPV", market_scope="COMMERCIAL",
  segment="C", seats="5", launched="2020-01-01", powertrain="BEV",
  drivetrain="FWD", battery_kwh="30.0", price_thb="1190000",
  import_type="CKD", origin_country="TH", model_aliases="mts|mts-mt30")

for name, th, body, seg, seats in (("LBX", "แอลบีเอ็กซ์", "CROSSOVER", "B", "5"),
                                   ("UX", "ยูเอ็กซ์", "CROSSOVER", "C", "5"),
                                   ("RZ", "อาร์แซด", "CROSSOVER", "D", "5")):
    R("Lexus", name, "spec", model_th=th, body_type=body, segment=seg,
      seats=seats, launched="2024-01-01", powertrain="HEV", drivetrain="FWD",
      engine_cc="1490", battery_kwh="1.0", price_thb="2490000",
      import_type="CBU", origin_country="JP", model_aliases=name)
R("Lexus", "LX", "3.4L ICE", model_th="แอลเอ็กซ์", body_type="PPV",
  market_scope="NICHE", segment="E", seats="7", launched="2022-01-01",
  powertrain="ICE", drivetrain="4WD", engine_cc="3444", price_thb="7990000",
  import_type="CBU", origin_country="JP", model_aliases="lx|lx600")
R("Lexus", "LC", "5.0L ICE", model_th="แอลซี", body_type="COUPE",
  market_scope="NICHE", segment="E", seats="4", launched="2018-01-01",
  powertrain="ICE", drivetrain="RWD", engine_cc="4969", price_thb="12900000",
  import_type="CBU", origin_country="JP", model_aliases="lc|lc500")

R("Porsche", "Panamera", "2.9L PHEV", model_th="พานาเมร่า", body_type="SEDAN",
  market_scope="NICHE", segment="E", seats="4", launched="2024-01-01",
  powertrain="PHEV", drivetrain="AWD", engine_cc="2894", battery_kwh="25.9",
  price_thb="9900000", import_type="CBU", origin_country="DE",
  model_aliases="panamera")
R("Porsche", "Taycan", "89 kWh BEV", model_th="ไทคานน์", body_type="SEDAN",
  market_scope="NICHE", segment="E", seats="4", launched="2020-01-01",
  powertrain="BEV", drivetrain="AWD", battery_kwh="89.0",
  price_thb="7500000", import_type="CBU", origin_country="DE",
  model_aliases="taycan")
R("Porsche", "718", "4.0L ICE", model_th="718", body_type="COUPE",
  market_scope="NICHE", segment="D", seats="2", launched="2020-01-01",
  powertrain="ICE", drivetrain="RWD", engine_cc="3995", price_thb="7900000",
  import_type="CBU", origin_country="DE", model_aliases="718|cayman|boxster")

EXOTIC = dict(market_scope="NICHE", brand_segment="PERFORMANCE",
              import_type="CBU", seats="2", launched="2022-01-01",
              powertrain="ICE", drivetrain="AWD", engine_cc="3990",
              price_thb="25000000")
for brand, th, origin, models in (
    ("Ferrari", "เฟอร์รารี", "IT", ["296", "12Cilindri", "F8", "Roma", "SF90"]),
    ("Lamborghini", "ลัมโบร์กีนี", "IT", ["Urus", "Huracan", "Revuelto"]),
    ("McLaren", "แมคลาเรน", "GB", ["GTS"]),
    ("Lotus", "โลตัส", "GB", ["Eletre", "Emeya"]),
    ("Maserati", "มาเซราติ", "IT", ["Grecale", "Levante", "GranTurismo"]),
):
    for model in models:
        R(brand, model, "spec", brand_th=th, brand_origin=origin,
          oem_group=brand, model_th=model, body_type="COUPE", segment="D",
          model_aliases=model, **EXOTIC)
for brand, th, origin, models in (
    ("Bentley", "เบนท์ลีย์", "GB", ["Bentayga", "Flying Spur"]),
    ("Rolls-Royce", "โรลส์-รอยซ์", "GB", ["Ghost"]),
):
    for model in models:
        R(brand, model, "spec", brand_th=th, brand_origin=origin,
          oem_group="BMW Group" if brand == "Rolls-Royce" else "Volkswagen Group",
          model_th=model, body_type="SEDAN", segment="E", seats="5",
          market_scope="NICHE", brand_segment="PREMIUM_LUXURY",
          launched="2022-01-01", powertrain="PHEV", drivetrain="AWD",
          engine_cc="3996", battery_kwh="18.0", price_thb="25000000",
          import_type="CBU", model_aliases=model)
R("Land Rover", "Defender", "3.0L MHEV", brand_th="แลนด์โรเวอร์",
  brand_segment="PREMIUM_LUXURY", oem_group="JLR", brand_origin="GB",
  model_th="ดีเฟนเดอร์", body_type="SUV", market_scope="NICHE", segment="E",
  seats="5", launched="2020-01-01", powertrain="MHEV", drivetrain="AWD",
  engine_cc="2996", battery_kwh="0.5", price_thb="6900000",
  import_type="CBU", origin_country="GB", model_aliases="defender")
R("Land Rover", "Range Rover", "3.0L MHEV", model_th="เรนจ์โรเวอร์",
  body_type="SUV", market_scope="NICHE", segment="E", seats="5",
  launched="2022-01-01", powertrain="MHEV", drivetrain="AWD",
  engine_cc="2996", battery_kwh="0.5", price_thb="12900000",
  import_type="CBU", origin_country="GB",
  model_aliases="range rover|evoque|velar|range rover sport")
R("Jeep", "Wrangler", "2.0L ICE", brand_th="จี๊ป", brand_segment="MASS",
  oem_group="Stellantis", brand_origin="US", model_th="แรงเลอร์",
  body_type="SUV", market_scope="NICHE", segment="D", seats="5",
  launched="2020-01-01", powertrain="ICE", drivetrain="4WD", engine_cc="1995",
  price_thb="4290000", import_type="CBU", origin_country="US",
  model_aliases="wrangler|rubicon")

# ---------------------------------------------- German premium: real labels
# DLT writes the engine badge, not the range name: "C 220 d", "520d M Sport
# Pro", "iX1 eDrive20L". Each of those has to reach the right nameplate.
MB = dict(brand_segment="PREMIUM_LUXURY", oem_group="Mercedes-Benz Group",
          brand_origin="DE", import_type="CKD", origin_country="TH",
          seats="5", launched="2023-01-01")
for model, th, body, seg, pt, cc, kwh, price, aliases in (
    ("A-Class", "เอ-คลาส", "HATCHBACK", "C", "ICE", "1332", "", "2190000",
     "A 200|A200|A 250"),
    ("CLE", "ซีแอลอี", "COUPE", "D", "MHEV", "1999", "0.9", "3990000",
     "CLE 300|CLE 200|AMG CLE 53|MERCEDES-AMG CLE 53"),
    ("CLS", "ซีแอลเอส", "COUPE", "E", "MHEV", "1993", "0.9", "4290000",
     "CLS 220 d|CLS 300 d|AMG CLS 53"),
    ("GLB", "จีแอลบี", "CROSSOVER", "C", "ICE", "1332", "", "2790000",
     "GLB 200|GLB 220"),
    ("GLE", "จีแอลอี", "SUV", "E", "MHEV", "1993", "0.9", "5290000",
     "GLE 300 d|GLE 350 de|GLE 450|AMG GLE 53|MERCEDES-AMG GLE 53"),
    ("GLS", "จีแอลเอส", "SUV", "E", "MHEV", "2925", "0.9", "8290000",
     "GLS 350 d|GLS 450 d|GLS 450"),
    ("S-Class", "เอส-คลาส", "SEDAN", "E", "PHEV", "2999", "28.6", "8990000",
     "S 350 d|S 450|S 500|S 580 e|Maybach S 580 e"),
    ("EQE", "อีคิวอี", "SEDAN", "E", "BEV", "", "90.6", "4290000",
     "EQE 300|EQE 350|AMG EQE 53|EQE 350 4MATIC SUV"),
    ("V-Class", "วี-คลาส", "VAN", "E", "ICE", "1950", "", "4990000",
     "V 300 d|V 250"),
    ("Vito", "วีโต้", "VAN", "E", "ICE", "1950", "", "2790000",
     "VITO 119 CDI|VITO 119"),
    ("Sprinter", "สปรินเตอร์", "VAN", "E", "ICE", "2143", "", "2990000",
     "SPRINTER 419 CDI|SPRINTER 319 CDI|SPRINTER 388"),
    ("G-Class", "จี-คลาส", "SUV", "E", "ICE", "2925", "", "12900000",
     "G 450 D|G 450 d|G400 D|G450 D|AMG G 63"),
):
    scope = "COMMERCIAL" if model in {"Vito", "Sprinter"} else (
        "NICHE" if model in {"G-Class", "GLS"} else "CORE")
    R("Mercedes-Benz", model, "spec", **MB, model_th=th, body_type=body,
      segment=seg, powertrain=pt, drivetrain="RWD", engine_cc=cc,
      battery_kwh=kwh, price_thb=price, market_scope=scope,
      registration_type="RY2" if body == "VAN" else "",
      model_aliases=aliases)

BMW = dict(brand_segment="PREMIUM_LUXURY", oem_group="BMW Group",
           brand_origin="DE", import_type="CKD", origin_country="TH",
           seats="5", launched="2023-01-01")
for model, th, body, seg, pt, cc, kwh, price, aliases in (
    ("2 Series Gran Coupe", "ซีรีส์ 2", "SEDAN", "C", "ICE", "1998", "",
     "2390000", "220 Gran Coupe|220i Gran Coupe|218i"),
    ("4 Series", "ซีรีส์ 4", "COUPE", "D", "ICE", "1998", "", "3690000",
     "430i|420i|M440i|430i Coupe|430i Convertible|430i Cabrio"),
    ("7 Series", "ซีรีส์ 7", "SEDAN", "E", "PHEV", "2998", "18.7", "7990000",
     "740d|750e|M760e|i7 xDrive60|i7 eDrive50"),
    ("X4", "เอ็กซ์4", "CROSSOVER", "D", "MHEV", "1995", "0.5", "3990000",
     "X4 xDrive20d|X4 M"),
    ("X5", "เอ็กซ์5", "SUV", "E", "PHEV", "2998", "25.7", "5490000",
     "X5 xDrive30d|X5 xDrive50e"),
    ("X6", "เอ็กซ์6", "SUV", "E", "MHEV", "2998", "0.5", "5990000",
     "X6 xDrive40i"),
    ("X7", "เอ็กซ์7", "SUV", "E", "MHEV", "2993", "0.5", "6990000",
     "X7 xDrive40d|X7 M50d"),
    ("i5", "ไอ5", "SEDAN", "E", "BEV", "", "81.2", "4990000",
     "i5 eDrive40|i5 M60|i5 eDrive40 Touring"),
    ("iX", "ไอเอ็กซ์", "SUV", "E", "BEV", "", "111.5", "5990000",
     "iX xDrive50|iX xDrive40"),
    ("iX1", "ไอเอ็กซ์1", "CROSSOVER", "C", "BEV", "", "66.5", "2599000",
     "iX1 eDrive20L|iX1 xDrive30"),
    ("Z4", "แซด4", "COUPE", "D", "ICE", "1998", "", "4290000",
     "Z4 sDrive30i"),
    ("XM", "เอ็กซ์เอ็ม", "SUV", "E", "PHEV", "2998", "25.7", "12900000",
     "XM 50e"),
):
    R("BMW", model, "spec", **BMW, model_th=th, body_type=body, segment=seg,
      powertrain=pt, drivetrain="AWD", engine_cc=cc, battery_kwh=kwh,
      price_thb=price, model_aliases=aliases,
      market_scope="NICHE" if model in {"XM", "Z4"} else "CORE")

AUDI = dict(brand_segment="PREMIUM_LUXURY", oem_group="Volkswagen Group",
            brand_origin="DE", import_type="CBU", origin_country="DE",
            seats="5", launched="2023-01-01", market_scope="NICHE")
for model, th, body, seg, cc, price, aliases in (
    ("A1", "เอ1", "HATCHBACK", "B", "1498", "2290000", "A1 SB"),
    ("A4", "เอ4", "SEDAN", "D", "1984", "3290000", "A4 AV|A4"),
    ("A5", "เอ5", "COUPE", "D", "1984", "3690000", "A5 CP|A5 SB|A5 Avant|A5"),
    ("A7", "เอ7", "SEDAN", "E", "2995", "5490000", "A7 SB"),
    ("A8", "เอ8", "SEDAN", "E", "2995", "8990000", "A8L|A8"),
    ("Q8", "คิว8", "SUV", "E", "2995", "6490000", "Q8 SB|Q8 etron|Q8"),
    ("TT", "ทีที", "COUPE", "C", "1984", "3990000", "TT Coupe|TT RS|TT"),
    ("RS", "อาร์เอส", "SEDAN", "D", "2894", "8990000",
     "RS 4|RS 5|RS 7|RS Q8|S3"),
):
    R("Audi", model, "spec", **AUDI, model_th=th, body_type=body, segment=seg,
      powertrain="MHEV", drivetrain="AWD", engine_cc=cc, battery_kwh="0.5",
      price_thb=price, model_aliases=aliases)

# ------------------------------------------------------- long tail, by label
R("Honda", "Step WGN", "2.0L HEV", model_th="สเต็ปแวกอน", body_type="MPV",
  market_scope="GREY", segment="C", seats="7", launched="2022-01-01",
  powertrain="HEV", drivetrain="FWD", engine_cc="1993", battery_kwh="1.1",
  price_note="grey import", model_aliases="step wgn|stepwgn")
R("Honda", "Odyssey", "2.0L HEV", model_th="โอดิสซี", body_type="MPV",
  market_scope="GREY", segment="D", seats="7", launched="2021-01-01",
  powertrain="HEV", drivetrain="FWD", engine_cc="1993", battery_kwh="1.1",
  price_note="grey import", model_aliases="odyssey")
R("Mazda", "Mazda6", "2.5L ICE", model_th="มาสด้า6", body_type="SEDAN",
  market_scope="NICHE", segment="D", seats="5", launched="2018-01-01",
  powertrain="ICE", drivetrain="FWD", engine_cc="2488", price_thb="1890000",
  import_type="CBU", origin_country="JP", model_aliases="mazda 6")
R("Mazda", "MX-5", "2.0L ICE", model_th="เอ็มเอ็กซ์-5", body_type="COUPE",
  market_scope="NICHE", segment="B", seats="2", launched="2019-01-01",
  powertrain="ICE", drivetrain="RWD", engine_cc="1998", price_thb="2790000",
  import_type="CBU", origin_country="JP", model_aliases="mx-5|roadster")
R("Subaru", "BRZ", "2.4L ICE", model_th="บีอาร์แซด", body_type="COUPE",
  market_scope="NICHE", segment="D", seats="4", launched="2022-01-01",
  powertrain="ICE", drivetrain="RWD", engine_cc="2387", price_thb="2390000",
  import_type="CBU", origin_country="JP", model_aliases="brz")
R("Subaru", "Outback", "2.5L ICE", model_th="เอาท์แบ็ค", body_type="WAGON",
  market_scope="NICHE", segment="D", seats="5", launched="2021-01-01",
  powertrain="ICE", drivetrain="AWD", engine_cc="2498", price_thb="2290000",
  import_type="CBU", origin_country="JP", model_aliases="outback")
R("Mitsubishi", "Outlander PHEV", "2.4L PHEV", model_th="เอาท์แลนเดอร์",
  market_scope="GREY", body_type="CROSSOVER", segment="D", seats="7",
  launched="2022-01-01", powertrain="PHEV", drivetrain="AWD",
  engine_cc="2359", battery_kwh="20.0", price_note="grey import",
  model_aliases="outlander")
R("BYD", "BYD T3", "50 kWh BEV", model_th="บีวายดี ที3", body_type="VAN",
  market_scope="COMMERCIAL", registration_type="RY3", segment="UNKNOWN",
  seats="2", launched="2021-01-01", powertrain="BEV", drivetrain="FWD",
  battery_kwh="50.3", price_thb="999000", import_type="CBU",
  origin_country="CN", model_aliases="t3")
R("GWM", "Poer Sahar", "2.0L HEV", model_th="โพเออร์ ซาฮาร์",
  body_type="PICKUP", cab_type="DOUBLE_CAB", segment="F", seats="5",
  launched="2025-09-01", powertrain="HEV", drivetrain="4WD", engine_cc="1998",
  battery_kwh="1.8", price_thb="1399000", import_type="CBU",
  origin_country="CN", model_aliases="poer sahar|sahar|poer")
R("Volkswagen", "Caravelle", "2.0L ICE", brand_th="โฟล์คสวาเกน",
  brand_segment="MASS", oem_group="Volkswagen Group", brand_origin="DE",
  model_th="คาราเวล", body_type="VAN", registration_type="RY2",
  market_scope="COMMERCIAL", segment="E", seats="9", launched="2020-01-01",
  powertrain="ICE", drivetrain="FWD", engine_cc="1968", price_thb="3290000",
  import_type="CBU", origin_country="DE",
  model_aliases="caravelle|multivan|id buzz")
for brand, th, origin, model, body, seats, pt, kwh, price in (
    ("Seres", "เซเรส", "CN", "Seres 3", "CROSSOVER", "5", "BEV", "53.6",
     "899000"),
    ("Sokon", "โซคอน", "CN", "Sokon EC35", "VAN", "2", "BEV", "41.9",
     "849000"),
    ("Farizon", "ฟาริซอน", "CN", "Farizon SV", "VAN", "3", "BEV", "83.0",
     "1690000"),
    ("Nextem", "เน็กซ์เท็ม", "TH", "Nextem Orca", "VAN", "2", "BEV", "60.0",
     "1290000"),
    ("Daihatsu", "ไดฮัทสุ", "JP", "Hijet", "VAN", "2", "ICE", "", "590000"),
):
    R(brand, model, "spec", brand_th=th, brand_origin=origin,
      brand_segment="BUDGET", oem_group=brand, model_th=model,
      body_type=body, market_scope="COMMERCIAL" if body == "VAN" else "CORE",
      registration_type="RY3" if body == "VAN" else "", segment="UNKNOWN",
      seats=seats, launched="2023-01-01", powertrain=pt, drivetrain="FWD",
      engine_cc="658" if pt == "ICE" else "", battery_kwh=kwh,
      price_thb=price, import_type="CBU", origin_country=origin,
      model_aliases=model.split()[-1])


R("XPeng", "XPeng X9", "84 kWh BEV", model_th="เอ็กซ์เผิง เอ็กซ์9",
  body_type="MPV", segment="E", seats="7", launched="2025-03-01",
  powertrain="BEV", drivetrain="RWD", battery_kwh="84.5",
  price_thb="2599000", import_type="CBU", origin_country="CN",
  model_aliases="x9|xpeng x9")

#: Badge spellings for models already in the catalog. The importer only writes
#: the fields that are filled in, so naming the existing variant is enough.
ALIAS_ONLY = {
    "bmw.bmw_3": "320d|320i|318i|320Li|330Li|330e|M340i|M340i xDrive",
    "bmw.bmw_5": "520d|530e|540i",
    "bmw.bmw_x1": "X1 sDrive18i|X1 xDrive20d",
    "bmw.bmw_x3": "X3 xDrive20|X3 20 xDrive",
    "bmw.bmw_i4": "i4 eDrive40|i4 M50",
    "bmw.bmw_ix3": "iX3 Inspiring|iX3 Impressive",
    "mercedes_benz.mb_c_class": "C 200|C 220 d|C 250|C250|C 300|C 300 e|C 350 e",
    "mercedes_benz.mb_e_class": "E 200|E 220 d|E 300 e|E 350 e|E 300",
    "mercedes_benz.mb_gla": "GLA 200|GLA 250",
    "mercedes_benz.mb_glc": "GLC 200|GLC 220 d|GLC 300 d|GLC 300 e",
    "mercedes_benz.mb_eqs": "EQS 450|EQS 500|EQS 580",
    "gwm.tank300": "TANK 300 HYBRID|300 HYBRID",
    "gwm.tank500": "TANK 500 HYBRID|500 HYBRID",
    "toyota.alphard": "ALPHARD HYBRID|ALPHARD 2.5 HYBRID",
    "mg.mg_es": "ES5|MG ES5",
    "nissan.kicks": "KICKS e-POWER",
}


def main() -> None:
    catalog = Catalog.load()
    # Flag the brands already in the catalog whose DLT labels carry trim. The
    # importer only writes fields that are filled in, so naming an existing
    # model and variant is enough to set one brand-level flag.
    for model_id, aliases in ALIAS_ONLY.items():
        model = catalog.models[model_id]
        brand = catalog.brands[model.brand_id]
        variant = catalog.variants_of(model_id)[0]
        rows.append({"brand": brand.name_en, "model": model.name_en,
                     "variant": variant.name, "model_aliases": aliases})

    for brand_id in TRIM_DETAIL_EXISTING:
        brand = catalog.brands[brand_id]
        model = catalog.models_of(brand_id)[0]
        variant = catalog.variants_of(model.id)[0]
        rows.append({"brand": brand.name_en, "model": model.name_en,
                     "variant": variant.name, "trim_detail": "true"})

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(authoring.COLUMNS),
                                extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {len(rows)} rows to {OUT}")


if __name__ == "__main__":
    main()
