"""Text normalisation and fuzzy matching for messy DLT / press labels.

DLT statistic sheets spell the same car several ways across three years:
``TOYOTA``, ``โตโยต้า``, ``TOYOTA MOTOR``; ``YARIS ATIV`` vs ``ยาริส เอทีฟ`` vs
``YARIS-ATIV 1.2``. Nothing here guesses across brands - matching is always
scoped to a candidate list, and anything below the confidence floor is pushed
to the review queue rather than silently attached to the nearest name.
"""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from typing import Iterable, Optional, Sequence

# Thai tone marks / vowels that get dropped inconsistently in DLT exports.
_THAI_COMBINING = re.compile(r"[ัิ-ฺ็-๎]")
_NON_ALNUM = re.compile(r"[^0-9a-z฀-๿]+")
_CORPORATE_NOISE = re.compile(
    r"\b(motor|motors|automobile|automotive|auto|company|co|ltd|limited|"
    r"thailand|manufacturing|corporation|corp|inc|group|sales|"
    r"บริษัท|จำกัด|มหาชน|ประเทศไทย|ยานยนต์|มอเตอร์)\b"
)

#: Below this ratio a match is never accepted automatically.
MATCH_FLOOR = 0.86


#: DLT and the catalog disagree on whether a model number is joined to its
#: name: "ATTO3" vs "Atto 3", "MG4" vs "MG 4", "CX5" vs "CX-5". Splitting every
#: letter/digit boundary on both sides makes the two spellings the same key,
#: and does the same for "410KM" -> "410 km" and "2WD" -> "2 wd".
_LETTER_DIGIT = re.compile(r"(?<=[^\W\d_])(?=\d)|(?<=\d)(?=[^\W\d_])")


def fold(text: str, split_digits: bool = True) -> str:
    """Aggressive comparison key: case, spacing, punctuation and Thai marks.

    ``split_digits`` is on for matching and off for ``slug``: catalog ids are
    identity, and they should not churn because the matcher learned a trick.
    """
    if text is None:
        return ""
    s = unicodedata.normalize("NFKC", str(text)).strip().lower()
    s = _NON_ALNUM.sub(" ", s)
    if split_digits:
        s = _LETTER_DIGIT.sub(" ", s)
    s = _CORPORATE_NOISE.sub(" ", s)
    s = _THAI_COMBINING.sub("", s)
    return " ".join(s.split())


def tokens(text: str) -> list[str]:
    return fold(text).split()


def similarity(a: str, b: str) -> float:
    fa, fb = fold(a), fold(b)
    if not fa or not fb:
        return 0.0
    if fa == fb:
        return 1.0
    base = SequenceMatcher(None, fa, fb).ratio()
    ta, tb = set(fa.split()), set(fb.split())
    if ta and tb:
        jaccard = len(ta & tb) / len(ta | tb)
        # A raw label often carries extra trim words; reward full containment.
        if ta <= tb or tb <= ta:
            jaccard = max(jaccard, 0.9)
        base = max(base, (base + jaccard) / 2)
    return base


