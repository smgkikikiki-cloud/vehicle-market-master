"""Live retail price evidence: documents, claims, and the offers they support.

Three layers, because a price is only as good as the page it came from:

``SourceDocument``
    One fetched page.  Identified by the SHA-256 of its own content, so an
    outlet editing a published price produces a *new* document rather than
    silently changing an old one.

``PriceClaim``
    One number one outlet asserted, against one document.  Two outlets reporting
    the same launch make two claims.  A claim is evidence, never a fact.

``PriceOffer``
    :class:`vehreg.pricing.PriceRecord`.  A claim becomes an offer only when the
    publish policy below is satisfied; until then it sits in the review queue.

The policy, in one paragraph.  One Tier-A source (the manufacturer) is enough on
its own.  Tier-B sources need two claims that agree -- but Thai car media
republish the same press release within minutes, so two claims whose evidence
text is near-identical are counted once.  Without that check a single wrong
press release verifies itself.  Nothing here ever resolves a conflict by taking
the highest number, the lowest, or the newest article.

No network access lives in this module.  Fetching is ``tools/pricefeed_harvest``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
import hashlib
import json
import re
import unicodedata
from pathlib import Path
from typing import Iterable, Optional

from .catalog import Catalog, DATA_DIR, DEFAULT_YEAR
from .normalize import fold
from .pricing import PriceType

SCHEMA_VERSION = 1

#: Two documents whose body sketches overlap at least this much are one press
#: release wearing two mastheads, and vote once.
#:
#: The comparison is deliberately on the whole article, not on the price line.
#: A price table transcribed by two outlets reads almost identically line by
#: line -- "Alphard HEV Premium 4,290,000 บาท" -- while the writing around it
#: does not.  Comparing lines would collapse every independent report of the
#: same official price table into a single vote.
INDEPENDENCE_LIMIT = 0.55
SKETCH_SIZE = 96
SHINGLE_WORDS = 5

#: A claim below this is not evidence of anything; the amount was probably a
#: monthly instalment or a deposit that the extractor mistook for a price.
MIN_PLAUSIBLE_THB = 150_000
MAX_PLAUSIBLE_THB = 60_000_000


class PriceFeedError(ValueError):
    pass


class Tier(str, Enum):
    """How much one source is worth on its own."""

    A = "A"   # the manufacturer: pricelist, press release, official promotion
    B = "B"   # named car media that publish per-trim prices with dates
    C = "C"   # general media: discovery and corroboration only
    D = "D"   # social, dealer posts, OCR: alert only, never evidence

    @classmethod
    def parse(cls, raw: object) -> "Tier":
        try:
            return cls(str(raw or "").strip().upper())
        except ValueError as exc:
            raise PriceFeedError(f"unknown source tier {raw!r}") from exc


class ReviewReason(str, Enum):
    NO_TRIM_MATCH = "no_trim_match"
    TRIM_AMBIGUOUS = "trim_ambiguous"
    TRIM_NOT_IN_CATALOG = "trim_not_in_catalog"
    SINGLE_TIER_B = "single_tier_b"
    SOURCES_DISAGREE = "sources_disagree"
    CAMPAIGN_WITHOUT_CONDITIONS = "campaign_without_conditions"
    PRICE_TYPE_UNCLEAR = "price_type_unclear"
    IMPLAUSIBLE_AMOUNT = "implausible_amount"
    LOW_TIER_ONLY = "low_tier_only"


@dataclass(frozen=True, slots=True)
class Source:
    id: str
    name: str
    tier: Tier
    base_url: str = ""
    adapter: str = ""
    poll_minutes: int = 60
    #: Set for outlets that reprint manufacturer copy verbatim as a matter of
    #: course. They still produce claims; they just never carry a vote alone.
    republisher: bool = False

    def validate(self) -> list[str]:
        problems: list[str] = []
        if not self.id:
            problems.append("source id is required")
        if not isinstance(self.tier, Tier):
            problems.append(f"source {self.id}: tier must be a Tier")
        if type(self.poll_minutes) is not int or self.poll_minutes <= 0:
            problems.append(f"source {self.id}: poll_minutes must be positive")
        return problems


@dataclass(frozen=True, slots=True)
class SourceDocument:
    document_id: str          # "sha256:..."
    source_id: str
    url: str
    content_hash: str
    published_at: Optional[str] = None    # what the outlet says
    modified_at: Optional[str] = None     # changes when they edit a price
    first_seen_at: Optional[str] = None   # when this system first saw it
    fetched_at: Optional[str] = None
    title: str = ""
    snapshot_ref: str = ""
    #: A min-hash sketch of the article body. Two documents that are the same
    #: press release reprinted share most of it; two independent write-ups of
    #: the same price table share only the table.
    body_sketch: tuple[str, ...] = ()

    def validate(self) -> list[str]:
        problems: list[str] = []
        if not self.document_id.startswith("sha256:"):
            problems.append(f"{self.document_id}: document_id must be a sha256 ref")
        if not self.source_id:
            problems.append(f"{self.document_id}: source_id is required")
        if not self.url.startswith("https://"):
            problems.append(f"{self.document_id}: url must be https")
        for name in ("published_at", "modified_at", "first_seen_at", "fetched_at"):
            value = getattr(self, name)
            if value and _timestamp(value) is None:
                problems.append(f"{self.document_id}: {name} is not a timestamp")
        return problems

    def latency_hours(self) -> Optional[float]:
        """published_at -> first_seen_at, the half of the SLA we control."""
        published, seen = _timestamp(self.published_at), _timestamp(self.first_seen_at)
        if published is None or seen is None:
            return None
        return round((seen - published).total_seconds() / 3600, 2)


@dataclass(frozen=True, slots=True)
class PriceClaim:
    """One number, one outlet, one document. Evidence, not truth."""

    claim_id: str
    document_id: str
    source_id: str
    brand_raw: str
    model_raw: str
    trim_raw: str
    amount_thb: int
    price_type: PriceType
    evidence_text: str = ""          # short internal quote; never republished
    extraction_method: str = "rule"
    effective_from: Optional[str] = None
    effective_to: Optional[str] = None
    reference_price_thb: Optional[int] = None
    campaign_hint: str = ""
    option_hint: str = ""
    #: Filled by matching, not by extraction.
    trim_id: Optional[str] = None
    trim_candidates: tuple[str, ...] = ()

    def validate(self) -> list[str]:
        problems: list[str] = []
        if not self.claim_id:
            problems.append("claim_id is required")
        if not self.document_id:
            problems.append(f"{self.claim_id}: document_id is required")
        if type(self.amount_thb) is not int or self.amount_thb <= 0:
            problems.append(f"{self.claim_id}: amount_thb must be positive")
        if not isinstance(self.price_type, PriceType):
            problems.append(f"{self.claim_id}: price_type must be a PriceType")
        if not self.brand_raw or not self.model_raw:
            problems.append(f"{self.claim_id}: brand_raw and model_raw are required")
        return problems

    def key(self) -> tuple:
        """What two claims must share to be talking about the same price."""
        return (self.trim_id, self.amount_thb, self.price_type)


def _timestamp(raw: object) -> Optional[datetime]:
    if not raw:
        return None
    text = str(raw).strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def content_id(payload: bytes | str) -> str:
    data = payload.encode("utf-8") if isinstance(payload, str) else payload
    return "sha256:" + hashlib.sha256(data).hexdigest()


def normalise_evidence(text: str) -> str:
    """Strip everything that differs between two reprints of one press release."""
    value = unicodedata.normalize("NFKC", text or "").lower()
    value = re.sub(r"[\d,.]+", " ", value)      # the numbers are compared separately
    value = re.sub(r"[^\w฀-๿]+", " ", value)
    return " ".join(value.split())


def body_sketch(text: str) -> tuple[str, ...]:
    """A min-hash sketch of an article: the smallest hashed word 5-grams."""
    words = normalise_evidence(text).split()
    if len(words) < SHINGLE_WORDS:
        return ()
    hashes = {
        hashlib.blake2b(" ".join(words[i:i + SHINGLE_WORDS]).encode("utf-8"),
                        digest_size=6).hexdigest()
        for i in range(len(words) - SHINGLE_WORDS + 1)
    }
    return tuple(sorted(hashes)[:SKETCH_SIZE])


def sketch_overlap(left: Iterable[str], right: Iterable[str]) -> float:
    a, b = set(left), set(right)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def looks_reprinted(left: SourceDocument, right: SourceDocument) -> bool:
    """True when two articles are one press release under two mastheads."""
    if left.document_id == right.document_id:
        return True
    if not left.body_sketch or not right.body_sketch:
        # Nothing to compare. Two different outlets are still two observations;
        # claiming dependence here would silently sink every honest agreement.
        return False
    return sketch_overlap(left.body_sketch, right.body_sketch) >= INDEPENDENCE_LIMIT


# --------------------------------------------------------------------------
# Matching a claim to a trim
# --------------------------------------------------------------------------

def match_trim(catalog: Catalog, claim: PriceClaim) -> tuple[Optional[str], tuple[str, ...]]:
    """Return ``(trim_id, candidates)``. A tie is never broken automatically."""
    catalog.build_indexes()
    brand_id, _, _ = catalog.brand_index.lookup(claim.brand_raw)
    if brand_id is None:
        return None, ()
    # The grade line is more specific than the headline. One article covering
    # "Alphard / Vellfire" prices both, and only the line says which is which.
    model_id = None
    for text in (claim.trim_raw, f"{claim.brand_raw} {claim.model_raw}",
                 claim.model_raw):
        if not text:
            continue
        found, _, _ = catalog.model_index.lookup(f"{claim.brand_raw} {text}")
        if found is None:
            found, _, _ = catalog.model_index.lookup(text)
        if found is not None and found.startswith(brand_id + "."):
            model_id = found
            break
    if model_id is None:
        return None, ()
    model = catalog.models[model_id]
    siblings = [trim for trim in catalog.trims.values()
                if catalog.model_for_trim(trim.id).id == model_id]
    if not siblings:
        return None, ()

    wanted = grade_tokens(claim.trim_raw, model.name_en)
    exact = sorted({
        trim.id for trim in siblings
        if grade_tokens(trim.name, model.name_en) == wanted and wanted
        or any(grade_tokens(alias, model.name_en) == wanted and wanted
               for alias in trim.aliases)})
    if len(exact) == 1:
        return exact[0], tuple(exact)
    if exact:
        return None, tuple(exact)
    if not wanted:
        return None, ()

    # Media and the homologation register word the same grade differently
    # ("Fronx 1.5 GL 4AT" against "GL 1.5L 4AT"), so compare token sets rather
    # than strings.  A trim matches when every one of its own tokens appears in
    # the claim, and it must account for at least half of what the claim said --
    # otherwise a one-word grade would answer to every longer name.
    scored: list[tuple[int, str]] = []
    for trim in siblings:
        tokens = grade_tokens(trim.name, model.name_en)
        if tokens and tokens <= wanted and len(tokens) * 2 >= len(wanted):
            scored.append((len(tokens), trim.id))
    if not scored:
        return None, ()
    best = max(count for count, _ in scored)
    winners = sorted(trim_id for count, trim_id in scored if count == best)
    return (winners[0] if len(winners) == 1 else None), tuple(winners)


#: Unit words that one source writes and the other omits ("1.5L" vs "1.5").
NOISE_TOKENS = frozenset({"l", "cc", "litre", "liter", "รุ่น", "ใหม่"})


def grade_tokens(name: str, model_name: str) -> frozenset[str]:
    """The tokens that identify a grade: no nameplate, no unit noise."""
    nameplate = set(fold(model_name).split())
    return frozenset(
        token for token in fold(name).split()
        if token not in nameplate and token not in NOISE_TOKENS)


# --------------------------------------------------------------------------
# Consensus and the publish decision
# --------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class Verdict:
    state: str                       # "canonical" | "provisional" | "review"
    reasons: tuple[str, ...] = ()
    independent_claims: int = 0
    supporting_claim_ids: tuple[str, ...] = ()


def independent_groups(claims: Iterable[PriceClaim],
                       documents: Optional[dict[str, SourceDocument]] = None
                       ) -> list[list[PriceClaim]]:
    """Cluster claims that come from one voice. One group, one vote."""
    documents = documents or {}
    groups: list[list[PriceClaim]] = []
    for claim in claims:
        mine = documents.get(claim.document_id)
        for group in groups:
            same_voice = any(
                other.source_id == claim.source_id
                or (mine is not None and documents.get(other.document_id) is not None
                    and looks_reprinted(documents[other.document_id], mine))
                for other in group)
            if same_voice:
                group.append(claim)
                break
        else:
            groups.append([claim])
    return groups


def decide(claims: list[PriceClaim], sources: dict[str, Source], *,
           catalog: Optional[Catalog] = None,
           has_conditions: bool = True,
           documents: Optional[dict[str, SourceDocument]] = None) -> Verdict:
    """Whether a set of claims about one price may be published, and why not.

    ``claims`` must already agree on trim, amount and price type -- they are the
    supporting evidence for a single candidate offer.
    """
    if not claims:
        return Verdict("review", (ReviewReason.NO_TRIM_MATCH.value,))
    reasons: list[str] = []
    first = claims[0]

    if first.trim_id is None:
        reasons.append(ReviewReason.TRIM_AMBIGUOUS.value if first.trim_candidates
                       else ReviewReason.NO_TRIM_MATCH.value)
    elif catalog is not None and first.trim_id not in catalog.trims:
        reasons.append(ReviewReason.TRIM_NOT_IN_CATALOG.value)
    if not MIN_PLAUSIBLE_THB <= first.amount_thb <= MAX_PLAUSIBLE_THB:
        reasons.append(ReviewReason.IMPLAUSIBLE_AMOUNT.value)
    if first.price_type is PriceType.UNKNOWN:
        reasons.append(ReviewReason.PRICE_TYPE_UNCLEAR.value)
    if first.price_type is PriceType.CAMPAIGN_PRICE and not has_conditions:
        reasons.append(ReviewReason.CAMPAIGN_WITHOUT_CONDITIONS.value)

    tiers = {claim.source_id: sources[claim.source_id].tier
             for claim in claims if claim.source_id in sources}
    usable = [claim for claim in claims
              if tiers.get(claim.source_id) in (Tier.A, Tier.B)]
    groups = independent_groups(usable, documents)
    votes = len(groups)
    supporting = tuple(claim.claim_id for claim in claims)

    if reasons:
        return Verdict("review", tuple(sorted(set(reasons))), votes, supporting)
    if not usable:
        return Verdict("review", (ReviewReason.LOW_TIER_ONLY.value,), 0, supporting)

    tier_a = any(tiers.get(claim.source_id) is Tier.A for claim in usable)
    if tier_a:
        return Verdict("canonical", (), votes, supporting)
    # Tier B alone: two independent voices, and neither a known republisher on
    # its own, before anything reaches the public site.
    solo_republisher = all(sources[c.source_id].republisher for c in usable)
    if votes >= 2 and not solo_republisher:
        return Verdict("canonical", (), votes, supporting)
    return Verdict("provisional", (ReviewReason.SINGLE_TIER_B.value,), votes, supporting)


def group_claims(claims: Iterable[PriceClaim]) -> dict[tuple, list[PriceClaim]]:
    """Bucket claims by the price they describe, so disagreement is visible."""
    buckets: dict[tuple, list[PriceClaim]] = {}
    for claim in claims:
        buckets.setdefault(claim.key(), []).append(claim)
    return buckets


def conflicting(claims: Iterable[PriceClaim]) -> dict[tuple, set[int]]:
    """trim+type -> the distinct amounts claimed. More than one is a conflict."""
    seen: dict[tuple, set[int]] = {}
    for claim in claims:
        if claim.trim_id is None:
            continue
        seen.setdefault((claim.trim_id, claim.price_type), set()).add(claim.amount_thb)
    return {key: amounts for key, amounts in seen.items() if len(amounts) > 1}


# --------------------------------------------------------------------------
# On-disk store
# --------------------------------------------------------------------------

def feed_dir(data_dir: Path | str = DATA_DIR, year: int = DEFAULT_YEAR) -> Path:
    return Path(data_dir) / str(year) / "market" / "pricefeed"


def load_sources(data_dir: Path | str = DATA_DIR,
                 year: int = DEFAULT_YEAR) -> dict[str, Source]:
    path = feed_dir(data_dir, year) / "sources.json"
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload.get("sources"), list):
        raise PriceFeedError(f"{path}: sources must be an array")
    sources: dict[str, Source] = {}
    for raw in payload["sources"]:
        unknown = set(raw) - set(Source.__dataclass_fields__)
        if unknown:
            raise PriceFeedError(f"{path}: unknown source fields: {sorted(unknown)}")
        source = Source(
            id=str(raw.get("id") or "").strip(),
            name=str(raw.get("name") or "").strip(),
            tier=Tier.parse(raw.get("tier")),
            base_url=str(raw.get("base_url") or "").strip(),
            adapter=str(raw.get("adapter") or "").strip(),
            poll_minutes=int(raw.get("poll_minutes") or 60),
            republisher=bool(raw.get("republisher", False)),
        )
        problems = source.validate()
        if problems:
            raise PriceFeedError(f"{path}: " + "; ".join(problems))
        if source.id in sources:
            raise PriceFeedError(f"{path}: duplicate source {source.id}")
        sources[source.id] = source
    return sources


def _claim_from_dict(raw: dict) -> PriceClaim:
    unknown = set(raw) - set(PriceClaim.__dataclass_fields__)
    if unknown:
        raise PriceFeedError(f"unknown claim fields: {sorted(unknown)}")
    return PriceClaim(
        claim_id=str(raw.get("claim_id") or ""),
        document_id=str(raw.get("document_id") or ""),
        source_id=str(raw.get("source_id") or ""),
        brand_raw=str(raw.get("brand_raw") or ""),
        model_raw=str(raw.get("model_raw") or ""),
        trim_raw=str(raw.get("trim_raw") or ""),
        amount_thb=int(raw.get("amount_thb") or 0),
        price_type=PriceType.parse(raw.get("price_type")),
        evidence_text=str(raw.get("evidence_text") or ""),
        extraction_method=str(raw.get("extraction_method") or "rule"),
        effective_from=raw.get("effective_from") or None,
        effective_to=raw.get("effective_to") or None,
        reference_price_thb=(int(raw["reference_price_thb"])
                             if raw.get("reference_price_thb") else None),
        campaign_hint=str(raw.get("campaign_hint") or ""),
        trim_id=raw.get("trim_id") or None,
        trim_candidates=tuple(raw.get("trim_candidates") or ()),
    )


def _document_from_dict(raw: dict) -> SourceDocument:
    unknown = set(raw) - set(SourceDocument.__dataclass_fields__)
    if unknown:
        raise PriceFeedError(f"unknown document fields: {sorted(unknown)}")
    text_fields = ("document_id", "source_id", "url", "content_hash",
                   "title", "snapshot_ref")
    payload = {name: raw.get(name) or ("" if name in text_fields else None)
               for name in SourceDocument.__dataclass_fields__}
    payload["body_sketch"] = tuple(raw.get("body_sketch") or ())
    return SourceDocument(**payload)


def load_batch(path: Path | str) -> tuple[list[SourceDocument], list[PriceClaim]]:
    """Read one harvest batch: the documents fetched and the claims read off them."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    for key in ("documents", "claims"):
        if not isinstance(payload.get(key), list):
            raise PriceFeedError(f"{path}: {key} must be an array")
    documents = [_document_from_dict(raw) for raw in payload["documents"]]
    claims = [_claim_from_dict(raw) for raw in payload["claims"]]
    known = {document.document_id for document in documents}
    problems: list[str] = []
    for document in documents:
        problems.extend(document.validate())
    for claim in claims:
        problems.extend(claim.validate())
        if claim.document_id not in known:
            problems.append(f"{claim.claim_id}: claim has no document in this batch")
    if problems:
        raise PriceFeedError(f"{path}: " + "; ".join(sorted(set(problems))))
    return documents, claims


