from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    if new in text:
        return
    if old not in text:
        raise SystemExit(f"marker not found in {path}: {old[:80]!r}")
    p.write_text(text.replace(old, new, 1), encoding="utf-8")


# ---------------------------------------------------------------- entities.py
replace_once(
    "vehreg/entities.py",
    '"""The four identity layers and the facet-resolution chain.\n\n    Brand  ->  Model  ->  Generation  ->  Variant\n',
    '"""The registration identity layers and the facet-resolution chain.\n\n    Brand  ->  Model  ->  Generation  ->  Variant\n\n``MarketTrim`` is a fifth, catalog-only child below Generation. It records the\nactual grades offered to buyers (price, dimensions and fitment) but is\ndeliberately outside ``RESOLUTION_CHAIN``: a trim never receives or allocates\nregistration volume merely because the catalog knows it exists.\n',
)

trim_entity = '''@dataclass(frozen=True, slots=True)\nclass MarketTrim:\n    """One marketed trim/grade, kept outside registration analytics.\n\n    ``Variant`` remains the analytical spec line used to classify DLT volume.\n    A MarketTrim is the retail offering beneath the generation and may point to\n    its parent analytical variant when that mapping is known. Its own exact\n    powertrain/price/specification is useful to market-offering and fitment\n    products, but ``resolve()`` and the cube never iterate trims.\n    """\n\n    id: str                                   # "toyota.alphard.ah40.trim.z_premier"\n    generation_id: str\n    name: str                                 # marketed grade, e.g. "Z Premier"\n    variant_id: Optional[str] = None           # analytical Variant, if known\n    powertrain: Powertrain = Powertrain.UNKNOWN\n    price_thb: Optional[float] = None\n    drivetrain: Drivetrain = Drivetrain.UNKNOWN\n    engine_code: str = ""\n    engine_cc: Optional[int] = None\n    battery_kwh: Optional[float] = None\n    transmission: str = ""\n    seats: Optional[int] = None\n    length_mm: Optional[int] = None\n    width_mm: Optional[int] = None\n    height_mm: Optional[int] = None\n    wheelbase_mm: Optional[int] = None\n    tire_front: str = ""\n    tire_rear: str = ""\n    wheel_front: str = ""\n    wheel_rear: str = ""\n    aliases: tuple[str, ...] = ()\n    # Source-system IDs only. Example: {"ecosticker": ("uuid",)}.\n    source_refs: dict[str, tuple[str, ...]] = field(default_factory=dict)\n    notes: str = ""\n\n    def validate(self) -> list[str]:\n        problems: list[str] = []\n        if self.price_thb is not None and self.price_thb < 0:\n            problems.append("price_thb must not be negative")\n        if self.engine_cc is not None and self.engine_cc <= 0:\n            problems.append("engine_cc must be positive")\n        if self.battery_kwh is not None and self.battery_kwh < 0:\n            problems.append("battery_kwh must not be negative")\n        if self.seats is not None and self.seats <= 0:\n            problems.append("seats must be positive")\n        for field_name in ("length_mm", "width_mm", "height_mm", "wheelbase_mm"):\n            value = getattr(self, field_name)\n            if value is not None and value <= 0:\n                problems.append(f"{field_name} must be positive")\n        return [f"trim {self.id}: {p}" for p in problems]\n\n\n'''
replace_once(
    "vehreg/entities.py",
    "@dataclass(frozen=True, slots=True)\nclass ResolvedVehicle:",
    trim_entity + "@dataclass(frozen=True, slots=True)\nclass ResolvedVehicle:",
)

