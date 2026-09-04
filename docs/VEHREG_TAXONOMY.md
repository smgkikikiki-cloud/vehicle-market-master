# โครงสร้าง category ของ vehreg

เอกสารนี้อธิบายว่า "ทุกปัจจัย" ที่เจ้าของระบุ ถูกเก็บไว้ที่ชั้นไหน และทำไม
ชื่อ facet ทุกตัวเป็นภาษาอังกฤษเพราะมันคือชื่อคอลัมน์จริงในฐานข้อมูล

## กติกา 5 ข้อที่ทั้งระบบยึด

**1. facet แต่ละตัวเป็นอิสระต่อกัน** `segment` ไม่บอกอะไรเกี่ยวกับ `body_type`
และ `market_position` ไม่ได้เดาจากชื่อรุ่น แต่คำนวณจากราคา เมื่อทุกแกนตั้งฉากกัน
มันจึง cross กันได้ทุกคู่โดยไม่ต้องเขียนเคสพิเศษ

**2. แยกปี ไม่ยุ่งกับอดีต** catalog หนึ่งชุด = หนึ่งปี อยู่คนละโฟลเดอร์
ยอดปี 2026 ถูกจัดด้วย catalog 2026 เท่านั้น ไม่มีการอ่านข้ามปี ไม่มีการย้อนราคา
ปีที่ปิดไปแล้วไม่ขยับ ปีหน้าคือ `catalog fork` ออกมาแล้วแก้

**3. หนึ่งรุ่น = หนึ่ง body** ชื่อเดียวขายสองบอดี้ = คนละรุ่นไปเลย
โดย**บอดี้หลักใช้ชื่อเปล่า** ส่วนอีกบอดี้ต่อท้าย — `City` / `City Hatchback`,
`Mazda2` / `Mazda2 Hatchback`, `Mazda3` / `Mazda3 Hatchback` ฉลากเปล่าจาก DLT
จึงตกลงบอดี้หลักเอง ไม่กำกวม

กระบะแยกสองทางตามประเภทจดทะเบียน: `Double Cab` (รย.1) กับ `Cab` (รย.3)
ไม่แยกตอนเดียว/สมาร์ทแค็บ **เพราะ DLT ไม่ได้บอก** — แยกเท่าที่ข้อมูลแยกได้จริง

**4. `nameplate` ประกอบกลับ** ที่แตกไปตามข้อ 3 รวมกลับได้ด้วย `nameplate`
Revo ทุกแค็บ + Champ → `Hilux` อันเดียว และโฉมของรุ่นเดียวกันเรียงตามเวลา
(Camry XV70 → XV80 วางต่อกัน) จะดูแบบรวมหรือแบบแตกก็ `--by nameplate` กับ
`--by model` เอา

**5. แยกเฉพาะที่ข้อมูลแยกได้จริง** DLT ไม่ประกาศยอดระดับรุ่นย่อย
catalog จึงเก็บเป็น **spec line** ไม่ใช่ trim list — รวมทุก trim ที่ไม่ต่างกัน
ในสายตารายงาน แล้วเก็บชื่อ trim เดิมไว้เป็น alias กับช่วงราคาจริง

## 4 ชั้นของตัวตน (identity layers)

```
Brand  →  Model  →  Generation  →  Variant        ทั้งหมดอยู่ในปีเดียว
ยี่ห้อ     รุ่น+บอดี้    โฉม          spec line
             ↑
        nameplate รวมกลับ (Hilux)
```

| ชั้น | เก็บ facet อะไร | เหตุผล |
|---|---|---|
| `Brand` | `brand_segment`, `oem_group`, `brand_origin` | คงที่ทั้งยี่ห้อ |
| `Model` | `nameplate`, `body_type`, `cab_type`, `registration_type`, `market_scope` | นิยามว่า "รุ่นนี้คืออะไร" — `body_type`/`cab_type` ล็อกไว้ ห้าม override ที่ชั้นล่าง |
| `Generation` | `segment`, `seats`, `launched`, `ended` | โฉมใหม่ย้าย segment ได้ เรียงตาม `launched` เสมอ |
| `Variant` | `powertrain`, `drivetrain`, `engine_cc`, `battery_kwh`, `price_thb` → `market_position`, `price_min_thb`/`price_max_thb`, `import_type`, `origin_country` | หนึ่ง spec ไม่ใช่หนึ่ง trim |

