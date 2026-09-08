"""Side-by-side comparison, and an honest account of what cannot be compared.

The card never ranks things that are not the same quantity. A plug-in hybrid's
electric-only range is not a short BEV range; its smaller battery is not a worse
battery; a BEV's zero tailpipe CO2 is a definition rather than an advantage. Any
row that would have to pretend otherwise says so instead, and still shows every
number it has.

Everything here is evidence with a link back to it. Candidate cards come from
the ECO homologation register, which proves a configuration exists, not that it
is what the showroom sells today — those cards are marked provisional and their
prices are declared tax figures, never retail.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from vehreg.battlecard import BattleCardEngine
from vehreg.catalog import Catalog, DATA_DIR, DEFAULT_YEAR
from vehreg.comparable_specs import (
    ComparableCohort, ComparableSpecError, ECOCandidateSpecStore, SpecRegistry,
)
from vehreg.product import ProductMaster

st.set_page_config(page_title="เทียบสเปค | TDR", layout="wide")
st.title("เทียบสเปค")
st.caption(
    "ทุกช่องมีที่มา กดดูได้ · แถวไหนเทียบไม่ได้จะบอกว่าเทียบไม่ได้และบอกเหตุผล "
    "ไม่ยัดตัวเลขคนละความหมายมาไว้คอลัมน์เดียวกันแล้วประกาศผู้ชนะ"
)

YEAR = DEFAULT_YEAR

#: Why a row declines to pick a winner. Said in the reader's language, because
#: "INSUFFICIENT_DATA" on a page is just the code talking to itself.
STATUS_TH = {
    "COMPARABLE": ("เทียบได้", "🟢"),
    "COMPARABLE_WITH_GAPS": ("เทียบได้ (บางคันไม่มีข้อมูล)", "🟡"),
    "NOT_COMPARABLE_ACROSS_POWERTRAIN": (
        "เทียบข้ามระบบขับเคลื่อนไม่ได้ — คนละความหมาย", "⛔"),
    "NOT_APPLICABLE_TO_OTHERS": ("รถคันอื่นไม่มีสิ่งนี้อยู่แล้ว", "➖"),
    "CONTEXT_NOT_SHARED": ("วัดกันคนละมาตรฐาน จึงแยกแถว", "⛔"),
    "INSUFFICIENT_DATA": ("ข้อมูลไม่พอ", "⚪️"),
    "INFORMATION_ONLY": ("ดูประกอบ ไม่ตัดสินแพ้ชนะ", "ℹ️"),
    "SET_DIFFERENCE": ("รายการต่างกัน", "ℹ️"),
}

VALUE_STATE_TH = {
    "NOT_APPLICABLE": "ไม่มีในรถประเภทนี้",
    "NOT_AVAILABLE": "แหล่งไม่ได้ระบุ",
    "UNKNOWN": "ยังไม่มีใครหา",
}


@st.cache_resource
def load_all():
    registry = SpecRegistry.load(DATA_DIR, YEAR)
    return (registry, ComparableCohort.load(DATA_DIR, YEAR),
            ECOCandidateSpecStore.load(DATA_DIR, YEAR, registry=registry),
            Catalog.load(DATA_DIR, YEAR))


try:
    registry, cohort, store, catalog = load_all()
except (ComparableSpecError, Exception) as exc:            # noqa: BLE001
    st.error("โหลดชุดเทียบสเปคไม่สำเร็จ")
    st.exception(exc)
    st.stop()

as_of = st.sidebar.date_input("ณ วันที่", value=date.today())
# Core first: the alphabetically first profile is "comfort", three fields wide,
# and landing on it makes the page look empty on arrival.
profiles = sorted(registry.profiles,
                  key=lambda name: (not name.endswith("_core"), name))
profile_id = st.sidebar.selectbox("ชุดหัวข้อ", profiles)
source = st.sidebar.radio(
    "เทียบจาก", ["ECO (รอตรวจ)", "trim ที่ผ่านการตรวจแล้ว"])

backlog = cohort.expansion_backlog
st.sidebar.caption(
    f"กลุ่ม {cohort.id}: อยู่ในเกณฑ์ {len(cohort.model_ids)} รุ่น · "
    f"เทียบได้ตอนนี้ {len(cohort.pilot_model_ids)} รุ่น")
if backlog:
    st.sidebar.info(
        f"อีก {len(backlog)} รุ่นอยู่ในเกณฑ์แต่ยังไม่ได้เลือกรุ่นย่อยตัวแทน "
        "จึงยังไม่ขึ้นมาเทียบ — เป็นงานค้าง ไม่ได้ถูกตัดออกจากเซกเมนต์:\n\n"
        + "\n".join(f"- {m}" for m in backlog))

if source.startswith("ECO"):
    # The pilot only. A model in the universe without a chosen representative
    # has nothing to put in a column, and guessing one would be the judgement
    # this design refuses to automate.
    pilot = set(cohort.pilot_model_ids)
    options = {f'{r["label"]}  ({r["model_id"]})': r["source_id"]
               for r in store.list(representatives_only=True)
               if r["model_id"] in pilot}
    st.info("การ์ดจากหลักฐาน ECO — ยืนยันว่าสเปคนี้ผ่านการรับรอง "
            "ไม่ได้ยืนยันว่าโชว์รูมขายรุ่นย่อยนี้อยู่ตอนนี้ และราคาที่เห็นคือราคาแจ้ง ไม่ใช่ราคาขาย")
else:
    master = ProductMaster.load(DATA_DIR, YEAR)
    options = {t.id: t.id for t in master.catalog.trims.values()}

picked = st.multiselect("เลือก 2–6 คัน", sorted(options), max_selections=6)
if len(picked) < 2:
    st.stop()

engine = BattleCardEngine(registry)
try:
    if source.startswith("ECO"):
        card = engine.candidate_card(store, [options[p] for p in picked],
                                     profile_id=profile_id)
    else:
        card = engine.trim_card(ProductMaster.load(DATA_DIR, YEAR),
                                [options[p] for p in picked],
                                profile_id=profile_id, as_of=as_of)
except ComparableSpecError as exc:
    st.error(str(exc))
    st.stop()

labels = {s["subject_id"]: s["label"] for s in card["subjects"]}
columns = st.columns(len(card["subjects"]))
for column, subject in zip(columns, card["subjects"]):
    with column:
        st.markdown(f"**{subject['label']}**")
        st.caption(subject.get("powertrain") or "—")
        evidence = subject.get("price_evidence") or {}
        if evidence.get("amount_thb"):
            st.caption(f"{evidence['amount_thb']:,} บาท "
                       f"({evidence['price_type']}) — ไม่ใช่ราคาขายจริง")
        listed = subject.get("current_list_price")
        if listed:
            st.metric("ราคาปกติ", f"{listed['amount_thb']:,}")


def cell_text(cell):
    if cell.get("display") is not None:
        return cell["display"]
    return VALUE_STATE_TH.get(cell.get("value_state") or "", "—")


rows = []
for row in card["rows"]:
    definition = registry.fields[row["field_key"]]
    label, mark = STATUS_TH.get(row["comparison_status"],
                                (row["comparison_status"], ""))
    context = " · ".join(f"{k}={v}" for k, v in row["comparison_context"].items() if v)
    entry = {"หัวข้อ": definition.label_th + (f"  [{context}]" if context else ""),
             "สถานะ": f"{mark} {label}"}
    for subject_id, cell in row["cells"].items():
        text = cell_text(cell)
        if subject_id in row["leaders"]:
            text = f"★ {text}"
        entry[labels[subject_id]] = text
    rows.append(entry)

st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
st.caption("★ = ดีที่สุดในแถวนั้น เฉพาะแถวที่เทียบกันได้จริงเท่านั้นจึงจะมีดาว")

with st.expander("ที่มาของแต่ละช่อง"):
    provenance = []
    for row in card["rows"]:
        for subject_id, cell in row["cells"].items():
            if cell.get("source_ref"):
                provenance.append({
                    "หัวข้อ": row["field_key"], "รถ": labels[subject_id],
                    "ค่า": cell_text(cell), "แหล่ง": cell.get("source"),
                    "ความน่าเชื่อถือ": cell.get("verification_status"),
                    "ลิงก์": cell["source_ref"]})
    st.dataframe(pd.DataFrame(provenance), width="stretch", hide_index=True)

st.caption(f"โหมด {card['mode']} · ชุดหัวข้อ {card['profile_id']} · "
           f"เทียบได้ {card['coverage'].get('comparable_rows', 0)} แถว จาก "
           f"{len(card['rows'])} แถว")
