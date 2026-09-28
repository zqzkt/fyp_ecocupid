"""Overview page: headline numbers, top topics, emerging topics and coverage by country."""

import html

import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from filters import current_filters, format_month
from metrics import topic_totals
from style import FONT_PX, html_table, kpi_card, series_color, style_figure, surface_color, text_color

# A topic is "emerging / niche" when its total article_count across the current filters equals this.
EMERGING_MAX = 1

# Where each country's bubble sits on the map (lat, lon), with its label placed to avoid neighbours.
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

filters = current_filters()
df = filters.data
top_n = st.sidebar.slider("Top topics to show", min_value=5, max_value=10, value=8, key="top_n")

st.title("Overview")

if df.empty:
    st.info("No articles match the current filters.")
    st.stop()

totals = topic_totals(df)

# KPI cards
kpis = [
    ("Articles", f"{int(df['article_count'].sum()):,}"),
    ("Topics", f"{df['topic_name'].nunique():,}"),
    ("Countries", f"{df['country'].nunique():,}"),
    ("Period", filters.period),
]
# Period gets a wider card so a month range fits on one line.
for column, (label, value) in zip(st.columns([1, 1, 1, 1.6]), kpis):
    column.html(kpi_card(label, value))

# What's happening?
top = totals.iloc[0]
top_countries = df.loc[df["topic_name"] == top["topic_name"], "country"].nunique()
tied = totals.loc[
    (totals["article_count"] == top["article_count"]) & (totals.index > 0), "topic_name"
].tolist()
summary = (
    f"<b>{html.escape(top['topic_name'])}</b> was the most-covered topic in "
    f"<b>{html.escape(filters.period)}</b>, with <b>{int(top['article_count']):,} "
    f"article{'s' if top['article_count'] != 1 else ''}</b> across "
    f"<b>{top_countries} countr{'ies' if top_countries != 1 else 'y'}</b>."
)
if tied:
    summary += f" Tied with {html.escape(', '.join(tied))}."
st.html(f'<div class="insight-card"><h3>What\'s happening?</h3><p>{summary}</p></div>')

# Top topics
st.header(f"Top {min(top_n, len(totals))} topics")
top_topics = totals.head(top_n)
bar = go.Figure(
    go.Bar(
        x=top_topics["article_count"],
        y=top_topics["topic_name"],
        orientation="h",
        marker=dict(color=series_color(), cornerradius=4),
        text=top_topics["article_count"],
        textposition="outside",
        textfont_size=FONT_PX,
        cliponaxis=False,
        hovertemplate="%{y}: %{x:,} articles<extra></extra>",
    )
)
bar.update_yaxes(autorange="reversed", ticksuffix="  ")
bar.update_xaxes(
    title_text="Articles", range=[0, top_topics["article_count"].max() * 1.12], showgrid=False
)
bar.update_layout(bargap=0.35)
st.plotly_chart(style_figure(bar, height=110 + 70 * len(top_topics)), config={"displayModeBar": False})

# Articles by country
st.header("Articles by country")
by_country = df.groupby("country", as_index=False)["article_count"].sum()
unmapped = sorted(set(by_country["country"]) - COUNTRY_MARKERS.keys())
by_country = by_country[by_country["country"].isin(COUNTRY_MARKERS.keys())].copy()
by_country["lat"] = by_country["country"].map(lambda c: COUNTRY_MARKERS[c][0])
by_country["lon"] = by_country["country"].map(lambda c: COUNTRY_MARKERS[c][1])
by_country["label"] = by_country["country"] + ": " + by_country["article_count"].map("{:,}".format)

geo = px.scatter_geo(
    by_country,
    lat="lat",
    lon="lon",
    size="article_count",
    size_max=70,
    text="label",
    custom_data=["country", "article_count"],
)
geo.update_traces(
    marker=dict(color=series_color(), opacity=0.8, sizemin=10, line=dict(width=2, color=surface_color())),
    textposition=[COUNTRY_MARKERS[c][2] for c in by_country["country"]],
    textfont=dict(size=FONT_PX, color=text_color(), weight="bold"),
    hovertemplate="%{customdata[0]}: %{customdata[1]:,} articles<extra></extra>",
)
geo.update_geos(
    projection_type="mercator",
    lataxis_range=[-11, 24],
    lonaxis_range=[88, 138],
    resolution=50,
    showcountries=True,
    countrycolor="rgba(128, 128, 128, 0.6)",
    showland=True,
    landcolor="rgba(128, 128, 128, 0.15)",
    showocean=False,
    showlakes=False,
    showframe=False,
    bgcolor="rgba(0, 0, 0, 0)",
)
st.plotly_chart(style_figure(geo, height=700), config={"displayModeBar": False})
if unmapped:
    st.caption(f"Not shown on the map (no map position set): {', '.join(unmapped)}")

# Emerging / niche topics
st.header("Emerging / niche topics")
st.caption(
    f"Topics with a total of {EMERGING_MAX} article{'s' if EMERGING_MAX != 1 else ''} "
    "across the current filters, newest first."
)
emerging_names = totals.loc[totals["article_count"] == EMERGING_MAX, "topic_name"]
emerging = (
    df[df["topic_name"].isin(emerging_names)]
    .groupby("topic_name", as_index=False)
    .agg(countries=("country", lambda s: ", ".join(sorted(s.unique()))), first_seen=("month", "min"))
    .sort_values(["first_seen", "topic_name"], ascending=[False, True])
)
if emerging.empty:
    st.info("No emerging topics for the current filters.")
else:
    emerging["first_seen"] = emerging["first_seen"].map(format_month)
    emerging.columns = ["Topic", "Countries", "First seen"]
    st.html(html_table(emerging))
