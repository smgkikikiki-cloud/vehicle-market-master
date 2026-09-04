from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

from vehreg.db import connect
from vehreg.market_metrics import rolling_window, ytd_window
from vehreg.provincial import (
    DEFAULT_PUBLICATION_FILE,
    available_periods,
    category_competition,
    ensure_schema,
    geographic_profile,
    load_publication_rules,
    reconciliation_for_period,
    regional_profile,
)
from vehreg.web_bootstrap import bootstrap_database, database_path

ROOT = Path(__file__).resolve().parents[1]
PROVINCIAL_XLSX = Path(os.environ.get("VEHREG_PROVINCIAL_XLSX", "")) if os.environ.get("VEHREG_PROVINCIAL_XLSX") else None

st.set_page_config(page_title="Regional Market | TDR", layout="wide")
st.title("Regional Market")
st.caption(
    "Selected high-volume models with provincial registration detail. "
    "Province means registration location, not dealer retail-sale territory."
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
ensure_schema(conn)
periods = available_periods(conn)
rules = load_publication_rules(DEFAULT_PUBLICATION_FILE)

if not rules:
    st.error("ยังไม่มี geo publication whitelist")
    conn.close()
    st.stop()

if not periods:
    st.warning(
        "Regional Market พร้อมแล้ว แต่ยังไม่มี provincial facts ในฐานข้อมูล. "
        "ให้นำเข้า DLT provincial workbook ผ่าน admin/CLI ก่อน"
    )
    st.code(
        "python -m vehreg.provincial_cli ingest /path/to/provincial.xlsx",
        language="bash",
    )
    conn.close()
    st.stop()

category_options = []
for rule in rules:
    if rule.category not in [item[0] for item in category_options]:
        category_options.append((rule.category, rule.category_label))
category_label_map = {code: label for code, label in category_options}

period = st.sidebar.selectbox("เดือนข้อมูล", periods, index=len(periods) - 1)
window = st.sidebar.radio("ช่วงเวลา", ["Month", "Rolling 3M", "YTD"], horizontal=False)
category = st.sidebar.selectbox(
    "กลุ่มรถ",
    [code for code, _ in category_options],
    format_func=lambda code: category_label_map[code],
)
category_rules = [rule for rule in rules if rule.category == category]
model_label = st.sidebar.selectbox("รุ่น", [rule.label for rule in category_rules])
selected_rule = next(rule for rule in category_rules if rule.label == model_label)

if window == "Month":
    period_from = period_to = period
elif window == "Rolling 3M":
    period_from, period_to = rolling_window(period, 3)
else:
    period_from, period_to = ytd_window(period)

missing = [p for p in periods if period_from <= p <= period_to]
if not missing:
    st.warning(f"ไม่มี provincial data ในช่วง {period_from} ถึง {period_to}")
    conn.close()
    st.stop()

profile = geographic_profile(
    conn,
    selected_rule,
    category_rules,
    period_from,
    period_to,
)
province_df = pd.DataFrame(profile)
if province_df.empty or float(province_df["units"].sum()) == 0:
    st.info("ไม่มีข้อมูลรุ่นนี้ในช่วงเวลาที่เลือก")
    conn.close()
    st.stop()

region_df = pd.DataFrame(regional_profile(profile))
selected_total = float(province_df["units"].sum())
nonzero = province_df[province_df["units"] > 0].copy()
leader = nonzero.iloc[0]
strongest = (
    nonzero[nonzero["over_index"].notna()]
    .sort_values(["over_index", "units"], ascending=[False, False])
    .iloc[0]
    if not nonzero[nonzero["over_index"].notna()].empty
    else None
)

k1, k2, k3, k4 = st.columns(4)
k1.metric("Registrations", f"{selected_total:,.0f}")
k2.metric("Provinces with registrations", f"{len(nonzero):,}")
k3.metric("Top province", str(leader["province"]), f"{leader['distribution_share']*100:.1f}% of model")
if strongest is not None:
    k4.metric("Strongest over-index", str(strongest["province"]), f"{strongest['over_index']:.2f}x")
else:
    k4.metric("Strongest over-index", "—")

st.caption(
    f"{selected_rule.label} · {period_from} → {period_to} · "
    f"comparison set: {category_label_map[category]}"
)

left, right = st.columns([1.35, 1])
with left:
    st.subheader("Top provinces")
    top = nonzero.head(20).sort_values("units", ascending=True)
    st.plotly_chart(
        px.bar(
            top,
            x="units",
            y="province",
            orientation="h",
            labels={"units": "Registrations", "province": ""},
        ),
        use_container_width=True,
    )
with right:
    st.subheader("Regional mix")
    region_show = region_df.copy()
    region_show["distribution_share_pct"] = region_show["distribution_share"] * 100
    st.plotly_chart(
        px.bar(
            region_show.sort_values("units", ascending=True),
            x="units",
            y="region",
            orientation="h",
            labels={"units": "Registrations", "region": ""},
        ),
        use_container_width=True,
    )
    st.dataframe(
        region_show[["region", "units", "distribution_share_pct", "over_index"]],
        use_container_width=True,
        hide_index=True,
        column_config={
            "units": st.column_config.NumberColumn("Registrations", format="%.0f"),
            "distribution_share_pct": st.column_config.NumberColumn("Model mix", format="%.1f%%"),
            "over_index": st.column_config.NumberColumn("Over-index", format="%.2fx"),
        },
    )

st.subheader("Geographic over-index")
st.caption(
    "Over-index compares this model's share inside the selected competitive set in each province "
    "with its share of the same set nationwide. 1.00x = national average."
)
index_df = nonzero[nonzero["over_index"].notna()].copy()
index_df = index_df.sort_values(["over_index", "units"], ascending=[False, False]).head(20)
if not index_df.empty:
    st.plotly_chart(
        px.bar(
            index_df.sort_values("over_index", ascending=True),
            x="over_index",
            y="province",
            orientation="h",
            labels={"over_index": "Over-index (x)", "province": ""},
        ),
        use_container_width=True,
    )

st.subheader("Competitive position by province")
province_options = ["Nationwide", *nonzero["province"].tolist()]
chosen_province = st.selectbox("จังหวัดสำหรับเทียบคู่แข่ง", province_options)
competition = pd.DataFrame(
    category_competition(
        conn,
        category_rules,
        period_from,
        period_to,
        province=None if chosen_province == "Nationwide" else chosen_province,
    )
)
if not competition.empty:
    competition["share_pct"] = competition["share"] * 100
    st.dataframe(
        competition[["rank", "label", "units", "share_pct"]],
        use_container_width=True,
        hide_index=True,
        column_config={
            "units": st.column_config.NumberColumn("Registrations", format="%.0f"),
            "share_pct": st.column_config.NumberColumn("Share in selected set", format="%.1f%%"),
        },
    )

with st.expander("Methodology / QA"):
    st.markdown(
        "- Regional Market is intentionally curated; it does not expose every registered model.\n"
        "- Province is the vehicle's registration location, not proof of dealer retail-sale location.\n"
        "- Geographic over-index is relative to the curated category shown on this page, not the entire Thai vehicle market.\n"
        "- Provincial facts are stored separately from national facts to prevent double-counting."
    )
    if period_from == period_to:
        recon = reconciliation_for_period(conn, period)
        st.json(recon)

conn.close()
