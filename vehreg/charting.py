"""One look for every chart in the deck.

Two complaints drove this module, both from looking at the running app rather
than at the code:

* Long model names came back truncated to ``Aion Hyptec HT …``. Plotly sizes the
  left margin before it knows how wide the tick labels are, and Thai glyphs are
  wider per character than Latin ones, so the names the chart exists to show
  were the first thing cut.
* Every bar was the same blue.

The colour answer is deliberately not "give each bar its own hue". These are
single-series charts: a hue per bar would repeat what bar length already says,
and worse, a filter that drops one brand would repaint every brand below it.
So magnitude charts take one hue stepped by value -- a brand keeps its shade
while its number holds -- and only the charts that carry a *sign* get two hues.

The steps come from a palette validated for contrast and for colour-vision
deficiency; the light-mode ordinal floor is ``#86b6ef``, which is why the ramp
starts there rather than at white.
"""

from __future__ import annotations

from typing import Any, Sequence

import plotly.express as px
import plotly.graph_objects as go

#: Blue, light to dark. Ordinal use on a light surface starts at step 250.
SEQUENTIAL_BLUE: tuple[str, ...] = (
    "#86b6ef", "#6da7ec", "#5598e7", "#3987e5",
    "#2a78d6", "#256abf", "#1c5cab", "#0d366b",
)

#: The diverging pair: cool gain, warm loss, and a grey that reads as "nothing".
POSITIVE = "#2a78d6"
NEGATIVE = "#e34948"
NEUTRAL = "#b6b5ad"

GRID = "rgba(11, 11, 11, 0.08)"
INK_MUTED = "#52514e"


def magnitude_colors(values: Sequence[float]) -> list[str]:
    """A shade per bar, keyed to the value rather than to the row's position.

    Keying on value is what keeps the encoding honest: the darkest bar is the
    biggest number, and a brand that did not move does not change colour just
    because the brand above it dropped out of the filter.
    """
    numbers = [float(v or 0.0) for v in values]
    top = max(numbers, default=0.0)
    if top <= 0:
        return [SEQUENTIAL_BLUE[len(SEQUENTIAL_BLUE) // 2]] * len(numbers)
    last = len(SEQUENTIAL_BLUE) - 1
    return [SEQUENTIAL_BLUE[min(last, int(v / top * last))] for v in numbers]


def _style(fig: go.Figure, *, value_axis: str = "x") -> go.Figure:
    """Recessive frame, and axis labels that are never clipped."""
    fig.update_layout(
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        bargap=0.35,
        margin=dict(l=10, r=30, t=10, b=40),
        font=dict(color=INK_MUTED),
        showlegend=False,
        hoverlabel=dict(font_size=13),
    )
    # automargin is the fix for the truncated names: it measures the rendered
    # labels and grows the margin to fit them instead of cutting them off.
    fig.update_yaxes(automargin=True, showgrid=False, zeroline=False,
                     title_text="", ticksuffix="  ")
    fig.update_xaxes(automargin=True, showgrid=True, gridcolor=GRID,
                     zeroline=False)
    if value_axis == "y":
        fig.update_yaxes(showgrid=True, gridcolor=GRID)
        fig.update_xaxes(showgrid=False)
    return fig


def _rounded(fig: go.Figure) -> go.Figure:
    fig.update_traces(marker_cornerradius=4, cliponaxis=False)
    return fig


def rank_bar(data, *, x: str, y: str, height: int,
             value_format: str = ",.0f", labels: dict[str, str] | None = None,
             hover_unit: str = "") -> go.Figure:
    """Horizontal ranking bar: one hue stepped by value, values written on.

    ``data`` must already be sorted the way it should read, which for a
    horizontal bar means smallest first so the biggest lands on top.
    """
    values = list(data[x])
    text = [format(float(v or 0.0), value_format) for v in values]
    fig = px.bar(
        data, x=x, y=y, orientation="h", height=height,
        labels=labels or {}, text=text,
    )
    fig.update_traces(
        marker_color=magnitude_colors(values),
        textposition="outside",
        textfont=dict(color=INK_MUTED, size=12),
        hovertemplate="%{y}<br>%{x:" + value_format + "}"
                      + (f" {hover_unit}" if hover_unit else "")
                      + "<extra></extra>",
    )
    return _rounded(_style(fig))


def signed_bar(data, *, x: str, y: str, height: int,
               value_format: str = "+.2f", labels: dict[str, str] | None = None,
               hover_unit: str = "") -> go.Figure:
    """Horizontal bar for a value that can go either way.

    Share movement has a sign, and painting gainers and losers the same blue
    threw that away: the reader had to find the heading to know which half of
    the deck they were looking at.
    """
    values = [float(v or 0.0) for v in data[x]]
    text = [format(v, value_format) for v in values]
    fig = px.bar(
        data, x=x, y=y, orientation="h", height=height,
        labels=labels or {}, text=text,
    )
    fig.update_traces(
        marker_color=[POSITIVE if v > 0 else NEGATIVE if v < 0 else NEUTRAL
                      for v in values],
        # "auto" rather than "outside": on a losers chart the longest bar runs
        # left, and its value printed outside landed against the category name
        # -- "Toyota -6.29" read as one string. Long bars take the label inside.
        textposition="auto",
        textfont=dict(color=INK_MUTED, size=12),
        insidetextfont=dict(color="#ffffff", size=12),
        hovertemplate="%{y}<br>%{x:" + value_format + "}"
                      + (f" {hover_unit}" if hover_unit else "")
                      + "<extra></extra>",
    )
    fig.add_vline(x=0, line_width=1, line_color=GRID)
    return _rounded(_style(fig))


def trend_line(data, *, x: str, y: str, labels: dict[str, str] | None = None
               ) -> go.Figure:
    fig = px.line(data, x=x, y=y, markers=True, labels=labels or {})
    fig.update_traces(line=dict(color=SEQUENTIAL_BLUE[4], width=2),
                      marker=dict(size=8))
    return _style(fig, value_axis="y")


def composition_pie(data, *, names: str, values: str) -> go.Figure:
    """Pie slices read as identity, so they take the categorical order.

    Kept to eight visible hues; anything past that has already been folded into
    "Other" by the caller.
    """
    fig = px.pie(data, names=names, values=values,
                 color_discrete_sequence=CATEGORICAL)
    fig.update_traces(marker=dict(line=dict(color="#ffffff", width=2)),
                      textfont=dict(size=12))
    fig.update_layout(paper_bgcolor="rgba(0,0,0,0)",
                      margin=dict(l=10, r=10, t=10, b=10))
    return fig


#: Fixed categorical order. Validated as a set; never cycled or regenerated.
CATEGORICAL: tuple[str, ...] = (
    "#2a78d6", "#eb6834", "#1baf7a", "#eda100",
    "#e87ba4", "#008300", "#4a3aa7", "#e34948",
)
