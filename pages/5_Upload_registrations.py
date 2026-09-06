"""Hand the warehouse a file, see what it would do, then decide."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

import ui
from vehreg import uploads
from vehreg.catalog import DATA_DIR, Catalog
from vehreg.db import clear_period, connect
from vehreg.ingest import ingest_csv
from vehreg.web_bootstrap import bootstrap_database, database_path, pivot_dir

st.set_page_config(page_title="อัปโหลดยอดจดทะเบียน | TDR", layout="wide")
st.title("อัปโหลดยอดจดทะเบียน")
st.caption(
    "รับไฟล์ DLT ทั้งแบบ CSV รายเดือน และ Excel ที่โหลดจากเว็บ gdcatalog "
    "ระบบจะอ่านให้เองว่าเป็นชีตแบบไหน แล้วลองโหลดในฐานข้อมูลชั่วคราวก่อน "
    "ยังไม่แตะข้อมูลจริงจนกว่าจะกดยืนยัน"
)

STAGING = Path(st.session_state.get("_staging", "")) or None


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
loaded = {
    str(row["period"]): float(row["units"])
    for row in conn.execute(
        "SELECT period, SUM(units) AS units FROM fact_registration GROUP BY period"
    )
}
conn.close()

picked = st.file_uploader("เลือกไฟล์", type=["csv", "xlsx", "xlsm"])
if picked is None:
    st.info("ยังไม่ได้เลือกไฟล์")
    st.stop()

@st.cache_resource(show_spinner="กำลังอ่านไฟล์…")
def read_upload(payload: bytes, name: str, _dir: str):
    """Parse once per file, not once per click.

    Streamlit reruns the whole script on every widget change, and re-reading a
    26 MB workbook each time made the page take about forty seconds to answer a
    checkbox. The cache key is the file's own bytes, so a different file is
    always parsed afresh.
    """
    return uploads.inspect(uploads.stage(payload, name, Path(_dir)))


try:
    upload = read_upload(picked.getvalue(), picked.name,
                         str(db_path.parent / "uploads"))
except ValueError as exc:
    st.error(str(exc))
    st.stop()

kind_label = {
    "workbook-long": "Excel — ชีตรายแถว (ดีที่สุด)",
    "workbook-pivot": "Excel — ชีต pivot",
    "csv": "CSV",
}[upload.kind]
st.success(f"อ่านไฟล์ได้: {kind_label} · {upload.detail}")
for warning in upload.warnings:
    st.warning(warning)

frame = pd.DataFrame(
    [
        {
            "เดือน": period,
            "ยอดในไฟล์": units,
            "ในฐานข้อมูลแล้ว": loaded.get(period),
            "สถานะ": "มีอยู่แล้ว" if period in loaded else "ยังไม่มี",
        }
        for period, units in sorted(upload.periods.items())
    ]
)
st.subheader(f"ไฟล์นี้มี {len(frame)} เดือน · รวม {upload.total:,.0f} คัน")
st.dataframe(frame, width="stretch", hide_index=True,
             column_config={
                 "ยอดในไฟล์": st.column_config.NumberColumn(format="%.0f"),
                 "ในฐานข้อมูลแล้ว": st.column_config.NumberColumn(format="%.0f"),
             })

new_periods = [p for p in sorted(upload.periods) if p not in loaded]
chosen = st.multiselect(
    "เลือกเดือนที่จะโหลด",
    sorted(upload.periods),
    default=new_periods,
    help="ค่าเริ่มต้นคือเฉพาะเดือนที่ยังไม่มีในฐานข้อมูล",
)
if not chosen:
    st.info("เลือกอย่างน้อยหนึ่งเดือน")
    st.stop()

replacing = [p for p in chosen if p in loaded]
replace_ok = False
if replacing:
    st.warning(
        "เดือนต่อไปนี้มีข้อมูลอยู่แล้ว: " + ", ".join(replacing) +
        " — ถ้าโหลดทับ ข้อมูลเดิมของเดือนนั้นจะถูกลบก่อน"
    )
    replace_ok = st.checkbox("ยืนยันว่าจะเขียนทับเดือนที่มีอยู่แล้ว")

st.subheader("ตรวจก่อนโหลด")
st.caption(
    "โหลดลงฐานข้อมูลชั่วคราวเพื่อดูว่าจะจับเข้ารุ่นได้เท่าไหร่ "
    "ข้อมูลจริงยังไม่ถูกแตะ"
)
if st.button("ตรวจ (dry run)", type="primary"):
    results = []
    for period in chosen:
        try:
            results.append(uploads.dry_run(upload, period, live_db=db_path))
        except ValueError as exc:
            st.error(f"{period}: {exc}")
    if results:
        st.session_state["_dry"] = [
            {
                "เดือน": r.period,
                "แถว": r.rows,
                "ยอดในไฟล์": r.units_in_file,
                "เข้าฐานข้อมูล": r.units_loaded,
                "ค้าง review": r.units_review,
                "รู้แค่ยี่ห้อ %": round(r.brand_grain_share * 100, 1),
            }
            for r in results
        ]
        st.session_state["_dry_unmatched"] = {
            r.period: r.top_unmatched for r in results
        }

if st.session_state.get("_dry"):
    st.dataframe(pd.DataFrame(st.session_state["_dry"]), width="stretch",
                 hide_index=True)
    for period, rows in st.session_state.get("_dry_unmatched", {}).items():
        if not rows:
            continue
        with st.expander(f"{period}: ป้ายที่จับเข้ารุ่นไม่ได้"):
            st.dataframe(
                pd.DataFrame(rows, columns=["ป้ายจาก DLT", "คัน"]),
                width="stretch", hide_index=True,
            )

    st.subheader("โหลดจริง")
    blocked = bool(replacing) and not replace_ok
    if blocked:
        st.info("ติ๊กยืนยันการเขียนทับด้านบนก่อน")
    if st.button("โหลดเข้าฐานข้อมูลจริง", disabled=blocked):
        conn = connect(db_path)
        report = []
        for period in chosen:
            year = int(period[:4])
            target = uploads.keep(upload, period, pivot_dir())
            if period in loaded:
                # Every table the old load wrote, not just the two obvious
                # ones. Leaving fact_trim behind doubled 2026-07 in the trim
                # ledger the first time this ran, because the replacement gets
                # a new source_id and the ledger keys on it.
                clear_period(conn, period)
            ingest_csv(conn, Catalog.load(DATA_DIR, year), target,
                       f"UPLOAD {period}", publisher="DLT",
                       notes=f"อัปโหลดจาก {upload.path.name}",
                       allow_duplicate_payload=True)
            report.append(f"{period} → {target.name}")
        conn.close()
        # The other pages cache the bootstrap; without this they keep serving
        # the warehouse as it was before this upload.
        st.cache_resource.clear()
        st.session_state.pop("_dry", None)
        st.success("โหลดแล้ว: " + " · ".join(report))
        st.caption("ไฟล์ถูกเก็บไว้ใน data/raw_pivot เพื่อให้ rebuild ได้เหมือนเดิม")