# ---------------------------------------------------------------- catalog.py
replace_once(
    "vehreg/catalog.py",
    "    brand -> models[] -> generations[] -> variants[]\n",
    "    brand -> models[] -> generations[] -> variants[]\n                                      -> trims[]  (retail catalog only)\n",
)
replace_once(
    "vehreg/catalog.py",
    "    Brand, Generation, Model, ResolvedVehicle, Variant, cross_check, resolve,\n",
    "    Brand, Generation, MarketTrim, Model, ResolvedVehicle, Variant, cross_check, resolve,\n",
)
replace_once(
    "vehreg/catalog.py",
    "        self.variants: dict[str, Variant] = {}\n        self.brand_index = MatchIndex()\n",
    "        self.variants: dict[str, Variant] = {}\n        # Retail trims are deliberately separate from analytical variants.\n        self.trims: dict[str, MarketTrim] = {}\n        self.brand_index = MatchIndex()\n",
)
replace_once(
    "vehreg/catalog.py",
    "        self.variant_index = MatchIndex()\n        self._models_by_brand: dict[str, list[str]] = {}\n        self._variants_by_model: dict[str, list[str]] = {}\n",
    "        self.variant_index = MatchIndex()\n        # Useful to catalog/enrichment code only; Resolver does not consult it.\n        self.trim_index = MatchIndex()\n        self._models_by_brand: dict[str, list[str]] = {}\n        self._variants_by_model: dict[str, list[str]] = {}\n        self._trims_by_generation: dict[str, list[str]] = {}\n        self._trims_by_variant: dict[str, list[str]] = {}\n",
)
replace_once(
    "vehreg/catalog.py",
    "        self.generations[gen_id] = Generation(\n",
    "        self._trims_by_generation[gen_id] = []\n        self.generations[gen_id] = Generation(\n",
)
replace_once(
    "vehreg/catalog.py",
    "        for raw_variant in raw.get(\"variants\", []):\n            self._add_variant(gen_id, model_id, raw_variant, source)\n\n    def _add_variant",
    "        for raw_variant in raw.get(\"variants\", []):\n            self._add_variant(gen_id, model_id, raw_variant, source)\n        # Market trims are loaded only after variants, so an optional `variant`\n        # reference can be resolved without changing the analytical hierarchy.\n        for raw_trim in raw.get(\"trims\", []):\n            self._add_trim(gen_id, raw_trim, source)\n\n    def _add_variant",
)

trim_loader = '''    def _resolve_trim_variant_ref(self, gen_id: str, raw_ref: Any,\n                                  source: str) -> Optional[str]:\n        if raw_ref in (None, ""):\n            return None\n        ref = str(raw_ref).strip()\n        if ref in self.variants and self.variants[ref].generation_id == gen_id:\n            return ref\n        candidate = f"{gen_id}.{slug(ref)}"\n        if candidate in self.variants:\n            return candidate\n        for variant in self.variants.values():\n            if variant.generation_id == gen_id and slug(variant.name) == slug(ref):\n                return variant.id\n        raise CatalogError(\n            f"{source}: trim variant reference {ref!r} does not exist under {gen_id}")\n\n    def _add_trim(self, gen_id: str, raw: dict, source: str) -> None:\n        if not raw.get("name"):\n            raise CatalogError(f"{source}: trim under {gen_id} is missing name")\n        trim_id = f"{gen_id}.trim.{slug(raw.get('id') or raw['name'])}"\n        if trim_id in self.trims:\n            raise CatalogError(f"{source}: duplicate trim id {trim_id!r}")\n        variant_id = self._resolve_trim_variant_ref(\n            gen_id, raw.get("variant_id") or raw.get("variant"), source)\n        source_refs = {\n            str(key): _tuple(value)\n            for key, value in dict(raw.get("source_refs") or {}).items()\n            if str(key).strip()\n        }\n        trim = MarketTrim(\n            id=trim_id,\n            generation_id=gen_id,\n            name=raw["name"],\n            variant_id=variant_id,\n            powertrain=_facet(Powertrain, raw.get("powertrain"),\n                              Powertrain.UNKNOWN),\n            price_thb=raw.get("price_thb"),\n            drivetrain=_facet(Drivetrain, raw.get("drivetrain"),\n                              Drivetrain.UNKNOWN),\n            engine_code=raw.get("engine_code", ""),\n            engine_cc=raw.get("engine_cc"),\n            battery_kwh=raw.get("battery_kwh"),\n            transmission=raw.get("transmission", ""),\n            seats=raw.get("seats"),\n            length_mm=raw.get("length_mm"),\n            width_mm=raw.get("width_mm"),\n            height_mm=raw.get("height_mm"),\n            wheelbase_mm=raw.get("wheelbase_mm"),\n            tire_front=raw.get("tire_front", ""),\n            tire_rear=raw.get("tire_rear", ""),\n            wheel_front=raw.get("wheel_front", ""),\n            wheel_rear=raw.get("wheel_rear", ""),\n            aliases=_tuple(raw.get("aliases")),\n            source_refs=source_refs,\n            notes=raw.get("notes", ""),\n        )\n        self.trims[trim_id] = trim\n        self._trims_by_generation.setdefault(gen_id, []).append(trim_id)\n        if variant_id:\n            self._trims_by_variant.setdefault(variant_id, []).append(trim_id)\n\n'''
replace_once(
    "vehreg/catalog.py",
    "    # -------------------------------------------------------------- indexes\n",
    trim_loader + "    # -------------------------------------------------------------- indexes\n",
)
replace_once(
    "vehreg/catalog.py",
    "        self.variant_index = MatchIndex()\n        for brand in self.brands.values():\n",
    "        self.variant_index = MatchIndex()\n        self.trim_index = MatchIndex()\n        for brand in self.brands.values():\n",
)
replace_once(
    "vehreg/catalog.py",
    "        for variant in self.variants.values():\n            model = self.model_for_variant(variant.id)\n            surfaces = [variant.name, *variant.aliases]\n            surfaces += [f\"{model.name_en} {s}\" for s in surfaces if s]\n            self.variant_index.add(variant.id, [s for s in surfaces if s])\n\n    # ------------------------------------------------------------ traversal\n",
    "        for variant in self.variants.values():\n            model = self.model_for_variant(variant.id)\n            surfaces = [variant.name, *variant.aliases]\n            surfaces += [f\"{model.name_en} {s}\" for s in surfaces if s]\n            self.variant_index.add(variant.id, [s for s in surfaces if s])\n        for trim in self.trims.values():\n            model = self.model_for_trim(trim.id)\n            surfaces = [trim.name, *trim.aliases]\n            surfaces += [f\"{model.name_en} {s}\" for s in surfaces if s]\n            self.trim_index.add(trim.id, [s for s in surfaces if s])\n\n    # ------------------------------------------------------------ traversal\n",
)

