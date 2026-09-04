# vehreg — คู่มือใช้งาน

ระบบดูดยอดจดทะเบียนรถใหม่ของกรมการขนส่งทางบก แล้วแจงเป็น dynamic big data
ที่ cross ได้ทุกแกน: ยี่ห้อ × รุ่น × รุ่นย่อย × segment × body type ×
market position × powertrain × ประเทศผลิต × CBU/SKD/CKD × brand segment

**ทำงานเป็นรายปี** catalog แต่ละปีแยกโฟลเดอร์กันสนิท ไม่มีการอ่านข้ามปี
ตอนนี้มี catalog + ข้อมูลจริง **2022–2026** (พ.ศ. 2565–2569)

**ข้อจำกัดที่ต้องรู้ก่อนใช้:** DLT ไม่ประกาศยอดแยกรุ่นย่อย ละเอียดสุดคือระดับ
"แบบรถ" ระบบจึงไม่แยก trim และไม่ยอมให้ฉลากที่บอกแค่ชื่อรุ่นตกลงไประดับ trim
(ดูหัวข้อ *grain* ท้ายไฟล์)

ใช้ Python standard library ล้วน ไม่ต้อง pip install ไม่ต้องมี server
ฐานข้อมูลเป็นไฟล์ SQLite ไฟล์เดียว

## เริ่มใช้ใน 4 คำสั่ง

```bash
python -m vehreg facets                       # ดู vocabulary ทั้งหมด
python -m vehreg init                         # ตรวจ catalog + สร้าง warehouse
python -m vehreg dlt load --fetch-year 2026   # โหลดจาก DLT + ingest
python -m vehreg cube --by segment,powertrain
```

ข้อมูลดิบที่โหลดมาแล้วอยู่ใน `data/raw/dlt_<YYYY-MM>.csv` คู่กับ `.meta.json`
(resource id, URL, เวลาโหลด, sha256) สร้างฐานใหม่ทั้งหมดจากไฟล์พวกนี้ได้โดยไม่ต้องต่อเน็ต

## ขั้นตอนจริง

### 1. หาไฟล์ข้อมูลมาก่อน

กรมการขนส่งทางบกเผยแพร่สถิติจดทะเบียนรายเดือนที่หน้า "สถิติการขนส่ง"
และบางชุดอยู่บน data.go.th โหลดไฟล์เอง (Excel → Save As CSV UTF-8)
แล้วเก็บไว้ใน `data/raw/`

**สำคัญ:** กระบะกระจายอยู่สองไฟล์
* **รย.1** — double cab (4 ประตู) รวมอยู่กับรถยนต์นั่ง
* **รย.3** — single cab กับ smart/space cab

ต้องดึงมาทั้งคู่ถึงจะเห็นกระบะครบ และตอน ingest ต้องบอกประเภทให้ถูก
เพราะระบบใช้ประเภทนี้เป็นตัวตัดสินว่า `REVO` ในไฟล์นั้นคือแค็บไหน

### 2. ingest

รองรับสองทรง:

```bash
# ทรงยาว: หนึ่งแถวต่อหนึ่งเดือน
python -m vehreg ingest data/raw/ry1_2026.csv --registration-type RY1

# ทรงกว้าง: เดือนเป็นคอลัมน์ (ทรงที่ DLT ใช้บ่อย)
python -m vehreg ingest data/raw/ry3_2026.csv --wide --registration-type RY3
```

หัวคอลัมน์ไทย/อังกฤษเดาให้อัตโนมัติ (`เดือน`, `ยี่ห้อ`, `แบบรถ`, `จำนวน`, …)
ถ้าเดาผิดสั่งตรง ๆ ได้: `--col-period เดือน --col-brand ยี่ห้อ --col-units จำนวน`

