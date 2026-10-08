"""Presentation styling shared by every page: large fonts, cards, tables and chart defaults."""

from __future__ import annotations

import html

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# Base font size for everything on the dashboard (presented in a large room).
FONT_PX = 20

# Single-series marks use slot 1 of the reference palette, stepped per theme.
SERIES_COLOR = {"light": "#2a78d6", "dark": "#3987e5"}
SURFACE_COLOR = {"light": "#ffffff", "dark": "#0e1117"}
TEXT_COLOR = {"light": "#31333f", "dark": "#fafafa"}
# Categorical hues in fixed order (reference palette), validated for colour-blind separation.
CATEGORICAL = {
    "light": ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"],
    "dark": ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"],
}
OTHER_COLOR = "#8a8a86"  # for any series past the eighth: never generate a new hue
# One-hue blue ramp for magnitude; the "near zero" end recedes toward the page background.
SEQUENTIAL = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]

_CSS = f"""
<style>
html {{ font-size: {FONT_PX}px; }}
[data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] p,
[data-testid="stWidgetLabel"] p, [data-testid="stMarkdownContainer"] p,
[data-testid="stSidebarNav"] span, [data-testid="stButtonGroup"] button p,
[data-testid="stSliderTickBarMin"], [data-testid="stSliderTickBarMax"],
[data-testid="stSliderThumbValue"], [data-testid="stAlert"] p {{
  font-size: {FONT_PX}px !important;
}}

.kpi-card, .insight-card {{
  border: 1px solid rgba(128, 128, 128, 0.35);
  border-radius: 0.5rem;
  background: rgba(128, 128, 128, 0.06);
  padding: 0.75rem 1rem;
  height: 100%;
}}
.kpi-card .kpi-label {{ font-size: {FONT_PX}px; opacity: 0.8; }}
.kpi-card .kpi-value {{ font-size: {int(FONT_PX * 1.75)}px; font-weight: 700; line-height: 1.2; }}
.insight-card h3 {{ font-size: {int(FONT_PX * 1.4)}px; margin: 0 0 0.25rem; padding: 0; }}
.insight-card p {{ font-size: {int(FONT_PX * 1.15)}px !important; margin: 0; line-height: 1.5; }}

table.big-table {{ width: 100%; border-collapse: collapse; font-size: {FONT_PX}px; }}
table.big-table th, table.big-table td {{
  text-align: left; padding: 0.4rem 0.75rem; border-bottom: 1px solid rgba(128, 128, 128, 0.3);
}}
table.big-table th {{ font-weight: 700; }}
</style>
"""


def apply_style() -> None:
    st.html(_CSS)


def theme() -> str:
    try:
        return "dark" if st.context.theme.type == "dark" else "light"
    except AttributeError:
        return "light"


def series_color() -> str:
    return SERIES_COLOR[theme()]


def surface_color() -> str:
    return SURFACE_COLOR[theme()]


def text_color() -> str:
    return TEXT_COLOR[theme()]


def categorical_colors(names: list[str]) -> dict[str, str]:
    """Map each name to a categorical colour, in the given order."""
    palette = CATEGORICAL[theme()]
    return {name: palette[i] if i < len(palette) else OTHER_COLOR for i, name in enumerate(names)}


def sequential_colorscale() -> list[str]:
    return SEQUENTIAL if theme() == "light" else SEQUENTIAL[::-1]


def kpi_card(label: str, value: str) -> str:
    return (
        f'<div class="kpi-card"><div class="kpi-label">{html.escape(label)}</div>'
        f'<div class="kpi-value">{html.escape(value)}</div></div>'
    )


def html_table(df: pd.DataFrame) -> str:
    # to_html escapes cell values, so topic names from the database render as text.
    return df.to_html(index=False, escape=True, border=0, classes="big-table")


def style_figure(fig: go.Figure, height: int) -> go.Figure:
    fig.update_layout(
        height=height,
        font=dict(size=FONT_PX),
        hoverlabel=dict(font_size=FONT_PX),
        legend=dict(font_size=FONT_PX),
        margin=dict(l=10, r=10, t=10, b=10),
    )
    fig.update_xaxes(tickfont_size=FONT_PX, title_font_size=FONT_PX)
    fig.update_yaxes(tickfont_size=FONT_PX, title_font_size=FONT_PX)
    return fig
