"""Upsert collected Facebook posts and comments into Supabase."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv


# =========================================================
# CONFIG
# =========================================================

REPO_ROOT = Path(__file__).resolve().parents[2]

load_dotenv(REPO_ROOT / ".env")

BATCH_SIZE = 100


POST_COLUMNS = (
    "post_id",
    "platform",
    "country",
    "source_name",
    "page_name",
    "published_at",
    "url",
    "text",
    "likes",
    "comments_count",
    "shares",
    "primary_topic",
    "matched_topics",
)


COMMENT_COLUMNS = (
    "comment_id",
    "parent_post_id",
    "platform",
    "post_url",
    "country",
    "source_name",
    "primary_topic",
    "published_at",
    "text",
    "likes",
)


# =========================================================
# SUPABASE CREDENTIALS
# =========================================================

def _credentials() -> tuple[str, str]:

    url = (
        os.environ
        .get("SUPABASE_URL", "")
        .strip()
        .rstrip("/")
    )

    key = (
        os.environ.get("SUPABASE_SECRET_KEY")
        or os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
        or os.environ.get("SUPABASE_KEY")
        or ""
    ).strip()

    if not url or not key:

        raise SystemExit(
            "SUPABASE_URL and SUPABASE_KEY "
            "(or SUPABASE_SECRET_KEY) "
            "are required in .env"
        )

    return url, key


# =========================================================
# HTTP HEADERS
# =========================================================

def _headers(
    key: str,
    *,
    with_bearer: bool
) -> dict[str, str]:

    headers = {
        "apikey": key,
        "Content-Type": "application/json",

        # Upsert rather than creating duplicates
        "Prefer": (
            "resolution=merge-duplicates,"
            "return=minimal"
        ),
    }

    if with_bearer:
        headers["Authorization"] = f"Bearer {key}"

    return headers


# =========================================================
# PROJECT / CLEAN ROWS
# =========================================================

def project(
    row: dict[str, Any],
    columns: tuple[str, ...],
    required_id: str,
) -> dict[str, Any] | None:

    if not row.get(required_id):
        return None

    output = {}

    for column in columns:

        value = row.get(column)

        if value == {}:
            value = None

        output[column] = value

    return output


# =========================================================
# UPSERT
# =========================================================

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

    endpoint = (
        f"{base_url}/rest/v1/"
        f"{table}"
        f"?on_conflict={on_conflict}"
    )

    written = 0

    use_bearer = True

    for start in range(
        0,
        len(rows),
        BATCH_SIZE
    ):

        chunk = rows[
            start:start + BATCH_SIZE
        ]

        response = session.post(
            endpoint,
            json=chunk,
            headers=_headers(
                key,
                with_bearer=use_bearer
            ),
            timeout=60,
        )

        # Same fallback behaviour as X pipeline
        if (
            use_bearer
            and response.status_code in {401, 403}
            and "jwt" in response.text.lower()
        ):

            use_bearer = False

            response = session.post(
                endpoint,
                json=chunk,
                headers=_headers(
                    key,
                    with_bearer=False
                ),
                timeout=60,
            )

        if not response.ok:

            raise SystemExit(
                f"{table} upsert failed "
                f"({response.status_code}): "
                f"{response.text[:1200]}"
            )

        written += len(chunk)

        print(
            f"{table}: "
            f"upserted "
            f"{written}/{len(rows)}"
        )

    return written


# =========================================================
# SYNC FACEBOOK ROWS
# =========================================================

def sync_facebook_rows(
    posts: list[dict[str, Any]],
    comments: list[dict[str, Any]],
) -> dict[str, int]:

    base_url, key = _credentials()

    session = requests.Session()

    projected_posts = [
        row
        for row in (
            project(
                post,
                POST_COLUMNS,
                "post_id"
            )
            for post in posts
        )
        if row
    ]

    projected_comments = [
        row
        for row in (
            project(
                comment,
                COMMENT_COLUMNS,
                "comment_id"
            )
            for comment in comments
        )
        if row
    ]

    counts = {

        "facebook_posts": upsert_batches(
            session,
            base_url,
            key,
            "facebook_posts",
            projected_posts,
            "post_id",
        ),

        "facebook_comments": upsert_batches(
            session,
            base_url,
            key,
            "facebook_comments",
            projected_comments,
            "comment_id",
        ),
    }

    print(
        json.dumps(
            counts,
            indent=2
        )
    )

    return counts