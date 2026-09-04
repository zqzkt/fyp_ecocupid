"""Upsert collected X JSONL into Supabase (x_users, x_posts, x_replies)."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(REPO_ROOT / ".env")

DEFAULT_X_DIR = REPO_ROOT / "data" / "raw" / "x"
BATCH_SIZE = 100

USER_COLUMNS = (
    "author_id",
    "username",
    "name",
    "description",
    "location",
    "inferred_country",
    "followers_count",
    "following_count",
    "tweet_count",
    "listed_count",
    "created_at",
    "collected_at",
)
POST_COLUMNS = (
    "post_id",
    "author_id",
    "conversation_id",
    "text",
    "lang",
    "inferred_country",
    "like_count",
    "reply_count",
    "repost_count",
    "quote_count",
    "bookmark_count",
    "impression_count",
    "total_engagement",
    "discussion_ratio",
    "amplification_ratio",
    "is_reply",
    "possibly_sensitive",
    "reply_settings",
    "source",
    "query",
    "hashtags",
    "mentions",
    "urls",
    "media_keys",
    "media_types",
    "parent_tweet_id",
    "geo",
    "place",
    "media",
    "referenced_tweets",
    "annotations",
    "context_annotations",
    "created_at",
    "collected_at",
)
REPLY_COLUMNS = (
    "reply_id",
    "post_id",
    "parent_tweet_id",
    "conversation_id",
    "author_id",
    "text",
    "lang",
    "inferred_country",
    "like_count",
    "reply_count",
    "repost_count",
    "quote_count",
    "hashtags",
    "mentions",
    "urls",
    "media",
    "created_at",
    "collected_at",
)


def _credentials() -> tuple[str, str]:
    url = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
    key = (
        os.environ.get("SUPABASE_SECRET_KEY")
        or os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
        or os.environ.get("SUPABASE_KEY")
        or ""
    ).strip()
    if not url or not key:
        raise SystemExit("SUPABASE_URL and SUPABASE_KEY (or SUPABASE_SECRET_KEY) are required in .env")
    return url, key


def _headers(key: str, *, with_bearer: bool) -> dict[str, str]:
    headers = {
        "apikey": key,
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=minimal",
    }
    if with_bearer:
        headers["Authorization"] = f"Bearer {key}"
    return headers


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def project(row: dict[str, Any], columns: tuple[str, ...], required_id: str) -> dict[str, Any] | None:
    if not row.get(required_id):
        return None
    out: dict[str, Any] = {}
    for col in columns:
        value = row.get(col, [] if col == "media_types" else None)
        if value == {}:
            value = None
        out[col] = value
    if not out.get("created_at"):
        out["created_at"] = out.get("collected_at")
    if not out.get("created_at"):
        return None
    if "text" in columns and not out.get("text"):
        out["text"] = ""
    return out


def upsert_batches(
    session: requests.Session,
    base_url: str,
    key: str,
    table: str,
    rows: list[dict[str, Any]],
    on_conflict: str,
) -> int:
    if not rows:
        print(f"{table}: 0 rows")
        return 0

    endpoint = f"{base_url}/rest/v1/{table}?on_conflict={on_conflict}"
    written = 0
    use_bearer = True

    for start in range(0, len(rows), BATCH_SIZE):
        chunk = rows[start : start + BATCH_SIZE]
        response = session.post(
            endpoint,
            json=chunk,
            headers=_headers(key, with_bearer=use_bearer),
            timeout=60,
        )
        if use_bearer and response.status_code in {401, 403} and "jwt" in response.text.lower():
            use_bearer = False
            response = session.post(
                endpoint,
                json=chunk,
                headers=_headers(key, with_bearer=False),
                timeout=60,
            )
        if not response.ok:
            raise SystemExit(
                f"{table} upsert failed ({response.status_code}): {response.text[:1200]}\n"
                "If the tables are missing, run supabase/migrations/001_create_x_tables.sql. "
                "If RLS blocks writes, run supabase/migrations/002_x_table_policies.sql."
            )
        written += len(chunk)
        print(f"{table}: upserted {written}/{len(rows)}")
    return written


def sync_x_jsonl(out_dir: Path | None = None) -> dict[str, int]:
    out_dir = Path(out_dir) if out_dir else DEFAULT_X_DIR
    base_url, key = _credentials()
    session = requests.Session()

    users = [r for r in (project(row, USER_COLUMNS, "author_id") for row in read_jsonl(out_dir / "x_users.jsonl")) if r]
    posts = [r for r in (project(row, POST_COLUMNS, "post_id") for row in read_jsonl(out_dir / "x_posts.jsonl")) if r]
    replies = [r for r in (project(row, REPLY_COLUMNS, "reply_id") for row in read_jsonl(out_dir / "x_replies.jsonl")) if r]

    counts = {
        "x_users": upsert_batches(session, base_url, key, "x_users", users, "author_id"),
        "x_posts": upsert_batches(session, base_url, key, "x_posts", posts, "post_id"),
        "x_replies": upsert_batches(session, base_url, key, "x_replies", replies, "reply_id"),
    }
    print(json.dumps(counts, indent=2))
    return counts


def latest_post_id() -> str | None:
    """Return the newest stored post ID for X API since_id checkpoints."""
    base_url, key = _credentials()
    params = {"select": "post_id,created_at", "order": "created_at.desc", "limit": 1}
    response = requests.get(
        f"{base_url}/rest/v1/x_posts",
        params=params,
        headers=_headers(key, with_bearer=True),
        timeout=60,
    )
    if response.status_code in {401, 403} and "jwt" in response.text.lower():
        response = requests.get(
            f"{base_url}/rest/v1/x_posts",
            params=params,
            headers=_headers(key, with_bearer=False),
            timeout=60,
        )
    if not response.ok:
        raise SystemExit(f"Supabase checkpoint lookup failed ({response.status_code}): {response.text[:1200]}")
    rows = response.json()
    return str(rows[0]["post_id"]) if rows else None


def sync_x_rows(
    users: list[dict[str, Any]],
    posts: list[dict[str, Any]],
    replies: list[dict[str, Any]],
) -> dict[str, int]:
    """Project and upsert freshly collected X rows without local staging files."""
    base_url, key = _credentials()
    session = requests.Session()
    projected_users = [r for r in (project(row, USER_COLUMNS, "author_id") for row in users) if r]
    projected_posts = [r for r in (project(row, POST_COLUMNS, "post_id") for row in posts) if r]
    projected_replies = [r for r in (project(row, REPLY_COLUMNS, "reply_id") for row in replies) if r]
    counts = {
        "x_users": upsert_batches(session, base_url, key, "x_users", projected_users, "author_id"),
        "x_posts": upsert_batches(session, base_url, key, "x_posts", projected_posts, "post_id"),
        "x_replies": upsert_batches(session, base_url, key, "x_replies", projected_replies, "reply_id"),
    }
    print(json.dumps(counts, indent=2))
    return counts


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_X_DIR
    sync_x_jsonl(target)
