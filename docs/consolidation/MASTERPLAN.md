# TDR + Vehicle Market Master Consolidation Masterplan

**Revision 2 — Approved architecture, 9 September 2026**

## Goal

รวม `smgkikikiki-cloud/vehicle-market-master` และ `smgkikikiki-cloud/TDR` ให้กลายเป็น product เดียว โดยมีหลักสำคัญคือ:

- `TDR` เป็น repository หลักในระยะยาว
- `vehicle-market-master` ถูก absorb เข้ามาเป็น internal automotive data engine
- มี canonical vehicle data เพียงชุดเดียว
- ไม่มีการกรอก Model / Trim / Powertrain / Specs / Price ซ้ำในสองระบบ
- เว็บ public, admin, market analytics และ report ใช้ข้อมูลจาก canonical model ชุดเดียวกัน
- กรอกหรือแก้ vehicle fact หนึ่งครั้ง แล้วให้ publish pipeline กระจายผลไปทุกหน้า/API ที่ใช้ fact นั้น
- หน้า vehicle catalog, ราคา, campaign พร้อมเงื่อนไข, specs และ production facts เปิดให้ public
- subscription ให้สิทธิ์ใช้ data analytics tools และข้อมูลยอดจดทะเบียน/ยอดขายที่นำเสนอแบบ visualized
- ห้าม redesign behavior ที่ใช้งานได้อยู่โดยไม่จำเป็น
- ข้อมูลไม่ครบไม่ถือเป็น bug
- งานนี้เน้น architecture consolidation ก่อน data population

---

# 1. Target Product Architecture

โครงสร้างแนวคิดสุดท้าย:

```text
TDR
│
├── Automotive Data Engine
│   ├── Brand
│   ├── Model
│   ├── Generation
│   ├── MarketTrim
│   ├── Specs
│   ├── Price Ledger
│   ├── ECO Sticker ingestion
│   ├── DLT ingestion / matching
│   ├── Registration warehouse
│   └── DLT Trim Ledger
│
├── Industry Facts
│   ├── Plant
│   ├── Production Program
│   ├── Local Content
│   └── MiT
│
├── TDR Web
│   ├── รถ
│   ├── Market / Analytics
│   ├── TDR Report
│   └── News / Editorial
│
└── Admin / Data Workbench

```

หลักสำคัญ:

```text
External Sources
ECO / DLT / OEM / Price Sources
          ↓
Ingestion / Canonical Vehicle Workbench
          ↓
Validate / Review / Canonical Vehicle Master
          ↓
Versioned Publish Pipeline
          ↓
Public Catalog + Paid Analytics Projections
          ↓
       TDR Web

```

---

# 2. Repository Strategy

ให้ `TDR` เป็น repo หลัก

ไม่ต้อง merge แบบ copy ทุกไฟล์มาชนกันทันที

ให้ย้าย capability จาก `vehicle-market-master` เข้า `TDR` เป็น domain/module ที่ชัดเจน

ตัวอย่าง target structure:

```text
TDR/
├── app/                         # Next.js web
├── components/
├── lib/
│
├── automotive/
│   ├── catalog/
│   ├── pricing/
│   ├── specs/
│   ├── ecosticker/
│   ├── dlt/
│   ├── registration/
│   ├── trimledger/
│   ├── matching/
│   └── provenance/
│
├── industry/
│   ├── production/
│   ├── plants/
│   ├── local_content/
│   └── mit/
│
├── scripts/
├── supabase/
└── tests/

```

ชื่อ folder เปลี่ยนได้ตามภาษาหรือ ecosystem ที่เหมาะสม แต่ domain boundary ต้องคงแบบนี้

หลัง migration เสร็จ:

- `TDR` = active main repository
- `vehicle-market-master` = archive/read-only หรือระบุใน README ว่า superseded by TDR

---

# 3. Canonical Vehicle Model

ใช้ architecture ของ `vehicle-market-master` เป็น canonical truth โดยรักษา stable IDs ที่ใช้งานอยู่แล้ว และสร้าง crosswalk ให้ object เดิมของ TDR

โครงหลัก:

```text
Brand
  ↓
Model
  ↓
Generation
  ├── Variant          # analytical registration classification
  └── MarketTrim       # actual retail grade

```

## Variant

`Variant` ใช้สำหรับ registration analytics เท่านั้น

- เป็น analytical spec line
- DLT volume สามารถ resolve มาที่ Variant ได้
- หลาย MarketTrim อาจ fold เข้า Variant เดียว ถ้า DLT แยกไม่ได้
- ห้ามถือว่า Variant คือ retail trim