class MatchIndex:
    """Maps many spellings onto one catalog key.

    Three strategies, tried in order and reported separately so the ingest log
    can show why a row was attached to a car:

    ``exact``     folded strings are identical.
    ``contains``  the catalog name appears as a whole-token run inside the raw
                  label - this is what recognises ``YARIS ATIV 1.2 SMART`` as a
                  Yaris Ativ. The *longest* matching name wins, so ``Yaris``
                  never steals a row from ``Yaris Ativ``.
    ``fuzzy``     character/token similarity above ``floor``.

    A tie between two different keys is reported as ``ambiguous`` and matched to
    nothing; the caller queues it for the owner.
    """

    def __init__(self) -> None:
        # One surface can belong to several keys - "Hilux Revo" is a legitimate
        # name for three cab models - so this maps to a list, and a surface with
        # more than one owner is an ambiguity rather than a first-wins match.
        # ``priority`` breaks the tie only when one owner holds the surface as
        # its real name and the others merely as an alias: "City" is the City
        # sedan's name and only a derived alias of City Hatchback, so the sedan
        # wins, while "Hilux Revo" is an alias for every cab and stays ambiguous.
        self._exact: dict[str, dict[str, int]] = {}
        self._candidates: list[tuple[str, str, int]] = []

    def add(self, key: str, surfaces: Iterable[str], priority: int = 0) -> None:
        for surface in surfaces:
            folded = fold(surface)
            if not folded:
                continue
            owners = self._exact.setdefault(folded, {})
            owners[key] = max(owners.get(key, priority), priority)
            self._candidates.append((folded, key, priority))

    @staticmethod
    def _top(owners: dict[str, int]) -> list[str]:
        best = max(owners.values())
        return sorted(k for k, v in owners.items() if v == best)

    def _contains(self, raw_tokens: list[str]) -> tuple[Optional[str], int, bool]:
        best_len = 0
        owners: dict[str, int] = {}
        for surface, key, priority in self._candidates:
            st = surface.split()
            if not st or len(st) > len(raw_tokens):
                continue
            if not any(raw_tokens[i:i + len(st)] == st
                       for i in range(len(raw_tokens) - len(st) + 1)):
                continue
            if len(st) > best_len:
                best_len, owners = len(st), {key: priority}
            elif len(st) == best_len:
                owners[key] = max(owners.get(key, priority), priority)
        if not owners:
            return None, 0, False
        top = self._top(owners)
        return top[0], best_len, len(top) > 1

    def lookup(self, raw: str, floor: float = MATCH_FLOOR
               ) -> tuple[Optional[str], float, str]:
        """Return ``(key, score, how)``; key is ``None`` when nothing is safe."""
        folded = fold(raw)
        if not folded:
            return None, 0.0, "none"
        owners = self._exact.get(folded)
        if owners:
            top = self._top(owners)
            if len(top) > 1:
                return None, 0.0, "ambiguous"
            return top[0], 1.0, "exact"

        key, hit_len, tied = self._contains(folded.split())
        if tied:
            return None, 0.0, "ambiguous"
        if key is not None:
            # Longer catalog names inside the label are stronger evidence.
            return key, min(0.99, 0.90 + 0.03 * hit_len), "contains"

        best_key, best_score = None, 0.0
        for surface, candidate, _priority in self._candidates:
            score = similarity(folded, surface)
            if score > best_score:
                best_key, best_score = candidate, score
        if best_key is not None and best_score >= floor:
            return best_key, best_score, "fuzzy"
        return None, best_score, "none"

    def ambiguous_candidates(self, raw: str) -> list[str]:
        """Keys that tie for the longest whole-token match inside ``raw``."""
        folded = fold(raw)
        owners = self._exact.get(folded)
        if owners:
            top = self._top(owners)
            if len(top) > 1:
                return top
        raw_tokens = folded.split()
        best_len = 0
        hits: dict[str, int] = {}
        for surface, key, priority in self._candidates:
            st = surface.split()
            if not st or len(st) > len(raw_tokens):
                continue
            if not any(raw_tokens[i:i + len(st)] == st
                       for i in range(len(raw_tokens) - len(st) + 1)):
                continue
            if len(st) > best_len:
                best_len, hits = len(st), {key: priority}
            elif len(st) == best_len:
                hits[key] = max(hits.get(key, priority), priority)
        return self._top(hits) if hits else []

    def keys(self) -> set[str]:
        return {key for _, key, _p in self._candidates}

    def __len__(self) -> int:
        return len(self._candidates)


def split_brand_model(raw: str, brand_surfaces: Sequence[str]) -> tuple[str, str]:
    """Peel a known brand prefix off a combined ``BRAND MODEL`` cell."""
    folded = fold(raw)
    best = ""
    for surface in brand_surfaces:
        fs = fold(surface)
        if fs and (folded == fs or folded.startswith(fs + " ")) and len(fs) > len(best):
            best = fs
    if not best:
        return "", raw
    return best, folded[len(best):].strip()


