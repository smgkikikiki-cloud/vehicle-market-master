# Regional Market

## Purpose

Regional Market is a **separate curated product surface** from the national market dashboard.

- National Market = broad market breadth and canonical national registration facts.
- Regional Market = selective geographic depth for important mass-market models.
- Research / newsletter = interpretation that may use deeper internal datasets than either customer-facing surface exposes.

Provincial data is not a new filter on the national fact table. It is stored in its own warehouse table because it is a finer-grain representation of the same registrations and would double-count the market if mixed with national facts.

## Source grain

The DLT workbook currently supported by the importer has a `Data` sheet with the exact columns:

`ปี | เดือน | ประเภทรถ | จังหวัด | ยี่ห้อรถ | รุ่นรถ | จำนวนรถ`

The source is treated as a **snapshot**. Newer versions replace the previous snapshot under the stable source key `DLT Provincial Brand-Model-Province`; they are not added on top of one another.

Province means **registration location**, not proven dealer retail-sale territory.

## Private source handling

Do not commit the raw provincial workbook to the public repository.

Private data paths are ignored under:

- `data/private/`
- `data/provincial_raw/`

For a server deployment, mount/store the workbook privately and configure:

```bash
VEHREG_PROVINCIAL_XLSX=/private/path/provincial.xlsx
```

The Regional Market page bootstraps that snapshot idempotently when the environment variable is present. National pages continue to work without it.

Admin manual import:

```bash
python -m vehreg.provincial_cli ingest /private/path/provincial.xlsx
python -m vehreg.provincial_cli qa
```

## Publication whitelist

Customer-visible models are explicitly selected in:

`data/research/geo_publish.csv`

The initial publication groups are deliberately small:

- Pickup
- Mass small car
- Mass EV / crossover

Possessing provincial data for a model does **not** automatically make it customer-facing. Publication is an editorial decision.

## Reader-facing metrics

Regional Market currently exposes:

- registration footprint by province
- regional mix
- share inside the selected competitive set
- geographic over-index
- province-specific competitive ranking

### Geographic over-index

For a selected model and curated competitive set:

`over-index = model share of category in province / model share of category nationwide`

Interpretation:

- `1.00x` = in line with national competitive position
- `1.50x` = 50% more concentrated/competitive in that province than nationally
- `0.70x` = under-indexes relative to national position

This is a registration-footprint measure, not dealer sales.

## Data quality

`provincial_review` retains rows the canonical matcher refuses to guess.

`python -m vehreg.provincial_cli qa` compares matched provincial totals against canonical national RY1/RY2/RY3 facts for periods where both are available.

Rolling 3M and YTD reader views are disabled when any month in the requested window is missing, rather than silently summing an incomplete window.