## MarketTrim

`MarketTrim` คือรุ่นย่อยที่ขายจริง

ต้องรองรับ:

- exact powertrain
- drivetrain
- engine / motor
- battery
- transmission
- dimensions
- tyre
- wheel
- seats / payload
- source references
- comparable specs
- other paper specifications

MarketTrim ต้องไม่เก็บ registration volume

ห้ามเอา MarketTrim เข้า registration resolution chain ไม่ว่าข้อมูล DLT จะละเอียดเพียงใด

หาก DLT label มีหลักฐานตรงกับ MarketTrim ให้เก็บเป็น evidence-backed mapping แยกต่างหากสำหรับการแสดงผลหรือวิเคราะห์เฉพาะ coverage ที่รองรับ ห้ามเขียน registration fact หรือยอดสะสมลงบน MarketTrim

---

# 4. Price Architecture

ห้ามใช้ `TDR.trims.price_baht` เป็น source of truth ต่อไป

ราคา canonical ต้องอยู่ใน Price Ledger

```text
MarketTrim
   ↓
PriceLedger

```

Price Ledger ต้องรองรับ:

- list price
- introductory price
- campaign price
- finance price
- dealer price
- estimated price
- ECO Sticker price
- effective period
- superseded / withdrawn / sold out
- conditions
- historical prices

Campaign price ห้าม overwrite MSRP

เก็บ price history

หน้าเว็บสามารถ derive:

```text
current price
price range
historical price

```

จาก Price Ledger

สามารถมี cached/display fields ใน serving DB ได้ แต่ห้ามเป็น master ที่แก้เอง

---

# 5. Specs Architecture

สเปก canonical มาจาก Vehicle Master

รวม:

- powertrain
- engine
- battery
- motor output
- torque
- transmission
- drivetrain
- dimensions
- tyre
- wheel
- EV range
- seats
- payload
- fitment
- comparable specs

ใช้ explicit states เมื่อเหมาะสม:

```text
KNOWN
UNKNOWN
NOT_AVAILABLE
NOT_APPLICABLE

```

และ provenance เช่น:

```text
VERIFIED
PROVISIONAL

```

ห้ามสร้างค่าที่ไม่มี source

ข้อมูลไม่ครบ = acceptable

ค่าผิดหรือ invented = ไม่ acceptable

---

# 6. ECO Sticker

ECO Sticker เป็น evidence/enrichment source

ไม่ใช่ product authority

flow:

```text
ECO snapshot
    ↓
normalize
    ↓
match Brand / Model / Generation
    ↓
propose MarketTrim candidate
    ↓
human review
    ↓
attach evidence

```

กฎ:

- ห้าม auto-create canonical model แบบเดา
- ambiguity ต้องเข้า review
- retain ECO UUID
- retain source URL
- ECO recommended price เป็น evidence เท่านั้น
- label เป็น `ECO_STICKER_PRICE`
- ห้ามใช้ ECO เดา launch date
- ห้ามใช้ ECO เดา CBU / CKD
- ห้ามใช้ ECO เดาประเทศผลิต

---

# 7. Registration / DLT Architecture

ใช้ architecture ของ `vehicle-market-master`

canonical resolution:

```text
Brand
→ Model
→ Generation
→ Variant

```

registration resolution จบที่ Variant และไม่ resolve ลง MarketTrim

กรณีที่ DLT label มีรายละเอียดตรงกับ retail trim ให้สร้าง optional mapping แยก:

```text
DLT label
→ DLT Trim Ledger entry
→ evidence-backed MarketTrim link
```

mapping นี้ใช้ระบุความสัมพันธ์และ coverage เท่านั้น registration fact ยังคงอยู่ใน registration ledger และห้ามนับยอดซ้ำบน MarketTrim

registration fact ต้องรักษา actual grain ที่ DLT ให้มา

เช่น:

```text
BRAND
MODEL
VARIANT

```

ถ้า DLT ไม่แยก ห้าม invent split

ถ้ารถหนึ่ง model มีหลาย powertrain แต่ source เป็น model-grain:

- ถ้า source หรือ deterministic rule ระบุ powertrain ได้ ให้รักษาค่านั้น
- ใช้ `MIXED` เมื่อ evidence แสดงว่า row เดียวรวมหลาย powertrain
- ใช้ `UNKNOWN` หรือ unresolved เมื่อ source ไม่พอให้ตัดสินว่าเป็น powertrain ใด
- explicit allocation profile เป็น derived analytical layer พร้อม method/version และห้ามแก้ canonical registration fact

