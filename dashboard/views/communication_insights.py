"""Country-Specific Communication Insights page."""

from __future__ import annotations

import html

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from communication_channels_data import CommunicationChannelsDataError
from communication_insights_data import (
    LOW_EVIDENCE_MENTIONS,
    TONE_ADVICE,
    TONE_GROUPS,
    TONE_LABELS,
    build_topic_insights,
    country_channels,
    emotion_counts,
    lead_topic,
    load_insights_data,
    platform_name,
    recommendations,
    sentiment_months,
    top_emotions,
)
from filters import format_month
from load_data import get_data
from style import (
    categorical_colors,
    html_table,
    kpi_card,
    series_color,
    style_figure,
)


COUNTRIES = [
    "Brunei",
    "Indonesia",
    "Malaysia",
    "Philippines",
    "Singapore",
    "Thailand",
]


def insight_card(title: str, text: str) -> str:
    return (
        f'<div class="insight-card"><h3>{html.escape(title)}</h3>'
        f"<p>{html.escape(text)}</p></div>"
    )


# =====================================================================
# DATA + FILTERS
# =====================================================================

topic_stats = get_data()

try:
    data = load_insights_data()
except CommunicationChannelsDataError as exc:
    st.error(f"Could not load communication insight data: {exc}")
    st.stop()

if data["sentiment"].empty:
    st.info("sentiment_analysis has no rows yet. Run scripts/sentiment/sentiment_analysis.py first.")
    st.stop()

st.sidebar.header("Filters")
country = st.sidebar.selectbox("Country", COUNTRIES, key="insights_country")

topic_months = set(
    pd.to_datetime(topic_stats.loc[topic_stats["country"] == country, "month"].unique())
)
analysed_months = [
    month for month in sentiment_months(data["sentiment"], country)
    if month in topic_months
]

if not analysed_months:
    st.title(f"Communication Insights — {country}")
    st.info(
        f"No month has both news topics and sentiment analysis for {country} yet."
    )
    st.stop()

month = st.sidebar.selectbox(
    "Month",
    analysed_months[::-1],
    format_func=format_month,
    key=f"insights_month_{country}",
)

topics = topic_stats[
    (topic_stats["country"] == country) & (topic_stats["month"] == month)
]
insights, baseline = build_topic_insights(topics, data, country, month)
channels = country_channels(data, country, month, insights)


# =====================================================================
# HEADER + KPIs
# =====================================================================

st.title(f"Communication Insights — {country}")
st.caption(
    f"{format_month(month)} · Recommendations combine {country}'s top news topics, "
    "audience emotions on social media, and platform engagement."
)

lead = lead_topic(insights)
total_mentions = int(insights["mentions"].sum())

kpis = st.columns(4)
kpis[0].html(kpi_card("Lead topic", lead["topic"]))
kpis[1].html(kpi_card("Audience tone", TONE_LABELS[lead["tone"]]))
kpis[2].html(
    kpi_card(
        "Primary channel",
        platform_name(channels.iloc[0]["platform"]) if not channels.empty else "N/A",
    )
)
kpis[3].html(kpi_card("Social mentions analysed", f"{total_mentions:,}"))

if total_mentions < LOW_EVIDENCE_MENTIONS:
    st.warning(
        f"Only {total_mentions} social mentions were analysed for {country} in "
        f"{format_month(month)}. Treat these recommendations as indicative."
    )


# =====================================================================
# RECOMMENDED PLAN
# =====================================================================

st.header("Recommended communication plan")

cards = recommendations(country, insights, channels)
for start in range(0, len(cards), 2):
    columns = st.columns(2)
    for column, (title, text) in zip(columns, cards[start : start + 2]):
        column.html(insight_card(title, text))


# =====================================================================
# TOPIC-BY-TOPIC
# =====================================================================

st.header("Topic-by-topic guidance")

topic_table = pd.DataFrame(
    {
        "News rank": insights["rank"].map(lambda rank: f"#{rank}"),
        "Topic": insights["topic"],
        "Articles": insights["articles"].map("{:,}".format),
        "Social mentions": insights["mentions"].map("{:,}".format),
        "Audience tone": insights["tone"].map(TONE_LABELS.get),
        "Top emotions": insights["emotions"].map(lambda emotions: ", ".join(emotions) or "—"),
        "Best channel": insights["channel"].map(
            lambda platform: platform_name(platform) if platform else "—"
        ),
    }
)
st.html(html_table(topic_table))

