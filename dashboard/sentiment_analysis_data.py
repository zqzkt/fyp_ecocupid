"""Data loading and aggregation for the sentiment-analysis dashboard."""

from __future__ import annotations

import ast
import json

import pandas as pd
import streamlit as st

from communication_channels_data import _load_table


COUNTRIES = [
    "Brunei",
    "Indonesia",
    "Malaysia",
    "Philippines",
    "Singapore",
    "Thailand",
]
COUNTRY_ALIASES = {
    "BN": "Brunei",
    "ID": "Indonesia",
    "MY": "Malaysia",
    "PH": "Philippines",
    "SG": "Singapore",
    "TH": "Thailand",
}
TOPIC_LIMIT = 9
EMOTION_COLORS = {
    "admiration": "#9B59B6", "amusement": "#FFD93D", "anger": "#E74C3C",
    "annoyance": "#FF7F50", "approval": "#27AE60", "caring": "#2ECC71",
    "confusion": "#95A5A6", "curiosity": "#3498DB", "desire": "#F39C12",
    "disappointment": "#7F8C8D", "disapproval": "#C0392B", "disgust": "#556B2F",
    "embarrassment": "#FFB6C1", "excitement": "#FF6B35", "fear": "#8E44AD",
    "gratitude": "#20B2AA", "grief": "#2C3E50", "joy": "#F1C40F",
    "love": "#E91E63", "nervousness": "#A0522D", "optimism": "#7DCE82",
    "pride": "#6A5ACD", "realization": "#00BCD4", "relief": "#4DB6AC",
    "remorse": "#795548", "sadness": "#5DADE2", "surprise": "#FF00FF",
    "neutral": "#BDC3C7",
}
EMOTION_EMOJI = {
    "admiration": "👏", "amusement": "😄", "anger": "😠", "annoyance": "😒",
    "approval": "👍", "caring": "💚", "confusion": "😕", "curiosity": "🔎",
    "desire": "✨", "disappointment": "😞", "disapproval": "👎", "disgust": "🤢",
    "embarrassment": "😳", "excitement": "🎉", "fear": "😨", "gratitude": "🙏",
    "grief": "😢", "joy": "😊", "love": "❤️", "nervousness": "😬",
    "optimism": "🌱", "pride": "🦚", "realization": "💡", "relief": "😌",
    "remorse": "🙇", "sadness": "😢", "surprise": "😮", "neutral": "😐",
}
EMOTION_COLUMNS = [
    "admiration_count", "amusement_count", "anger_count", "annoyance_count",
    "approval_count", "caring_count", "confusion_count", "curiosity_count",
    "desire_count", "disappointment_count", "disapproval_count", "disgust_count",
    "embarrassment_count", "excitement_count", "fear_count", "gratitude_count",
    "grief_count", "joy_count", "love_count", "nervousness_count", "optimism_count",
    "pride_count", "realization_count", "relief_count", "remorse_count",
    "sadness_count", "surprise_count", "neutral_count",
]


def _emotion_name(column: str) -> str:
    return column.removesuffix("_count")


def prepare_sentiment() -> pd.DataFrame:
    sentiment = _load_table("sentiment_analysis")
    if sentiment.empty:
        return sentiment
    for column in ("year", "month", "total_items", *EMOTION_COLUMNS):
        if column in sentiment:
            sentiment[column] = pd.to_numeric(sentiment[column], errors="coerce")
    sentiment["country"] = sentiment["country"].astype(str).str.strip()
    sentiment["topic"] = sentiment["topic"].astype(str).str.strip()
    sentiment = sentiment[
        sentiment["country"].isin(COUNTRIES) & sentiment["topic"].ne("")
    ].copy()
    sentiment["_month"] = pd.to_datetime(
        dict(year=sentiment["year"], month=sentiment["month"], day=1),
        errors="coerce",
    )
    return sentiment.dropna(subset=["_month", "total_items"])


def dominant_emotion(row: pd.Series, numeric_columns: list[str]) -> str:
    emotion_counts = {
        _emotion_name(column): float(row[column] or 0)
        for column in numeric_columns
        if column.endswith("_count")
    }
    non_neutral = {
        emotion: count for emotion, count in emotion_counts.items()
        if emotion != "neutral" and count > 0
    }
    emotion_counts = non_neutral or emotion_counts
    return min(emotion_counts, key=lambda emotion: (-emotion_counts[emotion], emotion)) if emotion_counts else "unknown"