def to_dict(obj) -> dict:
    payload = {}
    for name in obj.__dataclass_fields__:
        value = getattr(obj, name)
        payload[name] = value.value if isinstance(value, Enum) else (
            list(value) if isinstance(value, tuple) else value)
    return payload


# --------------------------------------------------------------------------
# The run: claims in, offers and review items out
# --------------------------------------------------------------------------

@dataclass
class RunResult:
    offers: list[dict] = field(default_factory=list)
    provisional: list[dict] = field(default_factory=list)
    review: list[dict] = field(default_factory=list)
    trim_proposals: list[dict] = field(default_factory=list)
    latency: dict = field(default_factory=dict)

    def summary(self) -> dict:
        return {
            "canonical_offers": len(self.offers),
            "provisional": len(self.provisional),
            "review_items": len(self.review),
            "trim_proposals": len(self.trim_proposals),
            **self.latency,
        }


def measure_latency(documents: Iterable[SourceDocument]) -> dict:
    """published_at -> first_seen_at, per batch. The SLA, measured not asserted."""
    values = sorted(v for v in (d.latency_hours() for d in documents) if v is not None)
    if not values:
        return {"documents_with_latency": 0}
    middle = len(values) // 2
    median = (values[middle] if len(values) % 2
              else round((values[middle - 1] + values[middle]) / 2, 2))
    return {
        "documents_with_latency": len(values),
        "discovery_median_hours": median,
        "discovery_max_hours": values[-1],
        "within_24h": sum(v <= 24 for v in values),
    }


