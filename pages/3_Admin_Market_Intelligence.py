from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from vehreg import cube
from vehreg.db import connect
from vehreg.market_metrics import (
    compare_share_rows,
    missing_periods,
    previous_window,
    rolling_window,
    shift_period,
    window_is_complete,
    ytd_window,
)
from vehreg.web_bootstrap import bootstrap_database, database_path

st.set_page_config(page_title="Admin Market Intelligence | TDR", layout="wide")
st.title("Admin Market Intelligence")
st.caption(
    "Internal analyst deck. DLT first-registration counts are registration activity, "
    "not a monthly retail-sales ledger. Read raw volumes descriptively; use share and "
    "relative position for competitive movement."
)


@st.cache_resource
def boot() -> dict[str, object]:
    return bootstrap_database()


def distinct_model_values(conn, field: str, year: int) -> list[str]:
    allowed = {"brand", "origin_country"}
    if field not in allowed:
        raise ValueError(field)
    rows = conn.execute(
        f"SELECT DISTINCT {field} AS value FROM dim_unit "
        "WHERE catalog_year=? AND grain='MODEL' AND "
        f"{field} IS NOT NULL ORDER BY {field}",
        (year,),
    ).fetchall()
    return [str(row["value"]) for row in rows if row["value"] not in (None, "")]


def add_filter(filters: dict[str, object], key: str, value: str) -> None:
    if value != "ALL":
        filters[key] = value


def comparison_filters(filters: dict[str, object], dimension: str) -> dict[str, object]:
    """Keep the grouping field open so its shares have a useful denominator."""
    out = dict(filters)
    out.pop(dimension, None)
    return out


def market_rows(
    conn,
    dimension: str,
    filters: dict[str, object],
    period_from: str,
    period_to: str,
    scopes,
) -> tuple[list[dict[str, object]], float]:
    group_by = ["brand", "model"] if dimension == "model" else [dimension]
    result = cube.run(
        conn,
        group_by,
        filters=filters,
        period_from=period_from,
        period_to=period_to,
        scopes=scopes,
    )
    rows: list[dict[str, object]] = []
    for raw in result.rows:
        row = dict(raw)
        if dimension == "model":
            brand = str(row.get("brand") or "UNKNOWN")
            model = str(row.get("model") or "UNKNOWN")
            entity = f"{brand} {model}"
        else:
            entity = str(row.get(dimension) or "UNKNOWN")
        row["entity"] = entity
        rows.append(row)
    return rows, float(result.total_units)


