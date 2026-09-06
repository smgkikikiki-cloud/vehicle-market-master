"""Shared Streamlit pieces for the pages.

Lives beside the pages rather than inside ``vehreg`` because it is presentation:
the package stays importable without Streamlit installed.
"""

from __future__ import annotations

from typing import Callable, Iterable, Mapping, Sequence

import streamlit as st

#: The value every scope control starts on, meaning "do not narrow".
ANY = "ALL"

#: Chips per row. Streamlit columns do not wrap, so rows are made by hand.
_PER_ROW = 5


def active_filters(chosen: Mapping[str, tuple[str, str]],
                   any_value: str = ANY) -> dict[str, tuple[str, str]]:
    """The filters that are actually narrowing something.

    ``chosen`` maps a session-state key to ``(label, value)``. Anything still on
    the "any" value is not a filter, it is the absence of one.
    """
    return {key: (label, value) for key, (label, value) in chosen.items()
            if value not in (any_value, None, "")}


def clear_keys(keys: Iterable[str], defaults: Mapping[str, object]) -> None:
    """Put widget state back to its default.

    Two things about this are not obvious, and both were found by clicking the
    button rather than by reading the docs. Deleting the key does not reset the
    control: the query stops using the filter while the sidebar goes on showing
    the old value, so the page and the sidebar disagree. And writing the value
    from inside the click handler's own script run raises
    ``StreamlitWidgetAlreadyInstantiatedError``, because the sidebar widget was
    already built further up the page. So this runs as an ``on_click``
    callback, which Streamlit executes before the next run builds anything.
    """
    for key in keys:
        if key in defaults:
            st.session_state[key] = defaults[key]


def _reset(keys: Sequence[str], defaults: Mapping[str, object],
           on_change: Callable[[], None] | None) -> None:
    clear_keys(keys, defaults)
    if on_change:
        on_change()


def filter_bar(chosen: Mapping[str, tuple[str, str]],
               *, any_value: str = ANY,
               defaults: Mapping[str, object] | None = None,
               extra: Sequence[str] = (),
               ignored: Iterable[str] = (),
               on_change: Callable[[], None] | None = None) -> None:
    """Say which filters are on, and let them be taken off from here.

    Every number on these pages is silently scoped by controls that live in a
    sidebar the reader may not have opened. A filter left on from ten minutes
    ago reads as a fact about the market. So the active ones are named where
    the numbers are, and each one can be removed with the click that shows it.

    Nothing is drawn when nothing is filtered: an empty bar would be furniture.

    ``ignored`` names controls this page sets aside — the admin deck drops the
    scope it is ranking by, so that a brand ranking still has other brands to
    rank against. Those chips are still shown, because the control is not on
    ALL and hiding it would be its own lie, but they say they are not in force.
    """
    active = active_filters(chosen, any_value)
    if not active:
        return

    # Every chip resets to the "any" value unless the caller says otherwise;
    # the scope checkbox, for one, resets to False rather than to "ALL".
    resets: dict[str, object] = {key: any_value for key in chosen}
    resets.update({key: any_value for key in extra})
    resets.update(defaults or {})

    ignored = set(ignored)
    in_force = [key for key in active if key not in ignored]
    st.caption(
        f"กรองอยู่ {len(in_force)} อย่าง — กดเพื่อเอาออก"
        if len(in_force) == len(active)
        else f"กรองอยู่ {len(in_force)} อย่าง (อีก {len(active) - len(in_force)} "
             "ตัวไม่มีผลในหน้านี้) — กดเพื่อเอาออก"
    )
    items = list(active.items())
    for start in range(0, len(items), _PER_ROW):
        row = items[start:start + _PER_ROW]
        # A trailing spacer keeps a short row's chips at their natural width
        # instead of stretching one chip across the page.
        columns = st.columns(_PER_ROW + 1)
        for column, (key, (label, value)) in zip(columns, row):
            with column:
                off = key in ignored
                # A word here rather than a mark would be clearer, but the
                # chip is a button in a fixed column and the label truncates.
                # The caption above and the tooltip carry the explanation.
                caption = (f"⊘ {label}: {value}" if off
                           else f"{label}: {value}  ✕")
                helptext = ("หน้านี้ไม่ใช้ตัวกรองนี้ เพราะกำลังจัดอันดับด้วยมิตินี้ "
                            "— กดเพื่อเอาออก" if off else "เอาตัวกรองนี้ออก")
                st.button(caption, key=f"chip_{key}", help=helptext,
                          width="stretch", on_click=_reset,
                          args=([key], resets, on_change))

    if len(active) > 1:
        st.button("ล้างตัวกรองทั้งหมด", key="clear_all_filters",
                  on_click=_reset, args=([*active, *extra], resets, on_change))


