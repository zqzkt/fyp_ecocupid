"""
engagement_metric_comparison.py

EcoCupid Communication Framework - backend engagement calculations.

Loads BOTH clean_posts and clean_comments from Supabase and provides:
1. Country comparison within a selected platform
2. Overall platform comparison
3. Platform x country comparison
4. A switch to INCLUDE or EXCLUDE engagement received by comments

Definitions
-----------
Post engagement:
    likes + replies + reposts + quotes on posts

Comment engagement:
    likes + replies + reposts + quotes received by comment rows

Total engagement when include_comment_engagement=False:
    post engagement only

Total engagement when include_comment_engagement=True:
    post engagement + comment engagement

Important:
- reply_count on a post remains part of post engagement. It represents the audience
  action of replying/commenting on that post.
- A comment's own likes/replies/etc. are separate engagement actions received by
  that comment, so they are added only when comment engagement is enabled.
- Reach/impressions remain POST-level metrics. Comment rows are not added to reach.
"""

from __future__ import annotations

import json
import os
from typing import Any, Iterable

import numpy as np
import pandas as pd
from dotenv import load_dotenv
from supabase import Client, create_client


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

load_dotenv()

POSTS_TABLE = os.getenv("SOCIAL_POSTS_TABLE", "clean_posts")
COMMENTS_TABLE = os.getenv("SOCIAL_COMMENTS_TABLE", "clean_comments")
PAGE_SIZE = 1000

ENGAGEMENT_COLUMNS = [
    "like_count",
    "reply_count",
    "repost_count",
    "quote_count",
]

COMMON_COLUMNS = [
    "id",
    "source_id",
    "platform",
    "source_type",
    "inferred_country",
    "matched_keywords",
    "like_count",
    "reply_count",
    "repost_count",
    "quote_count",
    "impression_count",
    "total_engagement",
    "posted_at",
]

COUNTRY_MAP = {
    "SG": "Singapore",
    "SINGAPORE": "Singapore",
    "MY": "Malaysia",
    "MALAYSIA": "Malaysia",
    "ID": "Indonesia",
    "INDONESIA": "Indonesia",
    "TH": "Thailand",
    "THAILAND": "Thailand",
    "PH": "Philippines",
    "PHILIPPINES": "Philippines",
    "BN": "Brunei",
    "BRUNEI": "Brunei",
    "BRUNEI DARUSSALAM": "Brunei",
}

PLATFORM_MAP = {
    "youtube": "YouTube",
    "x": "X",
    "twitter": "X",
    "reddit": "Reddit",
    "instagram": "Instagram",
}

REACH_PLATFORMS = {"YouTube", "X"}


class EngagementDataError(RuntimeError):
    """Raised when engagement data cannot be loaded or processed."""


# ---------------------------------------------------------------------------
# Supabase connection / loading
# ---------------------------------------------------------------------------

def db() -> Client:
    """Create a Supabase client using credentials from .env."""
    url = os.getenv("SUPABASE_URL")
    key = (
        os.getenv("SUPABASE_KEY")
        or os.getenv("SUPABASE_ANON_KEY")
        or os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    )

    if not url or not key:
        raise EngagementDataError(
            "Missing Supabase credentials. Set SUPABASE_URL and SUPABASE_KEY "
            "(or SUPABASE_ANON_KEY / SUPABASE_SERVICE_ROLE_KEY) in .env."
        )

    return create_client(url, key)


def _load_table(client: Client, table_name: str) -> pd.DataFrame:
    """Load an entire Supabase table using pagination."""
    rows: list[dict[str, Any]] = []
    start = 0

    try:
        while True:
            response = (
                client.table(table_name)
                .select(",".join(COMMON_COLUMNS))
                .range(start, start + PAGE_SIZE - 1)
                .execute()
            )

            batch = response.data or []
            rows.extend(batch)

            if len(batch) < PAGE_SIZE:
                break

            start += PAGE_SIZE

    except Exception as exc:
        raise EngagementDataError(
            f"Failed to load data from '{table_name}': {exc}"
        ) from exc

    return pd.DataFrame(rows, columns=COMMON_COLUMNS)


