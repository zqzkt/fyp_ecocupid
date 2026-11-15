"""Upsert collected Reddit data into Supabase (reddit_posts, reddit_comments)."""

from __future__ import annotations

import json
import math
import os
import re
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(REPO_ROOT / ".env")

BATCH_SIZE = 100
TARGET_COUNTRIES = ("Singapore", "Malaysia", "Indonesia", "Philippines", "Thailand", "Brunei")

POST_COLUMNS = (
    "post_id",
    "post_url",
    "created_at",
    "author_name",
    "title",
    "body",
    "community_name",
    "flair",
    "comments_count",
    "subreddit",
    "score",
    "upvote_ratio",
    "domain",
    "topic",
    "country",
)

COMMENT_COLUMNS = (
    "comment_id",
    "comment_url",
    "comment_created_at",
    "author_name",
    "post_id",
    "post_title",
    "body",
    "subreddit_name",
    "parent_id",
    "score",
    "parent_kind",
    "depth",
    "topic",
    "country",
)


def _credentials() -> tuple[str, str]:
    url = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
    if url.endswith("/rest/v1"):
        url = url[: -len("/rest/v1")].rstrip("/")
    key = (
        os.environ.get("SUPABASE_SECRET_KEY")
        or os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
        or os.environ.get("SUPABASE_KEY")
        or ""
    ).strip()
    if not url or not key:
        raise SystemExit("SUPABASE_URL and SUPABASE_KEY (or SUPABASE_SECRET_KEY) are required in .env")
    if key.startswith("sb_publishable_") or key.startswith("sb_anon_"):
        raise SystemExit(
            "SUPABASE_KEY is a publishable/anonymous key. Use a server-only sb_secret_ "
            "or service_role key for this scraper, because RLS blocks writes from public keys."
        )
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


def topic_keyword_groups(month: str | None = None) -> dict[str, list[str]]:
    """Read top-three monthly topic keywords grouped by target country."""
    base_url, key = _credentials()
    params: dict[str, str | int] = {
        "select": "country,topic_name,topic_rank,monthly_keywords,month",
        "country": "in.(" + ",".join(TARGET_COUNTRIES) + ")",
        "topic_rank": "lte.3",
        "order": "month.desc,topic_rank.asc",
        "limit": "1000",
    }
    if month:
        params["month"] = f"eq.{month}"

    response = requests.get(
        f"{base_url}/rest/v1/monthly_topic_stats",
        params=params,
        headers=_headers(key, with_bearer=True),
        timeout=60,
    )
    if response.status_code in {401, 403} and "jwt" in response.text.lower():
        response = requests.get(
            f"{base_url}/rest/v1/monthly_topic_stats",
            params=params,
            headers=_headers(key, with_bearer=False),
            timeout=60,
        )
    if not response.ok:
        raise SystemExit(f"monthly_topic_stats lookup failed ({response.status_code}): {response.text[:1200]}")

    rows = response.json()
    if not month and rows:
        newest_month = max(row.get("month", "") for row in rows)
        rows = [row for row in rows if row.get("month") == newest_month]

    keywords_by_country = {country: [] for country in TARGET_COUNTRIES}
    seen_by_country = {country: set() for country in TARGET_COUNTRIES}
    for row in rows:
        country = row.get("country")
        if country not in keywords_by_country:
            continue
        raw = row.get("monthly_keywords") or ""
        values = raw if isinstance(raw, list) else str(raw).split(",")
        for value in values:
            keyword = str(value).strip()
            if keyword and keyword.casefold() not in seen_by_country[country]:
                seen_by_country[country].add(keyword.casefold())
                keywords_by_country[country].append(keyword)

    keywords_by_country = {country: values for country, values in keywords_by_country.items() if values}
    if not keywords_by_country:
        raise SystemExit("monthly_topic_stats returned no keywords for the requested month and countries.")
    return keywords_by_country


def keyword_in_text(text: str | None, keywords: list[str]) -> str | None:
    """Return the first keyword appearing in the text as a whole word or phrase, ignoring case."""
    for keyword in keywords:
        if re.search(rf"(?<!\w){re.escape(keyword)}(?!\w)", text or "", re.IGNORECASE):
            return keyword
    return None


def project(row: dict[str, Any], columns: tuple[str, ...], required_id: str) -> dict[str, Any] | None:
    """Project and validate a row to include only required columns and ID."""
    if not row.get(required_id):
        return None
    out: dict[str, Any] = {}
    for col in columns:
        value = row.get(col)
        if isinstance(value, float) and not math.isfinite(value):
            value = None
        elif value == {} or value == "":
            value = None
        out[col] = value
    return out


def upsert_batches(
    session: requests.Session,
    base_url: str,
    key: str,
    table: str,
    rows: list[dict[str, Any]],
    on_conflict: str,
) -> int:
    """Upsert rows into Supabase table in batches."""
    if not rows:
        print(f"{table}: 0 rows")
        return 0

    unique_rows: dict[Any, dict[str, Any]] = {}
    for row in rows:
        conflict_value = row.get(on_conflict)
        if conflict_value is not None:
            unique_rows[conflict_value] = row
    rows = list(unique_rows.values())
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
                "If the tables are missing, create them with the appropriate schema. "
                "Ensure supabase/migrations/ contains the necessary migration files."
            )
        written += len(chunk)
        print(f"{table}: upserted {written}/{len(rows)}")
    return written


def sync_reddit_data(
    posts: list[dict[str, Any]],
    comments: list[dict[str, Any]],
) -> dict[str, int]:
    """Project and upsert freshly collected Reddit data to Supabase."""
    base_url, key = _credentials()
    session = requests.Session()

    projected_posts = [r for r in (project(row, POST_COLUMNS, "post_id") for row in posts) if r]
    projected_comments = [r for r in (project(row, COMMENT_COLUMNS, "comment_id") for row in comments) if r]

    counts = {
        "reddit_posts": upsert_batches(session, base_url, key, "reddit_posts", projected_posts, "post_id"),
        "reddit_comments": upsert_batches(session, base_url, key, "reddit_comments", projected_comments, "comment_id"),
    }
    print(json.dumps(counts, indent=2))
    return counts
