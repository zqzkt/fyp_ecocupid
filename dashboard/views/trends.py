"""Trends page: topic mix by country, top topics over time and monthly coverage per country."""

import numpy as np
import plotly.graph_objects as go
import streamlit as st

from filters import current_filters, format_month
from metrics import topic_totals
from style import FONT_PX, categorical_colors, sequential_colorscale, style_figure

HEATMAP_TOPICS = 10
TREND_TOPICS = 5
# Countries with fewer articles than this under the current filters are flagged "low coverage".
LOW_COVERAGE_MIN = 25
# Below this many months, trend lines are flagged as indicative only.
MIN_TREND_MONTHS = 4

filters = current_filters()
df = filters.data

st.title("Trends")

if df.empty:
    st.info("No articles match the current filters.")
    st.stop()

totals = topic_totals(df)
month_labels = [format_month(m) for m in filters.months]


def format_share(share: float) -> str:
    if share == 0:
        return ""
    return "<1%" if share < 0.005 else f"{share:.0%}"


# Heatmap: top topics by country
st.header(f"Top {min(HEATMAP_TOPICS, len(totals))} topics by country")
show_counts = st.toggle("Show raw article counts", key="heatmap_counts")

heat_topics = totals["topic_name"].head(HEATMAP_TOPICS).tolist()
country_totals = df.groupby("country")["article_count"].sum().sort_index()  # across all topics
countries = country_totals.index.tolist()
counts = (
    df[df["topic_name"].isin(heat_topics)]
    .pivot_table(index="topic_name", columns="country", values="article_count", aggfunc="sum", fill_value=0)
    .reindex(index=heat_topics, columns=countries, fill_value=0)
)
shares = counts.div(country_totals, axis=1)
low_coverage = [c for c in countries if country_totals[c] < LOW_COVERAGE_MIN]
x_labels = [f"{c}<br><i>low coverage</i>" if c in low_coverage else c for c in countries]

customdata = np.dstack(
    [
        np.tile(np.array(countries, dtype=object), (len(heat_topics), 1)),
        counts.to_numpy(),
        np.tile(country_totals.to_numpy(), (len(heat_topics), 1)),
        shares.to_numpy(),
    ]
)
heatmap = go.Figure(
    go.Heatmap(
        z=counts if show_counts else shares,
        x=x_labels,
        y=heat_topics,
        text=counts.map(lambda v: f"{v:,}" if v else "") if show_counts else shares.map(format_share),
        texttemplate="%{text}",
        textfont_size=FONT_PX,
        customdata=customdata,
        hovertemplate=(
            "%{y} in %{customdata[0]}<br>%{customdata[1]:,} of %{customdata[2]:,} articles "
            "(%{customdata[3]:.1%})<extra></extra>"
        ),
        colorscale=sequential_colorscale(),
        zmin=0,
        showscale=False,
        xgap=2,
        ygap=2,
    )
)
heatmap.update_yaxes(autorange="reversed", ticksuffix="  ")
heatmap.update_xaxes(side="top")
st.plotly_chart(
    style_figure(heatmap, height=140 + 60 * len(heat_topics)), config={"displayModeBar": False}
)
if show_counts:
    st.caption("Each cell is the number of articles on that topic in that country.")
else:
    st.caption(
        "Each cell is the topic's share of all that country's articles, so a column "
        "need not add up to 100%."
    )
if low_coverage:
    st.caption(
        f"Low coverage: fewer than {LOW_COVERAGE_MIN} articles under the current filters "
        f"({', '.join(low_coverage)}), so percentages there rest on very few articles."
    )

# Trend lines: top topics over time
st.header(f"Top {min(TREND_TOPICS, len(totals))} topics over time")
if len(filters.months) < MIN_TREND_MONTHS:
    st.caption(
        f"Only {len(filters.months)} month{'s' if len(filters.months) != 1 else ''} of data "
        "in the selected range, so treat these trends as indicative."
    )
trend_topics = totals["topic_name"].head(TREND_TOPICS).tolist()
trend = (
    df[df["topic_name"].isin(trend_topics)]
    .groupby(["topic_name", "month"])["article_count"].sum()
    .unstack("month", fill_value=0)
    .reindex(index=trend_topics, columns=filters.months, fill_value=0)
)
lines = go.Figure()
for topic, color in categorical_colors(trend_topics).items():
    lines.add_trace(
        go.Scatter(
            x=month_labels,
            y=trend.loc[topic],
            name=topic,
            mode="lines+markers",
            line=dict(color=color, width=3),
            marker=dict(color=color, size=10),
            hovertemplate="%{y:,} articles",
        )
    )
lines.update_layout(
    hovermode="x unified",
    legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
)
lines.update_yaxes(title_text="Articles", rangemode="tozero")
st.plotly_chart(style_figure(lines, height=560), config={"displayModeBar": False})

# Coverage: articles per country per month
st.header("Articles per country per month")
coverage = (
    df.groupby(["month", "country"])["article_count"].sum()
    .unstack("country", fill_value=0)
    .reindex(index=filters.months, columns=sorted(filters.countries), fill_value=0)
)
# Colours follow the country across the whole dataset, so filtering never repaints a country.
country_colors = categorical_colors(filters.all_countries)
bars = go.Figure()
for country in coverage.columns:
    bars.add_trace(
        go.Bar(
            x=month_labels,
            y=coverage[country],
            name=country,
            marker=dict(color=country_colors[country], cornerradius=4),
            hovertemplate=f"{country}: %{{y:,}} articles<extra></extra>",
        )
    )
bars.update_layout(
    barmode="group",
    bargap=0.25,
    bargroupgap=0.08,
    legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
)
bars.update_yaxes(title_text="Articles")
st.plotly_chart(style_figure(bars, height=560), config={"displayModeBar": False})
