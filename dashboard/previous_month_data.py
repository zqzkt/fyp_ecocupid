"""Load collection status and summary counts for the previous calendar month."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any

import pandas as pd
import requests
import streamlit as st

from load_data import DashboardDataError, REQUEST_TIMEOUT, _credentials, _headers

PAGE_SIZE = 1000
PLATFORMS = ("facebook", "instagram", "reddit", "x", "youtube")
SOCIAL_TABLE_DATE_COLUMNS = {
    "clean_posts": "posted_at",
    "clean_comments": "posted_at",
    "facebook_posts": "published_at",
    "facebook_comments": "published_at",
    "instagram_posts": "posted_at",
    "instagram_comments": "comment_created_at",
    "reddit_posts": "created_at",
    "reddit_comments": "comment_created_at",
    "x_posts": "created_at",
    "x_replies": "created_at",
    "youtube_videos": "published_date",
}
SOCIAL_TABLES = (
    "clean_posts",
    "clean_comments",
    "facebook_comments",
    "facebook_posts",
    "instagram_comments",
    "instagram_posts",
    "reddit_comments",
    "reddit_posts",
    "x_posts",
    "x_replies",
    "youtube_comments",
    "youtube_videos",
)
PLATFORM_NAMES = {
    "facebook": "Facebook",
    "instagram": "Instagram",
    "reddit": "Reddit",
    "x": "X",
    "youtube": "YouTube",
}


def _fetch_rows(
    base_url: str,
    key: str,
    table: str,
    params: dict[str, str],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    offset = 0
    while True:
        page_params = {
            **params,
            "limit": str(PAGE_SIZE),
            "offset": str(offset),
        }
        endpoint = f"{base_url}/rest/v1/{table}"
        try:
            response = requests.get(
                endpoint,
                params=page_params,
                headers=_headers(key, with_bearer=True),
                timeout=REQUEST_TIMEOUT,
            )
            if (
                response.status_code in {401, 403}
                and "jwt" in response.text.lower()
            ):
                response = requests.get(
                    endpoint,
                    params=page_params,
                    headers=_headers(key, with_bearer=False),
                    timeout=REQUEST_TIMEOUT,
                )
        except requests.RequestException as exc:
            raise DashboardDataError(
                f"Could not reach Supabase: {type(exc).__name__}"
            ) from exc

        if not response.ok:
            raise DashboardDataError(
                f"{table} lookup failed "
                f"({response.status_code}): {response.text[:500]}"
            )

        try:
            page = response.json()
        except ValueError as exc:
            raise DashboardDataError(
                f"{table} returned a response that is not JSON"
            ) from exc

        rows.extend(page)
        if len(page) < PAGE_SIZE:
            return rows
        offset += len(page)


@st.cache_data(
    ttl=60,
    show_spinner="Loading previous month's collected data...",
)
def load_previous_month_data() -> tuple[
    date,
    pd.DataFrame,
    pd.DataFrame,
    dict[str, pd.DataFrame],
]:
    """Return previous-month summaries and full collected table records."""
    today = date.today()
    current_month_start = today.replace(day=1)
    month_start = (current_month_start - timedelta(days=1)).replace(day=1)
    start_time = datetime.combine(
        month_start,
        time.min,
        tzinfo=timezone.utc,
    ).isoformat()
    end_time = datetime.combine(
        current_month_start,
        time.min,
        tzinfo=timezone.utc,
    ).isoformat()

    base_url, key = _credentials()
    month = month_start.isoformat()
    news_rows = _fetch_rows(
        base_url,
        key,
        "monthly_topic_stats",
        {
            "select": "month,country,topic_id,topic_name,article_count,topic_rank",
            "month": f"eq.{month}",
            "order": "country.asc,topic_rank.asc",
        },
    )
    news_data_rows = _fetch_rows(
        base_url,
        key,
        "news_cleaned",
        {
            "select": "*",
            "and": f"(published_at.gte.{start_time},published_at.lt.{end_time})",
        },
    )
    social_tables: dict[str, pd.DataFrame] = {}
    for table in SOCIAL_TABLES:
        if table == "youtube_comments":
            social_tables[table] = pd.DataFrame()
            continue
        timestamp_column = SOCIAL_TABLE_DATE_COLUMNS[table]
        period_start, period_end = (
            (month_start.isoformat(), current_month_start.isoformat())
            if timestamp_column == "published_date"
            else (start_time, end_time)
        )
        rows = _fetch_rows(
            base_url,
            key,
            table,
            {
                "select": "*",
                "and": (
                    f"({timestamp_column}.gte.{period_start},"
                    f"{timestamp_column}.lt.{period_end})"
                ),
            },
        )
        social_tables[table] = pd.DataFrame(rows)

    youtube_video_rows = social_tables["youtube_videos"]
    if not youtube_video_rows.empty and "video_id" in youtube_video_rows:
        video_ids = youtube_video_rows["video_id"].dropna().astype(str).tolist()
        youtube_comments: list[dict[str, Any]] = []
        for batch_start in range(0, len(video_ids), 50):
            batch = video_ids[batch_start : batch_start + 50]
            video_filter = ",".join(f'"{video_id}"' for video_id in batch)
            youtube_comments.extend(
                _fetch_rows(
                    base_url,
                    key,
                    "youtube_comments",
                    {
                        "select": "*",
                        "video_id": f"in.({video_filter})",
                    },
                )
            )
        social_tables["youtube_comments"] = pd.DataFrame(youtube_comments)

    news = pd.DataFrame(news_rows)
    if news.empty:
        news_summary = pd.DataFrame(
            columns=[
                "country",
                "topic_count",
                "topic_article_assignments",
                "top_topic",
                "top_topic_article_count",
            ]
        )
    else:
        news["article_count"] = pd.to_numeric(
            news["article_count"],
            errors="coerce",
        ).fillna(0)
        top_topics = (
            news.sort_values(
                ["country", "article_count", "topic_name"],
                ascending=[True, False, True],
            )
            .drop_duplicates("country")
            .set_index("country")
        )
        news_summary = (
            news.groupby("country", as_index=False)
            .agg(
                topic_count=("topic_id", "nunique"),
                topic_article_assignments=("article_count", "sum"),
            )
            .merge(
                top_topics[["topic_name", "article_count"]],
                left_on="country",
                right_index=True,
                how="left",
            )
            .rename(
                columns={
                    "topic_name": "top_topic",
                    "article_count": "top_topic_article_count",
                }
            )
            .sort_values("country")
            .reset_index(drop=True)
        )

    social_posts = social_tables["clean_posts"]
    social_comments = social_tables["clean_comments"]
    summary_rows: list[dict[str, Any]] = []
    for platform in PLATFORMS:
        platform_posts = (
            social_posts[social_posts["platform"].str.casefold() == platform]
            if not social_posts.empty
            else pd.DataFrame()
        )
        platform_comments = (
            social_comments[
                social_comments["platform"].str.casefold() == platform
            ]
            if not social_comments.empty
            else pd.DataFrame()
        )
        environmental_count = 0
        if not platform_posts.empty:
            environmental_count = int(
                platform_posts["is_environmental"]
                .map(
                    lambda value: str(value).strip().casefold() == "true"
                )
                .sum()
            )
        summary_rows.append(
            {
                "platform": PLATFORM_NAMES[platform],
                "environmental_posts": environmental_count,
                "comments": len(platform_comments),
            }
        )

    social_summary = pd.DataFrame(summary_rows)
    return (
        month_start,
        news_summary,
        social_summary,
        {"news_cleaned": pd.DataFrame(news_data_rows)},
        social_tables,
    )
