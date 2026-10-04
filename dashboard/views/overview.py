"""Overview page: ASEAN-level coverage, topic mix and trends."""
import html
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from filters import current_filters, format_month
from load_data import get_news_cleaned
from metrics import topic_totals
from style import (
    FONT_PX,
    categorical_colors,
    kpi_card,
    sequential_colorscale,
    series_color,
    style_figure,
    surface_color,
    text_color,
)
# =====================================================================
# SETTINGS
# =====================================================================
HEATMAP_TOPICS = 10
TREND_TOPICS = 5
# Countries with fewer mentions than this under the current filters
# are flagged as low coverage.
LOW_COVERAGE_MIN = 25
# Below this many months, trend lines are flagged as indicative.
MIN_TREND_MONTHS = 4
COUNTRY_MARKERS = {
    "Brunei": (4.5, 114.7, "top center"),
    "Cambodia": (12.6, 104.9, "top center"),
    "Indonesia": (-2.5, 118.0, "bottom center"),
    "Laos": (19.9, 102.5, "top center"),
    "Malaysia": (4.2, 102.0, "top center"),
    "Myanmar": (21.0, 96.0, "top center"),
    "Philippines": (12.9, 121.8, "top center"),
    "Singapore": (1.35, 103.8, "bottom center"),
    "Thailand": (15.8, 101.0, "top center"),
    "Vietnam": (14.1, 108.3, "middle right"),
}
# =====================================================================
# FILTERS
# =====================================================================
filters = current_filters()
df = filters.data
top_n = st.sidebar.slider(
    "Top topics to show",
    min_value=5,
    max_value=10,
    value=8,
    key="top_n",
)
st.title("Overview")
if df.empty:
    st.info("No data matches the current filters.")
    st.stop()
# =====================================================================
# SUPPORTING DATA
# =====================================================================
totals = topic_totals(df)
news_cleaned = get_news_cleaned()
# Apply the same country and month filters to news_cleaned.
filtered_cleaned = news_cleaned[
    news_cleaned["country"].isin(filters.countries)
    & news_cleaned["month"].between(
        filters.start,
        filters.end,
    )
].copy()
# =====================================================================
# KPI CARDS
# =====================================================================
coverage = int(
    df["article_count"].sum()
)
unique_articles = (
    filtered_cleaned["article_id"].nunique()
    if not filtered_cleaned.empty
    else 0
)
topic_count = df["topic_id"].nunique()
country_count = df["country"].nunique()
kpis = [
    (
        "Coverage",
        f"{coverage:,}",
    ),
    (
        "Unique Articles",
        f"{unique_articles:,}",
    ),
    (
        "Topics",
        f"{topic_count:,}",
    ),
    (
        "Countries",
        f"{country_count:,}",
    ),
    (
        "Period",
        filters.period,
    ),
]
for column, (label, value) in zip(
    st.columns(
        [
            1,
            1.15,
            1,
            1,
            1.6,
        ]
    ),
    kpis,
):
    column.html(
        kpi_card(
            label,
            value,
        )
    )
st.caption(
    "Coverage is the total number of topic-country mentions. "
    "Unique Articles counts each article once even when it is "
    "associated with multiple countries or topics."
)
# =====================================================================
# WHAT'S HAPPENING?
# =====================================================================
top = totals.iloc[0]
top_countries = df.loc[
    df["topic_name"] == top["topic_name"],
    "country",
].nunique()
tied = totals.loc[
    (
        totals["article_count"]
        == top["article_count"]
    )
    & (
        totals.index > 0
    ),
    "topic_name",
].tolist()
summary = (
    f"<b>{html.escape(top['topic_name'])}</b> "
    f"was the most-covered topic in "
    f"<b>{html.escape(filters.period)}</b>, "
    f"with <b>{int(top['article_count']):,} "
    f"mention{'s' if top['article_count'] != 1 else ''}</b> "
    f"across <b>{top_countries} "
    f"countr{'ies' if top_countries != 1 else 'y'}</b>."
)
if tied:
    summary += (
        " Tied with "
        + html.escape(
            ", ".join(tied)
        )
        + "."
    )