### การ override เป็นชั้น ๆ

`resolve()` ไล่จากชั้นที่เฉพาะเจาะจงที่สุดออกไป — variant → generation → model →
brand — เจอค่าแรกที่ถูกกรอกก็ใช้ค่านั้น ค่าที่เป็น `None`/`""`/`UNKNOWN`
ไม่นับว่ากรอก จึงตกไปใช้ชั้นบนแทน ไม่ใช่ลบทิ้ง

ยกเว้น `body_type` กับ `cab_type` ที่ล็อกไว้ที่ชั้น model — ถ้ามีคนพยายาม override
ที่รุ่นย่อย ระบบจะฟ้องและไม่ยอมเขียนลงดิสก์ เพราะนั่นแปลว่ามันควรเป็นคนละรุ่น

ทุกค่าที่ resolve ได้ จะมี **provenance** ติดมาว่ามาจากชั้นไหน
(`python -m vehreg catalog show revo_double`)

### facet ที่คำนวณเอง ไม่เก็บ

`market_position`, `powertrain_group`, `is_electrified`, `is_plug_in`,
`is_locally_assembled` — คำนวณจาก facet อื่นทุกครั้ง จึงขัดแย้งกับต้นทางไม่ได้เลย
`registration_type` ก็ derive จาก body + cab ถ้าไม่กรอก

## Variant คือ "spec line" ไม่ใช่ trim

**DLT ไม่มีข้อมูลยอดจดทะเบียนแยกรุ่นย่อย** ข้อมูลสาธารณะละเอียดสุดคือระดับแบบรถ
เพราะฉะนั้นการไล่ใส่ trim ทุกตัวไม่ได้ทำให้ตอบคำถามอะไรได้เพิ่ม

กติกาคือ **แยก spec line ต่อเมื่อมันต่างกันในแกนที่รายงาน** — powertrain,
drivetrain, ประเภทนำเข้า, ประเทศผลิต, หรือราคาข้ามช่วง ที่เหลือยุบรวม

ตัวอย่าง Yaris Ativ 4 trim ยุบเหลือบรรทัดเดียว:

```
1.2L ICE   559,000   (ช่วง 559,000-709,000)
           aliases: 1.2 Sport | 1.2 Smart | 1.2 Premium | 1.2 Premium Luxury
```

ชื่อ trim เดิมกลายเป็น alias ทั้งหมด ถ้าวันหนึ่งมีแหล่งข้อมูลที่ระบุ trim มาจริง
มันจะจับคู่ลงบรรทัดที่ถูกได้ทันที ส่วนฉลากที่บอกแค่ชื่อรุ่น ระบบ**ไม่ยอม**
ให้มันตกลง spec line — ป้องกันการอ้างความละเอียดที่ต้นทางไม่มี

ถ้ายุบแล้วช่วงราคาข้ามเส้นแบ่ง band (เช่น 999,000 กับ 1,149,000)
validate จะฟ้องให้แยกบรรทัด

## market_scope — ตัดเกรย์ / ซูเปอร์คาร์ / ของไม่ significant

| ค่า | ความหมาย |
|---|---|
| `CORE` | ตัวแทนจำหน่ายทางการ ยอดมีนัยสำคัญ — **นับในรายงานโดยดีฟอลต์** |
| `NICHE` | ทางการแต่เป็น halo / ซูเปอร์คาร์ / ยอดน้อยมาก |
| `GREY` | ไม่ใช่ตัวแทนทางการ |

