"""Data and recommendation logic for country-specific communication insights.

Combines four analysed sources for one country and month:
- monthly_topic_stats: what the news is covering (top-ranked topics)
- sentiment_analysis: how social audiences feel about each topic keyword
- summary: what people are saying about each topic
- clean_posts / clean_comments: which platforms carry the conversation
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

from communication_channels_data import (
    _as_list,
    _load_table,
    add_date_columns,
    recommend_channels,
)


TOP_TOPICS = 3

# GoEmotions sentiment groups (Demszky et al., 2020).
POSITIVE_EMOTIONS = (
    "admiration", "amusement", "approval", "caring", "desire", "excitement",
    "gratitude", "joy", "love", "optimism", "pride", "relief",
)
NEGATIVE_EMOTIONS = (
    "anger", "annoyance", "disappointment", "disapproval", "disgust",
    "embarrassment", "fear", "grief", "nervousness", "remorse", "sadness",
)
AMBIGUOUS_EMOTIONS = ("confusion", "curiosity", "realization", "surprise")
TONE_GROUPS = {
    "positive": POSITIVE_EMOTIONS,
    "negative": NEGATIVE_EMOTIONS,
    "ambiguous": AMBIGUOUS_EMOTIONS,
}

# Positive labels outnumber the others, so almost every topic leans
# positive in absolute terms. A topic's tone is therefore judged against
# the regional average for the same month: it must exceed that average
# share by this many percentage points to count as distinctive.
TONE_MARGIN_PCT = 5

# Below this many social mentions a country/topic is flagged as thin evidence.
LOW_EVIDENCE_MENTIONS = 50

TONE_LABELS = {
    "negative": "Concerned",
    "ambiguous": "Curious",
    "positive": "Supportive",
    "regional": "In line with region",
}

TONE_ADVICE = {
    "negative": (
        "Acknowledge the concerns first, then lead with solutions and visible "
        "action. Avoid alarmist framing that deepens frustration."
    ),
    "ambiguous": (
        "Educate: use explainers, FAQs and myth-busting to answer the questions "
        "people are asking."
    ),
    "positive": (
        "Build on the goodwill: celebrate progress, spotlight community projects "
        "and invite people to take part."
    ),
    "regional": (
        "Use clear facts paired with a human story or a concrete call to action "
        "to make the topic stand out."
    ),
}

PLATFORM_NAMES = {
    "facebook": "Facebook",
    "instagram": "Instagram",
    "reddit": "Reddit",
    "x": "X",
    "youtube": "YouTube",
}

PLATFORM_FORMATS = {
    "facebook": "community stories, event calls and shareable updates",
    "instagram": "visual carousels and short reels",
    "reddit": "in-depth discussion threads and Q&A",
    "x": "timely updates tied to news moments",
    "youtube": "explainer videos and short documentaries",
}


def country_phrase(country: str) -> str:
    """Country name as used mid-sentence ("the Philippines")."""
    return "the Philippines" if country == "Philippines" else country


def platform_name(platform: Any) -> str:
    return PLATFORM_NAMES.get(str(platform).casefold(), str(platform))


# =====================================================================
# LOADING
# =====================================================================

@st.cache_data(ttl=600, show_spinner="Loading communication insight data...")
def load_insights_data() -> dict[str, pd.DataFrame]:
    """Load sentiment, discussion summaries and cleaned social activity."""
    sentiment = _load_table("sentiment_analysis")
    for column in ("year", "month", "total_items"):
        if column in sentiment:
            sentiment[column] = pd.to_numeric(sentiment[column], errors="coerce")

    summaries = _load_table("summary")
    if not summaries.empty:
        summaries["month"] = pd.to_datetime(summaries["month"], errors="coerce")

    return {
        "sentiment": sentiment,
        "summaries": summaries,
        "posts": add_date_columns(_load_table("clean_posts"), "posts"),
        "comments": add_date_columns(_load_table("clean_comments"), "comments"),
    }


def sentiment_months(sentiment: pd.DataFrame, country: str) -> list[pd.Timestamp]:
    """Months that have sentiment rows for a country."""
    rows = sentiment[sentiment["country"] == country].dropna(subset=["year", "month"])
    return sorted(
        {
            pd.Timestamp(year=int(row.year), month=int(row.month), day=1)
            for row in rows.itertuples()
        }
    )


# =====================================================================
# TONE
# =====================================================================

def emotion_counts(sentiment_rows: pd.DataFrame) -> pd.Series:
    """Sum every <emotion>_count column, indexed by emotion name."""
    columns = [
        column for column in sentiment_rows.columns
        if column.endswith("_count")
    ]
    counts = sentiment_rows[columns].apply(pd.to_numeric, errors="coerce").sum()
    counts.index = [column[: -len("_count")] for column in counts.index]
    return counts


def tone_shares(counts: pd.Series) -> dict[str, float]:
    """Share (%) of non-neutral emotion labels in each tone group."""
    totals = {
        group: float(counts.reindex(list(emotions)).fillna(0).sum())
        for group, emotions in TONE_GROUPS.items()
    }
    non_neutral = sum(totals.values())
    if not non_neutral:
        return {group: 0.0 for group in TONE_GROUPS}
    return {group: total / non_neutral * 100 for group, total in totals.items()}


def distinctive_tone(shares: dict[str, float], baseline: dict[str, float]) -> str:
    """Return the tone group that most exceeds the regional baseline, else "regional"."""
    lifts = {
        group: shares[group] - baseline[group]
        for group in TONE_GROUPS
        if shares[group] - baseline[group] >= TONE_MARGIN_PCT
    }
    return max(lifts, key=lifts.get) if lifts else "regional"


def top_emotions(counts: pd.Series, limit: int = 3) -> list[str]:
    """Most frequent emotions, excluding neutral."""
    counts = counts.drop("neutral", errors="ignore")
    counts = counts[counts > 0].sort_values(ascending=False)
    return list(counts.index[:limit])


# =====================================================================
# TOPIC INSIGHTS
# =====================================================================

def topic_keywords(value: Any) -> list[str]:
    """Split monthly_keywords into lower-case keywords."""
    return [keyword.casefold() for keyword in _as_list(value)]


def month_activity(data: dict[str, pd.DataFrame], month: pd.Timestamp) -> dict[str, pd.DataFrame]:
    """Clean posts/comments whose activity month is the selected month."""
    activity = {}
    for source_type in ("posts", "comments"):
        frame = data[source_type]
        activity[source_type] = frame[frame["_month"] == month] if not frame.empty else frame
    return activity


def build_topic_insights(
    topics: pd.DataFrame,
    data: dict[str, pd.DataFrame],
    country: str,
    month: pd.Timestamp,
) -> tuple[pd.DataFrame, dict[str, float]]:
    """
    Return one row per top-ranked news topic plus the regional tone baseline.

    topics is monthly_topic_stats for the country and month.
    """
    sentiment = data["sentiment"]
    month_sentiment = sentiment[
        (sentiment["year"] == month.year) & (sentiment["month"] == month.month)
    ]
    country_sentiment = month_sentiment[month_sentiment["country"] == country]
    baseline = tone_shares(emotion_counts(month_sentiment))

    summaries = data["summaries"]
    if not summaries.empty:
        summaries = summaries[
            (summaries["country"] == country) & (summaries["month"] == month)
        ]

    activity = month_activity(data, month)

    rows = []
    for topic in topics.sort_values("topic_rank").head(TOP_TOPICS).itertuples():
        keywords = topic_keywords(topic.monthly_keywords)
        topic_sentiment = country_sentiment[
            country_sentiment["topic"].astype(str).str.casefold().isin(keywords)
        ]
        counts = emotion_counts(topic_sentiment)
        shares = tone_shares(counts)
        tone = distinctive_tone(shares, baseline) if len(topic_sentiment) else "regional"

        channels, _ = recommend_channels(activity, country, keywords)

        summary = {}
        if not summaries.empty:
            match = summaries[summaries["keywords"] == topic.monthly_keywords]
            if not match.empty and isinstance(match.iloc[0]["summary"], dict):
                summary = match.iloc[0]["summary"]

        rows.append(
            {
                "topic": topic.topic_name,
                "rank": int(topic.topic_rank),
                "articles": int(topic.article_count),
                "keywords": keywords,
                "mentions": int(topic_sentiment["total_items"].sum()),
                "shares": shares,
                "tone": tone,
                "emotions": top_emotions(counts),
                "channel": channels.iloc[0]["platform"] if not channels.empty else None,
                "summary": summary,
            }
        )

    return pd.DataFrame(rows), baseline


def country_channels(
    data: dict[str, pd.DataFrame],
    country: str,
    month: pd.Timestamp,
    insights: pd.DataFrame,
) -> pd.DataFrame:
    """Rank platforms across all keywords of the country's top topics."""
    keywords = sorted({keyword for row in insights["keywords"] for keyword in row})
    channels, _ = recommend_channels(month_activity(data, month), country, keywords)
    return channels