unresolved rows ต้องเข้า review queue

ห้าม drop

ห้ามเดาเงียบๆ

---

# 8. DLT Trim Ledger

คง architecture trim ledger แยกจาก MarketTrim

นี่เป็น “second set of books” สำหรับ DLT labels ที่มี trim/battery/range detail เช่นบางแบรนด์จีนหรือ Tesla

หลัก:

```text
Master registration ledger
= folded model-level comparable dataset

DLT Trim Ledger
= additional detail layer

```

ห้ามทำให้ trim ledger เปลี่ยน master totals

ต้องมี reconciliation:

```text
sum(DLT Trim Ledger) == master model total

```

reconciliation ต้องตรวจใน coverage เดียวกันตาม source, period, registration class, province/region และ model พร้อม unknown bucket ไม่ใช่ตรวจเพียง grand total

เพื่อให้:

- Toyota vs BYD ยังเทียบ model-level อย่างปลอดภัย
- Chinese EV trim ranking เป็น feature เพิ่ม
- ไม่ทำลาย existing analytics

ใน UI/API ควรเรียกสิ่งนี้ว่า:

`DLT Trim Ledger`

หรือชื่อที่แยกชัดจาก retail `MarketTrim`

ห้ามใช้คำว่า `trim` แบบกำกวมใน internal contracts

---

# 9. Production / Plant / Local Content / MiT

เก็บ domain นี้ไว้ใน backend/data model

แต่ตัดออกจาก public information architecture แบบ section แยก

คงโครง:

```text
Vehicle / Generation
       ↓
ProductionProgram
       ↓
Plant

ProductionProgram
  ├── Local Content
  └── MiT

```

ProductionProgram รองรับ:

- plant
- production type
- platform
- SOP
- EOP
- annual production estimate
- export volume
- export markets
- source
- uncertainty

Local Content และ MiT ต้องผูกกับ ProductionProgram

ไม่ผูกตรงกับ consumer Model/MarketTrim

---

# 10. REMOVE Public "Thailand Production" Section

ตัด public section เหล่านี้ออก:

```text
/production
/plants
/plants/[slug]
/production/[slug]

```

รวมถึง:

- navigation entry “ผลิตในไทย”
- navigation entry “โรงงาน”
- plant gallery/index
- production gallery/index
- plant as first-class public destination

ไม่จำเป็นต้อง delete plant tables

แค่ไม่ expose เป็น product section

---

# 11. Vehicle Page Becomes the Main Dossier

ทุกอย่างที่เกี่ยวกับรถไปกองอยู่หน้า “รถ”

target model page:

```text
Vehicle
├── Brand / Model / Generation
├── MarketTrim
├── Price
├── Specs
├── Powertrain
├── Range
├── Wheel / Tyre
├── Dimensions
├── Country of production
├── CBU / CKD / SKD
├── Registration teaser / entitlement-aware market info
├── News
│
└── Thailand Production block
    └── แสดงเฉพาะเมื่อมีข้อมูล

```

ถ้ารถผลิตไทย ให้เพิ่ม block:

```text
Thailand Production
├── โรงงาน
├── Platform
├── SOP / EOP
├── Local Content
├── MiT
├── Production volume
└── Export information

```

ถ้าเป็น CBU ไม่มี production ไทย:

ไม่ต้อง render section นี้

ตัวอย่าง:

```text
Porsche 911
ประเทศผลิต: Germany
CBU
[ไม่มี Thailand Production block]

```

```text
Toyota Camry
ประเทศผลิต: Thailand
CKD
โรงงาน: Gateway
SOP: ...
Local Content: ...
MiT: ...

```

---

# 12. Public Information Architecture

ลด navigation ให้เหลือ product จริง

target:

```text
รถ
ตลาด / Analytics
TDR Report
ข่าว

```

ไม่ต้องมี:

```text
ผลิตในไทย
โรงงาน
บริษัท

```

ใน main navigation

`companies` สามารถเก็บใน backend ถ้าต้องใช้กับ supplier/news/research แต่ไม่ต้องเป็น main product section เว้นแต่มี use case ชัดเจนภายหลัง

---

# 13. TDR Model Editor Must Stop Being a Second Vehicle Master

ปัจจุบัน TDR admin สามารถแก้:

- model
- powertrain
- trim
- price
- wheel
- tyre
- range
- specs

ซึ่งซ้ำกับ Vehicle Master

หลัง consolidation:

ข้อมูลต่อไปนี้ต้องมาจาก canonical Automotive Data Engine:

```text
Brand
Model
Generation
MarketTrim
Powertrain
Specs
Tyre
Wheel
Range
Price

```