st.html(
    '<div class="insight-card">'
    "<h3>What's happening?</h3>"
    f"<p>{summary}</p>"
    "</div>"
)
# =====================================================================
# TOP TOPICS BY MENTIONS
# =====================================================================
st.header(
    f"Top {min(top_n, len(totals))} topics by mentions"
)
top_topics = totals.head(
    top_n
)
bar = go.Figure(
    go.Bar(
        x=top_topics["article_count"],
        y=top_topics["topic_name"],
        orientation="h",
        marker=dict(
            color=series_color(),
            cornerradius=4,
        ),
        text=top_topics["article_count"],
        textposition="outside",
        textfont_size=FONT_PX,
        cliponaxis=False,
        hovertemplate=(
            "%{y}: %{x:,} mentions"
            "<extra></extra>"
        ),
    )
)
bar.update_yaxes(
    autorange="reversed",
    ticksuffix="  ",
)
bar.update_xaxes(
    title_text="Mentions",
    range=[
        0,
        top_topics["article_count"].max()
        * 1.12,
    ],
    showgrid=False,
)
bar.update_layout(
    bargap=0.35
)
st.plotly_chart(
    style_figure(
        bar,
        height=110
        + 70 * len(top_topics),
    ),
    config={
        "displayModeBar": False
    },
)
# =====================================================================
# MENTIONS BY COUNTRY
# =====================================================================
st.header(
    "Mentions by country"
)
by_country = (
    df.groupby(
        "country",
        as_index=False,
    )["article_count"]
    .sum()
)
unmapped = sorted(
    set(by_country["country"])
    - COUNTRY_MARKERS.keys()
)
by_country = by_country[
    by_country["country"].isin(
        COUNTRY_MARKERS.keys()
    )
].copy()
by_country["lat"] = (
    by_country["country"]
    .map(
        lambda c:
            COUNTRY_MARKERS[c][0]
    )
)
by_country["lon"] = (
    by_country["country"]
    .map(
        lambda c:
            COUNTRY_MARKERS[c][1]
    )
)
by_country["label"] = (
    by_country["country"]
    + ": "
    + by_country["article_count"]
    .map("{:,}".format)
)
geo = px.scatter_geo(
    by_country,
    lat="lat",
    lon="lon",
    size="article_count",
    size_max=70,
    text="label",
    custom_data=[
        "country",
        "article_count",
    ],
)
geo.update_traces(
    marker=dict(
        color=series_color(),
        opacity=0.8,
        sizemin=10,
        line=dict(
            width=2,
            color=surface_color(),
        ),
    ),
    textposition=[
        COUNTRY_MARKERS[c][2]
        for c in by_country["country"]
    ],
    textfont=dict(
        size=FONT_PX,
        color=text_color(),
        weight="bold",
    ),
    hovertemplate=(
        "%{customdata[0]}: "
        "%{customdata[1]:,} mentions"
        "<extra></extra>"
    ),
)
geo.update_geos(
    projection_type="mercator",
    lataxis_range=[
        -11,
        24,
    ],
    lonaxis_range=[
        88,
        138,
    ],
    resolution=50,
    showcountries=True,
    countrycolor=(
        "rgba(128, 128, 128, 0.6)"
    ),
    showland=True,
    landcolor=(
        "rgba(128, 128, 128, 0.15)"
    ),
    showocean=False,
    showlakes=False,
    showframe=False,
    bgcolor="rgba(0, 0, 0, 0)",
)
map_event = st.plotly_chart(
    style_figure(
        geo,
        height=700,
    ),
    config={
        "displayModeBar": False
    },
    on_select="rerun",
    selection_mode="points",
    key="overview_country_map",
)
# Clicking a country bubble opens the Country Opportunity Explorer
# with the clicked country and current Overview date range selected.
if map_event.selection.points:
    selected_point = map_event.selection.points[0]
    customdata = selected_point.get("customdata")
    if customdata:
        selected_country = customdata[0]
        st.session_state["opportunity_country"] = selected_country
        st.session_state["opportunity_month_range"] = (
            filters.start,
            filters.end,
        )
        st.switch_page("views/country_opportunity.py")
if unmapped:
    st.caption(
        "Not shown on the map "
        "(no map position set): "
        + ", ".join(unmapped)
    )
# =====================================================================
# TOPIC MIX BY COUNTRY
# =====================================================================
st.header(
    f"Top {min(HEATMAP_TOPICS, len(totals))} topics by country"
)
show_counts = st.toggle(
    "Show raw mention counts",
    key="heatmap_counts",
)
heat_topics = (
    totals["topic_name"]
    .head(HEATMAP_TOPICS)
    .tolist()
)
country_totals = (
    df.groupby("country")[
        "article_count"
    ]
    .sum()
    .sort_index()
)
countries = (
    country_totals.index.tolist()
)
counts = (
    df[
        df["topic_name"].isin(
            heat_topics
        )
    ]
    .pivot_table(
        index="topic_name",
        columns="country",
        values="article_count",
        aggfunc="sum",
        fill_value=0,
    )
    .reindex(
        index=heat_topics,
        columns=countries,
        fill_value=0,
    )
)
shares = counts.div(
    country_totals,
    axis=1,
)
low_coverage = [
    country
    for country in countries
    if country_totals[country]
    < LOW_COVERAGE_MIN
]
x_labels = [
    (
        f"{country}<br>"
        "<i>low coverage</i>"
        if country in low_coverage
        else country
    )
    for country in countries
]
def format_share(
    share: float,
) -> str:
    if share == 0:
        return ""
    return (
        "<1%"
        if share < 0.005
        else f"{share:.0%}"
    )
