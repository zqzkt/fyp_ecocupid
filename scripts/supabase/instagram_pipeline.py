"""Upsert collected Instagram data into Supabase."""

from __future__ import annotations

import math
import os
from typing import Any

import requests
from dotenv import load_dotenv

from scripts.supabase.reddit_pipeline import upsert_batches

POST_COLUMNS = (
    "topic",
    "country",
    "hashtag",
    "post_id",
    "post_url",
    "caption",
    "posted_at",
    "author_username",
    "author_full_name",
    "author_follower_count",
    "author_is_verified",
    "like_count",
    "comment_count",
    "engagement_count",
    "engagement_rate",
    "media_type",
    "is_reel",
    "play_count",
)

COMMENT_COLUMNS = (
    "topic",
    "country",
    "hashtag",
    "post_id",
    "post_url",
    "post_author_username",
    "comment_id",
    "comment_text",
    "comment_username",
    "comment_created_at",
    "comment_like_count",
)


def monthly_keyword_specs(month: str | None = None) -> list[dict[str, str]]:
    """Read top-three monthly keywords with their topic and country."""
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
    load_dotenv(os.path.join(repo_root, ".env"))

    base_url = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
    if base_url.endswith("/rest/v1"):
        base_url = base_url[: -len("/rest/v1")].rstrip("/")
    key = (
        os.environ.get("SUPABASE_SECRET_KEY")
        or os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
        or os.environ.get("SUPABASE_KEY")
        or ""
    ).strip()
    if not base_url or not key:
        raise SystemExit("SUPABASE_URL and SUPABASE_KEY (or SUPABASE_SECRET_KEY) are required in .env")

    params: dict[str, str | int] = {
        "select": "country,topic_name,topic_rank,monthly_keywords,month",
        "topic_rank": "lte.3",
        "order": "month.desc,topic_rank.asc",
        "limit": "1000",
    }
    if month:
        params["month"] = f"eq.{month}"

    headers = {"apikey": key, "Authorization": f"Bearer {key}"}
    response = requests.get(
        f"{base_url}/rest/v1/monthly_topic_stats",
        params=params,
        headers=headers,
        timeout=60,
    )
    if response.status_code in {401, 403} and "jwt" in response.text.lower():
        response = requests.get(
            f"{base_url}/rest/v1/monthly_topic_stats",
            params=params,
            headers={"apikey": key},
            timeout=60,
        )
    if not response.ok:
        raise SystemExit(f"monthly_topic_stats lookup failed ({response.status_code}): {response.text[:1200]}")

    rows = response.json()
    if not month and rows:
        newest_month = max(row.get("month", "") for row in rows)
        rows = [row for row in rows if row.get("month") == newest_month]

    specs: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for row in rows:
        country = str(row.get("country") or "").strip()
        topic = str(row.get("topic_name") or "").strip()
        raw_keywords = row.get("monthly_keywords") or ""
        keywords = raw_keywords if isinstance(raw_keywords, list) else str(raw_keywords).split(",")
        for raw_keyword in keywords:
            keyword = str(raw_keyword).strip()
            identity = (country.casefold(), topic.casefold(), keyword.casefold())
            if not country or not topic or not keyword or identity in seen:
                continue
            seen.add(identity)
            specs.append({"country": country, "topic": topic, "keyword": keyword})

    if not specs:
        raise SystemExit("monthly_topic_stats returned no keywords for the requested month.")
    return specs


def _project(row: dict[str, Any], columns: tuple[str, ...], required_id: str) -> dict[str, Any] | None:
    if not row.get(required_id):
        return None

    projected = {}
    for column in columns:
        value = row.get(column)
        if isinstance(value, float) and not math.isfinite(value):
            value = None
        elif value == "" or value == {}:
            value = None
        projected[column] = value
    return projected


def sync_instagram_data(
    posts: list[dict[str, Any]],
    comments: list[dict[str, Any]],
) -> dict[str, int]:
    """Project and upsert Instagram posts and comments."""
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
    load_dotenv(os.path.join(repo_root, ".env"))

    base_url = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
    if base_url.endswith("/rest/v1"):
        base_url = base_url[: -len("/rest/v1")].rstrip("/")
    key = (
        os.environ.get("SUPABASE_SECRET_KEY")
        or os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
        or os.environ.get("SUPABASE_KEY")
        or ""
    ).strip()

    if not base_url or not key:
        raise RuntimeError("SUPABASE_URL and SUPABASE_KEY (or SUPABASE_SECRET_KEY) are required in .env")
    if key.startswith("sb_publishable_") or key.startswith("sb_anon_"):
        raise RuntimeError("Use a server-only Supabase secret/service-role key for scraper writes")

    projected_posts = [
        row for row in (_project(item, POST_COLUMNS, "post_id") for item in posts) if row
    ]
    projected_comments = [
        row for row in (_project(item, COMMENT_COLUMNS, "comment_id") for item in comments) if row
    ]

    session = requests.Session()
    counts = {
        "instagram_posts": upsert_batches(
            session, base_url, key, "instagram_posts", projected_posts, "post_id"
        ),
        "instagram_comments": upsert_batches(
            session, base_url, key, "instagram_comments", projected_comments, "comment_id"
        ),
    }
    return counts