TDR-specific admin แก้ได้เฉพาะ:

```text
featured
image
consumer/editorial description
news
events
report content
production facts
plants
local content
MiT
other TDR-specific metadata

```

ถ้าต้องการแก้ vehicle fact ให้เปิด canonical Vehicle Workbench เดียว

ไม่ให้มี TDR-specific duplicate editor

ทั้ง importer และ Vehicle Workbench ต้องเรียก canonical write service เดียวกัน เพื่อให้ validation, revision, provenance และ publish behavior เหมือนกัน

---

# 14. One Admin / Data Workbench

เป้าหมายสุดท้ายให้มี backend workspace เดียว

แนะนำ sections:

```text
Vehicles
├── Brand
├── Model
├── Generation
├── MarketTrim
├── Specs
├── Price Ledger
└── Source Evidence

Market
├── DLT Import
├── Matching
├── Unresolved Review
├── Alias Overrides
├── Registration Analytics
└── DLT Trim Ledger

Industry
├── Plants
├── Production Programs
├── Local Content
└── MiT

Editorial
├── Images
├── Featured
├── Descriptions
├── News
└── Reports

```

ผู้ดูแลข้อมูลไม่ควรต้องรู้ว่าข้อมูลอยู่ repo ไหน

การ save สำเร็จหมายถึง canonical revision ถูกบันทึกและเข้า publish queue แล้ว UI ต้องแสดง revision/publish status เพื่อไม่ให้ผู้ดูแลต้องเดาว่าข้อมูลขึ้นเว็บหรือยัง

---

# 15. Supabase Role

ไม่จำเป็นต้องย้าย raw warehouse ทุกอย่างเข้า Supabase ทันที

ให้แยก storage role ได้

ตัวอย่าง:

```text
Automotive Warehouse
- raw DLT
- ingestion state
- source snapshots
- matching
- review
- audit/provenance
- price evidence

Supabase Serving DB
- data needed by web
- public catalog projections
- member analytics projections
- editorial
- production facts

```

แต่ทั้งหมดอยู่ใน product/repo เดียวได้

หลักคือ:

**one canonical logical model, multiple storage roles**

ไม่ใช่:

**two independent masters**

---

# 16. Canonical IDs

ต้องใช้ stable cross-layer IDs

ห้าม regenerate canonical IDs ที่ Vehicle Master ใช้อยู่เพียงเพื่อให้ตรงกับ TDR UUID

ให้ inventory object ของทั้งสองระบบก่อน cutover แล้วสร้าง verified crosswalk:

```text
TDR object ID
→ canonical object ID
→ mapping status / method / reviewer
```

รักษา TDR UUID เดิมสำหรับ foreign keys, redirects หรือ legacy references ตามความจำเป็น ส่วนรายการที่ยัง map ไม่ได้ต้องอยู่ใน review queue ที่นับและตรวจย้อนหลังได้

ห้าม match vehicle objects ด้วยชื่อทุกครั้ง

อย่างน้อย:

```text
brand_id
model_id
generation_id
market_trim_id
variant_id

```

serving tables ใน Supabase ต้องเก็บ canonical external ID หรือใช้ ID เดียวกันถ้าทำได้

sync/publish ต้อง idempotent

running same import twice ต้องไม่สร้าง duplicate

ห้ามลบ object หรือ relationship ของ TDR ระหว่าง migration เพียงเพราะ Vehicle Master ยังไม่มี field ตรงกัน ให้ย้ายเข้า domain ที่ถูกต้องหรือเก็บเป็น unresolved migration record พร้อม provenance

---

# 17. Serving / Publish Layer

ใช้ canonical write pipeline เดียวสำหรับทั้งการนำเข้าข้อมูล การ review และการแก้ไขด้วยมือ

```text
Importer / Canonical Vehicle Workbench
        ↓
Validation + review rules
        ↓
Canonical transaction + revision
        ↓
Publish queue / outbox
        ↓
Build staged projections
        ↓
Reconcile + atomic activate
        ↓
Supabase API / TDR pages / cache revalidation
```

หลัก write once:

- ทุกการ create/update/withdraw เริ่มจาก canonical engine
- TDR pages, API routes และ admin ห้ามแก้ serving projections โดยตรง
- การแก้ fact เดิมสร้าง revision พร้อม actor, timestamp, reason และ provenance
- publisher คำนวณทุก projection ที่ได้รับผลกระทบ แล้วเปิดใช้เป็น release เดียว
- หลัง activate ให้ invalidate/revalidate cache ของทุกจุดที่ใช้ object นั้น
- งานล้มระหว่าง publish ต้องคง last-known-good release ไว้

