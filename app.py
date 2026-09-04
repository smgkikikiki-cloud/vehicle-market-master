from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

from vehreg import cube, dlt
from vehreg.catalog import DATA_DIR, Catalog, available_years
from vehreg.db import connect, rebuild_dimension
from vehreg.ingest import ingest_csv
from vehreg.monthly_state import (
    audit_log,
    delete_change,
    effective_state,
    ensure_schema as ensure_monthly_schema,
    history,
    set_state,
)
from vehreg.taxonomy import KNOWN_ORIGIN_COUNTRIES

ROOT = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get("VEHREG_DB", str(ROOT / "data" / "vehreg.sqlite3")))
RAW_DIR = ROOT / "data" / "raw"


@st.cache_resource
def bootstrap_database() -> dict[str, object]:
    """Build dimensions and ingest any committed monthly DLT files once."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = connect(DB_PATH)
    ensure_monthly_schema(conn)

    years = available_years(DATA_DIR)
    catalogs: dict[int, Catalog] = {}
    rebuilt: list[int] = []
    for year in years:
        catalog = Catalog.load(DATA_DIR, year)
        catalogs[year] = catalog
        rebuild_dimension(conn, catalog)
        rebuilt.append(year)

    ingested: list[str] = []
    for path in sorted(RAW_DIR.glob("dlt_????-??.csv")):
        period = path.stem.removeprefix("dlt_")
        try:
            year = int(period[:4])
        except ValueError:
            continue
        if year not in catalogs:
            continue

        absolute = str(path.resolve())
        already = conn.execute(
            "SELECT 1 FROM dim_source WHERE file_name = ? OR file_name LIKE ? "
            "OR file_name LIKE ? OR name IN (?,?,?) LIMIT 1",
            (absolute, f"%/{path.name}", f"%\\{path.name}",
             f"DLT {period}", path.name, f"WEB {period}"),
        ).fetchone()
        if already:
            continue

        ingest_csv(
            conn,
            catalogs[year],
            path,
            f"WEB {period}",
            colmap=dlt.column_map(),
            publisher="DLT",
        )
        ingested.append(period)

    conn.close()
    return {"years": rebuilt, "ingested": ingested, "db": str(DB_PATH)}


def open_conn():
    conn = connect(DB_PATH)
    ensure_monthly_schema(conn)
    return conn


def distinct_values(conn, field: str, year: int) -> list[str]:
    allowed = {
        "brand", "segment", "body_type", "powertrain", "powertrain_group",
        "import_type", "origin_country", "brand_origin",
    }
    if field not in allowed:
        raise ValueError(field)
    rows = conn.execute(
        f"SELECT DISTINCT {field} AS v FROM dim_unit "
        "WHERE catalog_year=? AND grain='MODEL' AND "
        f"{field} IS NOT NULL ORDER BY {field}",
        (year,),
    )
    return [str(r["v"]) for r in rows if r["v"] not in (None, "")]


def unit_options(conn, year: int, grain: str) -> dict[str, str]:
    rows = conn.execute(
        "SELECT unit_id, brand, model, variant FROM dim_unit "
        "WHERE catalog_year=? AND grain=? ORDER BY brand, model, variant",
        (year, grain),
    ).fetchall()
    out: dict[str, str] = {}
    for row in rows:
        parts = [row["brand"] or "?", row["model"] or row["unit_id"]]
        if grain == "VARIANT":
            parts.append(row["variant"] or "(variant)")
        label = " — ".join(str(p) for p in parts)
        if label in out:
            label += f"  [{row['unit_id']}]"
        out[label] = row["unit_id"]
    return out


def frame(result: cube.CubeResult) -> pd.DataFrame:
    df = pd.DataFrame(result.rows)
    if not df.empty:
        for dim in result.dimensions:
            if dim in df.columns:
                df[dim] = df[dim].fillna("UNKNOWN").astype(str)
    return df


def add_filter(filters: dict[str, object], key: str, value: str) -> None:
    if value != "ALL":
        filters[key] = value


def composition_chart(df: pd.DataFrame, dimension: str, chart_type: str):
    visual = df.copy()
    if chart_type == "Pie" and len(visual) > 10:
        visual = visual.sort_values("units", ascending=False)
        top = visual.head(9).copy()
        rest = float(visual.iloc[9:]["units"].sum())
        if rest:
            top = pd.concat([
                top,
                pd.DataFrame([{dimension: "Other", "units": rest}]),
            ], ignore_index=True)
        visual = top
    if chart_type == "Pie":
        return px.pie(visual, names=dimension, values="units")
    visual = visual.sort_values("units", ascending=True)
    return px.bar(visual, x="units", y=dimension, orientation="h")


st.set_page_config(page_title="TDR Vehicle Market", layout="wide")

try:
    boot = bootstrap_database()
except Exception as exc:
    st.error("เปิดฐานข้อมูลไม่สำเร็จ")
    st.exception(exc)
    st.stop()

conn = open_conn()
periods = [r["period"] for r in conn.execute(
    "SELECT DISTINCT period FROM fact_registration ORDER BY period"
)]

st.title("TDR Vehicle Market")
st.caption(f"Local database: {DB_PATH}")

if boot.get("ingested"):
    st.success("โหลด DLT ใหม่: " + ", ".join(boot["ingested"]))

if not periods:
    st.warning("ยังไม่มียอดจดทะเบียนในฐานข้อมูล แต่ Monthly Editor ยังใช้ได้")
    catalog_years = available_years(DATA_DIR)
    fallback_year = catalog_years[-1]
    selected_period = f"{fallback_year}-01"
else:
    selected_period = st.sidebar.selectbox(
        "เดือนข้อมูล", periods, index=len(periods) - 1,
    )

selected_year = int(selected_period[:4])

if st.sidebar.button("Reload catalog / raw data"):
    bootstrap_database.clear()
    st.rerun()

registration = st.sidebar.selectbox("ประเภทรถ DLT", ["ALL", "RY1", "RY2", "RY3"])
brand_values = distinct_values(conn, "brand", selected_year)
brand = st.sidebar.selectbox("ยี่ห้อ", ["ALL", *brand_values])
segment = st.sidebar.selectbox("Segment", ["ALL", "A", "B", "C", "D", "E", "F"])
body_family = st.sidebar.selectbox(
    "Body family",
    ["ALL", "SUV", "SEDAN", "HATCHBACK", "MPV", "PICKUP", "COUPE",
     "WAGON", "VAN", "TRUCK", "OTHER"],
)
powertrain = st.sidebar.selectbox(
    "Powertrain",
    ["ALL", "ICE", "MHEV", "HEV", "PHEV", "REEV", "BEV", "FCEV",
     "MIXED", "UNKNOWN"],
)
price_band = st.sidebar.selectbox(
    "Price band",
    ["ALL", "UNDER_1M", "1M_TO_2M", "2M_PLUS", "MIXED", "UNKNOWN"],
)
import_type = st.sidebar.selectbox(
    "CBU / CKD", ["ALL", "CBU", "CKD", "SKD", "MIXED", "UNKNOWN"]
)
origin_values = distinct_values(conn, "origin_country", selected_year)
origin = st.sidebar.selectbox("ประเทศผลิต", ["ALL", *origin_values])
include_all_scopes = st.sidebar.checkbox("รวม NICHE / GREY / COMMERCIAL", value=False)
scopes = "all" if include_all_scopes else None

filters: dict[str, object] = {}
add_filter(filters, "fact_registration_type", registration)
add_filter(filters, "brand", brand)
add_filter(filters, "segment", segment)
add_filter(filters, "body_family", body_family)
add_filter(filters, "powertrain", powertrain)
add_filter(filters, "price_band", price_band)
add_filter(filters, "import_type", import_type)
add_filter(filters, "origin_country", origin)

TAB_DASH, TAB_EDIT, TAB_HISTORY = st.tabs([
    "Dashboard", "Monthly State Editor", "History / Audit",
])

with TAB_DASH:
    if not periods:
        st.info("ใส่ DLT CSV ก่อนแล้วกราฟจะขึ้นอัตโนมัติ")
    else:
        total = cube.run(
            conn, [], filters=filters,
            period_from=selected_period, period_to=selected_period,
            scopes=scopes,
        )
        brands_result = cube.run(
            conn, ["brand"], filters=filters,
            period_from=selected_period, period_to=selected_period,
            scopes=scopes,
        )
        models_result = cube.run(
            conn, ["model"], filters=filters,
            period_from=selected_period, period_to=selected_period,
            scopes=scopes,
        )
        review = conn.execute(
            "SELECT COALESCE(SUM(units),0) AS u FROM ingest_review "
            "WHERE period=? AND status='open' AND best_guess IS NULL",
            (selected_period,),
        ).fetchone()["u"]

        a, b, c, d = st.columns(4)
        a.metric("Canonical registrations", f"{total.total_units:,.0f}")
        b.metric("Brands", f"{len(brands_result.rows):,}")
        c.metric("Models", f"{len(models_result.rows):,}")
        d.metric("Unmatched / review", f"{review or 0:,.0f}")

        st.subheader("Automatic chart")
        dimension_labels = {
            "Brand": "brand",
            "Model": "model",
            "Segment": "segment",
            "Body family": "body_family",
            "SUV type": "suv_type",
            "Powertrain": "powertrain",
            "Powertrain group": "powertrain_group",
            "Price band": "price_band",
            "CBU / CKD": "import_type",
            "Production country": "origin_country",
            "Brand origin": "brand_origin",
        }
        x1, x2 = st.columns(2)
        label = x1.selectbox("Group by", list(dimension_labels), index=0)
        chart_type = x2.selectbox("Chart", ["Bar", "Pie"])
        dimension = dimension_labels[label]
        result = cube.run(
            conn, [dimension], filters=filters,
            period_from=selected_period, period_to=selected_period,
            scopes=scopes,
        )
        df = frame(result)
        if df.empty:
            st.info("ไม่มีข้อมูลตาม filter นี้")
        else:
            st.plotly_chart(
                composition_chart(df, dimension, chart_type),
                use_container_width=True,
            )
            show = df[[dimension, "units", "share"]].copy()
            show["share"] = show["share"] * 100
            st.dataframe(show, use_container_width=True, hide_index=True)
            st.download_button(
                "Download CSV",
                data=show.to_csv(index=False).encode("utf-8-sig"),
                file_name=f"{selected_period}_{dimension}.csv",
                mime="text/csv",
            )

        st.subheader("Top models")
        top_models = frame(cube.run(
            conn, ["model"], filters=filters,
            period_from=selected_period, period_to=selected_period,
            scopes=scopes, limit=20,
        ))
        if not top_models.empty:
            top_models = top_models.sort_values("units", ascending=True)
            st.plotly_chart(
                px.bar(top_models, x="units", y="model", orientation="h"),
                use_container_width=True,
            )

        st.subheader("Monthly trend")
        end_index = periods.index(selected_period)
        start_period = periods[max(0, end_index - 11)]
        trend = frame(cube.timeseries(
            conn, [], bucket="period", filters=filters,
            period_from=start_period, period_to=selected_period,
            scopes=scopes,
        ))
        if not trend.empty:
            st.plotly_chart(
                px.line(trend, x="period", y="units", markers=True),
                use_container_width=True,
            )

with TAB_EDIT:
    years = available_years(DATA_DIR)
    default_year_index = years.index(selected_year) if selected_year in years else len(years) - 1
    e1, e2, e3 = st.columns(3)
    edit_year = e1.selectbox("Catalog year", years, index=default_year_index)
    default_month = int(selected_period[5:7]) if selected_period[:4] == str(edit_year) else 1
    edit_month_number = e2.selectbox(
        "Effective month", list(range(1, 13)), index=default_month - 1,
        format_func=lambda n: f"{n:02d}",
    )
    edit_grain = e3.selectbox("Level", ["MODEL", "VARIANT"])
    edit_month = f"{edit_year}-{edit_month_number:02d}"

    options = unit_options(conn, edit_year, edit_grain)
    if not options:
        st.warning("ไม่มี unit ใน catalog ปีนี้")
    else:
        unit_label = st.selectbox("Vehicle", list(options))
        unit_id = options[unit_label]
        state = effective_state(conn, unit_id, edit_month, grain=edit_grain)
        sources = state.get("effective_months", {})
        current = pd.DataFrame([
            {"field": "price_thb", "value": state.get("price_thb"),
             "from": sources.get("price_thb", "catalog")},
            {"field": "origin_country", "value": state.get("origin_country"),
             "from": sources.get("origin_country", "catalog")},
            {"field": "import_type", "value": state.get("import_type"),
             "from": sources.get("import_type", "catalog")},
        ])
        # Arrow requires one concrete dtype per column. This table intentionally
        # mixes a numeric price with text country/import values, so render the
        # reader-facing value column as text instead of relying on coercion.
        current["value"] = current["value"].map(
            lambda v: "" if v is None else str(v)
        )
        st.caption(f"Effective state at {edit_month}")
        st.dataframe(current, use_container_width=True, hide_index=True)

        field = st.radio(
            "Field to change",
            ["ราคา", "ประเทศผลิต", "CBU / CKD / SKD"],
            horizontal=True,
        )
        kwargs: dict[str, object] = {}
        if field == "ราคา":
            value = st.text_input(
                "New price (THB)", placeholder=str(state.get("price_thb") or "")
            )
            if value.strip():
                kwargs["price_thb"] = value
        elif field == "ประเทศผลิต":
            countries = sorted(KNOWN_ORIGIN_COUNTRIES)
            current_country = str(state.get("origin_country") or "UNKNOWN")
            if current_country not in countries:
                countries.append(current_country)
            value = st.selectbox(
                "New production country",
                countries,
                index=countries.index(current_country),
            )
            kwargs["origin_country"] = value
        else:
            imports = ["CBU", "CKD", "SKD", "UNKNOWN"]
            current_import = str(state.get("import_type") or "UNKNOWN")
            index = imports.index(current_import) if current_import in imports else 0
            value = st.selectbox("New import type", imports, index=index)
            kwargs["import_type"] = value

        reason = st.text_input("Reason / source note")
        note = st.text_input("Optional note")
        if st.button("Save monthly change", type="primary"):
            if not kwargs:
                st.error("ใส่ค่าที่จะเปลี่ยนก่อน")
            else:
                if note.strip():
                    kwargs["note"] = note.strip()
                try:
                    changed = set_state(
                        conn, unit_id, edit_month, grain=edit_grain,
                        reason=reason.strip() or None, **kwargs,
                    )
                    if changed:
                        st.success("บันทึกแล้ว")
                        st.rerun()
                    else:
                        st.info("ค่าเหมือนเดิม ไม่มีอะไรต้องแก้")
                except Exception as exc:
                    st.error(str(exc))

        h = pd.DataFrame(history(conn, unit_id, grain=edit_grain))
        if not h.empty:
            st.subheader("Change points ของคันนี้")
            st.dataframe(h, use_container_width=True, hide_index=True)

with TAB_HISTORY:
    years = available_years(DATA_DIR)
    h1, h2 = st.columns(2)
    history_year = h1.selectbox("Year", years, index=len(years) - 1, key="history_year")
    history_grain = h2.selectbox("Level", ["MODEL", "VARIANT"], key="history_grain")
    h_options = unit_options(conn, history_year, history_grain)
    if h_options:
        h_label = st.selectbox("Vehicle", list(h_options), key="history_vehicle")
        h_unit = h_options[h_label]
        changes = history(conn, h_unit, grain=history_grain)
        audits = audit_log(conn, h_unit, grain=history_grain)

        st.subheader("Vehicle history")
        if changes:
            st.dataframe(pd.DataFrame(changes), use_container_width=True, hide_index=True)
            delete_month = st.selectbox(
                "Delete mistaken change-point",
                [r["effective_month"] for r in changes],
            )
            delete_reason = st.text_input("Delete reason")
            if st.button("Delete selected change-point"):
                delete_change(
                    conn, h_unit, delete_month, grain=history_grain,
                    reason=delete_reason.strip() or "deleted in web editor",
                )
                st.success("ลบ change-point แล้ว; audit ยังอยู่")
                st.rerun()
        else:
            st.info("ยังไม่มี monthly change-point สำหรับคันนี้")

        st.subheader("Audit trail")
        if audits:
            st.dataframe(
                pd.DataFrame(audits[::-1]),
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.info("ยังไม่มี audit")

    st.subheader("Latest global edits")
    global_audit = audit_log(conn)
    if global_audit:
        st.dataframe(
            pd.DataFrame(global_audit[-200:][::-1]),
            use_container_width=True,
            hide_index=True,
        )

conn.close()