customdata = np.dstack(
    [
        np.tile(
            np.array(
                countries,
                dtype=object,
            ),
            (
                len(heat_topics),
                1,
            ),
        ),
        counts.to_numpy(),
        np.tile(
            country_totals.to_numpy(),
            (
                len(heat_topics),
                1,
            ),
        ),
        shares.to_numpy(),
    ]
)
heatmap = go.Figure(
    go.Heatmap(
        z=(
            counts
            if show_counts
            else shares
        ),
        x=x_labels,
        y=heat_topics,
        text=(
            counts.map(
                lambda value:
                    f"{value:,}"
                    if value
                    else ""
            )
            if show_counts
            else shares.map(
                format_share
            )
        ),
        texttemplate="%{text}",
        textfont_size=FONT_PX,
        customdata=customdata,
        hovertemplate=(
            "%{y} in %{customdata[0]}"
            "<br>"
            "%{customdata[1]:,} of "
            "%{customdata[2]:,} mentions "
            "(%{customdata[3]:.1%})"
            "<extra></extra>"
        ),
        colorscale=(
            sequential_colorscale()
        ),
        zmin=0,
        showscale=False,
        xgap=2,
        ygap=2,
    )
)
heatmap.update_yaxes(
    autorange="reversed",
    ticksuffix="  ",
)
heatmap.update_xaxes(
    side="top"
)
st.plotly_chart(
    style_figure(
        heatmap,
        height=140
        + 60 * len(heat_topics),
    ),
    config={
        "displayModeBar": False
    },
)
if show_counts:
    st.caption(
        "Each cell shows the number of mentions "
        "for that topic in that country."
    )
else:
    st.caption(
        "Each cell shows the topic's share of all "
        "mentions in that country. Because an article "
        "can contribute to multiple topic-country mentions, "
        "the percentages describe coverage rather than "
        "a share of unique articles."
    )
if low_coverage:
    st.caption(
        f"Low coverage: fewer than "
        f"{LOW_COVERAGE_MIN} mentions under "
        f"the current filters "
        f"({', '.join(low_coverage)})."
    )
# =====================================================================
# TOP 5 TOPICS OVER TIME
# =====================================================================
st.header(
    f"Top {min(TREND_TOPICS, len(totals))} topics over time"
)
st.caption(
    "The topics shown are the most-mentioned topics "
    f"across the selected countries during {filters.period}."
)
if len(filters.months) < MIN_TREND_MONTHS:
    st.caption(
        f"Only {len(filters.months)} "
        f"month{'s' if len(filters.months) != 1 else ''} "
        "of data are available in the selected range, "
        "so treat these trends as indicative."
    )
trend_topics = (
    totals["topic_name"]
    .head(TREND_TOPICS)
    .tolist()
)
trend = (
    df[
        df["topic_name"].isin(
            trend_topics
        )
    ]
    .groupby(
        [
            "topic_name",
            "month",
        ]
    )["article_count"]
    .sum()
    .unstack(
        "month",
        fill_value=0,
    )
    .reindex(
        index=trend_topics,
        columns=filters.months,
        fill_value=0,
    )
)
month_labels = [
    format_month(month)
    for month in filters.months
]
lines = go.Figure()
for topic, color in categorical_colors(
    trend_topics
).items():
    lines.add_trace(
        go.Scatter(
            x=month_labels,
            y=trend.loc[topic],
            name=topic,
            mode="lines+markers",
            line=dict(
                color=color,
                width=3,
            ),
            marker=dict(
                color=color,
                size=10,
            ),
            hovertemplate=(
                f"<b>{topic}</b><br>"
                "%{x}<br>"
                "%{y:,} mentions"
                "<extra></extra>"
            ),
        )
    )
lines.update_layout(
    hovermode="x unified",
    legend=dict(
        orientation="h",
        yanchor="bottom",
        y=1.02,
        x=0,
    ),
)
lines.update_yaxes(
    title_text="Mentions",
    rangemode="tozero",
)
st.plotly_chart(
    style_figure(
        lines,
        height=560,
    ),
    config={
        "displayModeBar": False
    },
)
# =====================================================================
# MENTIONS PER COUNTRY PER MONTH
# =====================================================================
st.header("Mentions per country per month")
st.caption(
    "Shows how environmental news coverage changes month by month "
    "for each selected country."
)
coverage_by_month = (
    df.groupby(
        [
            "month",
            "country",
        ]
    )["article_count"]
    .sum()
    .unstack(
        "country",
        fill_value=0,
    )
    .reindex(
        index=filters.months,
        columns=sorted(filters.countries),
        fill_value=0,
    )
)
# Keep each country's colour consistent even when
# countries are filtered in or out.
country_colors = categorical_colors(
    filters.all_countries
)
country_bars = go.Figure()
for country in coverage_by_month.columns:
    country_bars.add_trace(
        go.Bar(
            x=month_labels,
            y=coverage_by_month[country],
            name=country,
            marker=dict(
                color=country_colors[country],
                cornerradius=4,
            ),
            hovertemplate=(
                f"<b>{country}</b><br>"
                "%{x}<br>"
                "%{y:,} mentions"
                "<extra></extra>"
            ),
        )
    )
country_bars.update_layout(
    barmode="group",
    bargap=0.25,
    bargroupgap=0.08,
    legend=dict(
        orientation="h",
        yanchor="bottom",
        y=1.02,
        x=0,
    ),
)
country_bars.update_yaxes(
    title_text="Mentions",
    rangemode="tozero",
)
st.plotly_chart(
    style_figure(
        country_bars,
        height=560,
    ),
    config={
        "displayModeBar": False
    },
)