ถ้า canonical engine กับ Supabase ใช้คนละ storage ให้มี explicit publish commands:

```text
Canonical Vehicle Master
      ↓
publish_catalog
      ↓
Supabase

Registration Warehouse
      ↓
publish_market
      ↓
Supabase

Price Ledger
      ↓
publish_current_prices
      ↓
Supabase

```

publish ต้อง:

- deterministic
- idempotent
- keyed by stable IDs
- update existing records
- not duplicate
- preserve editorial-only fields where appropriate
- handle withdraw/close/supersede ด้วย tombstone หรือสถานะที่กำหนดชัด

ทุก release ต้องมี:

```text
release_id
schema_version
canonical_revision
source_snapshot/hash
scope and grain
record counts
coverage/freshness
created_at
activated_at
```

publisher ต้อง stage → validate → reconcile → activate แบบ atomic และรองรับ rollback ไป last-known-good release

หน้าเว็บทั้งหมดต้องอ่านจาก canonical projections หรือ API contract เดียวกัน เพื่อให้การกรอกหรือแก้ข้อมูลครั้งเดียวปรากฏในทุกจุดของ newly merged web โดยไม่ต้องแก้ซ้ำรายหน้า

---

# 18. Paywall / Entitlement Fix

นี่เป็น deployment gate ก่อนเปิด `publish_market` หรือยอดจดทะเบียนชุดใหม่ให้เว็บใช้

หน้า vehicle dossier และข้อมูลระดับรถเปิดฟรี ขอบเขต subscription เริ่มที่เครื่องมือวิเคราะห์และข้อมูลยอดจดทะเบียน/ยอดขายที่นำเสนอแบบ visualized

ก่อน cutover ต้องตรวจสิทธิ์ใน Supabase environment ที่ใช้งานจริง ไม่ตัดสินจาก migration file เพียงอย่างเดียว

target policy:

## Public

```text
vehicle catalog
current specs
current trims
current prices
campaign prices and conditions
vehicle-level price history
country of production
CBU / CKD / SKD
Thailand production facts
selected news
selected market teaser statistics if intentionally exposed

```

## Paid

```text
registration/sales visualizations
full registration time series behind analytical tools
market share
segment comparison
trim ranking
historical registration and market analytics
interactive charts
exports
downloadable datasets
advanced filters

```

ดังนั้น:

- raw/member registration fact tables ห้าม anon SELECT
- paid market facts ต้องมีทั้ง object grants และ RLS ตาม entitlement
- frontend blur ไม่ถือเป็น security
- ห้ามส่ง paid values ไป client แล้วแค่ CSS blur
- public catalog/spec/price endpoints ต้องใช้ได้โดยไม่ต้อง login
- paid chart/API requests ต้องตรวจ entitlement ฝั่ง server/database

ถ้าต้องการ teaser ให้ทำ public projection/view โดยเฉพาะ

เช่น:

```text
public_model_market_teaser

```

แทนการเปิด `registrations`

---

# 19. Registration Serving Model

TDR Supabase `registrations` สามารถคงเป็น serving table ได้

แต่ canonical resolution เกิดใน automotive engine ก่อน

flow:

```text
DLT Raw
 ↓
Vehicle Master matching
 ↓
review / resolve
 ↓
canonical registration facts
 ↓
TDR serving projection

```

TDR ไม่ควร resolve DLT labels independently

---

# 20. Trim-Level Market Analytics

หน้า Report โฆษณา trim-level registration

แต่ปัจจุบัน TDR model registrations ยังเป็น model-level

ให้ implement ภายหลังโดย consume `DLT Trim Ledger`

ต้องไม่เอา retail MarketTrim มาปนโดยไม่มี mapping evidence

target:

```text
Market Model Ranking
→ canonical registration fact

Chinese EV Trim Ranking
→ DLT Trim Ledger

Retail Trim Catalog
→ MarketTrim

```

สามอันนี้ต้องแยก semantic ชัด

---

# 21. Taxonomy Ownership

taxonomy ทั้งหมดต้องมี canonical source แห่งเดียว

เช่น:

```text
body_type
segment
powertrain
drivetrain
production_type
price_type
market status

```

TDR frontend ห้ามมี duplicate taxonomy ที่ drift เอง

สามารถมี display labels mapping ได้ แต่ stored values ต้องใช้ canonical taxonomy

ตัวอย่าง body type canonical:

```text
Sedan
Hatchback
Coupe
Crossover
PPV
Offroad ladder frame
MPV
Pickup truck
Van

```

presentation labels เปลี่ยนได้

canonical values ไม่ควรกระจาย hardcode หลายไฟล์

---

# 22. Data Completeness Policy

งาน migration นี้ห้าม invent data

ถ้า record ขาด:

- trim
- spec
- range
- wheel
- tyre
- factory
- price
- local content
- MiT

ให้ render missing/unknown อย่างตรงไปตรงมา

ไม่ถือเป็น failure

เป้าหมาย Phase นี้คือ architecture consistency

ไม่ใช่ 100% catalog completeness

---

# 23. Migration Sequence

ให้ทำเป็น phases

## Phase A — Freeze Contracts and Baseline

- document canonical ownership
- declare TDR main repo
- declare Vehicle Master canonical vehicle engine
- inventory และ diff vehicle/price/spec/industry/editorial data ทั้งสองระบบ
- map duplicated TDR fields/tables พร้อม owner และ migration action
- สร้าง verified ID crosswalk และ unresolved migration queue
- map public routes to remove
- define stable ID policy
- define write/publish/release/rollback contracts
- เก็บ baseline ของ registration totals, unresolved counts, trim-ledger coverage และ public routes

ห้าม rewrite UI ใหญ่ใน phase นี้

---

## Phase B — Bring Vehicle Engine Into TDR

ย้าย Python engine เป็น package/module ภายใน TDR โดยรักษา runtime boundary และ behavior เดิม ไม่ rewrite เป็น TypeScript ระหว่างย้าย

อย่างน้อย:

```text
catalog/entities
DLT ingestion
registration DB
matching/review
ECO ingestion
pricing
comparable specs
trim ledger
fitment
provenance

```

ย้าย tests มาด้วย

รักษา commands, fixtures, scheduled-job entrypoints และ behavior เดิม

---

## Phase C — Establish Canonical Write Pipeline

ทำให้:

```text
Brand
Model
Generation
Variant
MarketTrim
PriceLedger
Specs

```

เป็น single truth

สร้าง canonical create/update/withdraw workflow, validation, revision history, outbox และ shadow publisher ก่อน

ให้ TDR editor เดิมเรียก canonical write contract ได้ชั่วคราวจน Vehicle Workbench พร้อม

เมื่อ canonical write path ผ่าน end-to-end test แล้ว จึงปิดทุก TDR UI/API/action ที่เขียน duplicate vehicle facts

---

## Phase D — Establish Entitlement Boundary

ทำก่อน activate registration projections:

- public catalog/spec/trim/price/campaign/production queries
- member-only registration and market analytics queries
- explicit public teaser projections
- object grants + RLS + server-side entitlement checks
- verify anon/free/paid/expired-member access through page source and direct API
- do not rely on CSS blur

---

## Phase E — Build Serving Projection to Supabase

สร้าง staged, versioned publisher/sync สำหรับ:

```text
brands
models
generations if required
market trims
current specs
current prices
registration summaries

```

ทุก row ต้องผูก stable canonical ID

ทุก publisher ต้องผ่าน record-count, referential-integrity และ registration reconciliation ก่อน atomic activate พร้อม cache revalidation และ rollback

`publish_catalog` และ `publish_current_prices` เปิดใช้ได้เมื่อ public contract ผ่าน ส่วน `publish_market` เปิดใช้หลัง Phase D ผ่านเท่านั้น

---

## Phase F — Simplify Public TDR

ลบ public:

```text
/production
/plants
/plants/[slug]
/production/[slug]

```

remove navigation

เอา production facts ไป render ใน model page

แก้ search ไม่ให้ treat Plant เป็น main public content destination

---

## Phase G — Consolidate Vehicle Dossier

ให้ model page consume canonical projection

sections:

```text
consumer
technical
current and historical prices
campaign conditions
market teaser
Thailand production if applicable
news/editorial

```

อย่า duplicate logic จาก old production pages

---

## Phase H — Consolidate Admin

ลบ/disable duplicate TDR vehicle editing paths

replace ด้วย canonical Vehicle Workbench

เก็บ TDR editorial + industry editing

ทดสอบว่า create/update/withdraw vehicle fact หนึ่งครั้งแล้วทุก projection, API และหน้าที่เกี่ยวข้องเปลี่ยนตาม release เดียวกัน

---

## Phase I — Trim Analytics Integration

connect DLT Trim Ledger to paid TDR analytics

ต้องมี reconciliation against model totals

---

## Phase J — Archive Old Repo

เมื่อ:

