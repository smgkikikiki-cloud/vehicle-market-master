"""What the ingest could not place, and what each label actually needs.

The queue is not a list of decisions waiting to be clicked. Measured on the
warehouse as it stands, none of the 22,440 open units can be settled by a
lesson: most of them need a car adding to the catalog, a big block needs a
better file for one month, and the rest is factory codes DLT prints where the
model name goes. Telling the owner that, with the numbers behind it, is worth
more than a page of dropdowns that quietly encourage a wrong click to make a
counter go down.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

import ui
from vehreg import review
from vehreg.db import connect
from vehreg.ingest import sources_awaiting_reload
from vehreg.web_bootstrap import bootstrap_database, database_path

st.set_page_config(page_title="คิวรอตรวจ | TDR", layout="wide")
st.title("คิวรอตรวจ")
st.caption(
    "ทุกแถวที่ระบบไม่กล้าเดาว่าเป็นรถรุ่นไหน จะไม่ถูกทิ้งและไม่ถูกยัดเข้ารุ่นที่ใกล้ที่สุด "
    "มันมากองอยู่ที่นี่พร้อมเหตุผล — หน้านี้บอกว่าแต่ละกองต้องแก้ด้วยอะไร"
)


@st.cache_resource
def boot() -> dict[str, object]:
    return bootstrap_database()


try:
    boot()
except Exception as exc:                                   # noqa: BLE001
    st.error("เปิดฐานข้อมูลไม่สำเร็จ")
    st.exception(exc)
    st.stop()

db_path = database_path()
conn = connect(db_path)


@st.cache_resource
def catalogs() -> dict[int, review.Catalog]:
    return review.load_catalogs()


@st.cache_resource(show_spinner="กำลังจัดคิว…")
def triage(_stamp: int) -> list[review.Item]:
    """Group and classify the whole queue.

    Keyed on the number of open rows so that teaching, dismissing or reloading
    invalidates it and nothing else has to.
    """
    fresh = connect(database_path())
    try:
        return review.queue(fresh, catalogs(), limit=5000)
    finally:
        # `with` on a sqlite3 connection commits a transaction; it does not
        # close the handle.
        fresh.close()


stamp = conn.execute(
    "SELECT COUNT(*) AS n FROM ingest_review WHERE status = 'open'"
).fetchone()["n"]
items = triage(int(stamp))

if not items:
    st.success("คิวว่าง ไม่มีป้ายไหนค้างอยู่")
    st.stop()

open_units = sum(item.units for item in items)
plan = review.summary(items)

top = st.columns(len(plan) + 1)
# No delta on these: an arrow would read as a change over time, and these are a
# split of one number.
top[0].metric("ค้างทั้งหมด", f"{open_units:,.0f} คัน")
top[0].caption(f"{len(items):,} ป้าย")
for column, row in zip(top[1:], plan):
    column.metric(str(row["label"]), f"{float(row['units']):,.0f} คัน")
    column.caption(f"{row['labels']:,} ป้าย · "
                   f"{float(row['units']) / open_units:.0%} ของที่ค้าง")

warehouse = float(conn.execute(
    "SELECT COALESCE(SUM(units), 0) AS u FROM fact_registration"
).fetchone()["u"])
st.caption(
    f"{open_units:,.0f} คัน = {open_units / warehouse:.2%} ของทั้งคลัง "
    f"({warehouse:,.0f} คัน) และมันไม่ได้หายไปไหน — ยอดพวกนี้ถูกนับอยู่แล้ว "
    "ที่ระดับยี่ห้อ ที่ค้างคือความละเอียดระดับรุ่น"
)
st.divider()

tabs = st.tabs(["สอนได้เลย", "ต้องเพิ่มใน catalog", "ต้องหาไฟล์ที่ดีกว่า",
                "ปัดทิ้งได้", "โหลดไฟล์ซ้ำ"])


# ---------------------------------------------------------------- teachable
with tabs[0]:
    teachable = [item for item in items if item.teachable]
    st.caption(
        "ป้ายที่มีรุ่นใน catalog ใกล้พอจนตัดสินได้เลย เกณฑ์เดียวกับที่ระบบใช้จับคู่เอง "
        "(0.86) — ต่ำกว่านั้นไม่เอามาเสนอ เพราะข้อเสนอที่ไม่แน่จริงคือกับดักให้กดผิด"
    )
    if not teachable:
        st.info(
            "ตอนนี้ไม่มีป้ายไหนที่ระบบเสนอเองได้ ซึ่งเป็นเรื่องปกติ: "
            "ถ้าชื่อมันใกล้ถึง 0.86 ระบบก็จับคู่ไปแล้วตั้งแต่ตอนอ่านไฟล์ "
            "ที่ค้างอยู่คือของที่ 'มึงรู้ แต่ตัวหนังสือไม่รู้' — ใช้ช่องเลือกเองข้างล่างนี้ "
            "หรือไปเพิ่มรุ่นใน catalog ที่แท็บถัดไป"
        )
    for item in teachable[:40]:
        with st.container(border=True):
            head, action = st.columns([3, 2])
            head.markdown(f"**{item.raw_label}**")
            head.caption(
                f"{item.units:,.0f} คัน · {len(item.periods)} เดือน "
                f"({item.periods[0]}–{item.periods[-1]}) · "
                f"{review.REASON_LABELS.get(item.reason, item.reason)}"
            )
            if item.note:
                head.caption(f"⚠︎ {item.note}")
            labels = {c.unit_id: f"{c.label} · {c.score:.2f}"
                      for c in item.candidates}
            target = action.radio(
                "จับเข้ารุ่น", list(labels), format_func=labels.get,
                key=f"t_{item.key}", label_visibility="collapsed")
            scope = action.selectbox(
                "ผูกกับคลาส", [item.default_reg, "*"],
                format_func=lambda v: "ทุกคลาส" if v == "*" else v,
                key=f"r_{item.key}",
                help="บทเรียนจะทำงานเฉพาะไฟล์ที่เป็นคลาสนี้")
            if action.button("สอน", key=f"b_{item.key}", type="primary"):
                review.teach(conn, item, target, reg=scope)
                st.cache_resource.clear()
                st.success(
                    f"จำแล้ว: {item.raw_label} → {labels[target]} "
                    "— ยอดจะขยับหลังโหลดไฟล์ซ้ำที่แท็บสุดท้าย")
                st.rerun()

    st.divider()
    st.subheader("เลือกเอง")
    st.caption(
        "สำหรับกรณีที่มึงรู้ว่ามันคือรุ่นไหนแต่ชื่อมันไม่เหมือนกันเลย "
        "เช่น TR TRANSFORMER คือ Hiace ที่เอาไปต่อตัวถัง — "
        "ตรงนี้เป็นรายชื่อรุ่นทั้งหมดของยี่ห้อนั้น ไม่ใช่ข้อเสนอของระบบ "
        "และตัดรุ่นที่ catalog ปีเก่ายังไม่มีออกให้แล้ว"
    )
    manual = [item for item in items
              if item.brand_id and not item.teachable][:200]
    if not manual:
        st.caption("ไม่มีป้ายที่จับยี่ห้อได้แต่ยังไม่รู้รุ่น")
    else:
        pick = st.selectbox(
            "ป้ายที่ค้าง", manual,
            format_func=lambda i: f"{i.raw_label} — {i.units:,.0f} คัน "
                                  f"({len(i.periods)} เดือน)",
            key="manual_item")
        options = review.models_for(
            [catalogs()[y] for y in pick.years if y in catalogs()],
            pick.brand_id)
        if not options:
            st.warning(f"ยี่ห้อ {pick.brand_id} ยังไม่มีรุ่นไหนที่ครบทุกปีของป้ายนี้")
        else:
            names = {c.unit_id: c.label for c in options}
            target = st.selectbox("คือรุ่นนี้", list(names),
                                  format_func=names.get, key="manual_target")
            scope = st.selectbox(
                "ผูกกับคลาส", [pick.default_reg, "*"],
                format_func=lambda v: "ทุกคลาส" if v == "*" else v,
                key="manual_scope")
            st.caption(f"จะจำว่า: {pick.raw_label} → {names[target]}")
            if st.button("สอนตามที่เลือก"):
                review.teach(conn, pick, target, reg=scope)
                st.cache_resource.clear()
                st.success("จำแล้ว — ไปโหลดไฟล์ซ้ำที่แท็บสุดท้ายให้ยอดขยับ")
                st.rerun()


# ------------------------------------------------------------ catalog gaps
with tabs[1]:
    gaps = review.catalog_gaps(items)
    gap_units = sum(float(g["units"]) for g in gaps) or 1.0
    head = sum(float(g["units"]) for g in gaps[:4])
    st.caption(
        "รถที่ DLT จดทะเบียนจริงแต่ catalog ยังไม่รู้จัก ไม่มี alias ไหนเสกขึ้นมาได้ "
        "ต้องเพิ่มรุ่นในไฟล์ยี่ห้อของปีนั้นก่อน เรียงตามยอด — "
        f"แค่ 4 ยี่ห้อแรกก็ {head / gap_units:.0%} ของกองนี้แล้ว"
    )
    frame = pd.DataFrame([
        {"ยี่ห้อ": g["brand"], "คัน": g["units"], "จำนวนป้าย": g["labels"]}
        for g in gaps
    ])
    st.dataframe(frame, width="stretch", hide_index=True, height=300,
                 column_config={"คัน": st.column_config.NumberColumn(
                     format="%.0f")})
    flat = pd.DataFrame([
        {"ยี่ห้อ": g["brand"], "รุ่นตามที่ DLT เขียน": m["model"],
         "คัน": m["units"], "ปี": m["years"], "จำนวนเดือน": m["months"]}
        for g in gaps for m in g["models"]
    ])
    ui.download_table(flat, stem="catalog_gaps", period="all",
                      label="ดาวน์โหลดรายการที่ต้องเพิ่ม (CSV)")
    st.caption(
        "⚠︎ ไม่ใช่ทุกป้ายที่ต้องเพิ่มเป็น 'รุ่นใหม่' — บางอันคือรุ่นย่อยของรุ่นที่มีอยู่แล้ว "
        "เช่น BMW 745Le คือ 7 Series ที่ยังไม่มี alias ถ้าเพิ่มเป็นรุ่นแยก 7 Series "
        "จะแตกเป็นสิบชิ้นและตัวเลขทุกตัวหลังจากนั้นผิดหมด "
        "กูลองเขียนกฎให้มันแยกเองแล้วมันพัง (Q7 ไปเจอ Q3, Model X ไปเจอ Model 3 "
        "ได้คะแนนเต็มทั้งคู่) เลยเอารายชื่อที่ catalog มีอยู่มาวางไว้ข้างๆ ให้มึงตัดสินเอง"
    )
    for gap in gaps[:12]:
        with st.expander(f"{gap['brand']} — {float(gap['units']):,.0f} คัน · "
                         f"{gap['labels']} ป้าย"):
            missing, existing = st.columns(2)
            missing.caption("**ที่ DLT มี แต่ catalog ไม่รู้จัก**")
            missing.dataframe(
                pd.DataFrame(gap["models"]).rename(columns={
                    "model": "รุ่นตามที่ DLT เขียน", "units": "คัน",
                    "years": "ปี", "months": "จำนวนเดือน"}),
                width="stretch", hide_index=True, height=280,
                column_config={"คัน": st.column_config.NumberColumn(
                    format="%.0f")})
            existing.caption("**ที่ catalog มีอยู่แล้ว — เติม alias ตรงนี้ได้มั้ย**")
            year = max(gap["years"]) if gap["years"] else None
            brand_id = str(gap["brand_id"] or "")
            if brand_id and year in catalogs():
                existing.dataframe(
                    pd.DataFrame(review.known_models(catalogs()[year],
                                                     brand_id)).rename(
                        columns={"model": "รุ่น", "id": "id",
                                 "aliases": "alias ที่มีแล้ว"}),
                    width="stretch", hide_index=True, height=280)
            else:
                existing.info("ยังจับยี่ห้อนี้เข้า catalog ไม่ได้ ต้องเพิ่มยี่ห้อก่อน")


# ------------------------------------------------------------ better source
with tabs[2]:
    stuck = [item for item in items if item.needs == review.NEEDS_SOURCE]
    st.caption(
        "ป้ายที่ไฟล์ต้นทางตอบไม่ได้เอง ส่วนใหญ่คือกระบะที่ต้องรู้ประเภทรถ (รย.) "
        "ถึงจะแยก cab ได้ แต่ไฟล์ pivot ไม่มีคอลัมน์นั้น การสอนที่นี่คือการเดา"
    )
    by_period: dict[str, float] = {}
    for item in stuck:
        for period in item.periods:
            by_period[period] = by_period.get(period, 0.0) + item.units / len(
                item.periods)
    st.dataframe(
        pd.DataFrame([{"เดือน": p, "คัน": u} for p, u in
                      sorted(by_period.items(), key=lambda kv: -kv[1])]),
        width="stretch", hide_index=True, height=260,
        column_config={"คัน": st.column_config.NumberColumn(format="%.0f")})
    st.dataframe(
        pd.DataFrame([{"ป้าย": i.raw_label, "คัน": i.units,
                       "เดือน": ", ".join(i.periods)} for i in stuck]),
        width="stretch", hide_index=True,
        column_config={"คัน": st.column_config.NumberColumn(format="%.0f")})


# ------------------------------------------------------------------ dismiss
with tabs[3]:
    junk = [item for item in items if item.needs == review.NEEDS_NOTHING]
    st.caption(
        "DLT กรอกรหัสโรงงานลงช่องรุ่นเป็นประจำ เช่น UVL4RDRE26KHE----- "
        "ปัดทิ้งไม่ได้แตะยอดเลยสักคัน ยอดยังเกาะที่ยี่ห้อเหมือนเดิม "
        "แค่เอาคำถามที่ไม่มีวันตอบได้ออกจากคิว"
    )
    st.dataframe(
        pd.DataFrame([{"ยี่ห้อ": i.raw_brand, "ที่ DLT เขียนในช่องรุ่น": i.raw_model,
                       "คัน": i.units, "จำนวนเดือน": len(i.periods)}
                      for i in junk]),
        width="stretch", hide_index=True, height=320,
        column_config={"คัน": st.column_config.NumberColumn(format="%.0f")})
    total = sum(i.units for i in junk)
    if junk:
        sure = st.checkbox(
            f"ยืนยันปัด {len(junk)} ป้าย ({total:,.0f} คัน) ออกจากคิว")
        if st.button("ปัดทิ้งทั้งหมด", disabled=not sure):
            changed = review.dismiss(conn, junk)
            st.cache_resource.clear()
            st.success(f"ปัดแล้ว {changed} แถว")
            st.rerun()


# ------------------------------------------------------------------- reload
with tabs[4]:
    st.caption(
        "การจับคู่เกิดตอนอ่านไฟล์ ไม่ใช่ตอนสอน ฉะนั้นบทเรียนที่สอนไว้ "
        "และรุ่นที่เพิ่งเพิ่มใน catalog จะยังไม่ขยับยอดจนกว่าจะอ่านไฟล์นั้นใหม่ "
        "การอ่านใหม่จะลบทุกอย่างที่ไฟล์นั้นเคยเขียนก่อน แล้วเขียนใหม่ทั้งชุด"
    )
    pending = sources_awaiting_reload(conn)
    if pending:
        st.dataframe(
            pd.DataFrame([{"ไฟล์": r["name"], "คัน": r["units"],
                           "แถว": r["rows"]} for r in pending]),
            width="stretch", hide_index=True,
            column_config={"คัน": st.column_config.NumberColumn(
                format="%.0f")})
    else:
        st.info("ยังไม่มีบทเรียนที่รออ่านไฟล์ซ้ำ")

    sources = conn.execute(
        "SELECT source_id, name FROM dim_source ORDER BY name").fetchall()
    names = {int(r["source_id"]): str(r["name"]) for r in sources}
    default = [int(r["source_id"]) for r in pending]
    chosen = st.multiselect(
        "เลือกไฟล์ที่จะอ่านใหม่", list(names), default=default,
        format_func=names.get)
    if chosen and st.button("อ่านใหม่", type="primary"):
        rows = []
        for source_id in chosen:
            try:
                state = review.reload_source(conn, source_id)
            except Exception as exc:                        # noqa: BLE001
                st.error(f"{names[source_id]}: {exc}")
                continue
            rows.append({"ไฟล์": state.name,
                         "review ก่อน": state.before_review,
                         "review หลัง": state.after_review,
                         "ย้ายออกได้": state.moved,
                         "หมายเหตุ": state.error or ""})
        st.cache_resource.clear()
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)

conn.close()
