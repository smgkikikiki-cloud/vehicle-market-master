"""Retail prices: what a car costs today, and the one place to fix it.

The ledger is append-only on purpose -- a number that was published has to stay
auditable -- so this page never overwrites a row. It offers the three things a
person actually needs when a price is wrong or has moved:

    ราคาเปลี่ยน   the old row is given an end date and stays true of its period
    ลงผิด         the old row is marked retracted, with the reason, and stops
                  counting; it is still readable
    เลิกขายราคานี้ an end date with no replacement

Campaign options are shown side by side and never ranked: a cash discount and a
0% finance deal are not comparable, and picking for the reader would be a lie.

The review queue at the bottom is the other half. Prices that only one outlet
reported, or that name a car with no trim yet, are held here rather than
published, and each one says why.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

from vehreg.catalog import Catalog, CatalogError, DATA_DIR, DEFAULT_YEAR
from vehreg.pricing import PriceType, to_conditions_dict
from vehreg.normalize import slug
from vehreg.product import (
    ProductMaster, append_prices, close_price, correct_price, find_price_rows,
    import_trims, save_campaign,
)
from vehreg.taxonomy import Powertrain
from vehreg import pricefeed

st.set_page_config(page_title="ราคา | TDR", layout="wide")
st.title("ราคาขายปลีก")
st.caption(
    "ราคาทุกตัวผูกกับ trim และมีที่มา แคมเปญเป็นตัวเลขอีกชุด ไม่ทับราคาปกติ "
    "แก้ราคาที่นี่ได้ แต่ของเดิมไม่ถูกลบ — มันถูกปิดหรือถูกทำเครื่องหมายว่าลงผิด พร้อมเหตุผล"
)

YEAR = DEFAULT_YEAR
FEED = pricefeed.feed_dir(DATA_DIR, YEAR)


def reload_master() -> ProductMaster:
    st.cache_resource.clear()
    return load_master()


@st.cache_resource
def load_master() -> ProductMaster:
    return ProductMaster.load(DATA_DIR, YEAR)


@st.cache_resource(show_spinner="กำลังตรวจคิวราคา…")
def run_batch(name: str):
    """One pass over a harvest batch. Cached: matching rebuilds catalog indexes."""
    documents, claims = pricefeed.load_batch(FEED / name)
    decisions_path = FEED / "review" / "decisions.json"
    decisions = (pricefeed.load_decisions(decisions_path)
                 if decisions_path.exists() else {})
    return pricefeed.run(
        documents, claims, pricefeed.load_sources(DATA_DIR, YEAR),
        Catalog.load(DATA_DIR, YEAR),
        campaigns=ProductMaster.load(DATA_DIR, YEAR).prices.campaigns,
        decisions=decisions)


try:
    master = load_master()
except (CatalogError, Exception) as exc:                    # noqa: BLE001
    st.error("โหลดข้อมูลราคาไม่สำเร็จ")
    st.exception(exc)
    st.stop()

as_of = st.sidebar.date_input("ณ วันที่", value=date.today())
reviewer = st.sidebar.text_input(
    "ผู้ตัดสินใจ", value="", placeholder="ชื่อคนที่กดแก้",
    help="เก็บลงในแถวราคา ทุกการแก้ต้องมีชื่อและเหตุผล")

priced = sorted({record.trim_id for record in master.prices.records})
st.sidebar.caption(f"{len(priced):,} trim มีราคาแล้ว จากทั้งหมด {len(master.catalog.trims):,}")

tab_now, tab_edit, tab_campaign, tab_queue = st.tabs(
    ["ราคาปัจจุบัน", "แก้ราคา", "แคมเปญ", "คิวรอตรวจ"])


# ---------------------------------------------------------------- ราคาปัจจุบัน
with tab_now:
    rows = []
    for trim_id in priced:
        quote = master.prices.campaign_quote(trim_id, as_of=as_of)
        cheapest = min((o["amount_thb"] for o in quote["campaign_options"]),
                       default=None)
        rows.append({
            "trim": trim_id,
            # A blank is not zero and not a guess: this trim has evidence of a
            # price, just not a current list price.
            "ราคาปกติ": f"{quote['list_price_thb']:,}" if quote["list_price_thb"] else "—",
            "แคมเปญ": len(quote["campaign_options"]) or "—",
            "ต่ำสุดของแคมเปญ": f"{cheapest:,}" if cheapest else "—",
            "หลักฐานราคาอื่น": ", ".join(sorted({
                r.price_type.value for r in master.prices.records_for(trim_id)
                if r.price_type is not PriceType.LIST_PRICE})) or "—",
        })
    frame = pd.DataFrame(rows)
    search = st.text_input("ค้นหา trim", placeholder="alphard")
    if search:
        frame = frame[frame["trim"].str.contains(search, case=False, na=False)]
    st.dataframe(frame, width="stretch", hide_index=True)

    chosen = st.selectbox("ดูรายละเอียด", ["—", *frame["trim"].tolist()])
    if chosen != "—":
        quote = master.prices.campaign_quote(chosen, as_of=as_of)
        left, right = st.columns([1, 2])
        left.metric("ราคาปกติ",
                    f"{quote['list_price_thb']:,}" if quote["list_price_thb"] else "—")
        if not quote["campaign_options"]:
            right.info("ไม่มีแคมเปญที่ใช้ได้ ณ วันที่เลือก")
        for option in quote["campaign_options"]:
            with right.container(border=True):
                st.write(f"**{option['option_label'] or option['option_id']}** — "
                         f"{option['amount_thb']:,} บาท"
                         + (f"  (ลด {option['discount_thb']:,} จาก "
                            f"{option['reference_price_thb']:,})"
                            if option["discount_thb"] else ""))
                if option["conditions"].get("text"):
                    st.caption(option["conditions"]["text"])
                terms = {k: v for k, v in option["conditions"].items() if k != "text"}
                if terms:
                    st.caption(" · ".join(f"{k}: {v}" for k, v in terms.items()))
                st.caption(f"ที่มา: {option['source']} — {option['source_ref']}")
        st.caption("แคมเปญคือทางเลือก ไม่ใช่ราคาที่ดีที่สุด ระบบไม่เลือกให้")

        history = master.prices.records_for(chosen, include_retracted=True)
        st.subheader("ประวัติ")
        st.dataframe(pd.DataFrame([{
            "จำนวน": r.amount_thb, "ประเภท": r.price_type.value,
            "เริ่ม": r.effective_from or r.observed_at, "ถึง": r.effective_to,
            "ถอน": r.retracted_at, "เหตุผล": r.retraction_reason or r.notes,
            "ที่มา": r.source, "ผู้ตัดสิน": r.reviewed_by,
        } for r in history]), width="stretch", hide_index=True)


# ------------------------------------------------------------------- แก้ราคา
with tab_edit:
    trim_id = st.selectbox("trim", ["—", *priced], key="edit_trim")
    price_type = st.selectbox("ประเภทราคา", [p.value for p in PriceType],
                              index=0, key="edit_type")
    if trim_id != "—":
        live = [r for r in find_price_rows(DATA_DIR, YEAR, trim_id=trim_id,
                                           price_type=price_type, as_of=as_of)
                if r["live"]]
        if not live:
            st.warning(f"ไม่มี {price_type} ที่ใช้ได้ ณ {as_of} — ใส่ราคาใหม่ด้วย "
                       "`market append-prices`")
        else:
            for row in live:
                st.info(f"ปัจจุบัน {row['row']['amount_thb']:,} บาท "
                        f"(เริ่ม {row['row'].get('effective_from') or row['row'].get('observed_at')}) "
                        f"— {row['row'].get('source', '')}")

            action = st.radio("จะทำอะไร", [
                "ราคาเปลี่ยน (ปิดของเดิม ออกแถวใหม่)",
                "ลงผิด (ถอนของเดิม ออกแถวใหม่)",
                "เลิกขายราคานี้ (ปิดเฉยๆ)",
            ], key="edit_action")
            reason = st.text_input("เหตุผล", key="edit_reason",
                                   placeholder="เช่น pricelist MY2027 / สื่อแก้ตัวเลขวันถัดมา")
            missing = [label for label, value in
                       (("ชื่อผู้ตัดสินใจ (ในแถบซ้าย)", reviewer), ("เหตุผล", reason))
                       if not value.strip()]
            if missing:
                st.warning("ต้องกรอก " + " และ ".join(missing) + " ก่อนจึงจะแก้ได้")

            if action.startswith("เลิกขาย"):
                ends = st.date_input("วันสุดท้ายที่ราคานี้ใช้", value=as_of)
                run = st.button("ปิดราคา", type="primary", disabled=bool(missing))
                call = lambda write: close_price(          # noqa: E731
                    DATA_DIR, YEAR, trim_id=trim_id, price_type=price_type,
                    ends=ends.isoformat(), reason=reason, reviewer=reviewer,
                    as_of=as_of, write=write)
            else:
                mode = "supersede" if action.startswith("ราคาเปลี่ยน") else "retract"
                amount = st.number_input("ราคาใหม่ (บาท)", min_value=1, step=1000,
                                         value=int(live[0]["row"]["amount_thb"]))
                starts = st.date_input(
                    "ราคาใหม่เริ่มวันที่", value=as_of,
                    help="ราคาเปลี่ยน: ต้องหลังวันที่ราคาเดิมเริ่ม")
                source = st.text_input("ที่มา", value="official_oem")
                source_ref = st.text_input("ลิงก์ที่มา", placeholder="https://…")
                run = st.button("บันทึกการแก้", type="primary",
                                disabled=bool(missing))
                call = lambda write: correct_price(        # noqa: E731
                    DATA_DIR, YEAR, trim_id=trim_id, price_type=price_type,
                    amount_thb=int(amount), reason=reason, reviewer=reviewer,
                    mode=mode, effective_from=starts.isoformat(), source=source,
                    source_ref=source_ref, as_of=as_of, write=write)

            if run:
                try:
                    preview = call(False)     # dry run first, always
                    st.write(preview)
                    result = call(True)
                    st.success(result)
                    master = reload_master()
                except CatalogError as exc:
                    # These messages name the fix; show them as they are.
                    st.error(str(exc))


# -------------------------------------------------------------------- แคมเปญ
with tab_campaign:
    campaigns = master.prices.campaigns
    st.write(f"{len(campaigns)} แคมเปญ")
    for campaign in campaigns.values():
        live = campaign.live_on(as_of)
        with st.expander(f"{'🟢' if live else '⚪️'} {campaign.name or campaign.id}"
                         f" — {campaign.brand_id}", expanded=False):
            st.caption(f"`{campaign.id}` · {campaign.starts or '—'} → "
                       f"{campaign.ends or 'ไม่ระบุวันจบ'}")
            if campaign.notes:
                st.caption(campaign.notes)
            for option in campaign.options:
                st.write(f"**{option.id}** — {option.label}")
                st.caption(json.dumps(to_conditions_dict(option.conditions),
                                      ensure_ascii=False))
            st.caption(f"ที่มา: {campaign.source} — {campaign.source_ref}")

    st.subheader("เพิ่ม / แก้แคมเปญ")
    st.caption("วางทั้งก้อน แคมเปญเล็กและเปลี่ยนทั้งชุด จึงแทนที่ทั้งอัน "
               "ปิดแคมเปญไม่ลบราคาที่เคยประกาศ")
    draft = st.text_area("JSON", height=240, key="campaign_json", value=json.dumps({
        "id": "campaign.<brand>.<name>", "brand_id": "", "name": "",
        "starts": None, "ends": None, "source": "", "source_ref": "",
        "options": [{"id": "cash", "label": "", "conditions": {
            "booking_to": None, "quota_units": None,
            "finance_required": False, "text": ""}}],
    }, ensure_ascii=False, indent=2))
    if st.button("บันทึกแคมเปญ", type="primary"):
        try:
            payload = json.loads(draft)
            st.write(save_campaign(DATA_DIR, YEAR, payload, write=False))
            st.success(save_campaign(DATA_DIR, YEAR, payload, write=True))
            master = reload_master()
        except (json.JSONDecodeError, CatalogError) as exc:
            st.error(str(exc))


# --------------------------------------------------------------- คิวรอตรวจ
def decide(claim_ids, *, action, trim_id=None, campaign_id=None, option_id=None,
           notes=""):
    """Record the same answer for every claim behind one price.

    Answers merge, so vouching for a price does not undo the campaign it was
    bound to a moment earlier. Rejecting replaces: it withdraws the answer.
    """
    path = FEED / "review" / "decisions.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    for claim_id in claim_ids:
        entry = {"claim_id": claim_id, "action": action, "reviewer": reviewer,
                 "reviewed_at": date.today().isoformat(), "notes": notes}
        for name, value in (("trim_id", trim_id), ("campaign_id", campaign_id),
                            ("option_id", option_id)):
            if value:
                entry[name] = value
        pricefeed.save_decision(path, entry, write=True,
                                replace=action == "reject")
    run_batch.clear()


def publish_now(batch_name):
    """Re-run with the new decisions and append whatever is now canonical."""
    result = run_batch(batch_name)
    rows = pricefeed.to_price_rows(
        result, observed_at=date.today().isoformat(),
        source_of=pricefeed.load_sources(DATA_DIR, YEAR))
    if not rows:
        return {"added": 0}
    written = append_prices(DATA_DIR, YEAR, {"prices": rows}, write=True)
    reload_master()
    return written


with tab_queue:
    batches = sorted(FEED.glob("batch-*.json"))
    if not batches:
        st.info("ยังไม่มี batch จาก harvester")
    else:
        pick = st.selectbox("batch", [p.name for p in batches],
                            index=len(batches) - 1)
        try:
            result = run_batch(pick)
        except pricefeed.PriceFeedError as exc:
            st.error(str(exc))
            st.stop()

        summary = result.summary()
        columns = st.columns(4)
        columns[0].metric("ขึ้นได้เลย", summary["canonical_offers"])
        columns[1].metric("รอยืนยัน (ภายใน)", summary["provisional"])
        columns[2].metric("รอตรวจ", summary["review_items"])
        columns[3].metric("รุ่นที่ยังไม่มีในระบบ", summary["trim_proposals"])
        st.caption(
            "รอยืนยัน = สื่อเจ้าเดียวรายงาน เห็นได้ในนี้ ไม่ขึ้นหน้าเว็บสาธารณะ "
            f"· วัดเวลาจากวันที่สื่อลง ถึงวันที่ระบบเห็น: "
            f"median {summary.get('discovery_median_hours', '—')} ชม., "
            f"อยู่ใน 24 ชม. {summary.get('within_24h', 0)} จาก "
            f"{summary.get('documents_with_latency', 0)} ชิ้น")

        if not reviewer.strip():
            st.warning("กรอกชื่อผู้ตัดสินใจในแถบซ้ายก่อน จึงจะกดรับหรือปฏิเสธได้")

        if st.button("เขียนราคาที่ผ่านแล้วลง ledger", type="primary",
                     disabled=not result.offers):
            st.success(publish_now(pick))

        def label(item):
            return (f"{item['amount_thb']:,} บาท · {item['price_type']} · "
                    f"{item['trim_id'] or item.get('trim_raw') or '—'} · "
                    f"{', '.join(item['sources'])}")

        st.subheader("รอยืนยัน — สื่อเจ้าเดียว")
        st.caption("กดยืนยันคือมึงรับรองด้วยตัวเอง ว่าแหล่งเดียวพอสำหรับราคานี้")
        for item in result.provisional:
            with st.container(border=True):
                st.write(label(item))
                st.caption(" · ".join(item["urls"]) or "—")
                left, right = st.columns(2)
                if left.button("ยืนยันและเผยแพร่", key=f"pub-{item['claim_ids'][0]}",
                               disabled=not reviewer.strip()):
                    decide(item["claim_ids"], action="publish",
                           notes="ยืนยันด้วยตัวเองจากแหล่งเดียว")
                    st.success(publish_now(pick))
                    st.rerun()
                if right.button("ปฏิเสธ", key=f"rej-{item['claim_ids'][0]}",
                                disabled=not reviewer.strip()):
                    decide(item["claim_ids"], action="reject")
                    st.rerun()

        st.subheader("รอตรวจ")
        fixable = [i for i in result.review if i["trim_id"]]
        st.caption(f"{len(fixable)} รายการที่รู้ trim แล้ว เหลือแค่เหตุผลอื่น · "
                   f"{len(result.review) - len(fixable)} รายการยังไม่รู้ว่าเป็นรุ่นไหน")
        for item in fixable:
            with st.container(border=True):
                st.write(label(item))
                st.caption("ติดที่: " + ", ".join(item["reasons"]))
                if "campaign_without_conditions" in item["reasons"]:
                    names = list(master.prices.campaigns)
                    campaign_id = st.selectbox(
                        "ผูกกับแคมเปญ", ["—", *names],
                        key=f"camp-{item['claim_ids'][0]}")
                    option_id = "—"
                    if campaign_id != "—":
                        option_id = st.selectbox(
                            "ทางเลือก",
                            ["—", *[o.id for o in
                                    master.prices.campaigns[campaign_id].options]],
                            key=f"opt-{item['claim_ids'][0]}")
                    if st.button("ผูกแคมเปญ", key=f"bind-{item['claim_ids'][0]}",
                                 disabled=not reviewer.strip()
                                 or campaign_id == "—" or option_id == "—"):
                        decide(item["claim_ids"], action="accept",
                               campaign_id=campaign_id, option_id=option_id)
                        st.rerun()
                if st.button("ปฏิเสธ", key=f"rejr-{item['claim_ids'][0]}",
                             disabled=not reviewer.strip()):
                    decide(item["claim_ids"], action="reject")
                    st.rerun()

        st.subheader("รุ่นที่ยังไม่มีในระบบ")
        st.caption("ราคากับรุ่นมาด้วยกัน กดรับทีเดียวได้ทั้งคู่ — วันเปิดตัวรุ่นยังไม่มี"
                   "ในแคตตาล็อก นั่นคือความหมายของคำว่าเปิดตัว")
        catalog = Catalog.load(DATA_DIR, YEAR)
        for proposal in result.trim_proposals:
            key = proposal["claim_ids"][0]
            title = (f"{proposal['brand_raw']} {proposal['model_raw']} — "
                     f"{proposal['trim_raw'] or '(ไม่ระบุรุ่นย่อย)'} · "
                     f"{proposal['amount_thb']:,} บาท")
            with st.expander(title):
                brand_id, model_id = pricefeed.match_model(
                    catalog, proposal["brand_raw"], proposal["model_raw"],
                    proposal["trim_raw"])
                if brand_id is None:
                    st.warning("ไม่รู้จักแบรนด์นี้ในแคตตาล็อก ต้องเพิ่มแบรนด์ก่อน")
                    continue
                models = sorted(m for m in catalog.models
                                if m.startswith(brand_id + "."))
                model_choice = st.selectbox(
                    "รุ่น", models,
                    index=models.index(model_id) if model_id in models else 0,
                    key=f"m-{key}")
                generations = [g.id for g in catalog.generations_of(model_choice)]
                if not generations:
                    st.warning("รุ่นนี้ยังไม่มี generation ต้องเพิ่มในแคตตาล็อกก่อน")
                    continue
                generation = st.selectbox("โฉม", generations, key=f"g-{key}")
                name = st.text_input("ชื่อรุ่นย่อย",
                                     value=proposal["trim_raw"], key=f"n-{key}")
                powertrain = st.selectbox(
                    "ระบบขับเคลื่อน",
                    [p.value for p in Powertrain if p is not Powertrain.UNKNOWN],
                    key=f"p-{key}")
                url = st.text_input("ลิงก์ที่มา",
                                    value=", ".join(proposal.get("urls", [])),
                                    key=f"u-{key}")
                ready = bool(reviewer.strip() and name.strip() and url.strip())
                if not ready:
                    st.caption("ต้องมีชื่อผู้ตัดสินใจ ชื่อรุ่นย่อย และลิงก์ที่มา")
                if st.button("สร้าง trim แล้วรับราคา", key=f"mk-{key}",
                             disabled=not ready):
                    local_id = slug(name)[:60]
                    payload = {"generation_id": generation, "trims": [{
                        "id": local_id, "name": name.strip(),
                        "powertrain": powertrain,
                        "source_refs": {"press": [u.strip() for u in url.split(",")
                                                  if u.strip()]},
                        "notes": f"สร้างจากข่าวราคา รับโดย {reviewer}",
                    }]}
                    try:
                        st.write(import_trims(DATA_DIR, YEAR, payload))
                        st.success(import_trims(DATA_DIR, YEAR, payload, write=True))
                        decide(proposal["claim_ids"], action="accept",
                               trim_id=f"{generation}.trim.{local_id}",
                               notes="สร้าง trim พร้อมรับราคา")
                        reload_master()
                        st.rerun()
                    except CatalogError as exc:
                        st.error(str(exc))
