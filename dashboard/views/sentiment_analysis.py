"""Regional sentiment-analysis overview for one month."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from sentiment_analysis_data import (
    COUNTRIES,
    EMOTION_COLORS,
    EMOTION_COLUMNS,
    EMOTION_EMOJI,
    aggregate_topics,
    load_representative_posts,
    load_sentiment,
    load_country_summaries,
)
from style import html_table, kpi_card, style_figure


def _emotion_name(column: str) -> str:
    return column.removesuffix("_count")


def _bubble_figure(topics: pd.DataFrame, selected_countries: list[str]) -> go.Figure:
    emotions = sorted(topics["dominant_emotion"].unique())
    max_value = float(topics["total_items"].max())
    sizeref = 2 * max_value / (270**2) if max_value else 1
    figure = go.Figure()

    positions = [
        (-10, 9), (0, 9), (10, 9),
        (-10, 0), (0, 0), (10, 0),
        (-10, -9), (0, -9), (10, -9),
    ]
    for index, row in topics.iterrows():
        x_position, y_position = positions[index]
        bubble_diameter = 270 * (float(row["total_items"]) / max_value) ** 0.5
        label_inside = bubble_diameter >= 125
        emotion = row["dominant_emotion"]
        color = EMOTION_COLORS.get(emotion, "#BDC3C7")
        figure.add_trace(
            go.Scatter(
                x=[x_position],
                y=[y_position],
                mode="markers",
                name=str(emotion).title(),
                customdata=[[index]],
                marker={
                    "size": [float(row["total_items"])],
                    "sizemode": "area",
                    "sizeref": sizeref,
                    "sizemin": 62,
                    "color": color,
                    "line": {"color": "rgba(255,255,255,0.9)", "width": 2},
                },
                hovertemplate=(
                    f"<b>{row['topic']}</b><br>{int(row['total_items']):,} discussions<br>"
                    f"Countries: {int(row['countries_count'])}/{len(selected_countries)}"
                    "<extra></extra>"
                ),
                showlegend=False,
            )
        )
        if label_inside:
            figure.add_annotation(
                x=x_position,
                y=y_position,
                text=f"<b>{row['topic']}</b><br>{int(row['total_items']):,}<br>discussions",
                showarrow=False,
                font={"size": 15, "color": "#000000"},
                align="center",
            )
        else:
            label_x = x_position + 3.8
            label_y = y_position + 3.2
            figure.add_annotation(
                x=x_position,
                y=y_position,
                ax=label_x,
                ay=label_y,
                xref="x",
                yref="y",
                axref="x",
                ayref="y",
                text=f"<b>{row['topic']}</b><br>{int(row['total_items']):,} discussions",
                showarrow=True,
                arrowhead=2,
                arrowsize=1,
                arrowwidth=1,
                arrowcolor="#000000",
                bgcolor="rgba(255,255,255,0.9)",
                borderpad=4,
                font={"size": 14, "color": "#000000"},
            )

    for emotion in emotions:
        figure.add_trace(
            go.Scatter(
                x=[None],
                y=[None],
                mode="markers",
                name=emotion.title(),
                marker={"size": 14, "color": EMOTION_COLORS.get(emotion, "#BDC3C7")},
            )
        )

    figure.update_layout(
        xaxis={"visible": False, "range": [-15.5, 15.5], "fixedrange": True},
        yaxis={
            "visible": False,
            "range": [-13.5, 13.5],
            "scaleanchor": "x",
            "fixedrange": True,
        },
        showlegend=True,
        legend={"title": {"text": "Dominant emotion"}, "orientation": "v"},
        hovermode="closest",
    )
    return style_figure(figure, height=650)


def _render_topic_insights(
    topic: pd.Series,
    sentiment: pd.DataFrame,
    month: pd.Timestamp,
    selected_countries: list[str],
) -> None:
    rows = sentiment[
        (sentiment["_month"] == month)
        & sentiment["country"].isin(selected_countries)
        & (sentiment["topic"] == topic["topic"])
    ]
    emotion_counts = {
        _emotion_name(column): int(rows[column].sum())
        for column in EMOTION_COLUMNS
        if column in rows
    }
    top_emotions = sorted(
        ((name, count) for name, count in emotion_counts.items() if count > 0),
        key=lambda item: (-item[1], item[0]),
    )[:3]

    st.subheader(f"Topic Insights: {topic['topic']}")
    st.caption(
        f"{int(topic['total_items']):,} discussions in {month:%B %Y} across "
        f"{int(topic['countries_count'])} selected countries."
    )
    columns = st.columns(3)
    columns[0].html(kpi_card("Dominant emotion", str(topic["dominant_emotion"]).title()))
    columns[1].html(
        kpi_card(
            "Countries discussing",
            f"{int(topic['countries_count'])}/{len(selected_countries)}",
        )
    )
    columns[2].html(kpi_card("Discussion volume", f"{int(topic['total_items']):,}"))

    country_breakdown = (
        rows.groupby("country", as_index=False)["total_items"]
        .sum()
        .sort_values(["total_items", "country"], ascending=[False, True])
        .rename(columns={"country": "Country", "total_items": "Discussions"})
    )
    country_breakdown["Discussions"] = country_breakdown["Discussions"].astype(int)
    st.markdown("**Country contribution**")
    st.html(html_table(country_breakdown))

    if top_emotions:
        emotion_html = "".join(
            (
                f'<span style="display:inline-block;margin:0 .5rem .5rem 0;'
                f'padding:.45rem .7rem;border-radius:999px;background:'
                f'{EMOTION_COLORS.get(name, "#BDC3C7")};color:#000;font-weight:600">'
                f'{EMOTION_EMOJI.get(name, "•")} {name.title()} · {count:,}</span>'
            )
            for name, count in top_emotions
        )
        st.markdown("**Top emotions**")
        st.html(emotion_html)

    summaries = load_country_summaries(month, selected_countries, str(topic["topic"]))
    # Every country discussing the topic gets a card, plus any country with a
    # summary but no scored discussions, so no country's view is dropped.
    summary_countries = list(country_breakdown["Country"]) + sorted(
        set(summaries) - set(country_breakdown["Country"])
    )
    st.markdown("**What each country is saying**")
    for country in summary_countries:
        with st.container(border=True):
            st.markdown(f"**{country}**")
            match = summaries.get(country, {})
            points = match.get("points", [])
            if match.get("shared"):
                st.caption(
                    f"No {country} summary for this topic. Showing the related "
                    f"\"{match['topic']}\" summary, which shares the keywords: "
                    f"{', '.join(match['shared'])}."
                )
            elif not points:
                st.caption(f"No discussion summary has been generated for {country} yet.")
            for heading, text in points:
                st.markdown(f"- **{heading}:** {text}" if heading else f"- {text}")

    posts = load_representative_posts(month, selected_countries, str(topic["topic"]))
    st.markdown("**Representative posts — highest-engagement post per platform**")
    if posts.empty:
        st.caption("No matching clean posts with engagement data were found.")
    else:
        for post in posts.itertuples():
            platform = getattr(post, "platform", "Unknown")
            with st.container(border=True):
                st.markdown(f"**{platform or 'Unknown'}**")
                caption = str(post.cleaned_text)
                words = caption.split()
                if len(words) > 300:
                    caption = " ".join(words[:300]) + " ..."
                st.markdown(caption)
                st.caption(f"Total engagement: {int(post.total_engagement):,}")
                post_url = str(getattr(post, "post_url", "") or "").strip()
                st.link_button(
                    "Link to original post →",
                    post_url or "#",
                    disabled=not post_url,
                )


st.title("Sentiment Analysis")
st.caption(
    "Explore the topics generating the most social discussion and the dominant "
    "emotion associated with each topic."
)

sentiment = load_sentiment()
if sentiment.empty:
    st.info("sentiment_analysis has no usable rows yet. Run the sentiment pipeline first.")
    st.stop()

available_months = sorted(pd.Timestamp(month) for month in sentiment["_month"].unique())
available_countries = [
    country for country in COUNTRIES if country in set(sentiment["country"])
]
default_month = available_months[-1]

st.sidebar.header("Sentiment Filters")
available_years = sorted({month.year for month in available_months})
selected_year = st.sidebar.selectbox(
    "Year",
    available_years,
    index=available_years.index(default_month.year),
    key="sentiment_month",
)
months_for_year = [month for month in available_months if month.year == selected_year]
selected_month = st.sidebar.selectbox(
    "Month",
    months_for_year,
    index=len(months_for_year) - 1,
    format_func=lambda month: month.strftime("%B"),
    key="sentiment_month_value",
)
selected_countries = st.sidebar.pills(
    "Countries",
    available_countries,
    selection_mode="multi",
    default=available_countries,
    key="sentiment_countries",
)

if not selected_countries:
    st.warning("Select at least one country.")
    st.stop()
if selected_month not in available_months:
    st.info("No sentiment-analysis data is available for the selected month.")
    st.stop()

topics = aggregate_topics(sentiment, selected_month, list(selected_countries))
if topics.empty:
    st.info("No sentiment-analysis rows match the selected month and countries.")
    st.stop()

month_rows = sentiment[
    (sentiment["_month"] == selected_month)
    & sentiment["country"].isin(selected_countries)
]
most_emotional_topic = topics.sort_values(
    ["emotion_variety", "total_items", "topic"],
    ascending=[False, False, True],
).iloc[0]
total_discussions = int(month_rows["total_items"].sum())
most_discussed_country = (
    month_rows.groupby("country")["total_items"].sum().sort_values(ascending=False).index[0]
)

kpis = st.columns(4)
kpis[0].html(kpi_card("Total discussions analysed", f"{total_discussions:,}"))
kpis[1].html(kpi_card("Top topic", str(topics.iloc[0]["topic"])))
kpis[2].html(
    kpi_card(
        "Most emotional topic",
        str(most_emotional_topic["topic"]),
    )
)
kpis[3].html(kpi_card("Most discussed country", most_discussed_country))

st.header("What are people talking about?")
st.caption(
    f"This bubble chart shows the top {len(topics)} topics by discussion volume for {selected_month:%B %Y}. "
    "Click on a bubble to view more details about the topic."
)
event = st.plotly_chart(
    _bubble_figure(topics, list(selected_countries)),
    width="stretch",
    on_select="rerun",
    selection_mode="points",
    config={
        "displayModeBar": False,
        "doubleClick": False,
        "scrollZoom": False,
    },
    key="sentiment_topic_bubbles",
)

selected_points = getattr(getattr(event, "selection", None), "points", [])
if selected_points:
    customdata = selected_points[0].get("customdata")
    point_index = customdata[0] if isinstance(customdata, list) else customdata
    if point_index is not None and int(point_index) < len(topics):
        with st.container(border=True):
            _render_topic_insights(
                topics.iloc[int(point_index)],
                sentiment,
                selected_month,
                list(selected_countries),
            )
