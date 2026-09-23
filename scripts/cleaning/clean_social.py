"""Normalize social-media posts and comments into shared Supabase tables."""

from __future__ import annotations

import re
import sys
from importlib import import_module
from datetime import datetime, timezone
from typing import Any, Iterable

import requests
from dotenv import load_dotenv

REPO_ROOT = __import__("pathlib").Path(__file__).resolve().parents[2]
load_dotenv(REPO_ROOT / ".env")
demojize = import_module("emoji").demojize

BATCH_SIZE = 100
PAGE_SIZE = 1000
MENTION_RE = re.compile(r"(?<!\w)@[A-Za-z0-9_]{1,50}", re.UNICODE)
WHITESPACE_RE = re.compile(r"\s+")
VULGARITY_RE = re.compile(
    r"\b(?:motherfuck(?:er|ing|ed)?|fuck(?:er|ing|ed|s)?|shit(?:ty|ting|ted|s)?|"
    r"asshole(?:s)?|bitch(?:es|y)?|bastard(?:s)?|cunt(?:s)?|dick(?:head|s)?|"
    r"pussy(?:cat|s)?|damn(?:ed|it)?|crap(?:py)?|ass)\b",
    re.IGNORECASE,
)

# Keep high-signal fields for sentiment analysis, filtering, grouping, and auditability.
CLEAN_COLUMNS = (
    "source_id",
    "platform",
    "source_type",
    "original_text",
    "cleaned_text",
    "lang",
    "inferred_country",
    "author_id",
    "conversation_id",
    "parent_source_id",
    "created_at",
    "matched_keywords",
    "like_count",
    "reply_count",
    "repost_count",
    "quote_count",
    "impression_count",
    "total_engagement",
    "source_table",
    "cleaned_at",
)

def credentials() -> tuple[str, str]:
    import os

    url = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
    key = (os.environ.get("SUPABASE_SECRET_KEY") or os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_KEY") or "").strip()
    if not url or not key:
        raise SystemExit("SUPABASE_URL and SUPABASE_KEY are required in .env")
    return url, key


def headers(key: str, *, write: bool = False) -> dict[str, str]:
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=minimal" if write else "return=representation",
    }


def replace_emoji(text: str) -> str:
    return demojize(text, delimiters=("[", "]"), language="en")


def clean_text(text: str | None) -> str:
    text = replace_emoji(text or "")
    text = MENTION_RE.sub("", text)
    text = VULGARITY_RE.sub(lambda match: match.group(0)[0] + "*" * (len(match.group(0)) - 1), text)
    return WHITESPACE_RE.sub(" ", text).strip()