def current_table(rows: list[dict[str, object]]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame()
    data = pd.DataFrame(rows)
    data = data.sort_values(["units", "entity"], ascending=[False, True]).reset_index(drop=True)
    data.insert(0, "rank", range(1, len(data) + 1))
    data["share_pct"] = data["share"].astype(float) * 100.0
    return data[["rank", "entity", "units", "share_pct"]]


def movement_table(
    previous_rows: list[dict[str, object]],
    current_rows_: list[dict[str, object]],
) -> pd.DataFrame:
    rows = compare_share_rows(previous_rows, current_rows_, "entity")
    if not rows:
        return pd.DataFrame()
    data = pd.DataFrame(rows)
    data["share_previous_pct"] = data["share_previous"] * 100.0
    data["share_current_pct"] = data["share_current"] * 100.0
    return data[
        [
            "entity",
            "units_previous",
            "units_current",
            "units_change",
            "share_previous_pct",
            "share_current_pct",
            "share_change_pp",
        ]
    ]


def render_movement(
    conn,
    *,
    title: str,
    previous_from: str,
    previous_to: str,
    current_from: str,
    current_to: str,
    dimension: str,
    filters: dict[str, object],
    scopes,
) -> None:
    previous_rows, previous_total = market_rows(
        conn, dimension, filters, previous_from, previous_to, scopes
    )
    current_rows_, current_total = market_rows(
        conn, dimension, filters, current_from, current_to, scopes
    )
    data = movement_table(previous_rows, current_rows_)
    st.subheader(title)
    st.caption(
        f"Previous: {previous_from} → {previous_to} ({previous_total:,.0f} registrations) · "
        f"Current: {current_from} → {current_to} ({current_total:,.0f} registrations)"
    )
    if data.empty:
        st.info("ไม่มีข้อมูลสำหรับการเปรียบเทียบนี้")
        return

    gainers = data.sort_values(
        ["share_change_pp", "units_current"], ascending=[False, False]
    ).head(10)
    losers = data.sort_values(
        ["share_change_pp", "units_current"], ascending=[True, False]
    ).head(10)

    left, right = st.columns(2)
    with left:
        st.markdown("**Share gainers**")
        chart = gainers.sort_values("share_change_pp", ascending=True)
        st.plotly_chart(
            px.bar(
                chart,
                x="share_change_pp",
                y="entity",
                orientation="h",
                labels={"share_change_pp": "Share change (pp)", "entity": ""},
            ),
            use_container_width=True,
        )
    with right:
        st.markdown("**Share losers**")
        chart = losers.sort_values("share_change_pp", ascending=False)
        st.plotly_chart(
            px.bar(
                chart,
                x="share_change_pp",
                y="entity",
                orientation="h",
                labels={"share_change_pp": "Share change (pp)", "entity": ""},
            ),
            use_container_width=True,
        )

    st.dataframe(
        data.sort_values(
            ["share_change_pp", "units_current"], ascending=[False, False]
        ),
        use_container_width=True,
        hide_index=True,
        column_config={
            "units_previous": st.column_config.NumberColumn(format="%.0f"),
            "units_current": st.column_config.NumberColumn(format="%.0f"),
            "units_change": st.column_config.NumberColumn(format="%+.0f"),
            "share_previous_pct": st.column_config.NumberColumn(format="%.2f%%"),
            "share_current_pct": st.column_config.NumberColumn(format="%.2f%%"),
            "share_change_pp": st.column_config.NumberColumn(format="%+.2f pp"),
        },
    )


try:
    state = boot()
except Exception as exc:
    st.error("เปิดฐานข้อมูลไม่สำเร็จ")
    st.exception(exc)
    st.stop()

conn = connect(database_path())
periods = [
    str(row["period"])
    for row in conn.execute("SELECT DISTINCT period FROM fact_registration ORDER BY period")
]
if not periods:
    st.warning("ยังไม่มี registration facts ในฐานข้อมูล")
    conn.close()
    st.stop()

selected_period = st.sidebar.selectbox("เดือนข้อมูล", periods, index=len(periods) - 1)
selected_year = int(selected_period[:4])

grouping_labels = {
    "Brand": "brand",
    "Model": "model",
    "Segment": "segment",
    "Body family": "body_family",
    "Powertrain": "powertrain",
    "Powertrain group": "powertrain_group",
    "Price band": "price_band",
    "CBU / CKD": "import_type",
    "Production country": "origin_country",
    "Brand origin": "brand_origin",
}
grouping_label = st.sidebar.selectbox("Compare / rank by", list(grouping_labels))
dimension = grouping_labels[grouping_label]

registration = st.sidebar.selectbox("ประเภทรถ DLT", ["ALL", "RY1", "RY2", "RY3"])
brand_values = distinct_model_values(conn, "brand", selected_year)
brand = st.sidebar.selectbox("Brand scope", ["ALL", *brand_values])
segment = st.sidebar.selectbox("Segment scope", ["ALL", "A", "B", "C", "D", "E", "F"])
body_family = st.sidebar.selectbox(
    "Body scope",
    ["ALL", "SUV", "SEDAN", "HATCHBACK", "MPV", "PICKUP", "COUPE", "WAGON", "VAN", "TRUCK", "OTHER"],
)
powertrain = st.sidebar.selectbox(
    "Powertrain scope",
    ["ALL", "ICE", "MHEV", "HEV", "PHEV", "REEV", "BEV", "FCEV", "MIXED", "UNKNOWN"],
)
price_band = st.sidebar.selectbox(
    "Price scope",
    ["ALL", "UNDER_1M", "1M_TO_2M", "2M_PLUS", "MIXED", "UNKNOWN"],
)
import_type = st.sidebar.selectbox(
    "CBU / CKD scope", ["ALL", "CBU", "CKD", "SKD", "MIXED", "UNKNOWN"]
)
origin_values = distinct_model_values(conn, "origin_country", selected_year)
origin = st.sidebar.selectbox("Production country scope", ["ALL", *origin_values])
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
analysis_filters = comparison_filters(filters, dimension)

if dimension in filters:
    st.info(
        f"{grouping_label} scope ถูกเปิดออกอัตโนมัติในหน้านี้เพื่อให้เปรียบเทียบ "
        f"{grouping_label} กับคู่แข่งได้จริง; filter อื่นยังมีผลตามปกติ"
    )

st.warning(
    "Interpretation rule: raw monthly registration volumes may move with registration timing "
    "and seasonality. This deck does not label MoM unit changes as sales growth. "
    "Competitive movement is ranked by market-share change within the same filtered market."
)

tab_structure, tab_movement, tab_ytd, tab_raw = st.tabs(
    ["Market structure", "Share movement", "YTD position", "Raw registration trend"]
)

with tab_structure:
    rows, total = market_rows(
        conn,
        dimension,
        analysis_filters,
        selected_period,
        selected_period,
        scopes,
    )
    table = current_table(rows)
    a, b, c = st.columns(3)
    a.metric("Registrations in scope", f"{total:,.0f}")
    b.metric(grouping_label + " entities", f"{len(table):,}")
    if not table.empty:
        c.metric(
            "Leader share",
            f"{table.iloc[0]['share_pct']:.2f}%",
            help=str(table.iloc[0]["entity"]),
        )
    else:
        c.metric("Leader share", "—")

    if table.empty:
        st.info("ไม่มีข้อมูลตาม scope นี้")
    else:
        visual = table.head(30).sort_values("share_pct", ascending=True)
        st.plotly_chart(
            px.bar(
                visual,
                x="share_pct",
                y="entity",
                orientation="h",
                labels={"share_pct": "Market share (%)", "entity": ""},
            ),
            use_container_width=True,
        )
        st.dataframe(
            table,
            use_container_width=True,
            hide_index=True,
            column_config={
                "units": st.column_config.NumberColumn("Registrations", format="%.0f"),
                "share_pct": st.column_config.NumberColumn("Share", format="%.2f%%"),
            },
        )

with tab_movement:
    previous_month = shift_period(selected_period, -1)
    same_month_last_year = shift_period(selected_period, -12)
    current_3m_from, current_3m_to = rolling_window(selected_period, 3)
    previous_3m_from, previous_3m_to = previous_window(selected_period, 3)

    compare_mode = st.radio(
        "Comparison window",
        ["Previous month", "Rolling 3M vs previous 3M", "Same month last year"],
        horizontal=True,
    )

    if compare_mode == "Previous month":
        if previous_month not in periods:
            st.info(f"ไม่มีข้อมูล {previous_month}; ไม่สร้าง MoM comparison จากเดือนที่หาย")
        else:
            render_movement(
                conn,
                title="Share movement vs previous month",
                previous_from=previous_month,
                previous_to=previous_month,
                current_from=selected_period,
                current_to=selected_period,
                dimension=dimension,
                filters=analysis_filters,
                scopes=scopes,
            )
    elif compare_mode == "Rolling 3M vs previous 3M":
        needed_from = previous_3m_from
        needed_to = current_3m_to
        if not window_is_complete(periods, needed_from, needed_to):
            missing = ", ".join(missing_periods(periods, needed_from, needed_to))
            st.info("Rolling comparison ถูกปิดเพราะเดือนใน window ไม่ครบ: " + missing)
        else:
            render_movement(
                conn,
                title="Rolling 3-month share movement",
                previous_from=previous_3m_from,
                previous_to=previous_3m_to,
                current_from=current_3m_from,
                current_to=current_3m_to,
                dimension=dimension,
                filters=analysis_filters,
                scopes=scopes,
            )
    else:
        if same_month_last_year not in periods:
            st.info(
                f"ไม่มีข้อมูลเดือนเดียวกันของปีก่อน ({same_month_last_year}); "
                "ไม่สร้าง YoY จากข้อมูลที่ไม่ครบ"
            )
        else:
            render_movement(
                conn,
                title="Same-month year-over-year share movement",
                previous_from=same_month_last_year,
                previous_to=same_month_last_year,
                current_from=selected_period,
                current_to=selected_period,
                dimension=dimension,
                filters=analysis_filters,
                scopes=scopes,
            )

with tab_ytd:
    ytd_from, ytd_to = ytd_window(selected_period)
    if not window_is_complete(periods, ytd_from, ytd_to):
        missing = ", ".join(missing_periods(periods, ytd_from, ytd_to))
        st.info("YTD ถูกปิดเพราะข้อมูลปีนี้ยังขาดเดือน: " + missing)
    else:
        rows, total = market_rows(
            conn, dimension, analysis_filters, ytd_from, ytd_to, scopes
        )
        table = current_table(rows)
        st.caption(f"YTD {ytd_from} → {ytd_to} · {total:,.0f} registrations")
        if table.empty:
            st.info("ไม่มีข้อมูลตาม scope นี้")
        else:
            st.dataframe(
                table,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "units": st.column_config.NumberColumn("Registrations", format="%.0f"),
                    "share_pct": st.column_config.NumberColumn("YTD share", format="%.2f%%"),
                },
            )

        previous_ytd_from = f"{selected_year - 1:04d}-01"
        previous_ytd_to = f"{selected_year - 1:04d}-{selected_period[5:7]}"
        if window_is_complete(periods, previous_ytd_from, previous_ytd_to):
            render_movement(
                conn,
                title="YTD share change vs prior-year YTD",
                previous_from=previous_ytd_from,
                previous_to=previous_ytd_to,
                current_from=ytd_from,
                current_to=ytd_to,
                dimension=dimension,
                filters=analysis_filters,
                scopes=scopes,
            )
        else:
            missing = ", ".join(
                missing_periods(periods, previous_ytd_from, previous_ytd_to)
            )
            st.caption(
                "Prior-year YTD comparison unavailable because these months are missing: "
                + missing
            )

with tab_raw:
    trend_from = shift_period(selected_period, -11)
    trend = cube.timeseries(
        conn,
        [],
        bucket="period",
        filters=filters,
        period_from=trend_from,
        period_to=selected_period,
        scopes=scopes,
    )
    trend_df = pd.DataFrame(trend.rows)
    st.caption(
        "Descriptive only: this is raw DLT registration activity. "
        "No MoM sales-growth label or automatic demand interpretation is applied."
    )
    if trend_df.empty:
        st.info("ไม่มีข้อมูล trend ตาม scope นี้")
    else:
        expected = pd.DataFrame(
            {"period": [shift_period(trend_from, offset) for offset in range(12)]}
        )
        trend_df = expected.merge(trend_df[["period", "units"]], on="period", how="left")
        st.plotly_chart(
            px.line(trend_df, x="period", y="units", markers=True),
            use_container_width=True,
        )
        st.dataframe(trend_df, use_container_width=True, hide_index=True)

conn.close()