trim_traversal = '''    def generation_for_trim(self, trim_id: str) -> Generation:\n        return self.generations[self.trims[trim_id].generation_id]\n\n    def model_for_trim(self, trim_id: str) -> Model:\n        return self.models[self.generation_for_trim(trim_id).model_id]\n\n    def brand_for_trim(self, trim_id: str) -> Brand:\n        return self.brands[self.model_for_trim(trim_id).brand_id]\n\n    def variant_for_trim(self, trim_id: str) -> Optional[Variant]:\n        variant_id = self.trims[trim_id].variant_id\n        return self.variants.get(variant_id) if variant_id else None\n\n    def trims_of_generation(self, generation_id: str) -> list[MarketTrim]:\n        return [self.trims[t] for t in self._trims_by_generation.get(generation_id, [])]\n\n    def trims_of_variant(self, variant_id: str) -> list[MarketTrim]:\n        return [self.trims[t] for t in self._trims_by_variant.get(variant_id, [])]\n\n    def trims_of(self, model_id: str) -> list[MarketTrim]:\n        out: list[MarketTrim] = []\n        for generation in self.generations_of(model_id):\n            out.extend(self.trims_of_generation(generation.id))\n        return out\n\n'''
replace_once(
    "vehreg/catalog.py",
    "    def models_of(self, brand_id: str) -> list[Model]:\n",
    trim_traversal + "    def models_of(self, brand_id: str) -> list[Model]:\n",
)
replace_once(
    "vehreg/catalog.py",
    "    def iter_resolved(self) -> Iterator[ResolvedVehicle]:\n        for variant_id in self.variants:\n            yield self.resolve(variant_id)\n",
    "    def iter_resolved(self) -> Iterator[ResolvedVehicle]:\n        # Intentionally variants only. Retail trims enrich the catalog but never\n        # multiply or allocate registration facts.\n        for variant_id in self.variants:\n            yield self.resolve(variant_id)\n",
)
replace_once(
    "vehreg/catalog.py",
    "        problems += self.duplicate_body_warnings()\n",
    "        for trim in self.trims.values():\n            problems += trim.validate()\n            if trim.variant_id:\n                parent = self.variants[trim.variant_id]\n                if trim.powertrain is not Powertrain.UNKNOWN and \\\n                        parent.powertrain is not Powertrain.UNKNOWN and \\\n                        trim.powertrain is not parent.powertrain:\n                    problems.append(\n                        f\"trim {trim.id}: powertrain {trim.powertrain.value} \"\n                        f\"does not match analytical variant {parent.id} \"\n                        f\"({parent.powertrain.value})\")\n        problems += self.duplicate_body_warnings()\n",
)

# ---------------------------------------------------------------- __init__.py
replace_once(
    "vehreg/__init__.py",
    "    entities   Brand / Model / Generation / Variant + the override resolver\n",
    "    entities   Brand / Model / Generation / Variant + retail MarketTrim\n",
)
replace_once(
    "vehreg/__init__.py",
    "    Brand, Generation, Model, ResolvedVehicle, Variant, resolve,\n",
    "    Brand, Generation, MarketTrim, Model, ResolvedVehicle, Variant, resolve,\n",
)