ทุกแถวจบที่อย่างใดอย่างหนึ่งเสมอ — เป็น fact ที่จับคู่ได้ พร้อมบันทึกว่าจับคู่ด้วยวิธีไหน
คะแนนเท่าไหร่ หรือเข้าคิว review พร้อมเหตุผล **ไม่มีการเดาให้ไปลงรุ่นที่ใกล้ที่สุด**
ยอดรวมจึงกระทบยอดกับไฟล์ต้นทางได้เสมอ

ingest ไฟล์เดิมซ้ำไม่ทำให้ตัวเลขคูณสอง (มี UNIQUE key ต่อ source)
แถวที่เป็นปีอื่นซึ่งยังไม่มี catalog จะเข้าคิว `no-catalog-for-year` ไม่ถูกจัดมั่ว

### 3. เคลียร์คิว review

```bash
python -m vehreg review                       # ดูว่าอะไรจับคู่ไม่ได้ กี่คัน
python -m vehreg review --map "model:DEEPAL S05=changan.deepal_s07"

# กระบะที่ฉลากไม่บอกแค็บ: สอนแยกตามประเภทจดทะเบียนได้
python -m vehreg review --map "model:TOYOTA REVO=toyota.hilux_revo_smart_cab" --reg RY3
```

คิว review จะบอกตัวเลือกมาให้เลยเวลามันกำกวม เช่น

```
Toyota Hilux Revo   model-ambiguous: toyota.hilux_revo_single_cab | toyota.hilux_revo_smart_cab
```

สอนครั้งเดียว ครั้งต่อไปจับคู่เอง (เก็บในตาราง `alias_override`)
ระหว่างที่ยังไม่สอน ยอดไม่หาย — มันถูกนับไว้ที่ระดับยี่ห้อ (grain = BRAND)
ถ้ามันคือรถที่ยังไม่มีใน catalog ให้ไปเพิ่มใน catalog แทน (ข้อ 5)

### 4. ถามข้อมูล

```bash
# ทุก segment × powertrain (นับเฉพาะ CORE โดยดีฟอลต์)
python -m vehreg cube --by segment,powertrain

# รวมกระบะทุกแค็บกลับเป็น nameplate เดียว
python -m vehreg cube --by nameplate --filter body_type=PICKUP

# อยากเห็นของที่ถูกตัดออกด้วย
python -m vehreg cube --by brand --scope all
python -m vehreg cube --by model --scope NICHE

# เฉพาะกระบะ แจงตามแค็บ × ประเภทจดทะเบียน × ช่วงราคา
python -m vehreg cube --by cab_type,registration_type,market_position \
    --filter body_type=PICKUP --allocate

# BEV จีน CBU เทียบ BEV ประกอบไทย
python -m vehreg cube --by brand,import_type,origin_country --filter powertrain=BEV

# รายไตรมาส / รายเดือน
python -m vehreg cube --by powertrain_group,quarter
python -m vehreg cube --by brand,period --from 2026-01 --to 2026-06

# เทียบครึ่งปี
python -m vehreg growth --by brand_segment --base 2026-01 --compare 2026-06

# ส่งออกไป Excel / Looker
python -m vehreg cube --by brand,model,powertrain,market_position --csv out.csv
```

กรองด้วย `--filter <facet>=<ค่า>[,<ค่า>]` ได้ทุก facet และ group ด้วย `--by`
ได้ทุก facet เช่นกัน รวม `period`, `quarter`, `year`, `province`, `grain`

**ทุกคำสั่ง cube นับเฉพาะ `market_scope = CORE`** คือรถที่ขายโดยตัวแทนจำหน่าย
ทางการและมียอดมีนัยสำคัญ ตัดเกรย์ ตัดซูเปอร์คาร์ ตัดของยอดหยิบมือออกหมด
และมันจะพิมพ์บอกทุกครั้งว่าตัดอะไรออกไปกี่คัน:

```
total: 1,063,684 units
excluded by scope: MIXED 49,471, NICHE 144 (pass --scope all to include them)
```