# =====================================================================
# RECOMMENDATIONS
# =====================================================================

def lead_topic(insights: pd.DataFrame) -> pd.Series:
    """Topic with the most audience conversation; news rank breaks ties."""
    return insights.sort_values(["mentions", "rank"], ascending=[False, True]).iloc[0]


def recommendations(
    country: str,
    insights: pd.DataFrame,
    channels: pd.DataFrame,
) -> list[tuple[str, str]]:
    """Plain-language recommendations derived from the country's data."""
    items = []
    place = country_phrase(country)

    lead = lead_topic(insights)
    if lead["mentions"]:
        items.append(
            (
                f"Lead with {lead['topic']}",
                f"It drew the most social conversation in {place} "
                f"({lead['mentions']:,} mentions) and ranks #{lead['rank']} in news "
                "coverage, so audiences are already engaged.",
            )
        )
    else:
        items.append(
            (
                f"Lead with {lead['topic']}",
                f"It is the #{lead['rank']} news topic in {place}. There is no "
                "social conversation on it yet, so content can set the agenda.",
            )
        )

    tone = lead["tone"]
    emotions = ", ".join(lead["emotions"]) or "no strong emotions"
    items.append(
        (
            f"Tone: {TONE_LABELS[tone].lower()}",
            f"Reactions to {lead['topic']} centre on {emotions}. {TONE_ADVICE[tone]}",
        )
    )

    if not channels.empty:
        primary = channels.iloc[0]["platform"]
        text = (
            f"{platform_name(primary)} carries the most engagement and activity "
            f"on these topics in {place}. Use it for "
            f"{PLATFORM_FORMATS.get(str(primary).casefold(), 'core messaging')}."
        )
        if len(channels) > 1:
            secondary = channels.iloc[1]["platform"]
            text += f" Extend reach on {platform_name(secondary)}."
        items.append((f"Channel: {platform_name(primary)}", text))

    # A topic the news covers heavily but audiences barely discuss is an
    # opening to start the conversation.
    quiet = insights[
        (insights["topic"] != lead["topic"])
        & (insights["mentions"] < insights["mentions"].max() * 0.25)
    ]
    if not quiet.empty:
        gap = quiet.sort_values("rank").iloc[0]
        items.append(
            (
                f"Opportunity: {gap['topic']}",
                f"Ranked #{gap['rank']} in news but only {gap['mentions']:,} social "
                "mentions. Introducing it early could position the brand as a "
                "first mover.",
            )
        )

    return items
