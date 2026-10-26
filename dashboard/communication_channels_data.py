"""Supabase data access and recommendation logic for communication channels."""

from __future__ import annotations

import ast
import json
import os
from typing import Any

import pandas as pd
import requests
import streamlit as st
from dotenv import load_dotenv


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(REPO_ROOT, ".env"))

PAGE_SIZE = 1000
REQUEST_TIMEOUT = 60
COUNTRY_ALIASES = {
    "BN": "Brunei",
    "Brunei": "Brunei",
    "ID": "Indonesia",
    "Indonesia": "Indonesia",
    "MY": "Malaysia",
    "Malaysia": "Malaysia",
    "PH": "Philippines",
    "Philippines": "Philippines",
    "SG": "Singapore",
    "Singapore": "Singapore",
    "TH": "Thailand",
    "Thailand": "Thailand",
}


class CommunicationChannelsDataError(RuntimeError):
    """Raised when communication-channel data cannot be loaded."""


def _credentials() -> tuple[str, str]:
    url = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
    key = (
        os.environ.get("SUPABASE_SECRET_KEY")
        or os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
        or os.environ.get("SUPABASE_KEY")
        or ""
    ).strip()
    if not url or not key:
        raise CommunicationChannelsDataError(
            "SUPABASE_URL and a Supabase key are required in .env."
        )
    return url, key


def _headers(key: str) -> dict[str, str]:
    return {"apikey": key, "Authorization": f"Bearer {key}"}


def _load_table(table: str, columns: str = "*") -> pd.DataFrame:
    base_url, key = _credentials()
    rows: list[dict[str, Any]] = []
    offset = 0

    while True:
        response = requests.get(
            f"{base_url}/rest/v1/{table}",
            params={
                "select": columns,
                "limit": str(PAGE_SIZE),
                "offset": str(offset),
            },
            headers=_headers(key),
            timeout=REQUEST_TIMEOUT,
        )
        if response.status_code == 404:
            return pd.DataFrame()
        if not response.ok:
            raise CommunicationChannelsDataError(
                f"{table} lookup failed ({response.status_code}): "
                f"{response.text[:300]}"
            )
        page = response.json()
        if not page:
            break
        rows.extend(page)
        if len(page) < PAGE_SIZE:
            break
        offset += len(page)

    return pd.DataFrame(rows)


@st.cache_data(ttl=600, show_spinner="Loading communication channel data...")
def load_framework_data() -> dict[str, pd.DataFrame]:
    """Load the cleaned posts and comments used by this page."""
    return {
        "posts": _load_table("clean_posts"),
        "comments": _load_table("clean_comments"),
    }


def _as_list(value: Any) -> list[str]:
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return []
    text = str(value).strip()
    if not text:
        return []
    for parser in (json.loads, ast.literal_eval):
        try:
            parsed = parser(text)
        except (ValueError, SyntaxError, TypeError, json.JSONDecodeError):
            continue
        if isinstance(parsed, (list, tuple, set)):
            return [str(item).strip() for item in parsed if str(item).strip()]
    return [item.strip() for item in text.split(",") if item.strip()]


def _matches_topic(value: Any, terms: set[str]) -> bool:
    values = {item.casefold() for item in _as_list(value)}
    return bool(values & terms)


def normalize_country(value: Any) -> str:
    """Use the six dashboard country names for country selectors and joins."""
    value = str(value or "").strip()
    return COUNTRY_ALIASES.get(value, value)


def add_date_columns(
    frame: pd.DataFrame,
    source_type: str,
) -> pd.DataFrame:
    """Derive filter dates from the timestamp defined for each clean table."""
    result = frame.copy()
    if source_type == "comments":
        activity_time = result.get(
            "parent_posted_at",
            pd.Series(index=result.index, dtype="object"),
        )
        activity_time = activity_time.fillna(
            result.get("posted_at", pd.Series(index=result.index, dtype="object"))
        )
    else:
        activity_time = result.get(
            "posted_at",
            pd.Series(index=result.index, dtype="object"),
        )

    timestamp = pd.to_datetime(activity_time, errors="coerce", utc=True)
    result["_year"] = timestamp.dt.year
    result["_month"] = timestamp.dt.tz_localize(None).dt.to_period("M").dt.to_timestamp()
    result["_country"] = result.get(
        "inferred_country", pd.Series(index=result.index)
    ).map(normalize_country)
    return result


def topic_options(data: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Extract country/topic choices from matched keywords in clean tables."""
    rows: list[dict[str, str]] = []
    for source_type in ("posts", "comments"):
        frame = add_date_columns(data[source_type], source_type)
        if frame.empty:
            continue
        for _, row in frame.iterrows():
            country = normalize_country(row.get("_country"))
            if not country:
                continue
            rows.extend(
                {"country": country, "topic": topic}
                for topic in _as_list(row.get("matched_keywords"))
            )
    if not rows:
        return pd.DataFrame(columns=["country", "topic"])
    return pd.DataFrame(rows).drop_duplicates().sort_values(["country", "topic"])


def recommend_channels(
    data: dict[str, pd.DataFrame],
    country: str,
    topic: str | list[str],
) -> tuple[pd.DataFrame, dict[str, int]]:
    """Rank platforms using activity volume and engagement for one or more keywords."""
    topics = [topic] if isinstance(topic, str) else topic
    terms = {term.casefold() for term in topics}
    activity_frames = []
    for source_type in ("posts", "comments"):
        frame = add_date_columns(data[source_type], source_type)
        if frame.empty:
            continue
        frame = frame[
            frame["_country"].str.casefold() == country.casefold()
        ].copy()
        if frame.empty:
            continue
        frame = frame[
            frame["matched_keywords"].apply(lambda value: _matches_topic(value, terms))
        ].copy()
        frame["source_type"] = source_type[:-1]
        activity_frames.append(frame)

    if not activity_frames:
        return pd.DataFrame(), {"activity_rows": 0}

    activity = pd.concat(activity_frames, ignore_index=True)
    activity["platform"] = activity["platform"].fillna("Unknown").astype(str)
    engagement = pd.to_numeric(
        activity["total_engagement"]
        if "total_engagement" in activity
        else pd.Series(0, index=activity.index),
        errors="coerce",
    ).fillna(0)
    activity["_engagement"] = engagement

    summary = (
        activity.groupby("platform", as_index=False)
        .agg(
            activity_items=("platform", "size"),
            total_engagement=("_engagement", "sum"),
            avg_engagement=("_engagement", "mean"),
            posts=("source_type", lambda values: (values == "post").sum()),
            comments=("source_type", lambda values: (values == "comment").sum()),
        )
    )

    max_engagement = max(float(summary["total_engagement"].max()), 1.0)
    max_items = max(float(summary["activity_items"].max()), 1.0)
    summary["engagement_score"] = summary["total_engagement"] / max_engagement
    summary["activity_score"] = summary["activity_items"] / max_items
    summary["score"] = (
        summary["engagement_score"] * 0.6
        + summary["activity_score"] * 0.4
    )
    summary["recommendation"] = summary.apply(
        lambda row: (
            "Primary channel"
            if row["score"] >= summary["score"].max() * 0.75
            else "Secondary channel"
        ),
        axis=1,
    )
    summary["engagement_score"] = (summary["score"] * 100).round(1)
    summary = summary.rename(columns={"engagement_score": "recommendation_score"})
    summary = summary.sort_values(
        ["score", "total_engagement", "activity_items"],
        ascending=False,
    )
    return summary, {
        "activity_rows": len(activity),
    }