### 5. เติม catalog (ตรงนี้คือของที่อยู่ในหัวเจ้าของ)

```bash
python -m vehreg catalog export mycars.csv     # เอาของที่มีอยู่ออกมาแก้
# หรือเริ่มจากศูนย์:
python -m vehreg catalog template mycars.csv   # ไฟล์เปล่าพร้อมตัวอย่าง 2 แถว

# กรอกใน Excel: หนึ่งแถว = หนึ่งรุ่นย่อย
python -m vehreg catalog import mycars.csv --dry-run
python -m vehreg catalog import mycars.csv
python -m vehreg init                          # rebuild dimension
```

กติกาตอนกรอกที่ต้องรู้:

* **หนึ่งชื่อรุ่น = หนึ่ง body** ถ้ากรอกชื่อเดิมแต่ body ใหม่ ระบบจะฟ้องและ
  ไม่เขียนอะไรเลย ให้ตั้งชื่อแยก เช่น `Mazda2 Sedan` กับ `Mazda2 Hatchback`
* **บอดี้หลักใช้ชื่อเปล่า** `Mazda2` (ซีดาน) กับ `Mazda2 Hatchback`
  เหมือน `City` / `City Hatchback` ฉลากเปล่าจะตกลงบอดี้หลักเอง
* **กระบะแยกสองทาง** `<รุ่น> Double Cab` (`cab_type=DOUBLE_CAB` → รย.1) กับ
  `<รุ่น> Cab` (`cab_type=SINGLE_SMART` → รย.3) ไม่ต้องแยกตอนเดียว/แค็บ
  เพราะ DLT ไม่ได้บอก
* **`nameplate` คือตัวรวมกลับ** ปล่อยว่างได้ถ้าชื่อรุ่นบอกอยู่แล้ว
  (`Mazda2 Sedan` → `Mazda2`) แต่ถ้ารวมข้ามชื่อต้องกรอก — Revo กับ Champ
  ใส่ `Hilux` ทั้งคู่
* **`market_scope`** ปล่อยว่าง = `CORE` ใส่ `NICHE` สำหรับซูเปอร์คาร์/ของยอดหยิบมือ
  `GREY` สำหรับของที่ไม่ใช่ตัวแทนทางการ แล้วมันจะไม่เข้ารายงาน
* **หนึ่งแถว = หนึ่ง spec ไม่ใช่หนึ่ง trim** trim ที่ไม่ต่างกันในแกนที่รายงาน
  ให้ยุบรวม แล้วใส่ช่วงราคาจริงที่ `price_min_thb` / `price_max_thb`
  เอาชื่อ trim เดิมไปใส่ `variant_aliases` ถ้ายุบข้ามช่วงราคา validate จะฟ้อง
* **ปล่อย `registration_type` ว่างไว้** ระบบเติมให้เอง — double cab เป็น รย.1
  ที่เหลือเป็น รย.3
* **`generation` ปล่อยว่างได้** ถ้าไม่แยกโฉม กรอกแล้วเรียงตาม `launched` เอง
* import ซ้ำได้ปลอดภัย แถวที่ชี้รุ่นย่อยเดิมจะอัปเดตทับ ไม่สร้างซ้ำ
* ถ้าแถวไหนทำให้ catalog ผิดกติกา **ไม่เขียนลงดิสก์เลย** และบอกว่าแถวไหนผิด

คำสั่งอื่น:

```bash
python -m vehreg catalog stats                 # นับว่ามีอะไรอยู่เท่าไหร่
python -m vehreg catalog validate              # ตรวจกติกาข้ามแกนทั้งหมด
python -m vehreg catalog audit                 # ราคาไหนยังไม่ได้ยืนยัน
python -m vehreg catalog show revo_double      # ดูว่าแต่ละ facet มาจากชั้นไหน
python -m vehreg catalog years                 # มี catalog ปีไหนบ้าง
python -m vehreg catalog nameplate Hilux       # รวมกลับ: ทุกแค็บ ทุกโฉม เรียงเวลา
python -m vehreg catalog scope NICHE           # รุ่นที่ถูกกันออกจากรายงาน
```