def load_engagement_data(
    client: Client | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load both posts and comments from Supabase."""
    client = client or db()

    posts = _load_table(client, POSTS_TABLE)
    comments = _load_table(client, COMMENTS_TABLE)

    return posts, comments


# ---------------------------------------------------------------------------
# Standardisation
# ---------------------------------------------------------------------------

def _normalise_country(value: Any) -> Any:
    if pd.isna(value):
        return np.nan

    text = str(value).strip()
    if not text:
        return np.nan

    return COUNTRY_MAP.get(text.upper(), text.title())


def _normalise_platform(value: Any) -> Any:
    if pd.isna(value):
        return np.nan

    text = str(value).strip()
    if not text:
        return np.nan

    return PLATFORM_MAP.get(text.lower(), text)


def prepare_content(df: pd.DataFrame, content_type: str) -> pd.DataFrame:
    """Standardise either the posts or comments DataFrame."""
    if df.empty:
        result = df.copy()
        result["content_type"] = content_type
        return result

    result = df.copy()

    result["country"] = result["inferred_country"].apply(_normalise_country)
    result["platform"] = result["platform"].apply(_normalise_platform)
    result["content_type"] = content_type

    for column in ENGAGEMENT_COLUMNS:
        result[column] = pd.to_numeric(
            result[column], errors="coerce"
        ).fillna(0)

    result["impression_count"] = pd.to_numeric(
        result["impression_count"], errors="coerce"
    )

    # Recalculate rather than trusting a stored total so the definition is
    # identical for posts and comments.
    result["calculated_engagement"] = result[ENGAGEMENT_COLUMNS].sum(axis=1)

    result["posted_at"] = pd.to_datetime(
        result["posted_at"], errors="coerce", utc=True
    )

    return result


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------

def _parse_keywords(value: Any) -> list[str]:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return []

    if isinstance(value, list):
        return [str(item).strip() for item in value]

    text = str(value).strip()
    if not text:
        return []

    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return [str(item).strip() for item in parsed]
    except (json.JSONDecodeError, TypeError):
        pass

    return [text]


def filter_by_topic(df: pd.DataFrame, topic: str | None) -> pd.DataFrame:
    """
    Temporary topic filtering using matched_keywords.

    Replace this later with topic_id/topic_name filtering when the social
    topic-modelling output is connected.
    """
    if not topic or df.empty:
        return df.copy()

    target = topic.strip().casefold()

    mask = df["matched_keywords"].apply(
        lambda value: any(
            keyword.casefold() == target
            for keyword in _parse_keywords(value)
        )
    )

    return df.loc[mask].copy()


def filter_content(
    df: pd.DataFrame,
    *,
    topic: str | None = None,
    platforms: Iterable[str] | None = None,
    countries: Iterable[str] | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> pd.DataFrame:
    """Apply the same filters to posts and comments."""
    result = filter_by_topic(df, topic)

    if platforms:
        wanted = {_normalise_platform(p) for p in platforms}
        result = result[result["platform"].isin(wanted)]

    if countries:
        wanted = {_normalise_country(c) for c in countries}
        result = result[result["country"].isin(wanted)]

    if start_date:
        start = pd.Timestamp(start_date, tz="UTC")
        result = result[result["posted_at"] >= start]

    if end_date:
        end = pd.Timestamp(end_date, tz="UTC")
        if len(str(end_date)) <= 10:
            end = end + pd.Timedelta(days=1) - pd.Timedelta(microseconds=1)
        result = result[result["posted_at"] <= end]

    return result.copy()


# ---------------------------------------------------------------------------
# Aggregation helpers
# ---------------------------------------------------------------------------

def _aggregate_content(
    df: pd.DataFrame,
    group_by: list[str],
    prefix: str,
) -> pd.DataFrame:
    """Aggregate posts or comments before merging the two result sets."""
    metric_columns = [
        f"{prefix}_count",
        f"{prefix}_engagement",
        f"{prefix}_likes",
        f"{prefix}_replies",
        f"{prefix}_reposts",
        f"{prefix}_quotes",
    ]

    if df.empty:
        return pd.DataFrame(columns=group_by + metric_columns)

    grouped = (
        df.groupby(group_by, dropna=False)
        .agg(
            **{
                f"{prefix}_count": ("source_id", "size"),
                f"{prefix}_engagement": ("calculated_engagement", "sum"),
                f"{prefix}_likes": ("like_count", "sum"),
                f"{prefix}_replies": ("reply_count", "sum"),
                f"{prefix}_reposts": ("repost_count", "sum"),
                f"{prefix}_quotes": ("quote_count", "sum"),
            }
        )
        .reset_index()
    )

    return grouped


def _aggregate_post_distribution(
    posts: pd.DataFrame,
    group_by: list[str],
) -> pd.DataFrame:
    """
    Calculate per-post distribution metrics.

    These remain post-based even when comment engagement is included because
    the denominator is the number of original posts/content items.
    """
    columns = group_by + [
        "avg_post_engagement",
        "median_post_engagement",
        "total_impressions",
    ]

    if posts.empty:
        return pd.DataFrame(columns=columns)

    result = (
        posts.groupby(group_by, dropna=False)
        .agg(
            avg_post_engagement=("calculated_engagement", "mean"),
            median_post_engagement=("calculated_engagement", "median"),
            total_impressions=("impression_count", lambda s: s.sum(min_count=1)),
        )
        .reset_index()
    )

    return result


def calculate_metrics(
    posts: pd.DataFrame,
    comments: pd.DataFrame,
    group_by: list[str],
    *,
    include_comment_engagement: bool = False,
) -> pd.DataFrame:
    """
    Calculate engagement metrics for the requested grouping.

    If include_comment_engagement=True:
        total_engagement = post_engagement + comment_engagement

    Otherwise:
        total_engagement = post_engagement

    Average engagement per post follows the same switch:
        total selected engagement / number of posts

    Median engagement per post remains the median of direct post engagement,
    because comment engagement would need to be linked back to each individual
    parent post before a true combined per-post median can be calculated.
    """
    post_summary = _aggregate_content(posts, group_by, "post")
    comment_summary = _aggregate_content(comments, group_by, "comment")
    post_distribution = _aggregate_post_distribution(posts, group_by)

    # Keep groups that have posts. This prevents a comment-only group from
    # appearing as a communication channel with zero original posts.
    result = post_summary.merge(
        comment_summary,
        on=group_by,
        how="left",
    ).merge(
        post_distribution,
        on=group_by,
        how="left",
    )

    if result.empty:
        return result

    comment_columns = [
        "comment_count",
        "comment_engagement",
        "comment_likes",
        "comment_replies",
        "comment_reposts",
        "comment_quotes",
    ]

    for column in comment_columns:
        if column not in result.columns:
            result[column] = 0
        result[column] = result[column].fillna(0)

    numeric_columns = [
        "post_count",
        "post_engagement",
        "post_likes",
        "post_replies",
        "post_reposts",
        "post_quotes",
    ] + comment_columns

    for column in numeric_columns:
        result[column] = pd.to_numeric(
            result[column], errors="coerce"
        ).fillna(0)

    if include_comment_engagement:
        result["total_engagement"] = (
            result["post_engagement"] + result["comment_engagement"]
        )
    else:
        result["total_engagement"] = result["post_engagement"]

    result["avg_engagement_per_post"] = np.where(
        result["post_count"] > 0,
        result["total_engagement"] / result["post_count"],
        np.nan,
    )

    # Reach belongs to the original post, not its comments.
    result["reach_to_engagement_ratio"] = np.nan
    result["engagement_rate_pct"] = np.nan

    for index, row in result.iterrows():
        platform = row["platform"] if "platform" in result.columns else None
        impressions = row["total_impressions"]
        engagement = row["total_engagement"]

        if (
            platform in REACH_PLATFORMS
            and pd.notna(impressions)
            and engagement > 0
        ):
            result.at[index, "reach_to_engagement_ratio"] = (
                impressions / engagement
            )

        if (
            platform in REACH_PLATFORMS
            and pd.notna(impressions)
            and impressions > 0
        ):
            result.at[index, "engagement_rate_pct"] = (
                engagement / impressions * 100
            )

    result["comment_engagement_included"] = include_comment_engagement

    round_columns = [
        "avg_post_engagement",
        "median_post_engagement",
        "avg_engagement_per_post",
        "reach_to_engagement_ratio",
        "engagement_rate_pct",
    ]

    for column in round_columns:
        if column in result.columns:
            result[column] = result[column].round(2)

    integer_columns = [
        "post_count",
        "post_engagement",
        "post_likes",
        "post_replies",
        "post_reposts",
        "post_quotes",
        "comment_count",
        "comment_engagement",
        "comment_likes",
        "comment_replies",
        "comment_reposts",
        "comment_quotes",
        "total_engagement",
    ]

    for column in integer_columns:
        if column in result.columns:
            result[column] = result[column].astype(int)

    return result


# ---------------------------------------------------------------------------
# Communication Framework comparisons
# ---------------------------------------------------------------------------

def compare_countries_within_platform(
    posts: pd.DataFrame,
    comments: pd.DataFrame,
    platform: str,
    *,
    include_comment_engagement: bool = False,
) -> pd.DataFrame:
    """Compare engagement between countries for one selected platform."""
    platform = _normalise_platform(platform)

    post_subset = posts[posts["platform"] == platform].copy()
    comment_subset = comments[comments["platform"] == platform].copy()

    result = calculate_metrics(
        post_subset,
        comment_subset,
        ["platform", "country"],
        include_comment_engagement=include_comment_engagement,
    )

    if not result.empty:
        result = result.sort_values(
            ["avg_engagement_per_post", "total_engagement"],
            ascending=[False, False],
        ).reset_index(drop=True)

    return result


def compare_platforms(
    posts: pd.DataFrame,
    comments: pd.DataFrame,
    *,
    include_comment_engagement: bool = False,
) -> pd.DataFrame:
    """Compare engagement across platforms overall."""
    result = calculate_metrics(
        posts,
        comments,
        ["platform"],
        include_comment_engagement=include_comment_engagement,
    )

    if not result.empty:
        result = result.sort_values(
            ["avg_engagement_per_post", "total_engagement"],
            ascending=[False, False],
        ).reset_index(drop=True)

    return result


def compare_platforms_by_country(
    posts: pd.DataFrame,
    comments: pd.DataFrame,
    *,
    include_comment_engagement: bool = False,
) -> pd.DataFrame:
    """Compare every available platform-country combination."""
    result = calculate_metrics(
        posts,
        comments,
        ["platform", "country"],
        include_comment_engagement=include_comment_engagement,
    )

    if not result.empty:
        result = result.sort_values(
            ["country", "avg_engagement_per_post"],
            ascending=[True, False],
        ).reset_index(drop=True)

    return result


def get_engagement_comparison(
    *,
    topic: str | None = None,
    platform: str | None = None,
    countries: Iterable[str] | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    include_comment_engagement: bool = False,
    client: Client | None = None,
) -> dict[str, pd.DataFrame]:
    """
    Main function for the future frontend.

    The future UI checkbox/toggle can map directly to:
        include_comment_engagement=True/False
    """
    raw_posts, raw_comments = load_engagement_data(client)

    posts = prepare_content(raw_posts, "post")
    comments = prepare_content(raw_comments, "comment")

    filter_args = {
        "topic": topic,
        "countries": countries,
        "start_date": start_date,
        "end_date": end_date,
    }

    posts = filter_content(posts, **filter_args)
    comments = filter_content(comments, **filter_args)

    within_platform = pd.DataFrame()

    if platform:
        within_platform = compare_countries_within_platform(
            posts,
            comments,
            platform,
            include_comment_engagement=include_comment_engagement,
        )

    return {
        "within_platform": within_platform,
        "across_platforms": compare_platforms(
            posts,
            comments,
            include_comment_engagement=include_comment_engagement,
        ),
        "platform_country": compare_platforms_by_country(
            posts,
            comments,
            include_comment_engagement=include_comment_engagement,
        ),
    }


# ---------------------------------------------------------------------------
# Terminal output / manual sanity check
# ---------------------------------------------------------------------------

def _print_selected_columns(
    title: str,
    df: pd.DataFrame,
) -> None:
    """Print a compact set of useful columns to the terminal."""
    print()
    print("=" * 90)
    print(title)
    print("=" * 90)

    if df.empty:
        print("No matching data.")
        return

    preferred = [
        "platform",
        "country",
        "post_count",
        "comment_count",
        "post_engagement",
        "comment_engagement",
        "total_engagement",
        "avg_engagement_per_post",
        "median_post_engagement",
        "total_impressions",
        "reach_to_engagement_ratio",
        "engagement_rate_pct",
    ]

    available = [column for column in preferred if column in df.columns]

    print(df[available].to_string(index=False))


if __name__ == "__main__":
    """
    No automated test suite is required for this project.

    Run:
        python engagement_metric_comparison.py

    The terminal prints real calculations from Supabase twice:
    1. excluding engagement received by comments
    2. including engagement received by comments

    This makes it easy to manually verify that the comment toggle changes the
    totals while the number of original posts and impressions stay unchanged.
    """

    try:
        raw_posts, raw_comments = load_engagement_data()

        posts = prepare_content(raw_posts, "post")
        comments = prepare_content(raw_comments, "comment")

        print()
        print("=" * 90)
        print("ENGAGEMENT METRIC COMPARISON - SUPABASE DATA CHECK")
        print("=" * 90)
        print(f"Posts loaded:    {len(posts):,}")
        print(f"Comments loaded: {len(comments):,}")
        print(f"Platforms:       {', '.join(sorted(posts['platform'].dropna().unique()))}")
        print(f"Countries:       {', '.join(sorted(posts['country'].dropna().unique()))}")

        # ---------------------------------------------------------------
        # 1. Cross-platform WITHOUT comment engagement
        # ---------------------------------------------------------------
        without_comments = compare_platforms(
            posts,
            comments,
            include_comment_engagement=False,
        )

        _print_selected_columns(
            "1. ACROSS PLATFORMS - COMMENT ENGAGEMENT EXCLUDED",
            without_comments,
        )

        # ---------------------------------------------------------------
        # 2. Cross-platform WITH comment engagement
        # ---------------------------------------------------------------
        with_comments = compare_platforms(
            posts,
            comments,
            include_comment_engagement=True,
        )

        _print_selected_columns(
            "2. ACROSS PLATFORMS - COMMENT ENGAGEMENT INCLUDED",
            with_comments,
        )

        # ---------------------------------------------------------------
        # 3. Example within-platform comparison: YouTube by country
        # ---------------------------------------------------------------
        youtube_countries = compare_countries_within_platform(
            posts,
            comments,
            "YouTube",
            include_comment_engagement=True,
        )

        _print_selected_columns(
            "3. YOUTUBE BY COUNTRY - COMMENT ENGAGEMENT INCLUDED",
            youtube_countries,
        )

        # ---------------------------------------------------------------
        # 4. Platform x country comparison
        # ---------------------------------------------------------------
        platform_country = compare_platforms_by_country(
            posts,
            comments,
            include_comment_engagement=True,
        )

        _print_selected_columns(
            "4. PLATFORM x COUNTRY - COMMENT ENGAGEMENT INCLUDED",
            platform_country,
        )

        print()
        print("=" * 90)
        print("CHECK COMPLETE")
        print("=" * 90)
        print(
            "Compare sections 1 and 2. When comments are included, "
            "post_count and impressions should stay the same, while "
            "total_engagement can increase."
        )

    except EngagementDataError as exc:
        print(f"ERROR: {exc}")