AGENT_REVIEWER = "agent-proposed"


def load_decisions(path: Path | str) -> dict[str, dict]:
    """Reviewer answers, keyed by claim id.

    A decision may name the trim a claim belongs to, the campaign and option a
    campaign price sits under, or reject the claim outright.  As in Phase 2, a
    decision this code wrote carries ``reviewer: "agent-proposed"`` and does not
    count: only a person's answer moves a price.
    """
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload.get("decisions"), list):
        raise PriceFeedError(f"{path}: decisions must be an array")
    allowed = {"claim_id", "trim_id", "campaign_id", "option_id", "action",
               "reviewer", "reviewed_at", "notes"}
    out: dict[str, dict] = {}
    for raw in payload["decisions"]:
        unknown = set(raw) - allowed
        if unknown:
            raise PriceFeedError(f"{path}: unknown decision fields: {sorted(unknown)}")
        claim_id = str(raw.get("claim_id") or "").strip()
        if not claim_id:
            raise PriceFeedError(f"{path}: decision without a claim_id")
        if claim_id in out:
            raise PriceFeedError(f"{path}: duplicate decision for {claim_id}")
        reviewer = str(raw.get("reviewer") or "").strip()
        if not reviewer:
            raise PriceFeedError(f"{path}: {claim_id}: reviewer is required")
        action = str(raw.get("action") or "accept").strip()
        if action not in {"accept", "reject"}:
            raise PriceFeedError(f"{path}: {claim_id}: invalid action {action!r}")
        out[claim_id] = {
            "claim_id": claim_id,
            "trim_id": raw.get("trim_id") or None,
            "campaign_id": raw.get("campaign_id") or None,
            "option_id": raw.get("option_id") or None,
            "action": action,
            "reviewer": reviewer,
            "origin": "agent" if reviewer.lower() == AGENT_REVIEWER else "human",
            "reviewed_at": raw.get("reviewed_at") or None,
            "notes": str(raw.get("notes") or ""),
        }
    return out