- imports pass
- web works
- publisher works
- admin works
- registration reconciliation passes
- scheduled ingestion/harvester jobs, secrets และ operational ownership ถูกย้ายครบ
- rollback และ last-known-good release ผ่านการทดสอบ

ให้ mark `vehicle-market-master` archived/superseded

---

# 24. Product Roadmap Alignment

การรวม repository และ migration A–J ไม่ถือว่า Product Phase 1–7 เสร็จโดยอัตโนมัติ

| Product phase | สิ่งที่ migration ต้องรักษาหรือเตรียม | สิ่งที่ต้องส่งมอบจึงถือว่า phase นั้นเสร็จ |
|---|---|---|
| Phase 1 — Vehicle Master 2.0 | Canonical identity, Generation, MarketTrim, exact powertrain, specs, fitment refs, provenance และ Price Ledger | Canonical write/read workflow ใช้งานได้ และ JAECOO 5 เป็น reference implementation ที่ผ่าน validation |
| Phase 2 — ECO ingestion | Snapshot, normalization, matching, candidate review, retained ECO UUID/source และ idempotent rerun | ECO records ถูกประมวลผลครบตาม snapshot; ambiguity อยู่ใน review queue; ไม่มี canonical object ที่สร้างจากการเดา |
| Phase 3 — Price Harvester | Source adapters, evidence queue, trim-specific price types, campaign options/conditions และ revision history | Current/historical ledger ใช้งานได้; วัด announcement→detection→publication latency ได้; เป้าหมาย publish ภายใน 24 ชั่วโมง; ไม่บังคับให้มีราคาทุกรุ่น |
| Phase 4 — Comparable Specs | C-Crossover pilot 20 รุ่น, representative trim decision, fact status และ battle-card contract | Pilot มี output ที่เทียบ cohort/powertrain ถูกต้อง พร้อม coverage/provenance; missing facts แสดงเป็น missing |
| Phase 5 — Change Engine | Release identity, canonical revision และ change-record contract | ตรวจ trim/price/spec changes ได้ และแยก market change ออกจาก data correction/taxonomy migration ก่อนสร้าง What's Changed feed |
| Phase 6 — Fitment Expansion | FitmentApplication schema เชื่อม Generation/MarketTrim กับ tyre/wheel/12V battery, axle/package/date range/status/source | เพิ่มและแก้ fitment ครั้งเดียวแล้ว vehicle dossier และ downstream parts projection อัปเดตตาม release; ไม่กระจาย generation fact ไปทุก trim โดยไม่มี evidence |
| Phase 7 — Productization | Shared APIs/projections และ skeleton ของ TDR Market, Sales/Manager Command และ Parts Demand | แต่ละ panel ใช้ canonical data จริงเท่าที่มี แสดง coverage ชัด และผ่าน entitlement ของตน; Parts Demand แยก observed registrations จาก modeled demand assumptions |

Phase 5 ใช้ change record ขั้นต่ำได้โดยไม่ต้องเพิ่ม message broker หรือ service ใหม่:

```text
change_id
object_type / object_id
change_type
before_revision / after_revision
effective_at
detected_at
classification = MARKET_CHANGE | DATA_CORRECTION | TAXONOMY_MIGRATION
evidence_refs
```

Phase 6 skeleton ใช้ relationship ที่ขยายต่อได้:

```text
FitmentApplication
→ generation_id / market_trim_id
→ component_type
→ axle_or_position
→ equipment_package
→ valid_from / valid_to
→ verification_status
→ source_refs
```

Phase 7 skeleton ต้องมี empty/partial states ที่บอก coverage ตามจริง และห้ามเปลี่ยนข้อมูลที่ขาดให้เป็นศูนย์

---

# 25. Things NOT To Do

ห้าม:

1. เอา TDR trim schema มาเป็น canonical แทน Vehicle Master
2. รวม Variant กับ MarketTrim
3. allocate registration ลง retail trim โดยไม่มี evidence
4. overwrite PriceLedger ด้วย `price_baht`
5. delete Plant/ProductionProgram domain เพียงเพราะลบหน้า public
6. turn Supabase into raw ingestion warehouse แบบรีบๆ
7. match cross-system records ด้วยชื่อเพียงอย่างเดียว
8. invent missing specs
9. expose paid registration rows to anon แล้วหวังพึ่ง CSS blur
10. redesign working registration engine ระหว่าง migration โดยไม่จำเป็น
11. rename taxonomy casually จน breaking existing data
12. remove provenance/source evidence
13. silently discard unresolved DLT rows
14. เขียน serving tables โดยตรงจน bypass canonical pipeline
15. นับ registration บน MarketTrim หรือ join retail trim volume โดยไม่มี evidence-backed coverage
16. ถือว่าการ merge repository เท่ากับ Phase 1–7 เสร็จ
17. เปิด registration projection ก่อน entitlement gate ผ่าน

