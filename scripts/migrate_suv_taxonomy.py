from __future__ import annotations

import json
from pathlib import Path

OFFROAD_MODELS = {
    "toyota.land_cruiser_300",
    "lexus.lx",
    "gwm.tank300",
    "gwm.tank500",
    "mercedes_benz.g_class",
    "suzuki.jimny",
    "jeep.wrangler",
}


def update_taxonomy() -> None:
    path = Path("vehreg/taxonomy.py")
    text = path.read_text(encoding="utf-8")

    old = '''    CROSSOVER = "CROSSOVER"          # monocoque, car-derived\n    SUV = "SUV"                      # monocoque, SUV-proportioned\n    PPV = "PPV"                      # body-on-frame SUV built off a pickup\n'''
    new = '''    CROSSOVER = "CROSSOVER"          # all monocoque/unibody SUVs and crossovers\n    PPV = "PPV"                      # pickup-derived passenger vehicle\n    OFFROAD = "OFFROAD"              # ladder-frame SUV that is not pickup-derived\n'''
    if old not in text:
        raise RuntimeError("BodyType block changed; refusing blind rewrite")
    text = text.replace(old, new)

    text = text.replace(
        "BODY_ON_FRAME = frozenset({BodyType.PPV, BodyType.PICKUP})",
        "BODY_ON_FRAME = frozenset({BodyType.PPV, BodyType.OFFROAD, BodyType.PICKUP})",
    )

    old_labels = '''        "HATCHBACK": "แฮทช์แบ็ก", "SEDAN": "ซีดาน", "CROSSOVER": "ครอสโอเวอร์",\n        "SUV": "เอสยูวี", "PPV": "เอสยูวีบอดี้ออนเฟรม (PPV)", "COUPE": "คูเป้",\n'''
    new_labels = '''        "HATCHBACK": "แฮทช์แบ็ก", "SEDAN": "ซีดาน", "CROSSOVER": "ครอสโอเวอร์ / SUV โมโนค็อก",\n        "PPV": "PPV พื้นฐานกระบะ", "OFFROAD": "SUV ออฟโรดโครงแชสซีส์", "COUPE": "คูเป้",\n'''
    if old_labels not in text:
        raise RuntimeError("BodyType labels changed; refusing blind rewrite")
    text = text.replace(old_labels, new_labels)

    old_aliases = '''    "BodyType": {\n        "SUV_BOF": "PPV", "BODY_ON_FRAME_SUV": "PPV", "PPV_SUV": "PPV",\n        "MINIVAN": "MPV", "CONVERTIBLE": "COUPE",\n'''
    new_aliases = '''    "BodyType": {\n        "SUV": "CROSSOVER", "MONOCOQUE_SUV": "CROSSOVER", "UNIBODY_SUV": "CROSSOVER",\n        "PPV_SUV": "PPV", "PICKUP_DERIVED_SUV": "PPV",\n        "SUV_BOF": "OFFROAD", "BODY_ON_FRAME_SUV": "OFFROAD",\n        "LADDER_FRAME_SUV": "OFFROAD", "OFFROAD_SUV": "OFFROAD",\n        "OFFROAD_LADDER_FRAME": "OFFROAD",\n        "MINIVAN": "MPV", "CONVERTIBLE": "COUPE",\n'''
    if old_aliases not in text:
        raise RuntimeError("BodyType aliases changed; refusing blind rewrite")
    text = text.replace(old_aliases, new_aliases)

    path.write_text(text, encoding="utf-8")


def migrate_catalogs() -> None:
    changed = []
    for path in sorted(Path("vehreg/data").glob("*/models/*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        brand_id = payload["brand"]["id"]
        dirty = False
        for model in payload.get("models", []):
            full_id = f"{brand_id}.{model['id']}"
            old = model.get("body_type")
            if full_id in OFFROAD_MODELS and old in {"SUV", "PPV", "CROSSOVER", "OFFROAD"}:
                new = "OFFROAD"
            elif old == "SUV":
                new = "CROSSOVER"
            else:
                new = old
            if new != old:
                model["body_type"] = new
                changed.append((str(path), full_id, old, new))
                dirty = True
        if dirty:
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"catalog body migrations: {len(changed)}")
    for row in changed:
        print(" | ".join(str(x) for x in row))


def update_python_references() -> None:
    for root in (Path("vehreg"), Path("pages"), Path("tests")):
        if not root.exists():
            continue
        for path in root.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            new = text.replace("BodyType.SUV", "BodyType.CROSSOVER")
            if new != text:
                path.write_text(new, encoding="utf-8")
                print("updated legacy BodyType.SUV reference", path)


def update_docs() -> None:
    path = Path("docs/VEHREG_TAXONOMY.md")
    text = path.read_text(encoding="utf-8")
    text = text.replace(
        "| `body_type` | HATCHBACK, SEDAN, CROSSOVER, SUV, PPV, COUPE, MPV, PICKUP, OTHER |",
        "| `body_type` | HATCHBACK, SEDAN, CROSSOVER, PPV, OFFROAD, COUPE, MPV, PICKUP, WAGON, VAN, TRUCK, OTHER |",
    )
    section = '''## SUV body taxonomy\n\nVehicle Master ใช้ SUV สามกลุ่มเท่านั้น:\n\n- `CROSSOVER` = SUV/crossover โครงสร้าง monocoque หรือ unibody ทุกขนาด\n- `PPV` = รถนั่งที่พัฒนาจากแพลตฟอร์มกระบะ เช่น Fortuner, Everest, MU-X, Pajero Sport, Terra\n- `OFFROAD` = SUV โครงแชสซีส์/ladder frame ที่ไม่ใช่ pickup-derived เช่น Land Cruiser 300, Lexus LX, Tank 300/500, G-Class, Jimny, Wrangler\n\nค่า `SUV` แบบเก่าไม่ใช่ canonical value อีกต่อไป และ parse เป็น `CROSSOVER` เพื่อรองรับข้อมูลเก่าเท่านั้น\n\n'''
    marker = "## Vocabulary ทั้งหมด\n"
    if "## SUV body taxonomy" not in text:
        if marker not in text:
            raise RuntimeError("taxonomy doc marker not found")
        text = text.replace(marker, section + marker)
    path.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    update_taxonomy()
    migrate_catalogs()
    update_python_references()
    update_docs()