`catalog nameplate` คือมุมมองที่รวมของที่แตกไปกลับมาให้ดูพร้อมรายละเอียด:

```
Toyota Hilux
  Hilux Revo Single Cab  (PICKUP/SINGLE_CAB, RY3)
    AN120    2020-06 -> current
      2.4L ICE                    599,000
  Hilux Revo Double Cab  (PICKUP/DOUBLE_CAB, RY1)
    AN120    2020-06 -> current
      2.4L ICE                    949,000
      2.8L ICE 4WD              1,359,000
  Hilux Champ  (PICKUP/SINGLE_CAB, RY3)
    CHAMP    2023-11 -> current
      2.0L ICE                    459,000

Toyota Camry
  Camry  (SEDAN, RY1)
    XV70     2018-10 -> 2024-11
      2.5L HEV                  1,749,000
    XV80     2024-11 -> current
      2.5L HEV                  1,899,000  (1,899,000-2,099,000)
```

### 6. ขึ้นปีใหม่ / ย้อนหลัง

```bash
python -m vehreg catalog fork --to 2027        # ก๊อป 2026 ไปเป็นจุดตั้งต้น
python -m vehreg --year 2027 catalog import newprices.csv
python -m vehreg --year 2027 init              # เพิ่ม dimension ของ 2027
python -m vehreg --year 2027 dlt load --fetch-year 2027
```

2026 ไม่ขยับเลย ยอดปี 2026 ยังถูกจัดด้วยราคาและ segment ของปี 2026 ตลอดไป

**ปี 2022–2025 ที่โหลดไว้แล้ว fork มาจาก catalog 2026 ทั้งหมด** แปลว่า
ยอดปีเก่าถูกจัดด้วย **ราคาปี 2026** และการจัดหมวดปี 2026 — ยี่ห้อ/รุ่น/บอดี้
ถูกอยู่ ส่วน `market_position` ของปีเก่ายังไม่ถูกจนกว่าจะแก้ราคาในโฟลเดอร์ปีนั้น

```bash
python -m vehreg --year 2023 catalog export prices_2023.csv   # แก้ราคาปีนั้น
python -m vehreg --year 2023 catalog import prices_2023.csv
python -m vehreg --year 2023 init
```

## เรื่อง grain กับ MIXED — อ่านก่อนเชื่อตัวเลข

DLT ประกาศละเอียดสุดแค่ระดับ "แบบรถ" ไม่ใช่รุ่นย่อย ทุก fact จึงบันทึกว่ามันมาถึง
ระดับไหน (`BRAND` / `MODEL` / `VARIANT`)

เวลา cross แกนที่รุ่นหนึ่งมีหลายค่า (เช่น Corolla Cross มีทั้ง ICE และ HEV)
แถวระดับ MODEL จะรายงานเป็น `MIXED` **ไม่ใช่เดาเลือกข้างใดข้างหนึ่ง**

`allocate` มีไว้เผื่ออนาคต ถ้ามีข้อมูลระดับ trim เข้ามา (หรือเจ้าของป้อนสัดส่วนเอง)
มันจะแตก MIXED ออกได้ แต่ตอนนี้ที่ต้นทางเป็น model ล้วน มันจะไม่ได้อะไร:

```bash
python -m vehreg allocate --fallback year      # คำนวณ mix จากแถวระดับรุ่นย่อยที่มี
python -m vehreg cube --by powertrain --allocate
```

MIXED ที่เหลืออยู่คือความจริงของข้อมูล ไม่ใช่บั๊ก — Corolla Cross ขายทั้ง ICE
และ HEV แต่ DLT รายงานรวม จะแยกได้ต้องมีข้อมูลที่ DLT ไม่ได้ให้