def scope_caption(shown: float, all_scopes: float,
                  month_total: float | None = None) -> str:
    """Explain the gap between the number on screen and the month DLT published.

    Two things shrink a headline figure and neither is visible in it. The scope
    setting drops niche, grey-import and commercial registrations, which is the
    right default for a market read and about 2,500 units a month. And volume
    the matcher could not attribute to a model does not reach an analysis that
    reads model grain. A reader comparing this screen with a DLT press release
    finds a number that is smaller and no reason why.

    ``month_total`` is only meaningful when nothing else is filtered, so the
    caller passes None once any scope is on: comparing a filtered figure with
    a whole month would be a worse comparison than none.
    """
    parts = [f"แสดง {shown:,.0f} คัน"]
    excluded = round(all_scopes - shown)
    if excluded > 0:
        parts.append(f"ตัดกลุ่ม NICHE / GREY / COMMERCIAL ออก {excluded:,.0f}")
    if month_total is not None:
        unattributed = round(month_total - all_scopes)
        parts.append(f"ยอดทั้งเดือนในฐานข้อมูล {month_total:,.0f}")
        if unattributed > 0:
            parts.append(f"ในนั้น {unattributed:,.0f} คันยังไม่ถูกจับเข้ารุ่น")
    return " · ".join(parts)


def _slug(text: str) -> str:
    keep = [c if (c.isalnum() or c in "-_") else "-" for c in str(text).strip()]
    return "".join(keep).strip("-").lower() or "table"


def _for_file(frame):
    """Make the table read the way the screen reads it.

    Two differences otherwise, and both make the file look like a different
    dataset from the one on screen: a share renders as 32.71437933757919 where
    the page says 32.71%, and a whole count renders as 19468.0. Percentages and
    point changes are rounded to the two decimals the page displays; counts
    that are whole become integers, which loses nothing.
    """
    out = frame.copy()
    for column in out.columns:
        name = str(column)
        if out[column].dtype.kind != "f":
            continue
        if name.endswith("_pct") or name.endswith("_pp"):
            out[column] = out[column].round(2)
        elif out[column].dropna().mod(1).eq(0).all():
            out[column] = out[column].astype("Int64")
    return out


def download_table(frame, *, stem: str, period: str, label: str = "ดาวน์โหลด CSV",
                   context: Mapping[str, str] | None = None,
                   key: str | None = None) -> None:
    """A download button for a table on screen.

    The file name carries the period and the active scope, because a folder of
    downloads called ``data.csv`` is a folder of files nobody can tell apart a
    week later. The CSV itself stays clean — no preamble rows — so it opens in
    a spreadsheet and parses in a script without special handling.

    ``utf-8-sig`` because Excel on Windows reads Thai as mojibake without the
    byte-order mark, which is where these files are going.
    """
    if frame is None or getattr(frame, "empty", True):
        return
    bits = [stem, period]
    for value in (context or {}).values():
        if value and value != ANY:
            bits.append(str(value))
    name = "_".join(_slug(bit) for bit in bits if bit) + ".csv"
    st.download_button(
        label, data=_for_file(frame).to_csv(index=False).encode("utf-8-sig"),
        file_name=name, mime="text/csv",
        key=key or f"dl_{_slug(name)}", width="content",
    )