def run(documents: list[SourceDocument], claims: list[PriceClaim],
        sources: dict[str, Source], catalog: Catalog, *,
        campaigns: Optional[dict] = None,
        decisions: Optional[dict[str, dict]] = None) -> RunResult:
    """Match, group, decide. Pure: no file or network access."""
    campaigns = campaigns or {}
    decisions = decisions or {}
    matched: list[PriceClaim] = []
    for claim in claims:
        answer = decisions.get(claim.claim_id)
        if answer and answer["origin"] == "human" and answer["action"] == "reject":
            continue
        trim_id, candidates = match_trim(catalog, claim)
        changes = {"trim_id": trim_id, "trim_candidates": candidates}
        if answer and answer["origin"] == "human":
            # A person outranks the matcher, and is the only way a campaign
            # price ever learns which campaign it belongs to.
            if answer["trim_id"]:
                changes["trim_id"] = answer["trim_id"]
                changes["trim_candidates"] = (answer["trim_id"],)
            if answer["campaign_id"]:
                changes["campaign_hint"] = answer["campaign_id"]
                changes["option_hint"] = answer["option_id"] or ""
        matched.append(_replace(claim, **changes))

    disputed = conflicting(matched)
    by_document = {document.document_id: document for document in documents}
    result = RunResult(latency=measure_latency(documents))

    for key, group in group_claims(matched).items():
        first = group[0]
        # A campaign price is only publishable once it is attached to a campaign
        # that states at least one condition of its own.
        campaign = campaigns.get(first.campaign_hint)
        option = campaign.option(first.option_hint) if campaign else None
        has_conditions = bool(option and (
            option.conditions.text or option.conditions.booking_to
            or option.conditions.booking_from or option.conditions.quota_units
            or option.conditions.finance_required))
        verdict = decide(group, sources, catalog=catalog,
                         has_conditions=has_conditions, documents=by_document)
        if (first.trim_id, first.price_type) in disputed:
            verdict = Verdict("review",
                              tuple(sorted(set(verdict.reasons) |
                                           {ReviewReason.SOURCES_DISAGREE.value})),
                              verdict.independent_claims,
                              verdict.supporting_claim_ids)
        item = _item(first, group, verdict, by_document)
        if verdict.state == "canonical":
            result.offers.append(item)
        elif verdict.state == "provisional":
            result.provisional.append(item)
        else:
            result.review.append(item)
            if ReviewReason.NO_TRIM_MATCH.value in verdict.reasons:
                result.trim_proposals.append(_trim_proposal(first, group))
    return result


