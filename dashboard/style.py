"""Presentation styling shared by every page: large fonts, cards, tables and chart defaults.

Colours and fonts come from EcoCupid's website (ecocupid-asean.com):
  primary  hsl(117 98% 19%) = #066001   deep green
  secondary hsl(76 60% 50%) = #a3cc33   lime (used here as an olive #688321 on cream for contrast)
  background hsl(46 50% 90%) = #f2ecd9  cream
  chart-1..5 = green, lime, blue, purple, orange (the site's own chart palette)
  fonts: Poppins (body), League Spartan (headings)
Dark mode adapts the site's own dark tokens (#0D1117, #161B22, #F0EDE6, #3A8A2E) with the lime as accent.

To change the brand, edit the constants below and the matching values in .streamlit/config.toml.
"""

from __future__ import annotations

import html

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# Base font size for everything on the dashboard (presented in a large room).
FONT_PX = 20

BODY_FONT = "Poppins, ui-sans-serif, system-ui, sans-serif"
DISPLAY_FONT = "'League Spartan', 'Helvetica Neue', Arial, sans-serif"

# Brand colour: single-series marks, KPI values and card accents.
SERIES_COLOR = {"light": "#066001", "dark": "#acd147"}
SURFACE_COLOR = {"light": "#f2ecd9", "dark": "#0d1117"}
TEXT_COLOR = {"light": "#000000", "dark": "#f0ede6"}
# Card surfaces and hairlines, matching the site's white cards with a faint border.
CARD_BG = {"light": "#ffffff", "dark": "#161b22"}
HAIRLINE = {"light": "rgba(0, 0, 0, 0.08)", "dark": "rgba(240, 237, 230, 0.12)"}
CARD_SHADOW = {
    "light": "0 1px 2px rgba(0, 0, 0, 0.06), 0 1px 1px rgba(0, 0, 0, 0.04)",
    "dark": "none",
}
# Categorical hues in fixed order: the site's chart palette first (green, lime, blue, purple,
# orange), then three extra hues. Checked for colour-blind separation.
CATEGORICAL = {
    "light": ["#066001", "#688321", "#0da2e7", "#8a2ce2", "#f59e24", "#7a0f3a", "#1b2a4a", "#b5179e"],
    "dark": ["#acd147", "#faad42", "#3ebaf4", "#af6feb", "#f06a97", "#a67c52", "#2bb5b0", "#b39ddb"],
}
OTHER_COLOR = "#8a8a86"  # for any series past the eighth: never generate a new hue
# One-hue green ramp for magnitude, from pale cream-green to the brand primary. The
# "near zero" end recedes toward the page background.
SEQUENTIAL = ["#e6efcf", "#c3d6ac", "#a1be8a", "#7ea669", "#5c8e48", "#397728", "#066001"]


def _css(mode: str) -> str:
    brand = SERIES_COLOR[mode]
    card_bg = CARD_BG[mode]
    hairline = HAIRLINE[mode]
    shadow = CARD_SHADOW[mode]
    return f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=League+Spartan:wght@600;700&family=Poppins:wght@400;500;600&display=swap');

html {{ font-size: {FONT_PX}px; }}
.stApp, .stApp p, .stApp label, .stApp li, .stApp th, .stApp td,
.stApp input, .stApp textarea, .stApp button p,
[data-testid="stSidebar"], [data-testid="stCaptionContainer"] {{
  font-family: {BODY_FONT};
}}
.stApp h1, .stApp h2, .stApp h3, .stApp h4 {{
  font-family: {DISPLAY_FONT};
  font-weight: 700;
  letter-spacing: -0.025em;
}}
[data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] p,
[data-testid="stWidgetLabel"] p, [data-testid="stMarkdownContainer"] p,
[data-testid="stSidebarNav"] span, [data-testid="stButtonGroup"] button p,
[data-testid="stSliderTickBarMin"], [data-testid="stSliderTickBarMax"],
[data-testid="stSliderThumbValue"], [data-testid="stAlert"] p {{
  font-size: {FONT_PX}px !important;
}}

.kpi-card, .insight-card {{
  border: 1px solid {hairline};
  border-left: 4px solid {brand};
  border-radius: 0.875rem;
  background: {card_bg};
  box-shadow: {shadow};
  padding: 0.75rem 1rem;
  height: 100%;
}}
.kpi-card .kpi-label {{ font-size: {FONT_PX}px; opacity: 0.8; }}
.kpi-card .kpi-value {{
  font-family: {DISPLAY_FONT};
  font-size: {int(FONT_PX * 1.75)}px; font-weight: 700; line-height: 1.2; color: {brand};
}}
.insight-card h3 {{
  font-family: {DISPLAY_FONT};
  font-size: {int(FONT_PX * 1.4)}px; margin: 0 0 0.25rem; padding: 0; color: {brand};
}}
.insight-card p {{ font-size: {int(FONT_PX * 1.15)}px !important; margin: 0; line-height: 1.5; }}

table.big-table {{ width: 100%; border-collapse: collapse; font-size: {FONT_PX}px; }}
table.big-table th, table.big-table td {{
  text-align: left; padding: 0.4rem 0.75rem; border-bottom: 1px solid {hairline};
}}
table.big-table th {{ font-weight: 700; border-bottom: 2px solid {brand}; }}
</style>
"""


def apply_style() -> None:
    st.html(_css(theme()))


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
        font=dict(size=FONT_PX, family=BODY_FONT),
        hoverlabel=dict(font_size=FONT_PX),
        legend=dict(font_size=FONT_PX),
        margin=dict(l=10, r=10, t=10, b=10),
    )
    fig.update_xaxes(tickfont_size=FONT_PX, title_font_size=FONT_PX)
    fig.update_yaxes(tickfont_size=FONT_PX, title_font_size=FONT_PX)
    return fig