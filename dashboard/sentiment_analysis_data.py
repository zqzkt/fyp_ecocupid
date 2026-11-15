"""Data loading and aggregation for the sentiment-analysis dashboard."""

from __future__ import annotations

import ast
import json
import re

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


def _normalize_country(value: object) -> str:
    return COUNTRY_ALIASES.get(str(value).strip().upper(), str(value).strip())


def _same_month(values: pd.Series, month: pd.Timestamp) -> pd.Series:
    timestamp = pd.to_datetime(values, errors="coerce", utc=True)
    return timestamp.dt.tz_localize(None).dt.to_period("M").dt.to_timestamp().eq(month)


@st.cache_data(ttl=600, show_spinner=False)
def _load_monthly_topics() -> pd.DataFrame:
    return _load_table(
        "monthly_topic_stats",
        "country,month,topic_name,monthly_keywords,topic_rank",
        {"topic_rank": "lte.3"},
    )


def _split_keywords(value: object) -> set[str]:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return set()
    keywords = value if isinstance(value, list) else str(value).split(",")
    return {str(k).strip().casefold() for k in keywords if str(k).strip()}


def _name_fit(name: str, keywords: frozenset[str]) -> float:
    """Share of a topic name's words that appear in its keywords."""
    words = set(re.findall(r"\w+", name.casefold())) - {"and"}
    keyword_words = {word for keyword in keywords for word in re.findall(r"\w+", keyword)}
    return len(words & keyword_words) / len(words) if words else 0.0


@st.cache_data(ttl=600, show_spinner=False)
def _monthly_topics_by_month() -> pd.DataFrame:
    """monthly_topic_stats rows with "_month", normalised country/topic_name, and "bubble".

    "bubble" is the topic_name the topic is shown under. The topic registry fixes
    a topic's name when it is first detected, but its keywords are re-derived every
    month, so one month can hold differently named topics with identical keywords
    (October 2026: Singapore's "National Park" and Malaysia's "Air Pollution & Air
    Quality", both air pollution/air quality/haze). Those share one bubble, named
    after whichever of their topic_names best describes the keywords.
    """
    topics = _load_monthly_topics()
    if topics.empty:
        return topics.assign(_month=pd.Series(dtype="datetime64[ns]"), bubble=pd.Series(dtype=str))
    topics = topics.assign(
        _month=pd.to_datetime(topics["month"], errors="coerce", utc=True)
        .dt.tz_localize(None).dt.to_period("M").dt.to_timestamp(),
        country=topics["country"].map(_normalize_country),
        topic_name=topics["topic_name"].astype(str).str.strip(),
        _keywords=topics["monthly_keywords"].map(lambda value: frozenset(_split_keywords(value))),
    )
    topics["bubble"] = topics["topic_name"]
    for (_, keywords), group in topics.groupby(["_month", "_keywords"]):
        if keywords and group["topic_name"].nunique() > 1:
            names = sorted(group["topic_name"].unique())
            topics.loc[group.index, "bubble"] = max(names, key=lambda name: _name_fit(name, keywords))
    return topics.drop(columns="_keywords")


def bubble_name(month: pd.Timestamp, country: str, topic_name: str) -> str | None:
    """The bubble a country's monthly_topic_stats topic is shown under, or None if it isn't one."""
    topics = _monthly_topics_by_month()
    match = topics.loc[
        (topics["_month"] == month)
        & (topics["country"] == country)
        & topics["topic_name"].str.casefold().eq(str(topic_name).strip().casefold()),
        "bubble",
    ]
    return match.iloc[0] if not match.empty else None


def _topic_rows(month: pd.Timestamp, countries: list[str], topic: str) -> pd.DataFrame:
    """monthly_topic_stats rows shown under this bubble."""
    topics = _monthly_topics_by_month()
    return topics[
        (topics["_month"] == month)
        & topics["country"].isin(countries)
        & topics["bubble"].str.casefold().eq(topic.casefold())
    ]


def topic_keywords(
    month: pd.Timestamp,
    countries: list[str],
    topic: str,
) -> set[str]:
    """Casefolded monthly_keywords of this bubble's topics for the month and countries."""
    rows = _topic_rows(month, countries, topic)
    return set().union(*map(_split_keywords, rows["monthly_keywords"]))


