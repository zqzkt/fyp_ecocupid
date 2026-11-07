"""Communication Framework: engagement comparison across platforms and countries."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# Allow this page to import the calculation module under scripts/.
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.communication_framework.engagement_metric_comparison import (
    EngagementDataError,
    compare_countries_within_platform,
    compare_platforms,
    compare_platforms_by_country,
    filter_content,
    load_engagement_data,
    prepare_content,
)
from style import (
    FONT_PX,
    categorical_colors,
    kpi_card,
    sequential_colorscale,
    series_color,
    style_figure,
)


# =====================================================================
# HELPERS
# =====================================================================

def _format_number(value) -> str:
    if value is None or pd.isna(value):
        return "N/A"
    value = float(value)
    if abs(value) >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if abs(value) >= 1_000:
        return f"{value / 1_000:.1f}K"
    return f"{value:,.0f}"


def _format_ratio(value) -> str:
    if value is None or pd.isna(value):
        return "N/A"
    return f"{float(value):,.1f}:1"


def _keyword_options(df: pd.DataFrame) -> list[str]:
    """Temporary topic options from matched_keywords."""
    options: set[str] = set()

    for value in df.get("matched_keywords", pd.Series(dtype=object)).dropna():
        if isinstance(value, list):
            values = value
        else:
            text = str(value).strip()
            if text.startswith("[") and text.endswith("]"):
                import json
                try:
                    parsed = json.loads(text)
                    values = parsed if isinstance(parsed, list) else [text]
                except json.JSONDecodeError:
                    values = [text]
            else:
                values = [text]

        for item in values:
            item = str(item).strip()
            if item:
                options.add(item)

    return sorted(options, key=str.casefold)


def _compact_table(df: pd.DataFrame, include_country: bool) -> pd.DataFrame:
    if df.empty:
        return df

    columns = ["platform"]
    if include_country:
        columns.append("country")

    columns += [
        "post_count",
        "total_engagement",
        "avg_engagement_per_post",
        "median_post_engagement",
        "total_impressions",
        "reach_to_engagement_ratio",
        "engagement_rate_pct",
    ]

    result = df[[c for c in columns if c in df.columns]].copy()

    result = result.rename(
        columns={
            "platform": "Platform",
            "country": "Country",
            "post_count": "Posts",
            "total_engagement": "Total Engagement",
            "avg_engagement_per_post": "Avg / Post",
            "median_post_engagement": "Median / Post",
            "total_impressions": "Views / Impressions",
            "reach_to_engagement_ratio": "Reach : Engagement",
            "engagement_rate_pct": "Engagement Rate (%)",
        }
    )

    if "Reach : Engagement" in result:
        result["Reach : Engagement"] = result["Reach : Engagement"].apply(_format_ratio)

    return result


def _room_for_labels(fig, height, *, right=105, bottom=75):
    """Apply final margins after style_figure so outside labels are not clipped."""
    fig = style_figure(fig, height=height)
    fig.update_layout(
        autosize=True,
        margin=dict(l=12, r=right, t=18, b=bottom),
        uniformtext=dict(mode="hide", minsize=10),
    )
    fig.update_xaxes(automargin=True)
    fig.update_yaxes(automargin=True)
    return fig


# =====================================================================
# LOAD SOCIAL DATA
# =====================================================================


try:
    raw_posts, raw_comments = load_engagement_data()
except EngagementDataError as exc:
    st.error(f"Could not load social engagement data from Supabase. {exc}")
    st.stop()

posts = prepare_content(raw_posts, "post")
comments = prepare_content(raw_comments, "comment")

if posts.empty:
    st.info("No social posts are available.")
    st.stop()


# =====================================================================
# PAGE-SPECIFIC FILTERS
# =====================================================================

# Styles are scoped to the sidebar, so the main dashboard charts and tables
# keep their existing EcoCupid styling.
st.markdown("""
<style>
/* Engagement filter styling: scoped to sidebar only */
section[data-testid="stSidebar"] [data-testid="stWidgetLabel"] p {
    color: #161616 !important;
    font-weight: 500 !important;
    white-space: normal !important;
}
section[data-testid="stSidebar"] [data-testid="stSelectbox"] [data-baseweb="select"] > div,
section[data-testid="stSidebar"] [data-testid="stDateInput"] [data-baseweb="input"] > div {
    background: #f1ead4 !important;
    border: 1px solid transparent !important;
    border-radius: 10px !important;
    box-shadow: none !important;
}
section[data-testid="stSidebar"] [data-testid="stSelectbox"] [data-baseweb="select"] > div *,
section[data-testid="stSidebar"] [data-testid="stDateInput"] input {
    color: #111 !important;
}
section[data-testid="stSidebar"] [data-testid="stDateInput"] input {
    background: #f1ead4 !important;
}
section[data-testid="stSidebar"] [data-testid="stToggle"] label {
    align-items: center !important;
}
</style>
""", unsafe_allow_html=True)

st.sidebar.header("Engagement Filters")

topic_options = _keyword_options(posts)
selected_topic_label = st.sidebar.selectbox(
    "Topic",
    ["All topics"] + topic_options,
    key="engagement_topic",
)
selected_topic = None if selected_topic_label == "All topics" else selected_topic_label

platform_options = sorted(posts["platform"].dropna().unique().tolist())
selected_platform = st.sidebar.selectbox(
    "Platform for country comparison",
    platform_options,
    key="engagement_platform",
)

country_options = sorted(posts["country"].dropna().unique().tolist())

# Use the same native Streamlit country pills as the Overview page.
# Keep a page-specific key so these selections remain independent of Overview.
selected_countries = st.sidebar.pills(
    "Countries",
    country_options,
    selection_mode="multi",
    default=country_options,
    key="engagement_countries",
)

include_comments = st.sidebar.toggle(
    "Include comment engagement",
    value=False,
    key="engagement_include_comments",
    help=(
        "When enabled, likes, replies, reposts and quotes received by comments "
        "are added to engagement received by the original posts."
    ),
)

# Month-range slider: inclusive complete calendar months, not individual dates.
valid_dates = posts["posted_at"].dropna()
start_date = None
end_date = None
if not valid_dates.empty:
    month_starts = pd.date_range(
        valid_dates.min().tz_localize(None).to_period("M").start_time,
        valid_dates.max().tz_localize(None).to_period("M").start_time,
        freq="MS",
    ).date.tolist()
    if len(month_starts) > 1:
        selected_months = st.sidebar.select_slider(
            "Months",
            options=month_starts,
            value=(month_starts[0], month_starts[-1]),
            format_func=lambda d: d.strftime("%b %Y"),
            key="engagement_month_range",
        )
        first_month, last_month = selected_months
    else:
        first_month = last_month = month_starts[0]
        st.sidebar.caption(f"Months: {first_month:%b %Y}")

    start_date = first_month
    end_date = (pd.Timestamp(last_month) + pd.offsets.MonthEnd(0)).date()

# Preserve the existing two-handle month slider and its green styling.
st.markdown("""
<style>
section[data-testid="stSidebar"] [data-testid="stSlider"] [role="slider"],
section[data-testid="stSidebar"] [data-testid="stSelectSlider"] [role="slider"] {
    background-color: #006400 !important;
    border-color: #006400 !important;
}
section[data-testid="stSidebar"] [data-testid="stSelectSlider"] [data-baseweb="slider"] > div > div {
    color: #006400 !important;
}
</style>
""", unsafe_allow_html=True)

if not selected_countries:
    st.warning("Select at least one country in the sidebar.")
    st.stop()

filter_args = {
    "topic": selected_topic,
    "countries": selected_countries,
    "start_date": str(start_date) if start_date else None,
    "end_date": str(end_date) if end_date else None,
}

filtered_posts = filter_content(posts, **filter_args)
filtered_comments = filter_content(comments, **filter_args)

if filtered_posts.empty:
    st.info("No posts match the selected filters.")
    st.stop()



# =====================================================================
# DASHBOARD — REFERENCE LAYOUT
# =====================================================================

st.markdown("""<style>
/* Compact, rounded cream/white chart panels */
div[data-testid="stVerticalBlockBorderWrapper"] > div {
    border-radius: 12px !important;
}
.ec-note {background:#f7d4c9; border-left:4px solid #df806d;
    border-radius:8px; padding:15px; color:#302820; font-size:0.88rem;}
.ec-small {color:#6c6c61; font-size:0.88rem;}
.ec-impressions-title {font-size:0.9rem; font-weight:700; margin:0 0 0.35rem 0; line-height:1.3;}
/* Green dotted grouping frame for impressions, independent of the KPI cards */
.st-key-ec_impressions_group {
    border: 2px dashed #79bf65 !important;
    background: rgba(229, 244, 218, 0.32) !important;
    padding: 7px 9px 9px !important;
    border-radius: 2px !important;
}
.st-key-ec_impressions_group [data-testid="stHorizontalBlock"] {gap: 8px !important;}
/* Keep both impression cards aligned and retain their green left borders */
[data-testid="stHorizontalBlock"] [data-testid="stHtml"] {min-width:0;}
/* Make hover labels readable rather than clipped by their containers */
.js-plotly-plot .hoverlayer .hovertext {pointer-events:none;}
</style>""", unsafe_allow_html=True)

overall = compare_platforms(filtered_posts, filtered_comments,
                            include_comment_engagement=include_comments)
platform_country = compare_platforms_by_country(
    filtered_posts, filtered_comments,
    include_comment_engagement=include_comments)

post_total = int(overall["post_count"].sum())
engagement_total = int(overall["total_engagement"].sum())
views = overall.loc[overall["platform"] == "YouTube", "total_impressions"].sum(min_count=1)
ximpressions = overall.loc[overall["platform"] == "X", "total_impressions"].sum(min_count=1)


# A single CSS grid keeps the four KPIs and the impressions group aligned.
# Unlike nested st.columns, the grid does not add an extra vertical offset.
import html as _html

def _metric_tile(label, value):
    return (
        '<div class="ec-kpi-tile">'
        f'<div class="ec-kpi-label">{_html.escape(str(label))}</div>'
        f'<div class="ec-kpi-value">{_html.escape(str(value))}</div>'
        '</div>'
    )

# Render heading, subtitle, all six same-size KPI cards and note together.
# This avoids Streamlit's default vertical gaps between separate elements.
KPI_CSS = """
<style>
.ec-summary {margin:0 0 10px;}
.ec-summary h1 {font-size:2.25rem;line-height:1.18;margin:0 0 5px;font-weight:750;color:#080808;}
.ec-summary-subtitle {font-size:1.05rem;color:#66665e;margin:0 0 12px;}
.ec-kpi-wrap {position:relative;padding-top:23px;}
.ec-impressions-heading {position:absolute;right:0;top:0;width:33.333%;box-sizing:border-box;
 font-size:14px;font-weight:700;color:#111;line-height:1.2;padding-left:7px;}
.ec-kpi-grid {display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:10px;align-items:stretch;}
.ec-kpi-tile {box-sizing:border-box;background:#fff;border-left:3px solid #006400;border-radius:12px;
 padding:12px 14px;min-width:0;height:92px;display:flex;flex-direction:column;justify-content:center;
 box-shadow:0 2px 1px rgba(0,0,0,.08);}
.ec-kpi-label {font-size:16px;line-height:1.25;color:#393939;white-space:normal;overflow-wrap:break-word;}
.ec-kpi-value {font-size:27px;font-weight:750;color:#006400;line-height:1.3;}
.ec-summary-note {font-size:15px;color:#66665e;margin:9px 0 0;}
@media(max-width:850px){.ec-kpi-grid{grid-template-columns:repeat(3,minmax(0,1fr));}
 .ec-impressions-heading{position:static;width:auto;padding:0 0 6px;}
 .ec-kpi-wrap{padding-top:0;}}
@media(max-width:500px){.ec-kpi-grid{grid-template-columns:repeat(2,minmax(0,1fr));}}
</style>
"""
summary_values = [
    ("Posts", f"{post_total:,}"),
    ("Total Engagement", _format_number(engagement_total)),
    ("Avg Engagement / Post", f"{engagement_total/post_total:,.1f}" if post_total else "N/A"),
    ("Platforms", str(overall["platform"].nunique())),
]
main_tiles = "".join(_metric_tile(label, value) for label, value in summary_values)
impression_tiles = (
    _metric_tile("YouTube Views", _format_number(views))
    + _metric_tile("X Impressions", _format_number(ximpressions))
)
summary_note = (
    f"{'Post + comment engagement' if include_comments else 'Post engagement only'} · "
    f"{selected_topic_label} · {len(selected_countries)} selected countries"
)
st.html(
    KPI_CSS
    + '<section class="ec-summary">'
    + '<h1>Engagement Comparison</h1>'
    + '<p class="ec-summary-subtitle">Compare how environmental content performs across media platforms and ASEAN countries.</p>'
    + '<div class="ec-kpi-wrap">'
    + '<div class="ec-impressions-heading">Impressions Metrics (YouTube &amp; X only)</div>'
    + '<div class="ec-kpi-grid">'
    + main_tiles + impression_tiles
    + '</div></div>'
    + f'<p class="ec-summary-note">{_html.escape(summary_note)}</p>'
    + '</section>'
)

# 1 — COUNTRY COMPARISON
st.subheader(f"1. {selected_platform} engagement by country")
st.caption("Compare engagement intensity across ASEAN countries for the selected platform. "
           "Switch between average and median per post.")

within = compare_countries_within_platform(
    filtered_posts, filtered_comments, selected_platform,
    include_comment_engagement=include_comments)
with st.container(border=True):
    chart_col, table_col = st.columns([1.1, 1], gap="medium")
    with chart_col:
        measure = st.segmented_control("Country chart measure", ["Average / Post", "Median / Post"],
                                       default="Average / Post", key="ec_country_measure",
                                       label_visibility="collapsed")
        metric = "median_post_engagement" if measure == "Median / Post" else "avg_engagement_per_post"
        if within.empty:
            st.info("No posts for this platform and country selection.")
        else:
            ordered = within.sort_values(metric, ascending=True)
            fig = go.Figure(go.Bar(x=ordered[metric], y=ordered["country"], orientation="h",
                marker_color=series_color(),
                text=ordered[metric].map(lambda x: f"{x:,.1f}"), textposition="outside",
                cliponaxis=False))
            fig.update_layout(bargap=.35, margin=dict(l=8,r=45,t=12,b=35))
            fig.update_xaxes(title_text=measure, rangemode="tozero", range=[0, max(float(ordered[metric].max()) * 1.17, 1)])
            fig.update_yaxes(title_text="")
            st.plotly_chart(_room_for_labels(fig, height=max(300, 95 + 48*len(ordered)), right=105),
                            use_container_width=True, config={"displayModeBar":False})
    with table_col:
        st.markdown("**Country metrics**")
        st.dataframe(_compact_table(within.sort_values("avg_engagement_per_post",ascending=False), True),
                     hide_index=True, use_container_width=True, height=max(295, 95+48*len(within)))

# 2 — PLATFORM COMPARISON
st.subheader("2. Engagement across platforms")
st.caption("Compare engagement intensity across platforms. Averages and medians are per post.")
with st.container(border=True):
    chart_col, table_col = st.columns([1.1, 1], gap="medium")
    with chart_col:
        measure2 = st.segmented_control("Platform chart measure", ["Average / Post", "Median / Post", "Total Engagement"],
                                        default="Average / Post", key="ec_platform_measure",
                                        label_visibility="collapsed")
        metric2 = {"Average / Post":"avg_engagement_per_post", "Median / Post":"median_post_engagement",
                   "Total Engagement":"total_engagement"}[measure2]
        ordered = overall.sort_values(metric2, ascending=True)
        colors = categorical_colors(sorted(ordered["platform"].tolist()))
        fig = go.Figure(go.Bar(x=ordered[metric2],y=ordered["platform"],orientation="h",
            marker_color=[colors[x] for x in ordered["platform"]],
            text=ordered[metric2].map(lambda x: f"{x:,.1f}" if metric2 != "total_engagement" else _format_number(x)),
            textposition="outside",cliponaxis=False))
        fig.update_layout(bargap=.3,margin=dict(l=8,r=50,t=12,b=35))
        fig.update_xaxes(title_text=measure2, rangemode="tozero", range=[0, max(float(ordered[metric2].max()) * 1.17, 1)])
        fig.update_yaxes(title_text="")
        st.plotly_chart(_room_for_labels(fig,height=max(310,100+53*len(ordered)),right=110),
                        use_container_width=True,config={"displayModeBar":False})
    with table_col:
        st.markdown("**Platform metrics**")
        st.dataframe(_compact_table(overall.sort_values("avg_engagement_per_post",ascending=False),False),
                     hide_index=True,use_container_width=True,height=max(305,100+53*len(overall)))

# ENGAGEMENT COMPOSITION AND REACH EFFICIENCY
left, right = st.columns(2, gap="medium")
with left:
    with st.container(border=True):
        st.markdown("**Engagement composition by platform**")
        st.caption("Breakdown of engagement into likes, replies, reposts and quotes.")
        if not overall.empty:
            # Restrained EcoCupid palette; no pink.
            components = [
                ("Likes", "post_likes", "comment_likes", "#176b43"),
                ("Replies", "post_replies", "comment_replies", "#58a8bf"),
                ("Reposts / Shares", "post_reposts", "comment_reposts", "#91b36b"),
                ("Quotes", "post_quotes", "comment_quotes", "#d6a64e"),
            ]
            fig = go.Figure()
            totals = overall["total_engagement"].replace(0, np.nan)
            for name, post_col, comment_col, color in components:
                vals = overall[post_col] + (overall[comment_col] if include_comments else 0)
                pct = (vals / totals * 100).fillna(0)
                fig.add_bar(
                    y=overall["platform"], x=pct, orientation="h", name=name,
                    marker_color=color,
                    text=pct.map(lambda x: f"{x:.0f}%" if x >= 12 else ""),
                    textposition="inside", insidetextanchor="middle",
                    customdata=np.column_stack([vals, pct]),
                    hovertemplate=(
                        "<b>%{y}</b><br>" + name + ": %{customdata[0]:,.0f} engagements<br>"
                        "Share: %{customdata[1]:.2f}%<extra></extra>"
                    ),
                )
            fig.update_layout(
                barmode="stack", height=365,
                margin=dict(l=8, r=10, t=10, b=105),
                legend=dict(orientation="h", x=0, xanchor="left", y=-0.43,
                            yanchor="top", font=dict(size=11)),
                hoverlabel=dict(align="left", font_size=12),
            )
            fig.update_xaxes(title_text="Share of total engagement", range=[0, 100],
                             ticksuffix="%", title_standoff=12)
            fig.update_yaxes(title_text="", automargin=True)
            st.plotly_chart(fig, use_container_width=True,
                            config={"displayModeBar": False})

with right:
    with st.container(border=True):
        st.markdown("**Reach efficiency (YouTube & X only)**")
        st.caption("Engagement rate (%) = total engagement ÷ views/impressions × 100. For example, 0.58% means 0.58 engagements per 100 impressions.")
        reach = overall[overall["platform"].isin(["YouTube","X"])].dropna(subset=["engagement_rate_pct"])
        if reach.empty:
            st.info("No available views/impressions for YouTube or X.")
        else:
            mode = st.segmented_control("Reach measure",["Engagement Rate (%)","Reach : Engagement"],
                                        default="Engagement Rate (%)",key="ec_reach_measure",
                                        label_visibility="collapsed")
            field = "engagement_rate_pct" if mode == "Engagement Rate (%)" else "reach_to_engagement_ratio"
            fig = go.Figure(go.Bar(y=reach["platform"],x=reach[field],orientation="h",
                marker_color=["#7138d8" if p=="YouTube" else "#4b9ee7" for p in reach["platform"]],
                text=reach[field].map(lambda v: f"{v:.2f}%" if field=="engagement_rate_pct" else f"{v:.1f}:1"),
                textposition="outside",cliponaxis=False))
            fig.update_layout(margin=dict(l=8,r=55,t=18,b=35),height=230)
            fig.update_xaxes(title_text=mode,rangemode="tozero", range=[0, max(float(reach[field].max()) * 1.2, 1e-6)])
            st.plotly_chart(_room_for_labels(fig,height=230,right=95,bottom=75),use_container_width=True,
                            config={"displayModeBar":False})
        st.caption("These rates measure engagement actions per view/impression, not the percentage of unique users who engaged. "
                   "Only YouTube and X have usable impression metrics in the collected data. "
                   "Rates can exceed 100% if multiple interactions are counted per view.")

# 3 — PLATFORM x COUNTRY
st.subheader("3. Platform × country comparison")
st.caption("Each cell shows average engagement per post; darker green indicates higher engagement.")
heat_col, note_col = st.columns([2.5,1],gap="medium")
with heat_col:
    with st.container(border=True):
        if platform_country.empty:
            st.info("No platform-country combinations match the filters.")
        else:
            heat = platform_country.pivot_table(index="platform",columns="country",
                    values="avg_engagement_per_post",aggfunc="mean")
            heat = heat.reindex(columns=[c for c in selected_countries if c in heat.columns])
            labels = heat.map(lambda v: "" if pd.isna(v) else f"{v:,.1f}")
            fig = go.Figure(go.Heatmap(z=heat.to_numpy(dtype=float),x=heat.columns.tolist(),
                y=heat.index.tolist(),text=labels.to_numpy(),texttemplate="%{text}",
                textfont_size=FONT_PX,colorscale=sequential_colorscale(),showscale=False,
                xgap=3,ygap=3,hovertemplate="%{y} · %{x}<br>Avg / Post: %{z:,.1f}<extra></extra>"))
            fig.update_xaxes(side="top")
            fig.update_yaxes(autorange="reversed")
            st.plotly_chart(style_figure(fig,height=max(320,100+62*len(heat.index))),
                            use_container_width=True,config={"displayModeBar":False})
    with st.expander("View platform × country metrics"):
        st.dataframe(
            _compact_table(platform_country, True),
            hide_index=True,
            use_container_width=True,
        )
with note_col:
    st.html("""
<div class="ec-note">
    <b>Understanding Engagement Metrics</b>

    <p><b>Total Engagement:</b> Measures overall audience
    interactions, helping identify platforms that generate
    the most engagement activity.</p>

    <p><b>Average Engagement per Post:</b> Shows engagement
    per post, allowing fairer comparisons between platforms
    with different posting volumes.</p>

    <p><b>Median Engagement per Post:</b> Represents typical
    post performance. It is less affected by unusually viral
    posts, making it useful for evaluating consistency.</p>

    <p><b>Why Both Metrics?</b> Comparing average and median
    helps EcoCupid identify platforms with strong engagement
    potential and dependable performance. A high average
    but low median suggests engagement may be driven by
    a few exceptionally popular posts.</p>

    <p><b>Reach Metrics:</b> Engagement Rate and
    Reach-to-Engagement Ratio are available only for YouTube
    and X, where views or impressions are collected.</p>
</div>
""")

