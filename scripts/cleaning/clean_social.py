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
        "conversation_id": first(row, "conversation_id", "video_id", "media_id", "link_id", "post_id"),
        "parent_source_id": first(row, "parent_tweet_id", "parent_id", "parent_id"),
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
    sources = (
        ("x", "post", "x_posts", "clean_posts"),
        ("reddit", "post", "reddit_posts", "clean_posts"),
        ("x", "comment", "x_replies", "clean_comments"),
        ("reddit", "comment", "reddit_comments", "clean_comments"),
        ("youtube", "post", "youtube_videos", "clean_posts"),
        ("youtube", "comment", "youtube_comments", "clean_comments"),
        ("instagram", "post", "instagram_posts", "clean_posts"),
        ("instagram", "comment", "instagram_comments", "clean_comments"),
    )
    counts = {"clean_posts": 0, "clean_comments": 0}
    for platform, source_type, source_table, target_table in sources:
        raw_rows = fetch_rows(session, base_url, key, source_table)
        cleaned = [r for r in (normalize_row(row, platform, source_type, source_table) for row in raw_rows) if r]
        counts[target_table] += upsert(session, base_url, key, target_table, cleaned)
        print(f"{source_table} -> {target_table}: {len(cleaned)} rows")
    print(counts)


if __name__ == "__main__":
    main()