for row in insights.itertuples():
    with st.expander(f"{row.topic}: suggested angle and what people are saying"):
        st.markdown(f"**Suggested angle:** {TONE_ADVICE[row.tone]}")
        if row.summary:
            st.markdown("**What people are saying**")
            for theme, text in row.summary.items():
                st.markdown(f"- **{theme}:** {text}")
        else:
            st.caption("No discussion summary is available for this topic.")
        st.caption("Keywords: " + ", ".join(row.keywords))


# =====================================================================
# AUDIENCE TONE
# =====================================================================

st.header(f"How {country} audiences feel")
st.caption(
    "Share of non-neutral emotion labels per topic, compared with the average "
    f"across all ASEAN countries in {format_month(month)}. A topic is marked "
    "Concerned, Curious or Supportive when that share is clearly above the "
    "regional average."
)

tone_names = {"positive": "Positive", "negative": "Negative", "ambiguous": "Curious / unsure"}
colors = categorical_colors(list(tone_names.values()))
labels = ["ASEAN average"] + insights["topic"].tolist()
share_rows = [baseline] + insights["shares"].tolist()

fig = go.Figure()
for group in TONE_GROUPS:
    fig.add_bar(
        y=labels,
        x=[shares[group] for shares in share_rows],
        name=tone_names[group],
        orientation="h",
        marker_color=colors[tone_names[group]],
        hovertemplate="%{y}: %{x:.0f}%<extra>" + tone_names[group] + "</extra>",
    )
fig.update_layout(
    barmode="stack",
    xaxis=dict(title="Share of emotion labels (%)", range=[0, 100]),
    yaxis=dict(autorange="reversed"),
    legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
)
st.plotly_chart(style_figure(fig, height=120 + 70 * len(labels)), width="stretch")

country_sentiment = data["sentiment"][
    (data["sentiment"]["country"] == country)
    & (data["sentiment"]["year"] == month.year)
    & (data["sentiment"]["month"] == month.month)
]
counts = emotion_counts(country_sentiment)
emotions = top_emotions(counts, limit=8)
if emotions:
    st.subheader("Most common emotions")
    emotion_fig = go.Figure(
        go.Bar(
            x=[int(counts[emotion]) for emotion in emotions],
            y=[emotion.title() for emotion in emotions],
            orientation="h",
            marker_color=series_color(),
            hovertemplate="%{y}: %{x:,}<extra></extra>",
        )
    )
    emotion_fig.update_layout(
        xaxis_title="Labelled posts and comments",
        yaxis=dict(autorange="reversed"),
    )
    st.plotly_chart(style_figure(emotion_fig, height=420), width="stretch")


# =====================================================================
# CHANNELS
# =====================================================================

st.header("Where to communicate")

if channels.empty:
    st.info(
        f"No cleaned social activity matched {country}'s top topics in "
        f"{format_month(month)}."
    )
else:
    st.caption(
        "Platforms ranked by 60% total engagement and 40% activity volume on the "
        "keywords of this month's top topics."
    )
    channel_table = pd.DataFrame(
        {
            "Channel": channels["platform"].map(platform_name),
            "Role": channels["recommendation"],
            "Score": channels["recommendation_score"].map("{:.0f}".format),
            "Activity items": channels["activity_items"].map("{:,}".format),
            "Total engagement": channels["total_engagement"].map("{:,.0f}".format),
        }
    )
    st.html(html_table(channel_table))


with st.expander("How these insights are built"):
    st.markdown(
        f"""
- **Topics** are {country}'s top three news topics for the month from
  `monthly_topic_stats`.
- **Social mentions** count posts and comments whose matched keywords belong to
  a topic, from `sentiment_analysis`. A post matching two keywords counts twice.
- **Audience tone** groups GoEmotions labels into positive, negative and curious /
  unsure, and compares each topic with the ASEAN average for the month. A group
  must be at least 5 percentage points above average to set the tone.
- **Lead topic** is the topic with the most social mentions; news rank breaks ties.
- **Channels** reuse the Communication Channels ranking: 60% engagement and 40%
  activity volume.
- **What people are saying** comes from the AI-generated discussion summaries in
  the `summary` table.
"""
    )