`grain = BRAND` คือแถวที่รู้แค่ยี่ห้อ (จับคู่รุ่นไม่ได้หรือกำกวม)
ยอดยังอยู่ครบ แต่ตอบคำถามระดับรุ่นไม่ได้จนกว่าจะเคลียร์คิว review

ยอดรวมไม่เปลี่ยน แต่ผลลัพธ์จะบอกชัดว่ากี่คันเป็น "ค่าประมาณจากการปันส่วน"
ไม่ใช่ตัวเลขที่ต้นทางรายงานมาจริง

`python -m vehreg coverage` บอกว่าตอนนี้ข้อมูลลึกถึงรุ่นย่อยกี่ %
และเหลือค้างคิว review กี่คัน

## โครงไฟล์

```
vehreg/
  taxonomy.py       vocabulary + กติกาข้ามแกน + ช่วงราคา + กติกา รย.
  entities.py       4 ชั้น + ตัว resolve และ provenance
  catalog.py        โหลด/ตรวจ/index catalog รายปี + fork ปีใหม่
  authoring.py      import/export CSV แบบแบน
  normalize.py      fold ข้อความไทย-อังกฤษ + จับคู่ชื่อ + ตรวจความกำกวม
  db.py             SQLite: dimension รายปี + fact + คิว review
  ingest.py         DLT export → fact, ใช้ประเภท รย. ตัดสินความกำกวม
  allocate.py       ปันส่วนยอดระดับรุ่นลงรุ่นย่อย
  cube.py           cross-tab
  cli.py            `python -m vehreg`
  dlt.py            ตัวโหลดจาก DLT open-data API
  trimledger.py     บัญชีที่สอง แยก trim ของค่ายจีน/Tesla
  data/<ปี>/models/ catalog รายยี่ห้อของแต่ละปี (JSON, แก้มือได้ diff ได้)
tools/
  seed_catalog.py       สร้าง catalog 2026 ตั้งต้น (รันครั้งเดียว)
  add_2026_models.py    เติม catalog จาก label จริงที่จับคู่ไม่ได้
tests/test_vehreg.py    76 เทสต์ ออฟไลน์ล้วน
docs/VEHREG_TAXONOMY.md เหตุผลการออกแบบ + ข้อที่เจ้าของต้องตัดสินใจ
```

รันเทสต์: `python -m unittest tests.test_vehreg`

## ที่ยังไม่ได้ทำ (จงใจ)

* ไม่มีตัวโหลดอัตโนมัติจากเว็บ DLT — ไม่เดา endpoint
* ไม่มี dashboard / web UI — ออก CSV แล้วต่อ Excel หรือ Looker เอาเอง
* ไม่มีข้อมูลยอดขายจากค่าย (wholesale) — คนละตัวเลขกับยอดจดทะเบียน
* ไม่มีข้อมูลปีเก่า และไม่เทียบข้ามปีอัตโนมัติ — ถ้าจะเทียบ 2026 กับ 2027
  ต้องมี catalog ทั้งสองปีและ ingest ทั้งสองปีเข้าฐานเดียวกัน
* **ไม่มียอดแยก trim** และจะไม่มีจนกว่าจะมีแหล่งข้อมูลอื่น
* catalog ยังเป็นโครงตั้งต้น ราคายังไม่ยืนยัน และรายการ NICHE เป็นแค่ข้อเสนอ

## แหล่งข้อมูลจริง: DLT open data API

พบแล้วและต่อท่อไว้แล้ว ไม่ต้องโหลดไฟล์เองอีก

```bash
python -m vehreg dlt list                      # ดู resource ทั้งหมดที่ DLT ประกาศ
python -m vehreg dlt fetch --month 2026-01     # โหลดอย่างเดียว
python -m vehreg dlt load  --month 2026-01     # โหลด + ingest
python -m vehreg dlt load  --fetch-year 2025   # ทุกเดือนของปีนั้น
```

