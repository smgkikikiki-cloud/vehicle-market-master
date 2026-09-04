"""Turning a DLT statistics export into classified facts.

The rule that shapes this module: **a row is never guessed into the nearest
name.** Every input row ends up either as a fact with a recorded match method
and score, or as an open row in ``ingest_review`` with the reason it could not
be placed. Totals therefore reconcile against the source file, and the owner can
see exactly how much volume is still unclassified.

Matching runs brand-first, then model within that brand, then trim within that
model. Scoping each step keeps a ``Seal`` from a BYD row ever landing on a
Porsche, no matter how the fuzzy score falls.
"""

from __future__ import annotations

import csv
import hashlib
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Optional, Sequence

from . import trimledger
from .catalog import Catalog
from .db import loaded_years, register_source
from .normalize import MatchIndex, fold, period_key, split_brand_model
from .taxonomy import Grain, RegistrationType

#: Header spellings seen in DLT and FTI exports, folded.
HEADER_HINTS: dict[str, tuple[str, ...]] = {
    "period": ("period", "month", "yearmonth", "เดอน", "ปเดอน", "งวด", "วนท", "ป"),
    "brand": ("brand", "make", "ยหอ", "ยหอรถ", "ตรารถ"),
    "model": ("model", "แบบ", "แบบรถ", "รน", "รนรถ", "แบบและรน"),
    "variant": ("variant", "trim", "รนยอย", "แบบยอย"),
    "units": ("units", "count", "qty", "quantity", "total", "จำนวน", "จานวน",
              "คน", "จดทะเบยน", "ยอดจดทะเบยน"),
    "province": ("province", "จงหวด"),
    "registration_type": ("registration", "type", "ประเภท", "ลกษณะ", "รย"),
}


@dataclass
class ColumnMap:
    period: Optional[str] = None
    brand: Optional[str] = None
    model: Optional[str] = None
    variant: Optional[str] = None
    units: Optional[str] = None
    province: Optional[str] = None
    registration_type: Optional[str] = None

    def missing(self) -> list[str]:
        needed = {"model or brand": self.model or self.brand,
                  "units": self.units, "period": self.period}
        return [name for name, value in needed.items() if not value]


def sniff_columns(header: Sequence[str]) -> ColumnMap:
    """Best-effort header mapping. Anything it gets wrong is overridable."""
    mapping = ColumnMap()
    for column in header:
        folded = fold(column).replace(" ", "")
        for field_name, hints in HEADER_HINTS.items():
            if getattr(mapping, field_name):
                continue
            if any(hint and hint in folded for hint in hints):
                setattr(mapping, field_name, column)
                break
    return mapping


@dataclass
class IngestReport:
    source_id: int
    rows_read: int = 0
    facts_written: int = 0
    units_matched: float = 0.0
    units_review: float = 0.0
    by_grain: dict[str, int] = field(default_factory=dict)
    reasons: dict[str, int] = field(default_factory=dict)
    trim_rows: int = 0

    @property
    def units_total(self) -> float:
        return self.units_matched + self.units_review

    @property
    def coverage(self) -> float:
        return self.units_matched / self.units_total if self.units_total else 0.0

    def render(self) -> str:
        lines = [
            f"rows read       : {self.rows_read}",
            f"facts written   : {self.facts_written}",
            f"units matched   : {self.units_matched:,.0f}",
            f"units in review : {self.units_review:,.0f}",
            f"coverage        : {self.coverage:.1%}",
        ]
        if self.by_grain:
            lines.append("grain           : " + ", ".join(
                f"{k}={v}" for k, v in sorted(self.by_grain.items())))
        if self.trim_rows:
            lines.append(f"trim ledger     : {self.trim_rows} rows "
                         "(Chinese marques + Tesla)")
        if self.reasons:
            lines.append("review reasons  : " + ", ".join(
                f"{k}={v}" for k, v in sorted(self.reasons.items())))
        return "\n".join(lines)