def topic_match_terms(
    month: pd.Timestamp,
    countries: list[str],
    topic: str,
) -> set[str]:
    """Casefolded keywords that sentiment_analysis.py mapped to this bubble's topics."""
    # Instagram tags rows with the topic name rather than a keyword.
    names = set(_topic_rows(month, countries, topic)["topic_name"].str.casefold())
    return {topic.casefold()} | names | topic_keywords(month, countries, topic)


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
    sentiment = sentiment.dropna(subset=["_month", "total_items"])
    # "topic" becomes the bubble name; "topic_name" keeps the stored name. The
    # inner join drops rows that aren't a monthly_topic_stats topic for their
    # country and month. It is case-sensitive on purpose: sentiment_analysis.py
    # writes topic_name exactly, while an older version wrote lowercase keywords
    # (e.g. "climate change") that would otherwise pass as topic names.
    bubbles = _monthly_topics_by_month()[["_month", "country", "topic_name", "bubble"]]
    sentiment = sentiment.assign(topic_name=sentiment["topic"]).merge(
        bubbles.drop_duplicates(["_month", "country", "topic_name"]),
        on=["_month", "country", "topic_name"],
    )
    sentiment["topic"] = sentiment["bubble"]
    return sentiment.drop(columns="bubble")


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
    country = posts.get(
        "inferred_country", pd.Series(index=posts.index, dtype="object")
    ).map(_normalize_country)
    # Same posts sentiment_analysis.py scores: environmental ones only.
    environmental = posts.get(
        "is_environmental", pd.Series(False, index=posts.index)
    ).astype(str).str.lower().isin(("true", "1", "t"))
    posts = posts[
        _same_month(posts.get("posted_at"), month)
        & country.isin(countries)
        & environmental
    ].copy()
    # Match each post against its own country's keywords for this bubble, as
    # sentiment_analysis.py does; keywords are shared across unrelated topics
    # in other countries (e.g. "air pollution").
    terms_by_country = {
        name: topic_match_terms(month, [name], topic)
        for name in set(_topic_rows(month, countries, topic)["country"])
    }
    posts = posts[
        [
            bool(terms_by_country.get(post_country, set()) & {
                str(item).strip().casefold()
                for item in (value if isinstance(value, list) else str(value).split(","))
            })
            for post_country, value in zip(country[posts.index], posts["matched_keywords"])
        ]
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


def _summary_points(value: object) -> list[tuple[str, str]]:
    """Turn a stored Gemini summary into (heading, text) pairs; heading may be blank."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            value = {"Raw_Summary": value}
    if not isinstance(value, dict):
        return []
    raw = value.get("Raw_Summary")
    if isinstance(raw, str) and len(value) == 1:
        # Gemini sometimes wraps its JSON in a ```json fence, which the
        # generator then stores unparsed.
        unfenced = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip())
        try:
            parsed = json.loads(unfenced)
            value = parsed if isinstance(parsed, dict) else {"Raw_Summary": unfenced}
        except json.JSONDecodeError:
            value = {"Raw_Summary": unfenced}
    points = []
    for heading, text in value.items():
        text = str(text or "").strip()
        if not text:
            continue
        # Placeholder keys from the prompt template carry no meaning.
        generic = re.fullmatch(r"(?i)topic\s*\d+|raw_summary", str(heading).strip())
        points.append(("" if generic else str(heading).strip(), text))
    return points


@st.cache_data(ttl=600, show_spinner=False)
def _load_month_summaries(month_key: str) -> pd.DataFrame:
    return _load_table(
        "summary", "country,topic_name,month,keywords,summary", {"month": f"eq.{month_key}"}
    )


def load_country_summaries(
    month: pd.Timestamp,
    countries: list[str],
    topic: str,
) -> dict[str, dict[str, object]]:
    """Gemini discussion summaries for one bubble, keyed by country.

    Each value has "topic" (the bubble the summary's topic is shown under),
    "shared" (keywords it shares with this bubble; empty for an exact match) and
    "points". A summary matches exactly when its topic_name is shown under this
    bubble. A country without one falls back to its summary that
    shares the most of the bubble's monthly keywords. Keywords are compared rather
    than the topic name, because registry names can lag behind what a topic
    covers that month (e.g. a "National Park" topic whose keywords are haze).
    """
    summaries = _load_month_summaries(f"{month:%Y-%m-01}")
    if summaries.empty or not {"country", "topic_name", "summary"}.issubset(summaries.columns):
        return {}
    summaries = summaries[
        summaries["country"].map(_normalize_country).isin(countries)
    ].assign(
        country=lambda frame: frame["country"].map(_normalize_country),
        topic_name=lambda frame: frame["topic_name"].astype(str).str.strip(),
        summary_keywords=lambda frame: frame.get(
            "keywords", pd.Series(index=frame.index, dtype=object)
        ).map(_split_keywords),
    )
    summaries["bubble"] = [
        bubble_name(month, country, name) or name
        for country, name in zip(summaries["country"], summaries["topic_name"])
    ]
    keywords = topic_keywords(month, countries, topic)

    result: dict[str, dict[str, object]] = {}
    for country, rows in summaries.groupby("country"):
        exact = rows[rows["bubble"].str.casefold().eq(topic.casefold())]
        if not exact.empty:
            points = [point for value in exact["summary"] for point in _summary_points(value)]
            result[country] = {"topic": topic, "shared": [], "points": points}
            continue
        related = [
            (sorted(row.summary_keywords & keywords), row.bubble, row.summary)
            for row in rows.itertuples()
            if row.summary_keywords & keywords
        ]
        if related:
            shared, related_topic, value = min(related, key=lambda item: (-len(item[0]), item[1]))
            result[country] = {
                "topic": related_topic,
                "shared": shared,
                "points": _summary_points(value),
            }
    return result


@st.cache_data(ttl=600, show_spinner="Loading sentiment-analysis data...")
def load_sentiment() -> pd.DataFrame:
    return prepare_sentiment()
