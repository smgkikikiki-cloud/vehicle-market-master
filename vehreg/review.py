"""The queue of labels the ingest refused to guess at, and how to settle them.

The ingest never places a row it is not sure about; it writes the row to
``ingest_review`` with the reason it stopped. That is the right behaviour and it
leaves a debt: 22,440 units sitting in the queue that only the owner can decide,
with no way to decide them except editing a catalog file by hand.

This module is that missing half. It groups the queue the way a person works
through it - by label, biggest volume first, because one decision about
"ISUZU D-MAX" settles every month it appears in - proposes the candidates the
matcher itself would have considered, and records the decision as an alias
override.

One thing it deliberately does not do is move the units. Matching happens at
ingest, so a lesson changes nothing until the source file is read again;
``reload_source`` is that step, and it is separate so that teaching twenty
labels costs one reload rather than twenty. Anything else would be a second
matcher living in the UI, disagreeing with the real one.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Iterable, Optional, Sequence

from . import dlt
from .catalog import DATA_DIR, Catalog, available_years
from .db import clear_source
from .ingest import ColumnMap, IngestReport, ingest_csv, teach_alias
from .normalize import fold, similarity
from .taxonomy import RegistrationType

#: How many suggestions are worth reading before a search box is the better
#: tool. Past about this many the list stops being a shortlist.
SUGGESTIONS = 8

#: The ingest's own MATCH_FLOOR. A lower bar was tried first, on the theory that
#: a person can judge a weak suggestion. Looking at what it produced settled it:
#: "BMW 730Ld M Sport" was offered the 3 Series at 0.44 and "NISSAN LEAF" was
#: offered the Almera at 0.47, and both are wrong in a way that would silently
#: misfile real registrations. Nothing between 0.45 and 0.86 was a suggestion
#: worth having, so the shortlist holds exactly what the matcher itself would
#: have accepted, and a label with nothing above the bar is reported as needing
#: a catalog entry rather than handed a plausible mistake.
SUGGESTION_FLOOR = 0.86

#: A brand this far from every brand in the catalog is almost certainly a marque
#: the catalog does not have - VOLT and FOMM are real Thai EV makers and no
#: alias can conjure them - so the honest answer is a catalog entry, not a
#: lesson. Set above the point where VOLT starts attracting Volvo at 0.67.
UNKNOWN_BRAND_FLOOR = 0.75

#: What a label actually needs, which is usually not a lesson. Sorting the queue
#: this way is the difference between "22,440 units are stuck" and a plan: most
#: of the volume here is a missing catalog entry or a weaker source file, and
#: only some of it is a decision the owner can take by clicking.
NEEDS_TEACH = "teach"        # a candidate exists; one click settles every month
NEEDS_CATALOG = "catalog"    # no catalog entry is close; add the car first
NEEDS_SOURCE = "source"      # the file cannot answer it; get a better file
NEEDS_NOTHING = "junk"       # not a car name at all, only worth dismissing

NEEDS_LABELS: dict[str, str] = {
    NEEDS_TEACH: "สอนได้เลย",
    NEEDS_CATALOG: "ต้องเพิ่มรุ่น/ยี่ห้อใน catalog ก่อน",
    NEEDS_SOURCE: "ต้องหาไฟล์ที่ดีกว่า",
    NEEDS_NOTHING: "ไม่ใช่ชื่อรถ ปัดทิ้งได้",
}

#: DLT prints a factory code in the รุ่น column often enough to be worth
#: recognising: one long unbroken token of capitals, digits and dashes, like
#: ``UVL4RDRE26KHE-----``. The single token is the whole signal - a first pass
#: stripped spaces before matching and duly filed "745Le xDrive M Sport" and
#: "TUNLAND DC 4X2 S PREMIUM" as codes, which is how a screenshot earns its
#: keep. Recognising a code only changes which bucket the row is filed under;
#: dismissing it is still a click.
_CODE_LIKE = re.compile(r"^(?=.*[0-9])(?=.*[A-Z])[A-Z0-9]+-*$")

REASON_LABELS: dict[str, str] = {
    "model-ambiguous": "ป้ายนี้เข้าได้หลายรุ่นเท่าๆ กัน",
    "model-not-found": "รู้ยี่ห้อ แต่ไม่รู้ว่ารุ่นไหน",
    "brand-not-found": "ไม่รู้จักแม้แต่ยี่ห้อ",
    "variant-not-found": "รู้รุ่น แต่ไม่รู้รุ่นย่อย",
    "no-catalog-for-year": "ยังไม่มี catalog ของปีนั้น",
    "bad-period": "อ่านเดือนไม่ออก",
    "bad-units": "อ่านจำนวนไม่ออก",
}


@dataclass(frozen=True)
class Candidate:
    """One catalog entry the owner could point a label at."""

    unit_id: str
    label: str
    reg_type: str
    score: float
    how: str


@dataclass(frozen=True)
class Item:
    """One raw label, gathered across every month and file it appears in."""

    key: str
    raw_brand: str
    raw_model: str
    raw_label: str
    reason: str
    units: float
    rows: int
    periods: tuple[str, ...]
    sources: tuple[tuple[int, str], ...]
    reg_types: tuple[str, ...]
    years: tuple[int, ...] = ()
    brand_id: str = ""
    candidates: tuple[Candidate, ...] = ()
    scope: str = "model"
    needs: str = NEEDS_CATALOG
    note: str = ""
    blocked: str = ""

    @property
    def teachable(self) -> bool:
        return self.needs == NEEDS_TEACH and bool(self.candidates)

    @property
    def search_text(self) -> str:
        """What to score a catalog name against - the model cell, not the label.

        Scoring the whole label flatters everything of the right brand, because
        the brand name matches itself. "BMW 730Ld M Sport" scored 0.57 against
        the i5 that way and 0.40 against it honestly.
        """
        return self.raw_model or self.raw_label

    @property
    def default_reg(self) -> str:
        """The class to scope a lesson to.

        One class across every row means the lesson can be that specific, which
        is what keeps "D-MAX means the double cab" out of the รย.3 files. A
        label seen under several classes has to be taught per class or not at
        all, so it falls back to every class and says so.
        """
        known = [r for r in self.reg_types if r]
        return known[0] if len(set(known)) == 1 else "*"


def _bucket(reason: str) -> str:
    return (reason or "").split(":", 1)[0]


CAB_WORDS: dict[str, str] = {
    "DOUBLE_CAB": "ตอนสี่ประตู · รย.1",
    "SINGLE_SMART": "ตอนเดียว/แค็บ · รย.3",
    "SMART_CAB": "แค็บ",
    "SINGLE_CAB": "ตอนเดียว",
}


def _model_label(catalog: Catalog, unit_id: str) -> str:
    """A name the owner can pick between.

    For the cab split the difference is the whole decision, and the DLT class is
    how it is actually distinguished, so it goes in the label rather than a
    taxonomy spelling like ``SINGLE_SMART``.
    """
    model = catalog.models.get(unit_id)
    if model is None:
        brand = catalog.brands.get(unit_id)
        return brand.name_en if brand else unit_id
    brand = catalog.brands.get(model.brand_id)
    name = model.name_en
    if brand and fold(name).split()[:1] != fold(brand.name_en).split()[:1]:
        # Some catalog names already carry the marque ("MG S5 EV"), and
        # "MG MG S5 EV" reads like a typo rather than a name.
        name = f"{brand.name_en} {name}"
    cab = CAB_WORDS.get(model.cab_type.value, "")
    return f"{name} ({cab})" if cab else name


def _reg_of(catalog: Catalog, unit_id: str) -> str:
    model = catalog.models.get(unit_id)
    return model.registration_type.value if model else "*"


def _surfaces_score(text: str, surfaces: Iterable[str]) -> float:
    folded = fold(text)
    return max((similarity(folded, fold(s)) for s in surfaces if s), default=0.0)


def _ambiguous_candidates(catalogs: Sequence[Catalog], reason: str
                          ) -> list[Candidate]:
    """The matcher already worked these out; the reason string carries them."""
    catalog = catalogs[-1]
    _, _, rest = reason.partition(":")
    out: list[Candidate] = []
    for raw in rest.split("|"):
        unit_id = raw.strip()
        if unit_id in catalog.models and _in_every_year(unit_id, catalogs,
                                                        "model"):
            out.append(Candidate(unit_id, _model_label(catalog, unit_id),
                                 _reg_of(catalog, unit_id), 1.0,
                                 "ตัวเลือกที่ระบบชั่งแล้วเสมอกัน"))
    return out


def _in_every_year(unit_id: str, catalogs: Sequence[Catalog], kind: str) -> bool:
    """A target has to exist in every year the label appears in.

    Each year has its own catalog, and a lesson is not scoped by year. Teaching
    "MINI JCW E" against the 2026 catalog while the rows are all 2025 would
    write facts whose unit_id has no dimension row for 2025 - a fact with every
    facet NULL, which is worse than the open review row it replaced.
    """
    table = "models" if kind == "model" else "brands"
    return all(unit_id in getattr(catalog, table) for catalog in catalogs)


def models_for(catalogs: Sequence[Catalog], brand_id: str) -> list[Candidate]:
    """Every model of one brand that exists in every year the label spans.

    This is the manual route, and it is a list rather than a ranking on purpose.
    Nothing in the strings says "TR TRANSFORMER" is a Hiace conversion or that
    "V80" is MG's van - a person knows that, and a person needs to find the
    entry, not be told which one the machine likes. A ranked shortlist here
    would only lend a wrong guess the appearance of agreement.
    """
    if not catalogs or brand_id not in catalogs[-1].brands:
        return []
    out = [Candidate(model.id, _model_label(catalogs[-1], model.id),
                     model.registration_type.value, 0.0, "เลือกเอง")
           for model in catalogs[-1].models_of(brand_id)
           if _in_every_year(model.id, catalogs, "model")]
    return sorted(out, key=lambda c: c.label)


def _model_candidates(catalogs: Sequence[Catalog], brand_id: str, text: str
                      ) -> list[Candidate]:
    catalog = catalogs[-1]
    scored: list[tuple[float, Candidate]] = []
    for model in catalog.models_of(brand_id):
        if not _in_every_year(model.id, catalogs, "model"):
            continue
        score = _surfaces_score(
            text, [model.name_en, model.name_th, *model.aliases])
        if score < SUGGESTION_FLOOR:
            continue
        scored.append((score, Candidate(
            model.id, _model_label(catalog, model.id),
            model.registration_type.value, score, "ชื่อใกล้เคียง")))
    scored.sort(key=lambda pair: (-pair[0], pair[1].label))
    return [candidate for _, candidate in scored[:SUGGESTIONS]]


def _brand_candidates(catalogs: Sequence[Catalog], text: str) -> list[Candidate]:
    catalog = catalogs[-1]
    scored: list[tuple[float, Candidate]] = []
    for brand in catalog.brands.values():
        if not _in_every_year(brand.id, catalogs, "brand"):
            continue
        score = _surfaces_score(
            text, [brand.name_en, brand.name_th, *brand.aliases])
        if score < SUGGESTION_FLOOR:
            continue
        scored.append((score, Candidate(brand.id, brand.name_en, "*", score,
                                        "ชื่อยี่ห้อใกล้เคียง")))
    scored.sort(key=lambda pair: (-pair[0], pair[1].label))
    return [candidate for _, candidate in scored[:SUGGESTIONS]]


def _looks_like_a_code(text: str) -> bool:
    token = (text or "").strip().upper()
    return (len(token) >= 10 and " " not in token
            and bool(_CODE_LIKE.match(token)))


def _decorate(catalogs: Sequence[Catalog], item: Item,
              reason_detail: str) -> Item:
    """Work out what this label actually needs, and offer only what fits.

    Every branch here can end in "no lesson will help you". That is the point:
    the queue is mostly not a set of decisions waiting to be clicked, and a page
    that presented it as one would push the owner into wrong clicks to make a
    number go down.
    """
    if item.reason == "model-ambiguous":
        candidates = _ambiguous_candidates(catalogs, reason_detail)
        if item.default_reg in {"*", RegistrationType.OTHER.value}:
            # The file carries no registration class, which is exactly why the
            # two cabs tie. A lesson would put a whole nameplate's month on one
            # cab, and the month was a mix of both - so the file is the problem
            # and the file is what to fix.
            return replace(
                item, candidates=tuple(candidates), scope="model",
                needs=NEEDS_SOURCE,
                note=("ไฟล์ต้นทางไม่มีคอลัมน์ประเภทรถ (รย.) เลยแยก cab ไม่ได้ "
                      "ของจริงเดือนนั้นมันปนกันทั้งสองแบบ ถ้าสอนตรงนี้เท่ากับ"
                      "ยกยอดทั้งก้อนไปรุ่นเดียว — ทางที่ถูกคือหาไฟล์ชีตรายแถว "
                      "(long sheet) ของเดือนนั้นมาโหลดทับ"))
        return replace(item, candidates=tuple(candidates), scope="model",
                       needs=NEEDS_TEACH if candidates else NEEDS_CATALOG,
                       note=(f"สอนแบบผูกกับคลาส {item.default_reg} เท่านั้น "
                             "ไฟล์คลาสอื่นจะไม่โดนบทเรียนนี้"))

    if item.reason == "brand-not-found":
        candidates = _brand_candidates(catalogs,
                                       item.raw_brand or item.raw_label)
        best = candidates[0].score if candidates else 0.0
        if best < UNKNOWN_BRAND_FLOOR:
            return replace(
                item, scope="brand", needs=NEEDS_CATALOG,
                blocked=("ไม่มียี่ห้อไหนใน catalog ใกล้พอ — อันนี้คือยี่ห้อที่ยัง"
                         "ไม่มีจริงๆ ต้องไปเพิ่มใน catalog ไม่ใช่สอน alias"))
        return replace(
            item, candidates=tuple(candidates), scope="brand",
            needs=NEEDS_TEACH,
            note=("สอนยี่ห้อได้แค่พายอดไปเกาะที่ยี่ห้อ ยังไม่รู้รุ่น "
                  "แถวจะย้ายไปกอง 'รู้ยี่ห้อ แต่ไม่รู้ว่ารุ่นไหน' ต่อ"))

    if item.reason in {"model-not-found", "variant-not-found"}:
        if not item.raw_model.strip():
            return replace(item, scope="model", needs=NEEDS_SOURCE, blocked=(
                "ไฟล์ไม่ได้บอกรุ่นมาเลย มีแต่ยี่ห้อ — ยอดเกาะอยู่ที่ยี่ห้อแล้ว "
                "จะละเอียดกว่านี้ต้องได้ไฟล์ที่กรอกรุ่นมา"))
        if _looks_like_a_code(item.raw_model):
            return replace(item, scope="model", needs=NEEDS_NOTHING, blocked=(
                "หน้าตาเป็นรหัสโรงงาน ไม่ใช่ชื่อรุ่น — ยอดเกาะที่ยี่ห้อไว้แล้ว "
                "ปัดออกจากคิวได้"))
        brand_id, _, _ = catalogs[-1].brand_index.lookup(
            item.raw_brand or item.raw_label)
        if brand_id and not _in_every_year(brand_id, catalogs, "brand"):
            brand_id = ""
        if not brand_id:
            return replace(item, scope="model", needs=NEEDS_CATALOG, blocked=(
                "จับยี่ห้อจากป้ายนี้ไม่ได้ เลยยังไม่รู้ว่าจะเสนอรุ่นของใคร"))
        candidates = _model_candidates(catalogs, brand_id, item.search_text)
        if not candidates:
            # At this threshold there is essentially never a suggestion here:
            # anything scoring 0.86 against a model name is what the ingest
            # would have matched on its own. So the verdict is a catalog entry,
            # and the page still offers the brand's full model list underneath
            # for the cases where the owner knows something the strings do not
            # - that "TR TRANSFORMER" is a Hiace conversion, say.
            years = "/".join(str(y) for y in item.years)
            return replace(item, scope="model", needs=NEEDS_CATALOG,
                           brand_id=brand_id, blocked=(
                               "ไม่มีรุ่นไหนของยี่ห้อนี้ใกล้พอ — ถ้าเป็นรถที่ขายจริง "
                               f"ต้องเพิ่มรุ่นใน catalog ปี {years} ก่อน "
                               "แล้วโหลดไฟล์ซ้ำ"))
        return replace(item, candidates=tuple(candidates), scope="model",
                       brand_id=brand_id, needs=NEEDS_TEACH)

    return replace(item, needs=NEEDS_SOURCE,
                   blocked="กองนี้แก้ด้วย alias ไม่ได้ ต้องแก้ที่ไฟล์หรือ catalog")


def load_catalogs(data_dir: Path | str = DATA_DIR) -> dict[int, Catalog]:
    return {year: Catalog.load(data_dir, year)
            for year in available_years(data_dir)}


def queue(conn: sqlite3.Connection, catalogs: dict[int, Catalog], *,
          limit: int = 40, reason: Optional[str] = None) -> list[Item]:
    """Open review rows grouped by label, heaviest first.

    Grouping is what makes the queue finishable: 5,099 open rows are about 1,300
    distinct labels, and one decision about a label settles every month it
    appears in.
    """
    rows = conn.execute(
        "SELECT raw_brand, raw_model, raw_label, "
        "  substr(reason, 1, CASE WHEN instr(reason, ':') > 0 "
        "                        THEN instr(reason, ':') - 1 "
        "                        ELSE length(reason) END) AS bucket, "
        "  MIN(reason) AS detail, SUM(units) AS units, COUNT(*) AS rows, "
        "  GROUP_CONCAT(DISTINCT period) AS periods, "
        "  GROUP_CONCAT(DISTINCT source_id) AS sources, "
        "  GROUP_CONCAT(DISTINCT COALESCE(reg_type, '')) AS regs "
        "FROM ingest_review WHERE status = 'open' "
        "GROUP BY raw_brand, raw_model, raw_label, bucket "
        "ORDER BY units DESC"
    ).fetchall()

    names = {int(r["source_id"]): str(r["name"]) for r in
             conn.execute("SELECT source_id, name FROM dim_source")}

    items: list[Item] = []
    for row in rows:
        bucket = str(row["bucket"] or "")
        if reason and bucket != reason:
            continue
        source_ids = [int(s) for s in str(row["sources"] or "").split(",") if s]
        periods = tuple(sorted(
            p for p in str(row["periods"] or "").split(",") if p))
        years = tuple(sorted({int(p[:4]) for p in periods}))
        item = Item(
            key=f"{bucket}|{row['raw_brand']}|{row['raw_model']}|{row['raw_label']}",
            raw_brand=str(row["raw_brand"] or ""),
            raw_model=str(row["raw_model"] or ""),
            raw_label=str(row["raw_label"] or ""),
            reason=bucket,
            units=float(row["units"] or 0.0),
            rows=int(row["rows"] or 0),
            periods=periods,
            sources=tuple((sid, names.get(sid, str(sid))) for sid in source_ids),
            reg_types=tuple(sorted(
                r for r in str(row["regs"] or "").split(",") if r)),
            years=years,
        )
        span = [catalogs[year] for year in years if year in catalogs]
        if not span:
            item = replace(item, needs=NEEDS_CATALOG,
                           blocked="ยังไม่มี catalog ของปีนี้")
        else:
            item = _decorate(span, item, str(row["detail"] or ""))
        items.append(item)
        if len(items) >= limit:
            break
    return items


def teach(conn: sqlite3.Connection, item: Item, target_id: str, *,
          reg: Optional[str] = None) -> list[int]:
    """Record the decision. Returns the sources that now need re-reading."""
    teach_alias(conn, item.scope, item.raw_label, target_id,
                reg or item.default_reg or "*")
    return [source_id for source_id, _ in item.sources]


def dismiss(conn: sqlite3.Connection, items: Item | Sequence[Item]) -> int:
    """Take labels out of the queue without claiming they were matched.

    DLT prints a factory code in the รุ่น column often enough to be worth a
    button. The units are not touched - they are already counted at whatever
    grain they reached, usually the brand - so this changes the open question
    and nothing in any total.
    """
    batch = [items] if isinstance(items, Item) else list(items)
    if not batch:
        return 0
    changed = 0
    with conn:
        for item in batch:
            cursor = conn.execute(
                "UPDATE ingest_review SET status = 'ignored' "
                "WHERE status = 'open' AND raw_label = ? AND raw_brand = ? "
                "AND raw_model = ? "
                "AND reason LIKE ?",
                (item.raw_label, item.raw_brand, item.raw_model,
                 f"{item.reason}%"))
            changed += cursor.rowcount
    return changed


def known_models(catalog: Catalog, brand_id: str) -> list[dict[str, object]]:
    """What the catalog already files under a brand, names and aliases.

    Shown beside the unmatched labels because that is where the answer usually
    is. "745Le xDrive M Sport" needs an alias on the 7 Series, which already
    carries 740d and 750e; adding it as its own model would split the nameplate
    into a dozen pieces and every 7 Series number after it would be wrong.
    Whether a label is a new car or a trim of a car already listed is knowledge
    about cars, not about strings - a rule that guessed it scored 1.00 for
    Q7-against-Q3 and Model X-against-Model 3 - so the tool lays the two lists
    side by side and the person decides.
    """
    return [{"model": model.name_en, "id": model.id,
             "aliases": ", ".join(model.aliases)}
            for model in sorted(catalog.models_of(brand_id),
                                key=lambda m: m.name_en)]


def catalog_gaps(items: Iterable[Item]) -> list[dict[str, object]]:
    """The labels that need a catalog entry, rolled up the way the work is done.

    Adding models means opening one brand file and adding several at once, so
    the list is by brand and ordered by volume. That ordering is the whole
    value: 901 missing labels sorted alphabetically is a wall, and sorted by
    units it is an afternoon - Nissan, Mercedes-Benz, VOLT and Toyota carry a
    third of the outstanding volume between them.
    """
    by_brand: dict[str, dict[str, object]] = {}
    for item in items:
        if item.needs != NEEDS_CATALOG:
            continue
        brand = item.raw_brand or "(ไม่มียี่ห้อ)"
        entry = by_brand.setdefault(brand, {"brand": brand, "units": 0.0,
                                            "labels": 0, "models": [],
                                            "brand_id": item.brand_id,
                                            "years": item.years})
        entry["units"] = float(entry["units"]) + item.units
        entry["labels"] = int(entry["labels"]) + 1
        entry["models"].append(
            {"model": item.raw_model or item.raw_label, "units": item.units,
             "years": "/".join(str(y) for y in item.years),
             "months": len(item.periods)})
    for entry in by_brand.values():
        entry["models"].sort(key=lambda m: -float(m["units"]))
    return sorted(by_brand.values(), key=lambda e: -float(e["units"]))


def summary(items: Iterable[Item]) -> list[dict[str, object]]:
    """Units per bucket, so the queue reads as a plan rather than a pile."""
    totals: dict[str, dict[str, float]] = {}
    for item in items:
        bucket = totals.setdefault(item.needs, {"units": 0.0, "labels": 0.0})
        bucket["units"] += item.units
        bucket["labels"] += 1
    return [{"needs": needs, "label": NEEDS_LABELS.get(needs, needs),
             "labels": int(v["labels"]), "units": v["units"]}
            for needs, v in sorted(totals.items(), key=lambda kv: -kv[1]["units"])]


@dataclass
class Reload:
    source_id: int
    name: str
    path: str
    before_review: float = 0.0
    after_review: float = 0.0
    report: Optional[IngestReport] = None
    error: str = ""

    @property
    def moved(self) -> float:
        return self.before_review - self.after_review


def _colmap_for(name: str) -> Optional[ColumnMap]:
    # The monthly API exports have their own header spellings and are ingested
    # with an explicit map; everything else is sniffed, the same as first time.
    return dlt.column_map() if name.startswith("WEB ") else None


def reload_source(conn: sqlite3.Connection, source_id: int, *,
                  data_dir: Path | str = DATA_DIR) -> Reload:
    """Read one source file again, from nothing.

    Everything the source wrote is deleted first. Re-ingesting on top would not
    work: both fact tables key on the resolved id, so a label that used to land
    on the brand and now lands on a model adds a row rather than replacing one,
    and the month reads double. That is not hypothetical - it is what the upload
    page did to 2026-07's trim ledger before this existed.
    """
    row = conn.execute(
        "SELECT name, file_name FROM dim_source WHERE source_id = ?",
        (source_id,)).fetchone()
    if row is None:
        raise ValueError(f"no source {source_id}")
    name, file_name = str(row["name"]), str(row["file_name"] or "")
    state = Reload(source_id=source_id, name=name, path=file_name)

    path = Path(file_name)
    if not path.exists():
        state.error = f"ไฟล์ต้นทางหายไป: {file_name}"
        return state

    before = conn.execute(
        "SELECT COALESCE(SUM(units), 0) AS units FROM ingest_review "
        "WHERE source_id = ? AND status != 'ignored'", (source_id,)).fetchone()
    state.before_review = float(before["units"] or 0.0)

    period = conn.execute(
        "SELECT MIN(period) AS period FROM ingest_review WHERE source_id = ?",
        (source_id,)).fetchone()["period"]
    if not period:
        period = conn.execute(
            "SELECT MIN(period) AS period FROM fact_registration "
            "WHERE source_id = ?", (source_id,)).fetchone()["period"]
    if not period:
        state.error = "ไม่รู้ว่า source นี้เป็นเดือนไหน"
        return state
    catalog = Catalog.load(data_dir, int(str(period)[:4]))

    clear_source(conn, source_id)
    # The file is by definition the same payload that is already loaded - it is
    # the one being reloaded - so the duplicate guard has nothing to protect
    # here and would only refuse.
    state.report = ingest_csv(conn, catalog, path, name,
                              colmap=_colmap_for(name),
                              allow_duplicate_payload=True)
    after = conn.execute(
        "SELECT COALESCE(SUM(units), 0) AS units FROM ingest_review "
        "WHERE source_id = ? AND status != 'ignored'", (source_id,)).fetchone()
    state.after_review = float(after["units"] or 0.0)
    return state
