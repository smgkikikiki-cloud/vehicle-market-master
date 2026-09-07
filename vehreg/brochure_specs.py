"""Targeted brochure extraction for Vehicle Master.

Brochures are heterogeneous, so this module does *not* attempt to digitize a
whole brochure schema.  It searches only for fields Vehicle Master currently
cares about and leaves everything else absent.  Missing is preferable to an
invented value.

The first pass uses the PDF text layer via PyMuPDF.  Image-only or badly encoded
PDFs are marked ``needs_vision`` for a later visual/OCR fallback rather than
silently guessing.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
import re
from typing import Any, Optional

import fitz  # PyMuPDF


@dataclass(frozen=True, slots=True)
class Evidence:
    value: Any
    page: int
    raw_label: str = ""
    raw_value: str = ""
    confidence: float = 0.9

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class BrochureExtraction:
    fields: dict[str, Evidence] = field(default_factory=dict)
    adas: list[str] = field(default_factory=list)
    page_count: int = 0
    text_chars: int = 0
    needs_vision: bool = False

    def put(self, key: str, value: Any, page: int, *, label: str = "", raw: str = "", confidence: float = 0.9) -> None:
        if value is None or value == "":
            return
        if key not in self.fields:
            self.fields[key] = Evidence(value, page, label, raw or str(value), confidence)

    def to_dict(self) -> dict[str, Any]:
        return {
            "fields": {k: v.to_dict() for k, v in sorted(self.fields.items())},
            "adas": list(self.adas),
            "page_count": self.page_count,
            "text_chars": self.text_chars,
            "needs_vision": self.needs_vision,
        }


_PRIVATE_USE_RE = re.compile(r"[\ue000-\uf8ff]")
_SPACE_RE = re.compile(r"\s+")
_NUMBER_RE = re.compile(r"-?\d[\d,]*(?:\.\d+)?")
_TYRE_RE = re.compile(r"\b(\d{3})\s*/\s*(\d{2,3})\s*R\s*(\d{2})\b", re.I)


def clean_text(text: str) -> str:
    # Some Thai brochure fonts map combining glyphs into the Unicode private-use
    # area. Removing those glyphs keeps stable consonant fragments and numbers,
    # which is sufficient for targeted matching without OCR.
    text = _PRIVATE_USE_RE.sub("", text or "")
    text = text.replace("\u200b", "").replace("\ufeff", "")
    return text


def _num(text: str) -> Optional[float]:
    m = _NUMBER_RE.search(text or "")
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", ""))
    except ValueError:
        return None


def _integer(text: str) -> Optional[int]:
    value = _num(text)
    return int(value) if value is not None else None


def _tyre(text: str) -> str:
    m = _TYRE_RE.search(text or "")
    if not m:
        return ""
    return f"{m.group(1)}/{m.group(2)} R{m.group(3)}"


def _drivetrain(text: str) -> str:
    low = clean_text(text).lower()
    if "ขับเคลอนล้อหน้า" in low or "front-wheel" in low or re.search(r"\bfwd\b", low):
        return "FWD"
    if "ขับเคลอนล้อหลัง" in low or "rear-wheel" in low or re.search(r"\brwd\b", low):
        return "RWD"
    if "4wd" in low or "four-wheel" in low or "ขับเคลอน 4 ล้อ" in low:
        return "4WD"
    if "awd" in low or "all-wheel" in low:
        return "AWD"
    return ""


def pdf_pages(path: Path | str) -> list[str]:
    document = fitz.open(str(path))
    try:
        return [clean_text(page.get_text("text", sort=True)) for page in document]
    finally:
        document.close()


# Ordered common Thai technical-table labels.  A frequent brochure layout puts
# all labels in one column and all values in the next; PyMuPDF then emits the
# labels as a block followed by the values.  This list lets us pair those blocks
# without assuming a page number or fixed row coordinates.
_TECH_ROWS: list[tuple[str, re.Pattern[str]]] = [
    ("drivetrain", re.compile(r"รูปแบบการขับเคลอน|drive\s*type|drivetrain", re.I)),
    ("motor_count", re.compile(r"จานวนมอเตอร์|number\s+of\s+motors?", re.I)),
    ("motor_power", re.compile(r"กาลังมอเตอร์.*สูงสุด|max(?:imum)?\s+motor\s+power", re.I)),
    ("torque_nm", re.compile(r"แรงบิดสูงสุด.*มอเตอร์|max(?:imum)?\s+torque", re.I)),
    ("battery_kwh", re.compile(r"ความจุพลังงานแบต|battery\s+capacity", re.I)),
    ("range_km", re.compile(r"ระยะทางการขับเคลอน|driving\s+range|range\s*\(.*km", re.I)),
    ("ac_charge_kw", re.compile(r"ชาร์จ.*\bAC\b.*สูงสุด|max(?:imum)?.*\bAC\b.*charg", re.I)),
    ("dc_charge_kw", re.compile(r"ชาร์จ.*\bDC\b.*สูงสุด|max(?:imum)?.*\bDC\b.*charg", re.I)),
    ("acceleration_0_100_s", re.compile(r"0\s*-\s*100.*วินาที|0\s*-\s*100.*sec", re.I)),
    ("top_speed_kmh", re.compile(r"ความเร็วสูงสุด|top\s+speed|max(?:imum)?\s+speed", re.I)),
    ("front_cargo_l", re.compile(r"สัมภาระด้านหน้า|front.*(?:cargo|luggage|boot)", re.I)),
    ("rear_cargo_l", re.compile(r"สัมภาระด้านหลัง|rear.*(?:cargo|luggage|boot)", re.I)),
    ("dimensions", re.compile(r"มิติตัวถัง|dimensions?", re.I)),
    ("wheelbase_mm", re.compile(r"ระยะฐานล้อ|wheelbase", re.I)),
    ("ground_clearance_mm", re.compile(r"ระยะ.*จากพน|ground\s+clearance", re.I)),
    ("tyre", re.compile(r"ขนาดล้อและยาง|tire\s+size|tyre\s+size", re.I)),
]


def _convert_row(key: str, raw: str) -> dict[str, Any]:
    if key == "drivetrain":
        return {"drivetrain": _drivetrain(raw)}
    if key in {"motor_count", "wheelbase_mm", "ground_clearance_mm", "top_speed_kmh", "front_cargo_l"}:
        return {key: _integer(raw)}
    if key in {"torque_nm", "battery_kwh", "range_km", "ac_charge_kw", "dc_charge_kw", "acceleration_0_100_s"}:
        return {key: _num(raw)}
    if key == "motor_power":
        nums = [float(x.replace(",", "")) for x in _NUMBER_RE.findall(raw)]
        result: dict[str, Any] = {}
        if nums:
            result["power_kw"] = nums[0]
        if len(nums) > 1:
            result["power_hp"] = nums[1]
        return result
    if key == "rear_cargo_l":
        nums = [int(float(x.replace(",", ""))) for x in _NUMBER_RE.findall(raw)]
        if not nums:
            return {}
        return {"rear_cargo_l": nums[0], "rear_cargo_max_l": nums[-1] if len(nums) > 1 else nums[0]}
    if key == "dimensions":
        nums = [int(float(x.replace(",", ""))) for x in _NUMBER_RE.findall(raw)]
        if len(nums) >= 3:
            # Thai brochures commonly label this row กว้าง x ยาว x สูง.
            return {"width_mm": nums[0], "length_mm": nums[1], "height_mm": nums[2]}
        return {}
    if key == "tyre":
        tyre = _tyre(raw)
        return {"tire_front": tyre, "tire_rear": tyre} if tyre else {}
    return {}


def _extract_column_table(lines: list[str], result: BrochureExtraction, page: int) -> None:
    found: list[tuple[int, str, str]] = []
    cursor = -1
    for key, pattern in _TECH_ROWS:
        idx = next((i for i in range(cursor + 1, len(lines)) if pattern.search(lines[i])), -1)
        if idx >= 0:
            found.append((idx, key, lines[idx]))
            cursor = idx

    # Fail closed: only trust the label-block/value-block heuristic when most of
    # the expected technical rows are present in order.
    if len(found) < 10:
        return
    value_start = found[-1][0] + 1
    values = [line.strip() for line in lines[value_start:] if line.strip()]
    if len(values) < len(found):
        return

    for (_, key, label), raw in zip(found, values):
        for out_key, value in _convert_row(key, raw).items():
            result.put(out_key, value, page, label=label, raw=raw, confidence=0.97)
        if key == "range_km":
            m = re.search(r"\b(NEDC|WLTP|CLTC|EPA)\b", label, re.I)
            if m:
                result.put("range_standard", m.group(1).upper(), page, label=label, raw=m.group(1), confidence=0.99)


def _extract_direct(text: str, result: BrochureExtraction, page: int) -> None:
    lines = [_SPACE_RE.sub(" ", x.strip()) for x in text.splitlines() if x.strip()]
    joined = "\n".join(lines)

    # Common inline tyre declaration anywhere in the brochure.
    tyre = _tyre(joined)
    if tyre:
        result.put("tire_front", tyre, page, raw=tyre, confidence=0.88)
        result.put("tire_rear", tyre, page, raw=tyre, confidence=0.88)

    # Seats.
    for line in lines:
        if ("รองรับผู้โดยสาร" in line or "ทนง" in line or re.search(r"\bseats?\b", line, re.I)):
            n = _integer(line)
            if n and 1 <= n <= 20:
                result.put("seats", n, page, raw=line, confidence=0.92)
                break

    # Screens and speakers are useful paper-spec fields.
    for line in lines:
        low = line.lower()
        if "มาตรวัด" in line or "instrument" in low or "cluster" in low:
            n = _num(line)
            if n and 3 <= n <= 30:
                result.put("instrument_screen_in", n, page, raw=line, confidence=0.9)
        if "คอนโซลกลาง" in line or "infotainment" in low or "central display" in low or "center display" in low:
            n = _num(line)
            if n and 5 <= n <= 40:
                result.put("infotainment_screen_in", n, page, raw=line, confidence=0.9)
        if "ลาโพง" in line or "speaker" in low:
            n = _integer(line)
            if n and 1 <= n <= 40:
                result.put("speaker_count", n, page, raw=line, confidence=0.9)
        if "ไร้สาย" in line and "วัตต์" in line or "wireless charg" in low:
            n = _num(line)
            if n and 1 <= n <= 500:
                result.put("wireless_charge_w", n, page, raw=line, confidence=0.9)

    # Boolean/compact paper specs. Presence is evidence; absence is not false.
    feature_patterns = {
        "panoramic_roof": r"panoramic|พาโนราม",
        "power_tailgate": r"ประตูท้าย.*ไฟฟ|power(?:ed)?\s+tailgate|electric\s+tailgate",
        "ventilated_front_seats": r"เบาะ.*ระบายอากาศ|ventilat(?:ed|ion).*seat",
        "massage_seat": r"massage.*seat|เบาะ.*นวด",
        "memory_seat": r"memory.*seat|เบาะ.*memory|จดจา.*เบาะ",
        "hud": r"\bHUD\b|head[- ]up display",
        "v2l": r"\bV2L\b|vehicle[- ]to[- ]load",
    }
    for key, pattern in feature_patterns.items():
        if re.search(pattern, joined, re.I):
            result.put(key, True, page, raw=pattern, confidence=0.88)

    cam = re.search(r"(?:กล้อง|camera)[^\n]{0,80}?(360|540)\s*(?:องศา|degree)?", joined, re.I)
    if cam:
        result.put("camera_degrees", int(cam.group(1)), page, raw=cam.group(0), confidence=0.95)

    # Common automotive SoC names/numbers. Keep the brochure wording instead of
    # trying to infer vendor/spec from a bare model number.
    chip = re.search(r"(?:Qualcomm|Snapdragon|NVIDIA|Nvidia|Orin|Dimensity|8155|8295|SA8155P)[^\n]{0,80}", joined, re.I)
    if chip:
        result.put("chip_soc", chip.group(0).strip(), page, raw=chip.group(0), confidence=0.82)

    # ADAS acronyms are much more consistent across manufacturers than prose.
    common_adas = [
        "AEB", "ACC", "FCW", "LDW", "LKA", "LDP", "ELK", "ICA", "TJA",
        "BSD", "DOW", "LCA", "RCTA", "RCTB", "RCW", "IES", "DAI", "ASL",
    ]
    for acronym in common_adas:
        if re.search(rf"(?<![A-Z0-9]){re.escape(acronym)}(?![A-Z0-9])", joined, re.I):
            if acronym not in result.adas:
                result.adas.append(acronym)

    _extract_column_table(lines, result, page)


def extract_brochure(path: Path | str) -> BrochureExtraction:
    pages = pdf_pages(path)
    result = BrochureExtraction(page_count=len(pages), text_chars=sum(len(x) for x in pages))
    result.needs_vision = result.text_chars < max(80, result.page_count * 40)
    for page_no, text in enumerate(pages, 1):
        _extract_direct(text, result, page_no)
    result.adas.sort()
    return result