THAI_MONTHS: dict[str, int] = {
    "มกราคม": 1, "มค": 1, "ม.ค.": 1,
    "กุมภาพันธ์": 2, "กพ": 2, "ก.พ.": 2,
    "มีนาคม": 3, "มีค": 3, "มี.ค.": 3,
    "เมษายน": 4, "เมย": 4, "เม.ย.": 4,
    "พฤษภาคม": 5, "พค": 5, "พ.ค.": 5,
    "มิถุนายน": 6, "มิย": 6, "มิ.ย.": 6,
    "กรกฎาคม": 7, "กค": 7, "ก.ค.": 7,
    "สิงหาคม": 8, "สค": 8, "ส.ค.": 8,
    "กันยายน": 9, "กย": 9, "ก.ย.": 9,
    "ตุลาคม": 10, "ตค": 10, "ต.ค.": 10,
    "พฤศจิกายน": 11, "พย": 11, "พ.ย.": 11,
    "ธันวาคม": 12, "ธค": 12, "ธ.ค.": 12,
}

ENGLISH_MONTHS: dict[str, int] = {
    m: i + 1 for i, m in enumerate(
        ["jan", "feb", "mar", "apr", "may", "jun",
         "jul", "aug", "sep", "oct", "nov", "dec"])
}


def _month_from_words(text: str) -> Optional[int]:
    stripped = re.sub(r"[.\s]", "", str(text))
    for name, num in THAI_MONTHS.items():
        if re.sub(r"[.\s]", "", name) and re.sub(r"[.\s]", "", name) in stripped:
            return num
    lowered = str(text).lower()
    for name, num in ENGLISH_MONTHS.items():
        if name in lowered:
            return num
    return None


def _to_gregorian(year: int) -> int:
    return year - 543 if year > 2400 else year


def period_key(value: str) -> str:
    """Normalise a period cell to ``YYYY-MM``.

    Accepts ``2024-03``, ``03/2024``, ``มี.ค. 2567``, ``Mar 2024`` and the
    Buddhist-era years DLT publishes in.
    """
    s = str(value).strip()
    numeric = re.search(r"(\d{4})\D+(\d{1,2})(?!\d)", s) or \
        re.search(r"(\d{1,2})\D+(\d{4})", s)
    word_month = _month_from_words(s)
    year_only = re.search(r"(\d{4})", s)

    if word_month is not None and year_only:
        return f"{_to_gregorian(int(year_only.group(1))):04d}-{word_month:02d}"
    if numeric:
        a, b = numeric.group(1), numeric.group(2)
        year, month = (a, b) if len(a) == 4 else (b, a)
        mo = int(month)
        if not 1 <= mo <= 12:
            raise ValueError(f"month out of range in {value!r}")
        return f"{_to_gregorian(int(year)):04d}-{mo:02d}"
    raise ValueError(f"cannot read a period from {value!r}")


def year_key(value: str) -> str:
    """Normalise a year cell to ``YYYY`` (Gregorian)."""
    m = re.search(r"(\d{4})", str(value))
    if not m:
        raise ValueError(f"cannot read a year from {value!r}")
    return f"{_to_gregorian(int(m.group(1))):04d}"


#: Suffixes this project appends when it splits a nameplate into models: one
#: per body, and one per pickup cab. Stripping them recovers the nameplate.
SPLIT_SUFFIX = re.compile(
    r"\s+(single cab|double cab|smart cab|club cab|king cab|open cab|"
    r"freestyle cab|giant cab|cab4|spark|sedan|hatchback|coupe|cab|"
    r"ตอนเดียว|4 ประตู|สมาร์ทแค็บ|คลับแค็บ|คิงแค็บ|โอเพ่นแค็บ|ฟรีสไตล์แค็บ|"
    r"ไจแอนท์แค็บ|แค็บโฟร์|สปาร์ค|ซีดาน|แฮทช์แบ็ก|ตอนเดียว/แค็บ|แค็บ)$",
    re.IGNORECASE)


def base_nameplate(name: str) -> str:
    """``Hilux Revo Double Cab`` -> ``Hilux Revo``. Idempotent on plain names."""
    return SPLIT_SUFFIX.sub("", str(name or "")).strip() or str(name or "")


def slug(text: str) -> str:
    s = fold(text, split_digits=False).replace(" ", "_")
    return re.sub(r"_+", "_", s).strip("_") or "unnamed"