def aggregate_topics(
    sentiment: pd.DataFrame,
    month: pd.Timestamp,
    countries: list[str],
) -> pd.DataFrame:
    filtered = sentiment[
        (sentiment["_month"] == month) & sentiment["country"].isin(countries)
    ]
    if filtered.empty:
        return pd.DataFrame()
    numeric_columns = [
        column for column in ("total_items", *EMOTION_COLUMNS)
        if column in filtered.columns
    ]
    grouped = (
        filtered.groupby("topic", as_index=False)[numeric_columns]
        .sum()
        .sort_values(["total_items", "topic"], ascending=[False, True])
        .head(TOPIC_LIMIT)
        .reset_index(drop=True)
    )
    grouped["countries_count"] = grouped["topic"].map(
        filtered.groupby("topic")["country"].nunique()
    )
    grouped["dominant_emotion"] = grouped.apply(
        lambda row: dominant_emotion(row, numeric_columns), axis=1
    )
    grouped["dominant_emotion_count"] = grouped.apply(
        lambda row: float(row[f"{row['dominant_emotion']}_count"]), axis=1
    )
    non_neutral_columns = [
        column for column in EMOTION_COLUMNS if column != "neutral_count"
    ]
    grouped["emotion_variety"] = grouped[non_neutral_columns].gt(0).sum(axis=1)
    return grouped


@st.cache_data(ttl=600, show_spinner="Loading representative posts...")
def load_representative_posts(
    month: pd.Timestamp,
    countries: list[str],
    topic: str,
) -> pd.DataFrame:
    posts = _load_table("clean_posts")
    required = {"cleaned_text", "matched_keywords", "total_engagement"}
    if posts.empty or not required.issubset(posts.columns):
        return pd.DataFrame()
    posts = posts.copy()
    timestamp = pd.to_datetime(posts.get("posted_at"), errors="coerce", utc=True)
    country = posts.get(
        "inferred_country", pd.Series(index=posts.index, dtype="object")
    ).map(
        lambda value: COUNTRY_ALIASES.get(
            str(value).strip().upper(), str(value).strip()
        )
    )
    posts = posts[
        timestamp.dt.tz_localize(None).dt.to_period("M").dt.to_timestamp().eq(month)
        & country.isin(countries)
    ].copy()
    topic_term = topic.casefold()
    posts = posts[
        posts["matched_keywords"].apply(
            lambda value: topic_term in {
                str(item).strip().casefold()
                for item in (value if isinstance(value, list) else str(value).split(","))
            }
        )
    ]
    posts["total_engagement"] = pd.to_numeric(
        posts["total_engagement"], errors="coerce"
    ).fillna(0)
    posts = posts[posts["cleaned_text"].fillna("").astype(str).str.strip().ne("")]
    posts["platform"] = posts.get(
        "platform", pd.Series("Unknown", index=posts.index)
    ).fillna("Unknown").astype(str).str.strip().replace("", "Unknown")
    posts = (
        posts.sort_values(["platform", "total_engagement"], ascending=[True, False])
        .drop_duplicates("platform", keep="first")
        .sort_values("total_engagement", ascending=False)
    )
    return _add_post_urls(posts)


def _add_post_urls(posts: pd.DataFrame) -> pd.DataFrame:
    """Resolve source post URLs using each platform's raw-table schema."""
    result = posts.copy()
    result["post_url"] = ""
    if "source_table" not in result or "source_id" not in result:
        return result

    source_specs = {
        "facebook": ("facebook_posts", "url", ("post_id",)),
        "instagram": ("instagram_posts", "post_url", ("post_id",)),
        "reddit": ("reddit_posts", "post_url", ("post_id",)),
        "x": ("x_posts", "urls", ("post_id",)),
    }
    for platform, indexes in result.groupby(result["platform"].str.casefold()).groups.items():
        spec = source_specs.get(platform)
        if not spec:
            continue
        source_table, url_column, id_columns = spec
        source_rows = _load_table(source_table)
        if source_rows.empty:
            continue
        source_frame = pd.DataFrame(source_rows)
        id_column = next(
            (column for column in id_columns if column in source_frame),
            None,
        )
        if url_column not in source_frame or not id_column:
            continue
        url_by_id: dict[str, str] = {}
        for raw_id, raw_url in zip(source_frame[id_column], source_frame[url_column]):
            url = _extract_post_url(raw_url, platform)
            if pd.notna(raw_id) and url:
                url_by_id[str(raw_id)] = url
        for index in indexes:
            source_id = str(result.at[index, "source_id"])
            raw_id = source_id.split(":", 2)[-1]
            result.at[index, "post_url"] = url_by_id.get(raw_id, "")
    return result


def _extract_post_url(value: object, platform: str) -> str:
    """Extract the first usable URL, including X's serialized urls field."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    if platform != "x":
        return str(value).strip()

    parsed: object = value
    if isinstance(value, str):
        text = value.strip()
        for parser in (json.loads, ast.literal_eval):
            try:
                parsed = parser(text)
                break
            except (ValueError, SyntaxError, TypeError, json.JSONDecodeError):
                parsed = text
    values = parsed if isinstance(parsed, (list, tuple, set)) else [parsed]
    for item in values:
        if isinstance(item, dict):
            url = item.get("expanded_url") or item.get("url")
        else:
            url = item
        if url and str(url).strip():
            return str(url).strip()
    return ""


@st.cache_data(ttl=600, show_spinner="Loading sentiment-analysis data...")
def load_sentiment() -> pd.DataFrame:
    return prepare_sentiment()