def first(row: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if row.get(key) is not None:
            return row[key]
    return None


def source_id(row: dict[str, Any], platform: str, source_type: str) -> str | None:
    keys = (
        ("reply_id", "comment_id", "id", "post_id", "name")
        if source_type == "comment"
        else ("post_id", "video_id", "media_id", "id", "name", "comment_id")
    )
    value = first(row, *keys)
    return f"{platform}:{source_type}:{value}" if value else None


def normalize_row(row: dict[str, Any], platform: str, source_type: str, source_table: str) -> dict[str, Any] | None:
    identifier = source_id(row, platform, source_type)
    original_text = first(row, "text", "body", "selftext", "comment", "caption", "title")
    if platform == "youtube" and source_type == "post":
        title = str(row.get("title") or "").strip()
        description = str(row.get("description") or "").strip()
        original_text = "\n\n".join(part for part in (title, description) if part)
    if not identifier or original_text is None:
        return None
    likes = int(first(row, "like_count", "likeCount", "score", "ups") or 0)
    replies = int(first(row, "reply_count", "comments_count", "total_reply_count", "num_comments") or 0)
    reposts = int(first(row, "repost_count", "retweet_count") or 0)
    quotes = int(first(row, "quote_count") or 0)
    total = first(row, "total_engagement")
    if total is None:
        total = likes + replies + reposts + quotes
    return {
        "source_id": identifier,
        "platform": platform,
        "source_type": source_type,
        "original_text": str(original_text),
        "cleaned_text": clean_text(str(original_text)),
        "lang": first(row, "lang", "language"),
        "inferred_country": first(row, "inferred_country", "country", "subreddit"),
        "author_id": first(row, "author_id", "user_id", "author", "author_fullname", "username"),
        "conversation_id": first(row, "conversation_id", "video_id", "media_id", "link_id", "post_id", "parent_post_id"),
        "parent_source_id": first(row, "parent_tweet_id", "parent_id", "parent_post_id"),
        "created_at": first(row, "created_at", "created_utc", "timestamp", "published", "published_date"),
        "matched_keywords": first(row, "matched_keywords", "keywords") or [],
        "like_count": likes,
        "reply_count": replies,
        "repost_count": reposts,
        "quote_count": quotes,
        "impression_count": first(row, "impression_count", "view_count", "viewCount"),
        "total_engagement": total,
        "source_table": source_table,
        "cleaned_at": datetime.now(timezone.utc).isoformat(),
    }


def fetch_rows(session: requests.Session, base_url: str, key: str, table: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    offset = 0
    while True:
        response = session.get(
            f"{base_url}/rest/v1/{table}",
            params={"select": "*", "limit": PAGE_SIZE, "offset": offset},
            headers=headers(key),
            timeout=60,
        )
        if response.status_code == 404:
            return []
        response.raise_for_status()
        page = response.json()
        rows.extend(page)
        if len(page) < PAGE_SIZE:
            return rows
        offset += PAGE_SIZE


def upsert(session: requests.Session, base_url: str, key: str, table: str, rows: list[dict[str, Any]]) -> int:
    for start in range(0, len(rows), BATCH_SIZE):
        chunk = rows[start : start + BATCH_SIZE]
        response = session.post(
            f"{base_url}/rest/v1/{table}?on_conflict=source_id",
            json=chunk,
            headers=headers(key, write=True),
            timeout=60,
        )
        response.raise_for_status()
    return len(rows)


def main() -> None:
    base_url, key = credentials()
    session = requests.Session()
    platform_tables = (
        ("x", "x_posts", "x_replies"),
        ("reddit", "reddit_posts", "reddit_comments"),
        ("youtube", "youtube_videos", "youtube_comments"),
        ("instagram", "instagram_posts", "instagram_comments"),
        ("facebook", "facebook_posts", "facebook_comments"),
    )
    counts = {"clean_posts": 0, "clean_comments": 0}
    for platform, post_table, comment_table in platform_tables:
        posts = fetch_rows(session, base_url, key, post_table)
        comments = fetch_rows(session, base_url, key, comment_table)
        post_countries = {
            str(first(row, "post_id", "video_id", "media_id", "id", "name")): first(
                row, "inferred_country", "country"
            )
            for row in posts
            if first(row, "post_id", "video_id", "media_id", "id", "name") is not None
        }
        cleaned_posts = [
            row for row in (normalize_row(item, platform, "post", post_table) for item in posts) if row
        ]
        cleaned_comments = []
        for item in comments:
            comment = dict(item)
            parent_id = first(comment, "post_id", "video_id", "media_id", "parent_post_id", "conversation_id")
            if parent_id is not None and str(parent_id) in post_countries:
                comment["inferred_country"] = post_countries[str(parent_id)]
                comment["country"] = post_countries[str(parent_id)]
            normalized = normalize_row(comment, platform, "comment", comment_table)
            if normalized:
                cleaned_comments.append(normalized)
        counts["clean_posts"] += upsert(session, base_url, key, "clean_posts", cleaned_posts)
        counts["clean_comments"] += upsert(session, base_url, key, "clean_comments", cleaned_comments)
        print(f"{post_table} -> clean_posts: {len(cleaned_posts)} rows")
        print(f"{comment_table} -> clean_comments: {len(cleaned_comments)} rows")
    print(counts)


if __name__ == "__main__":
    main()