---

# 26. Tests / Acceptance Criteria

Architecture consolidation ถือว่าสำเร็จเมื่อ:

## Vehicle identity

- มี Brand / Model / Generation / Variant / MarketTrim canonical แค่ชุดเดียว
- TDR frontend ไม่สร้าง retail trim master ของตัวเอง
- stable IDs ใช้ข้าม layers

## Price

- PriceLedger เป็น canonical
- หน้าเว็บ derive current price ได้
- historical price ยังอยู่
- campaign price ไม่ overwrite MSRP

## Registration

- master model totals เท่าเดิมก่อนและหลัง migration
- unresolved rows ไม่หาย
- DLT Trim Ledger reconcile กับ master totals ภายใน source/period/class/geography/coverage เดียวกัน
- unknown bucket ไม่หายระหว่าง fold หรือ publish
- MarketTrim ไม่เก็บ registration volume
- evidence-backed link ไป MarketTrim ไม่สร้าง registration fact ชุดที่สอง

## Web

- `/models` ทำงาน
- `/models/[slug]` ทำงาน
- หน้า vehicle dossier แสดง catalog, specs, current/historical prices และ campaign conditions แบบ public
- production information แสดงใน model page เฉพาะเมื่อมี
- `/production` ไม่เป็น product page แล้ว
- `/plants` ไม่เป็น product page แล้ว

## Admin

- มี editing workflow เดียวสำหรับ vehicle facts
- editorial fields ยังแก้ได้
- production/local-content/MiT ยังแก้ได้
- ไม่มี duplicate trim/spec/price editor
- create/update/withdraw หนึ่งครั้งผ่าน canonical workflow แล้วทุก projection/API/page เปลี่ยนตาม release เดียวกัน
- ไม่มี write route ที่แก้ serving projection โดยตรง

## Paywall

- anon user query raw paid registrations ไม่ได้
- paid member/server path ใช้ analytical tools และ registration visualizations ได้
- anon user เปิด vehicle catalog/spec/price/campaign endpoints ได้
- public page ไม่ leak hidden values
- teaser data เป็น intentionally public projection
- access tests ครอบคลุม anon, free member, paid member และ expired member

## Build/Test

- TypeScript compile clean
- existing Vehicle Master tests preserved
- existing TDR checks preserved
- reconciliation tests pass
- migration/publish idempotency tests pass
- staged publish failure ไม่เปลี่ยน active release
- rollback คืน last-known-good release ได้
- cache revalidation ทำให้ทุก consumer เห็น canonical revision เดียวกัน

---

# 27. Final Product Philosophy

TDR ไม่ควรเป็น collection ของหลายเว็บหรือหลายฐานที่เล่าเรื่องเดียวกัน

มันควรเป็น product เดียว:

```text
รถหนึ่งคัน
→ identity เดียว
→ specs เดียว
→ price history เดียว
→ production facts เดียว
→ registration ledger และ DLT Trim Ledger ที่แยก grain ชัด
→ จากนั้น render คนละมุมตาม user

```

Consumer เห็นรถ

Sales/Manager เห็นตลาด

TDR Analyst เห็น research layer

Admin เห็น evidence / ingestion / review

แต่ทั้งหมดอ้าง object ชุดเดียวกัน

---

# 28. Priority

ถ้าต้องเลือกทำเฉพาะสิ่งสำคัญก่อน:

1. Freeze ownership, baseline, stable-ID crosswalk และ release contracts
2. Absorb Vehicle Master engine/tests/jobs into TDR repo โดยรักษา behavior
3. Build canonical write-once pipeline, revision history และ shadow publisher
4. Lock paid registration data behind entitlement ก่อน activate `publish_market`
5. Activate versioned public catalog/spec/price projections และ paid market projections
6. Stop duplicate TDR trim/spec/price editing หลัง canonical Vehicle Workbench ใช้งานได้
7. Consolidate vehicle dossier และ remove `/production` / `/plants` public destinations
8. Build Phase 5–7 contracts/skeletons บน canonical projections
9. Integrate DLT Trim Ledger analytics พร้อม scoped reconciliation
10. Archive old repo หลัง jobs, secrets, rollback และ operational handover ผ่าน

อย่าเสียเวลาเติมข้อมูลให้ครบก่อน architecture consolidation เสร็จ
