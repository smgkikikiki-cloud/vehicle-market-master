# ECO Sticker brochure ingestion

Vehicle Master can discover brochure PDFs without browser automation.

The ECO Sticker landing-page frontend calls:

1. `GET https://api-car.ecosticker.go.th/api/v2/landing-page/cars` for list pagination.
2. `GET https://api-car.ecosticker.go.th/api/v2/landing-page/<car_id>` for the public car-detail object.
3. The detail object's `brochure_link` is the exact URL used by the public **Download brochure** button.
4. Current brochure links use `GET /api/v1/file/data?file_id=<uuid>`, which redirects to a short-lived object-storage URL containing the PDF.

For the JAECOO 5 EV MAX+ record `98c1d7de-79db-4581-b332-69abe657a532`, the V2 detail response returns:

`https://api-car.ecosticker.go.th/api/v1/file/data?file_id=d086cd15-ea65-4b25-ab6f-80ffb2071a31`

A live probe confirmed that the file endpoint returns HTTP 302 to the stored PDF.

## Batch tool

```bash
python tools/ecosticker_brochures.py --car-id 98c1d7de-79db-4581-b332-69abe657a532
python tools/ecosticker_brochures.py --all --limit 20
python tools/ecosticker_brochures.py --all
```

The complete-list mode paginates the public list rather than depending on the site's search field, because exact-name searches have been observed to omit valid records.

PDFs and candidate JSONL are stored under `.cache/` by default and are not committed. Brochures are SHA-256 hashed so repeated ECO records pointing to the same PDF can share one parse.

## Extraction contract

The parser is intentionally **targeted**, not a generic brochure digitizer. It currently looks for useful fields such as drivetrain, motor count/power/torque, high-voltage battery capacity, range and standard, AC/DC charging, dimensions, wheelbase, ground clearance, tyres, seats, screen sizes, speakers, selected comfort equipment and common ADAS acronyms.

A field absent from a brochure stays absent. The extractor does not manufacture `false`, zero or a guessed value. A PDF with too little usable text is marked `needs_vision` for a later visual fallback.

Every extracted value carries page/raw-text/confidence evidence. The staging tool also maps ECO `car_id` to an existing `MarketTrim` when that UUID is already present in `source_refs`; it does **not** create trims automatically.

## Price rule

Brochure ingestion does not extract or write price. Current retail pricing remains a separate Price Ledger concern.

## Important V2 field caveat

Do not trust field names from the V2 detail API blindly. In the JAECOO 5 EV MAX+ live response, `battery_capacity` is `138`, while the brochure's actual high-voltage battery capacity is `50.6 kWh`; `138` corresponds to a different energy metric. The brochure/spec extractor therefore treats source semantics conservatively instead of auto-mapping every API key into Vehicle Master.