class Resolver:
    """Brand -> model -> variant matching, scoped at every step.

    Matching always runs against every model of the brand, so a label that
    names its cab ("REVO DOUBLE CAB") resolves on its own. The DLT class of the
    file is used only to break a tie: a bare "REVO" matches all three cab models
    equally, and in a รย.1 export only the double cab is รย.1, so the tie
    resolves. Where the class still leaves two candidates - single vs smart cab
    in a รย.3 export - the row is reported ambiguous and queued, never guessed.
    """

    def __init__(self, catalog: Catalog, conn: sqlite3.Connection) -> None:
        self.catalog = catalog
        self.overrides: dict[tuple[str, str, str], str] = {
            (row["scope"], row["raw"], row["reg_type"]): row["target_id"]
            for row in conn.execute(
                "SELECT scope, raw, reg_type, target_id FROM alias_override")
        }
        self._model_index_by_brand: dict[str, MatchIndex] = {}
        self._variant_index_by_model: dict[str, MatchIndex] = {}
        self.last_candidates: list[str] = []

    def _models_index(self, brand_id: str) -> MatchIndex:
        if brand_id not in self._model_index_by_brand:
            index = MatchIndex()
            for model in self.catalog.models_of(brand_id):
                index.add(model.id, [model.name_en, model.name_th], priority=1)
                index.add(model.id, list(model.aliases))
            self._model_index_by_brand[brand_id] = index
        return self._model_index_by_brand[brand_id]

    def _has_residual(self, model_id: str, brand_id: str, text: str) -> bool:
        """True when ``text`` carries words the brand and model names do not."""
        model = self.catalog.models[model_id]
        brand = self.catalog.brands[brand_id]
        known: set[str] = set()
        for name in (model.name_en, model.name_th, brand.name_en, brand.name_th,
                     *model.aliases):
            known.update(fold(name).split())
        return bool([t for t in fold(text).split() if t not in known])

    def _narrow_by_class(self, candidates: list[str], reg: str) -> list[str]:
        if reg == "*" or not candidates:
            return candidates
        narrowed = [c for c in candidates
                    if self.catalog.models[c].registration_type.value == reg]
        if not narrowed and reg == RegistrationType.RY2.value:
            # A pickup registered รย.2 is a passenger conversion, so it sits on
            # the same body as the รย.1 rows rather than the cargo cabs.
            narrowed = [c for c in candidates
                        if self.catalog.models[c].registration_type
                        is RegistrationType.RY1]
        return narrowed or candidates

    def _variants_index(self, model_id: str) -> MatchIndex:
        if model_id not in self._variant_index_by_model:
            index = MatchIndex()
            for variant in self.catalog.variants_of(model_id):
                index.add(variant.id, [variant.name], priority=1)
                index.add(variant.id, list(variant.aliases))
            self._variant_index_by_model[model_id] = index
        return self._variant_index_by_model[model_id]

    def _override(self, scope: str, raw: str, reg: str = "*") -> Optional[str]:
        folded = fold(raw)
        return (self.overrides.get((scope, folded, reg))
                or self.overrides.get((scope, folded, "*")))

    def resolve(self, raw_brand: str, raw_model: str, raw_variant: str = "",
                reg: str = "*") -> tuple[Optional[str], Grain, str, float, str]:
        """Return ``(unit_id, grain, how, score, reason)``.

        ``unit_id`` is ``None`` only when even the brand could not be placed;
        otherwise the caller gets the deepest level that matched and the reason
        it stopped there.
        """
        label = " ".join(x for x in (raw_brand, raw_model, raw_variant) if x).strip()

        forced = (self._override("variant", label, reg)
                  or self._override("model", label, reg))
        if forced:
            grain = Grain.VARIANT if forced in self.catalog.variants else Grain.MODEL
            return forced, grain, "override", 1.0, ""

        brand_id = self._override("brand", raw_brand or label, reg)
        if not brand_id:
            brand_id, score, how = self.catalog.brand_index.lookup(raw_brand or label)
        else:
            score, how = 1.0, "override"
        if not brand_id and not raw_brand:
            # Combined "BRAND MODEL" cell: peel a known brand prefix off.
            surfaces = [b.name_en for b in self.catalog.brands.values()]
            surfaces += [b.name_th for b in self.catalog.brands.values() if b.name_th]
            surfaces += [a for b in self.catalog.brands.values() for a in b.aliases]
            prefix, rest = split_brand_model(label, surfaces)
            if prefix:
                brand_id, score, how = self.catalog.brand_index.lookup(prefix)
                raw_model = rest or raw_model
        if not brand_id:
            return None, Grain.BRAND, how, score, "brand-not-found"

        model_text = raw_model or label
        index = self._models_index(brand_id)
        model_id = self._override("model", model_text, reg)
        if model_id:
            model_score, model_how = 1.0, "override"
        else:
            model_id, model_score, model_how = index.lookup(model_text)
            if not model_id and model_how != "ambiguous" and model_text != label:
                # DLT sometimes splits a nameplate across the two columns -
                # ยี่ห้อ "GWM TANK" with รุ่น "300 HYBRID" - so the model name
                # only appears when the cells are read together.
                model_id, model_score, model_how = index.lookup(label)
            if not model_id and model_how == "ambiguous":
                # The label fits several models equally; the DLT class of the
                # file is the tie-breaker, and only when it leaves exactly one.
                narrowed = self._narrow_by_class(
                    index.ambiguous_candidates(model_text), reg)
                if len(narrowed) == 1:
                    model_id, model_score, model_how = (narrowed[0], 0.95,
                                                        "class-scoped")
                else:
                    self.last_candidates = narrowed
                    return brand_id, Grain.BRAND, how, score, (
                        "model-ambiguous: " + " | ".join(narrowed))
        if not model_id:
            self.last_candidates = []
            return brand_id, Grain.BRAND, how, score, "model-not-found"

        # For the marques that publish trim, the master stops at the model by
        # design: the detail belongs in the trim ledger, and letting the master
        # split some brands and fold others would make every brand-versus-brand
        # comparison unsafe.
        if self.catalog.brands[brand_id].trim_detail:
            return model_id, Grain.MODEL, model_how, model_score, ""

        # Otherwise only go looking for a spec line when the source actually
        # said something beyond the model name. Without this, a label like
        # "Honda e:N1" would match the folded line whose alias is "e:N1" and
        # claim trim-level precision the source never had.
        trim_text = raw_variant or (model_text if self._has_residual(
            model_id, brand_id, model_text) else "")
        if not trim_text:
            return model_id, Grain.MODEL, model_how, model_score, ""

        variant_id, variant_score, variant_how = self._variants_index(
            model_id).lookup(trim_text)
        if variant_id:
            return variant_id, Grain.VARIANT, variant_how, variant_score, ""
        return model_id, Grain.MODEL, model_how, model_score, (
            "variant-not-found" if raw_variant else "")


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_rows(path: Path, wide: bool = False, colmap: Optional[ColumnMap] = None
              ) -> tuple[ColumnMap, list[dict[str, Any]]]:
    """Read a long or wide CSV into ``{period, brand, model, variant, units}``.

    Wide mode is for the common DLT layout where each month is its own column;
    every non-label column whose header parses as a period becomes a row.
    """
    with open(path, newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        header = reader.fieldnames or []
        mapping = colmap or sniff_columns(header)
        raw_rows = list(reader)

    if not wide:
        return mapping, raw_rows

    period_columns: list[tuple[str, str]] = []
    label_columns = {mapping.brand, mapping.model, mapping.variant,
                     mapping.province, mapping.registration_type}
    for column in header:
        if column in label_columns:
            continue
        try:
            period_columns.append((column, period_key(column)))
        except ValueError:
            continue
    if not period_columns:
        raise ValueError(f"{path}: --wide given but no column header reads as a "
                         "period")

    long_rows: list[dict[str, Any]] = []
    for row in raw_rows:
        for column, period in period_columns:
            value = (row.get(column) or "").strip()
            if not value:
                continue
            new = {k: row.get(k) for k in label_columns if k}
            new["__period__"] = period
            new["__units__"] = value
            long_rows.append(new)
    mapping.period = "__period__"
    mapping.units = "__units__"
    return mapping, long_rows


def _number(raw: Any) -> Optional[float]:
    text = str(raw or "").replace(",", "").replace(" ", "").strip()
    if not text or text in {"-", "—", "n/a", "na"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def ingest_csv(conn: sqlite3.Connection, catalog: Catalog, path: Path | str,
               source_name: Optional[str] = None, *, wide: bool = False,
               colmap: Optional[ColumnMap] = None,
               default_registration_type: str = "RY1",
               url: str = "", publisher: str = "DLT",
               notes: str = "", trim_ledger: bool = True) -> IngestReport:
    path = Path(path)
    mapping, rows = read_rows(path, wide=wide, colmap=colmap)
    missing = mapping.missing()
    if missing:
        raise ValueError(
            f"{path}: cannot map required columns: {', '.join(missing)}. "
            f"Pass --col-<name> to name them explicitly.")

    source_id = register_source(
        conn, source_name or path.name, publisher=publisher, url=url,
        file_name=str(path), file_sha256=sha256_of(path),
        fetched_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        notes=notes)

    resolver = Resolver(catalog, conn)
    # A fact whose year has no catalog cannot be classified, and quietly
    # loading it would produce rows with every facet NULL. Queue it instead.
    known_years = set(loaded_years(conn)) or {catalog.year}
    report = IngestReport(source_id=source_id)
    facts: list[tuple] = []
    reviews: list[tuple] = []
    ledger_rows: list[dict[str, Any]] = []

    for row in rows:
        report.rows_read += 1
        units = _number(row.get(mapping.units))
        raw_brand = (row.get(mapping.brand) or "").strip() if mapping.brand else ""
        raw_model = (row.get(mapping.model) or "").strip() if mapping.model else ""
        raw_variant = ((row.get(mapping.variant) or "").strip()
                       if mapping.variant else "")
        label = " ".join(x for x in (raw_brand, raw_model, raw_variant) if x)

        try:
            period = period_key(row.get(mapping.period))
        except (ValueError, TypeError):
            reviews.append((source_id, None, raw_brand, raw_model, label, units,
                            "bad-period", None, None))
            report.reasons["bad-period"] = report.reasons.get("bad-period", 0) + 1
            report.units_review += units or 0.0
            continue

        if units is None:
            reviews.append((source_id, period, raw_brand, raw_model, label, None,
                            "bad-units", None, None))
            report.reasons["bad-units"] = report.reasons.get("bad-units", 0) + 1
            continue

        if int(period[:4]) not in known_years:
            reviews.append((source_id, period, raw_brand, raw_model, label, units,
                            "no-catalog-for-year", None, None))
            report.reasons["no-catalog-for-year"] = report.reasons.get(
                "no-catalog-for-year", 0) + 1
            report.units_review += units
            continue

        reg_raw = ((row.get(mapping.registration_type) or "").strip()
                   if mapping.registration_type else "")
        try:
            reg = RegistrationType.parse(reg_raw).value if reg_raw else \
                RegistrationType.parse(default_registration_type).value
        except ValueError:
            reg = RegistrationType.OTHER.value

        unit_id, grain, how, score, reason = resolver.resolve(
            raw_brand, raw_model, raw_variant, reg)

        # Group the ambiguity reasons so the report stays readable while the
        # review row keeps the full candidate list.
        bucket = reason.split(":", 1)[0] if reason else ""

        if unit_id is None:
            reviews.append((source_id, period, raw_brand, raw_model, label, units,
                            reason, None, score))
            report.reasons[bucket] = report.reasons.get(bucket, 0) + 1
            report.units_review += units
            continue

        if reason:
            # Placed, but less deeply than the source allowed. Record the fact
            # at the grain achieved *and* flag it, so precision loss is visible.
            reviews.append((source_id, period, raw_brand, raw_model, label, units,
                            reason, unit_id, score))
            report.reasons[bucket] = report.reasons.get(bucket, 0) + 1

        province = ((row.get(mapping.province) or "ALL").strip()
                    if mapping.province else "ALL")
        facts.append((period, reg, province or "ALL", unit_id, grain.value, units,
                      source_id, label, how, score))
        if grain in (Grain.MODEL, Grain.VARIANT):
            model_id = unit_id if grain is Grain.MODEL else \
                catalog.model_for_variant(unit_id).id
            ledger_rows.append({
                "period": period, "registration_type": reg,
                "province": province or "ALL", "model_id": model_id,
                "units": units, "raw_label": label,
            })
        report.units_matched += units
        report.by_grain[grain.value] = report.by_grain.get(grain.value, 0) + 1

    with conn:
        conn.executemany(
            "INSERT INTO fact_registration (period, registration_type, province, "
            "unit_id, grain, units, source_id, raw_label, match_how, match_score) "
            "VALUES (?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT (period, registration_type, province, unit_id, source_id, "
            "raw_label) DO UPDATE SET units = excluded.units, "
            "grain = excluded.grain, match_how = excluded.match_how, "
            "match_score = excluded.match_score",
            facts)
        conn.executemany(
            "INSERT INTO ingest_review (source_id, period, raw_brand, raw_model, "
            "raw_label, units, reason, best_guess, score) VALUES (?,?,?,?,?,?,?,?,?)",
            reviews)
    report.facts_written = len(facts)
    if trim_ledger:
        report.trim_rows = trimledger.record(conn, catalog, ledger_rows,
                                             source_id)
    return report


def teach_alias(conn: sqlite3.Connection, scope: str, raw: str, target_id: str,
                reg: str = "*") -> None:
    """Record an owner decision so the same label matches next time.

    ``reg`` limits the lesson to one DLT class, which is how "REVO" can mean the
    double cab in a รย.1 file and the smart cab in a รย.3 file.
    """
    if scope not in {"brand", "model", "variant"}:
        raise ValueError("scope must be brand, model or variant")
    if reg != "*":
        reg = RegistrationType.parse(reg).value
    with conn:
        conn.execute(
            "INSERT INTO alias_override (scope, raw, reg_type, target_id) "
            "VALUES (?,?,?,?) ON CONFLICT (scope, raw, reg_type) "
            "DO UPDATE SET target_id = excluded.target_id",
            (scope, fold(raw), reg, target_id))
        conn.execute(
            "UPDATE ingest_review SET status = 'mapped' "
            "WHERE status = 'open' AND lower(raw_label) LIKE ?",
            (f"%{raw.lower()}%",))
