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
    from scripts.supabase.twitter_pipeline import run_cleaner

    run_cleaner()
    return counts