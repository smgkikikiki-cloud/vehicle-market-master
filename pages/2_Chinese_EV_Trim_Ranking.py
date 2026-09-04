from __future__ import annotations

import pandas as pd
import streamlit as st

from vehreg.db import connect
from vehreg.rankings import chinese_ev_trim_ranking, model_ranking
from vehreg.web_bootstrap import bootstrap_database, database_path

st.set_page_config(page_title="Chinese EV Trim Ranking | TDR", layout="wide")
st.title("Chinese EV Trim Ranking")
st.caption(
    "ชั้นข้อมูลแยกจาก master market: master ยังรวม grade/range/drivetrain ของรุ่นเดียวกัน "
    "แต่หน้านี้เปิดดูยอดรุ่นย่อยที่ DLT ระบุจริง โดยไม่กระจายยอดที่ DLT ไม่ได้แยก"
)

@st.cache_resource
def boot() -> dict[str, object]:
    return bootstrap_database()

try:
    state = boot()
except Exception as exc:
    st.error("เปิดฐานข้อมูลไม่สำเร็จ")
    st.exception(exc)
    st.stop()

conn = connect(database_path())
periods = [r["period"] for r in conn.execute(
    "SELECT DISTINCT period FROM fact_trim ORDER BY period"
)]
if not periods:
    st.warning("ยังไม่มี trim ledger ในฐานข้อมูล — ingest DLT CSV ก่อน")
    conn.close()
    st.stop()

period = st.sidebar.selectbox("เดือน", periods, index=len(periods) - 1)
registration = st.sidebar.selectbox("DLT class", ["ALL", "RY1", "RY2", "RY3"])
powertrain = st.sidebar.selectbox("Powertrain", ["ALL", "BEV", "PHEV", "REEV"])

base_rows = chinese_ev_trim_ranking(
    conn, period,
    registration_type=None if registration == "ALL" else registration,
    powertrain=None if powertrain == "ALL" else powertrain,
)
base = pd.DataFrame(base_rows)

brands = sorted(base["brand"].dropna().unique().tolist()) if not base.empty else []
brand = st.sidebar.selectbox("ยี่ห้อ", ["ALL", *brands])
if brand != "ALL":
    base_rows = chinese_ev_trim_ranking(
        conn, period,
        registration_type=None if registration == "ALL" else registration,
        brand=brand,
        powertrain=None if powertrain == "ALL" else powertrain,
    )
    base = pd.DataFrame(base_rows)

models = sorted(base["model"].dropna().unique().tolist()) if not base.empty else []
model = st.sidebar.selectbox("รุ่น", ["ALL", *models])
rows = chinese_ev_trim_ranking(
    conn, period,
    registration_type=None if registration == "ALL" else registration,
    brand=None if brand == "ALL" else brand,
    model=None if model == "ALL" else model,
    powertrain=None if powertrain == "ALL" else powertrain,
)
df = pd.DataFrame(rows)

tab_trim, tab_powertrain = st.tabs(["Trim ranking", "Powertrain-split master"])

with tab_trim:
    if df.empty:
        st.info("ไม่มีข้อมูลตาม filter นี้")
    else:
        total = float(df["units"].sum())
        split_rows = int((df["trim"] != "DLT_UNSPLIT").sum())
        a, b, c = st.columns(3)
        a.metric("Registrations", f"{total:,.0f}")
        b.metric("Models", f"{df['model'].nunique():,}")
        c.metric("DLT-split trim rows", f"{split_rows:,}")

        visual = df.copy()
        visual["label"] = visual["brand"] + " " + visual["model"] + " — " + visual["trim"]
        st.bar_chart(visual.head(30).set_index("label")["units"], horizontal=True)

        show = df[[
            "rank", "brand", "model", "trim", "powertrain", "grade", "drive",
            "range_km", "battery_kwh", "units", "model_total", "share_of_model",
        ]].copy()
        show["share_of_model"] = show["share_of_model"] * 100
        show = show.rename(columns={"share_of_model": "share_of_model_pct"})
        st.dataframe(show, use_container_width=True, hide_index=True)
        st.download_button(
            "Download Chinese EV trim CSV",
            data=show.to_csv(index=False).encode("utf-8-sig"),
            file_name=f"{period}_chinese_ev_trim_ranking.csv",
            mime="text/csv",
        )
        if (df["trim"] == "DLT_UNSPLIT").any():
            st.caption(
                "DLT_UNSPLIT = เดือนนั้น DLT ลงแค่ชื่อรุ่นรวม เช่น GOOD CAT; "
                "ระบบจะไม่เดาสัดส่วน 400/500/600 เอง"
            )

with tab_powertrain:
    master = pd.DataFrame(model_ranking(
        conn, period,
        registration_type=None if registration == "ALL" else registration,
        limit=100,
    ))
    if master.empty:
        st.info("ไม่มี master facts ในเดือนนี้")
    else:
        st.caption(
            "รุ่นย่อยปกติยังรวมเหมือนเดิม แต่ model ที่มีหลาย powertrain จะถูกแยก "
            "เมื่อ raw DLT บอกได้ เช่น Deepal S05 BEV / S05 REEV"
        )
        show_master = master[["rank", "brand", "model", "powertrain", "units", "share"]].copy()
        show_master["share"] = show_master["share"] * 100
        show_master = show_master.rename(columns={"share": "share_pct"})
        st.dataframe(show_master, use_container_width=True, hide_index=True)

conn.close()