def _replace(claim: PriceClaim, **changes) -> PriceClaim:
    payload = {name: getattr(claim, name) for name in PriceClaim.__dataclass_fields__}
    payload.update(changes)
    return PriceClaim(**payload)


def _item(first: PriceClaim, group: list[PriceClaim], verdict: Verdict,
          documents: dict[str, SourceDocument]) -> dict:
    return {
        "trim_id": first.trim_id,
        "trim_candidates": list(first.trim_candidates),
        "amount_thb": first.amount_thb,
        "price_type": first.price_type.value,
        "reference_price_thb": first.reference_price_thb,
        "effective_from": first.effective_from,
        "effective_to": first.effective_to,
        "campaign_hint": first.campaign_hint,
        "option_hint": first.option_hint,
        "state": verdict.state,
        "reasons": list(verdict.reasons),
        "independent_claims": verdict.independent_claims,
        "claim_ids": list(verdict.supporting_claim_ids),
        "sources": sorted({claim.source_id for claim in group}),
        "urls": sorted({documents[claim.document_id].url for claim in group
                        if claim.document_id in documents}),
    }


def _trim_proposal(first: PriceClaim, group: list[PriceClaim]) -> dict:
    """A launch price and the trim it implies, as one decision for the owner.

    Without this the most valuable case -- a car announced today -- can never
    publish, because the trim it names does not exist until someone creates it.
    """
    return {
        "brand_raw": first.brand_raw,
        "model_raw": first.model_raw,
        "trim_raw": first.trim_raw,
        "amount_thb": first.amount_thb,
        "price_type": first.price_type.value,
        "claim_ids": [claim.claim_id for claim in group],
        "action": "propose_trim_and_price",
        "reviewer": "agent-proposed",
    }


def to_price_rows(result: RunResult, *, observed_at: str,
                  source_of: dict[str, Source]) -> list[dict]:
    """Canonical offers as PriceLedger rows. Nothing else is written."""
    rows: list[dict] = []
    for item in result.offers:
        row = {
            "trim_id": item["trim_id"],
            "amount_thb": item["amount_thb"],
            "price_type": item["price_type"],
            "observed_at": observed_at,
            "source": item["sources"][0],
            "source_ref": item["urls"][0] if item["urls"] else "",
        }
        for name in ("effective_from", "effective_to", "reference_price_thb"):
            if item.get(name):
                row[name] = item[name]
        if item["price_type"] == PriceType.CAMPAIGN_PRICE.value:
            row["campaign_id"] = item["campaign_hint"]
            if item.get("option_hint"):
                row["option_id"] = item["option_hint"]
        rows.append(row)
    return rows