* CKAN endpoint: `https://gdcatalog.dlt.go.th/api/3/action/datastore_search`
* dataset: *สถิติจำนวนรถจดทะเบียนครั้งแรก ตามกฎหมายว่าด้วยรถยนต์*
* **รายเดือน ม.ค. 2565 → ก.พ. 2569** (50 เดือน) และรายปี 2565–2568
* ทุกครั้งที่ fetch จะเขียน `data/raw/dlt_<YYYY-MM>.csv` คู่กับ `.meta.json`
  ที่บันทึก resource id, URL, เวลาโหลด, sha256 และยอดที่ข้ามไป

### สิ่งที่ข้อมูลจริงบอก

| เรื่อง | ความจริง |
|---|---|
| ฟิลด์ | `ปี พ.ศ.`, `เดือน`, `ประเภทรถ`, `ยี่ห้อ`, `รุ่น`, `จำนวน` |
| ประเภทรถ | มีทั้งรถแทร็กเตอร์/จักรยานยนต์ปนมา — ตัวโหลดเก็บเฉพาะ รย.1/2/3 แล้วรายงานยอดที่ข้าม |
| กระบะ | `HILUX REVO` โผล่ทั้ง รย.1, รย.2 และ รย.3 — ยืนยันว่าใช้ประเภทจดทะเบียนแยกแค็บถูกแล้ว |
| แยก trim | **แยกบางยี่ห้อ** ค่ายจีนยัด trim มาในช่อง `รุ่น` (`BYD ATTO3 (410KM-PREMIUM)`, `AION UT 420 STANDARD`, `JAECOO 5 EV Long Range Max`) ค่ายญี่ปุ่นไม่แยก |
| ก.พ. 2569 | ยังไม่สมบูรณ์ (6 แถว / 18 คัน) ตอนโหลด — ต้องรอ DLT อัปเดต |

## trim ledger — บัญชีที่สองสำหรับค่ายจีนกับ Tesla

DLT เขียนช่อง `รุ่น` ไม่เหมือนกันในแต่ละค่าย ญี่ปุ่นให้แค่ชื่อรุ่น
(`YARIS ATIV`) ส่วนค่ายจีนกับ Tesla ยัด trim/แบต/ระยะทาง/ขับเคลื่อนมาด้วย
(`BYD ATTO3 (410KM-PREMIUM)`, `AION UT 420 STANDARD`, `JAECOO 5 EV Long Range Max`)

ทิ้งไปก็เสียของ เอาเข้า master ก็พัง — Toyota รวม BYD แยก แล้วเทียบยี่ห้อไม่ได้อีกเลย
ระบบเลยเก็บสองบัญชี:

| | master | trim ledger |
|---|---|---|
| ตาราง | `fact_registration` | `fact_trim` + `dim_trim` |
| ความละเอียด | **รวม trim เป็นรุ่นเดียว ทุกยี่ห้อ** | แยกทุก trim |
| ครอบคลุม | ทุกยี่ห้อ | เฉพาะยี่ห้อที่ตั้ง `trim_detail` |

```bash
python -m vehreg trim list --brand BYD        # ดู trim
python -m vehreg trim check                   # กระทบยอดกับ master
python -m vehreg trim export data/trims_2026.csv
```

```
brand        nameplate       trim              grade      km    units
BYD          Dolphin         435KM-STD         STD       435    5,061
BYD          Atto 3          480KM-EXT         EXT       480    2,691
BYD          Atto 3          410KM-PREMIUM     PREMIUM   410    1,384
```