ทำไมไม่ลบทิ้ง: เพราะรถพวกนี้**ยังโผล่ในไฟล์ DLT** ถ้าลบออกจาก catalog
แถวพวกนั้นจะไปกองอยู่ในคิว review ตลอดกาล การ mark scope แทนทำให้มันยัง
จับคู่ได้ แต่ไม่เข้ารายงาน และ cube จะบอกทุกครั้งว่าตัดอะไรออกไปกี่คัน

seed ตอนนี้ mark เป็น NICHE ไว้ 9 รุ่น: Land Cruiser 300, Alphard, Mustang,
911, Cayenne, EQS, Lexus LM, Zeekr 009, EV9 — **เป็นแค่ชุดตั้งต้น**
`python -m vehreg catalog scope NICHE` ดูรายการ แล้วปรับเองผ่าน CSV ได้

## Vocabulary ทั้งหมด

ดูรายการเต็มพร้อมคำแปลไทยด้วย `python -m vehreg facets`

| facet | ค่า |
|---|---|
| `segment` | A, B, C, D, E, F, UNKNOWN |
| `body_type` | HATCHBACK, SEDAN, CROSSOVER, SUV, PPV, COUPE, MPV, PICKUP, OTHER |
| `cab_type` | DOUBLE_CAB, SMART_CAB, SINGLE_CAB, NOT_APPLICABLE |
| `market_position` | ENTRY, VOLUME, UPPER, LUXURY, UNKNOWN |
| `powertrain` | ICE, MHEV, HEV, PHEV, REEV, BEV, FCEV, UNKNOWN |
| `powertrain_group` | COMBUSTION, HYBRID, ZERO_EMISSION |
| `import_type` | CBU, SKD, CKD, UNKNOWN |
| `origin_country` | ISO-2: TH, CN, ID, MY, JP, KR, IN, DE, … |
| `brand_segment` | BUDGET, MASS, PREMIUM_TECH, PERFORMANCE, PREMIUM_LUXURY |
| `registration_type` | RY1, RY2, RY3, OTHER |
| `drivetrain` | FWD, RWD, AWD, 4WD, UNKNOWN |
| `market_scope` | CORE, NICHE, GREY, UNKNOWN |
| `nameplate` | ข้อความ เช่น `Hilux`, `Camry` |

## กระบะ กับ ประเภทจดทะเบียน

| แค็บ | `cab_type` | ประเภท |
|---|---|---|
| 4 ประตู | `DOUBLE_CAB` | **รย.1** (กรมฯ นับเป็นรถยนต์นั่ง) |
| ตอนเดียว + สมาร์ท/สเปซ/คลับแค็บ | `SINGLE_SMART` | รย.3 (รถยนต์บรรทุก) |

**หนึ่ง nameplate กระบะ = สองรุ่นในระบบ** เท่านั้น เช่น `Hilux Revo Double Cab`
กับ `Hilux Revo Cab` เพราะ DLT พิมพ์มาแค่ `HILUX REVO` แล้วบอกประเภทจดทะเบียน
— แยกละเอียดกว่านี้ก็เดาเอาเอง ซึ่งระบบนี้ไม่ทำ

(`SINGLE_CAB` กับ `SMART_CAB` ยังอยู่ใน vocabulary เผื่อวันหนึ่งมีแหล่งข้อมูล
ที่แยกได้จริง แต่ catalog ไม่ใช้)

ผลคือฉลากเปล่า `REVO` แกะออกได้ทุกไฟล์: รย.1 → Double Cab, รย.3 → Cab
ส่วน รย.2 (ดัดแปลงเกิน 7 ที่นั่ง) ถือตามบอดี้ รย.1

PPV (Fortuner / MU-X / Pajero Sport / Everest) เป็น `body_type = PPV` และเป็น
รย.1 — ไม่ใช่กระบะ แม้จะใช้แชสซีร่วมกัน

## การจับคู่ชื่อจากไฟล์ DLT

DLT พิมพ์ `แบบรถ` มาแค่ `REVO` ไม่ได้บอกแค็บ ระบบจึงทำงานสองจังหวะ:

1. จับคู่กับ**ทุกรุ่นของยี่ห้อนั้น** — ถ้าฉลากบอกแค็บมาเอง (`REVO DOUBLE CAB`)
   ก็จบตรงนี้ และชื่อจริงของรุ่นชนะ alias ที่ระบบสร้างให้เสมอ
   (`CITY` = City ซีดาน ไม่ใช่ City Hatchback)
2. ถ้าฉลากเข้าได้หลายรุ่นเท่ากัน ใช้**ประเภทจดทะเบียนของไฟล์**ตัดสิน
   * `REVO` ในไฟล์ รย.1 → เหลือ Double Cab ตัวเดียว → จับคู่ได้
   * `REVO` ในไฟล์ รย.3 → เหลือ Single + Smart → **ไม่เดา** ส่งเข้าคิว review
     พร้อมบอกว่าตัวเลือกคืออะไรบ้าง ยอดยังถูกนับไว้ที่ระดับยี่ห้อ ไม่หายไปไหน

สอนครั้งเดียวจบ และสอนแยกตามประเภทได้:

```bash
python -m vehreg review --map "model:TOYOTA REVO=toyota.hilux_revo_smart_cab" --reg RY3
```

## 6 ข้อที่กูตัดสินใจแทน — เจ้าของต้องยืนยัน

1. **Segment F = กระบะ** ตามที่สั่ง แต่ทำให้ไม่มีที่ให้รถใหญ่มาก
   (Land Cruiser 300, LX, S-Class, Alphard) ตอนนี้วางไว้ที่ `E` ทั้งหมด
2. **ช่องว่างราคา 1.8–2.0 ล้าน** โจทย์เขียน "1–1.8 ล้าน" แล้วข้ามไป "2 ล้าน+"
   ปิดช่องที่ 1.8 ล้าน ดังนั้น `LUXURY` = 1.8 ล้านขึ้นไป
   แก้ได้ที่เดียวคือ `PRICE_BAND_EDGES` ใน `vehreg/taxonomy.py`
3. **เพิ่ม MHEV** รถ 48V ไม่ใช่ HEV จริง ถ้าไม่อยากแยก ให้กรอกเป็น ICE
4. **ราคาใน seed ยังไม่ยืนยัน** ทุกรุ่นย่อยติดโน้ต `seed-unverified`
   `python -m vehreg catalog audit` ลิสต์ให้
5. **ยังไม่มีตัวโหลดอัตโนมัติจากเว็บ DLT** ไม่เขียน scraper เดา endpoint
   เจ้าของโหลดไฟล์มาเอง แล้วระบบบันทึก sha256 + URL ที่ระบุไว้เป็นหลักฐาน
6. **รายการ NICHE 9 รุ่น** เป็นการตีความ "ไม่ significant" ของกูเอง
   ปรับได้ที่คอลัมน์ `market_scope` และ **"Hilux Travo / Travo e"** ยังไม่ได้ใส่
   เพราะยืนยันชื่อทางการของ Toyota ไทยไม่ได้ ถ้าเจ้าของยืนยันสะกด
   เพิ่มเป็นแถวเดียวใน CSV โดยตั้ง `nameplate = Hilux` ก็รวมเข้ากลุ่มเดิมทันที

การจัดว่ารถคันไหนอยู่ segment / brand_segment ไหน เป็นของเจ้าของทั้งหมด
seed เป็นแค่จุดตั้งต้น แก้ผ่าน `catalog export` → แก้ใน Excel → `catalog import`

## ตอนนี้ seed ปี 2026 มีอะไรอยู่

28 ยี่ห้อ / 125 nameplate / 141 รุ่น (CORE 132, NICHE 9) / 168 spec line
— ในนั้นเป็นกระบะ 22 รุ่น (double cab 8 = รย.1, smart cab 7 + single cab 7 = รย.3)
ซึ่งรวมกลับเป็น 8 nameplate