* ยี่ห้อที่ `trim_detail = true` **master จะหยุดที่ระดับรุ่นเสมอ** ไม่มีทางเผลอแยก
* `trim check` ต้องขึ้น "agree on every model-month" ถ้าไม่ขึ้นแปลว่าสองบัญชีไม่ตรง
* ledger ดึง facet จาก master มาให้ด้วย (segment / body / powertrain / ช่วงราคา)
  จะ cross ต่อก็ได้ เช่น trim ไหนของ BEV ราคา 5 แสน-1 ล้าน ขายดีสุด
* เปิด/ปิดต่อยี่ห้อที่คอลัมน์ `trim_detail` ใน CSV — ตอนนี้เปิดไว้ 20 ยี่ห้อ
  (จีนทั้งหมด + Tesla)

## สถานะข้อมูลตอนนี้

| ปี | เดือน | คัน |
|---|---|---|
| 2022 | 12 | 841,644 |
| 2023 | 12 | 800,235 |
| 2024 | 12 | 599,902 |
| 2025 | 12 | 600,066 |
| 2026 | 1 (ม.ค.) | 90,728 |

รวม **49 เดือน / 2,932,575 คัน** จับคู่ได้ 99.95% (ค้าง review 1,497 คัน)
trim ledger 2,580 แถว / 383,416 คัน กระทบยอดกับ master ตรงทุก model-month

ก.พ. 2569 ที่ DLT ปล่อยมายังไม่สมบูรณ์ (18 คัน) เลยยังไม่โหลด

## แก้ประเภทเอง — `vehreg edit`

การจัดหมวดในนี้เป็น **ความเห็น** ที่มาจากความจำ ไม่ใช่ข้อเท็จจริง ผิดแน่ๆ หลายรุ่น
หน้าที่ของตัวแก้คือเอาหลักฐานมาวางตรงหน้าให้ตัดสินได้: ตอนนี้จัดว่าอะไร
มียอดเท่าไหร่ติดอยู่ และฉลากดิบจาก DLT อันไหนตกมาที่รุ่นนี้

```bash
python -m vehreg edit                 # เปิด http://127.0.0.1:8765
python -m vehreg --year 2023 edit     # แก้ปีอื่น
```

* stdlib ล้วน ไม่ต้อง pip ไม่ต่อเน็ต bind แค่ 127.0.0.1
* ตารางรุ่น **เรียงตามยอดคัน** แก้ 20 แถวแรกได้ผลกระทบเกินครึ่ง
* แก้ได้ inline: `segment`, `body_type`, `cab_type`, `รย.`, `market_scope`
* คลิกตัวเลขยอด → บานหน้าต่างข้าง: spec line (แก้ราคา/powertrain ได้)
  + **ฉลากจริงจาก DLT ที่ตกมาที่รุ่นนี้** พร้อมยอดและจำนวนเดือน
* แท็บ "คิวที่จับคู่ไม่ได้" → พิมพ์ `model_id` แล้วกดสอน (เลือกขอบเขต รย. ได้)
* ปุ่ม **rebuild dimension** ให้ผลการแก้มีผลกับ cube ทันที

### กติกาที่ตัวแก้บังคับ

* **แก้ผิดกติกาข้ามแกน = ไม่เขียนลงดิสก์เลย** และบอกว่าผิดข้อไหน เช่น เปลี่ยน
  double cab เป็น รย.3 จะถูกปฏิเสธทั้งก้อน catalog ไม่มีทางพังจากการแก้
* ทุกการแก้ลง **decision log** `vehreg/data/<ปี>/decisions.jsonl`
  เก็บค่าเดิม ค่าใหม่ เหตุผล เวลา — diff ใน Git ได้ ย้อนได้ รู้ว่าใครตัดสิน
* แก้แยกปีเสมอ ปีอื่นไม่ขยับ

### ถ้าจะแก้ทีละหลายร้อยแถวใน Excel

```bash
python -m vehreg catalog export --with-volume mycars.csv   # มีคอลัมน์ units เรียงให้แล้ว
python -m vehreg catalog import mycars.csv
python -m vehreg init
```
