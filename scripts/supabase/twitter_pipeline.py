"""Upsert collected X posts and replies into Supabase."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(REPO_ROOT / ".env")

DEFAULT_X_DIR = REPO_ROOT / "data" / "raw" / "x"
BATCH_SIZE = 100
MONTHLY_MAX_SPEND_USD = 5.00
MONTHLY_MAX_POSTS = 200
MONTHLY_REPLY_CONVERSATIONS = 5
MONTHLY_REPLIES_PER_CONVERSATION = 10
TARGET_COUNTRIES = ("Singapore", "Malaysia", "Indonesia", "Philippines", "Thailand", "Brunei")

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
    "matched_keywords",
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

    posts = [r for r in (project(row, POST_COLUMNS, "post_id") for row in read_jsonl(out_dir / "x_posts.jsonl")) if r]
    comment_path = out_dir / "x_replies.jsonl"
    if not comment_path.exists():
        comment_path = out_dir / "x_comments.jsonl"  # Legacy local export name.
    replies = []
    for row in read_jsonl(comment_path):
        if not row.get("reply_id"):
            row["reply_id"] = row.get("comment_id")
        projected = project(row, REPLY_COLUMNS, "reply_id")
        if projected:
            replies.append(projected)

    counts = {
        "x_users": 0,
        "x_posts": upsert_batches(session, base_url, key, "x_posts", posts, "post_id"),
        "x_replies": upsert_batches(session, base_url, key, "x_replies", replies, "reply_id"),
    }
    print(json.dumps(counts, indent=2))
    from scripts.social_media_pipeline import (
        run_cleaner,
        run_environmental_filter,
        run_sentiment,
    )

    run_cleaner()
    run_environmental_filter()
    run_sentiment()
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
    *,
    sentiment_platform: str | None = None,
    sentiment_dry_run: bool = False,
) -> dict[str, int]:
    """Project and upsert freshly collected X rows without local staging files."""
    base_url, key = _credentials()
    session = requests.Session()
    projected_posts = [r for r in (project(row, POST_COLUMNS, "post_id") for row in posts) if r]
    projected_replies = [
        r for r in (project(row, REPLY_COLUMNS, "reply_id") for row in replies) if r
    ]
    counts = {
        "x_users": 0,
        "x_posts": upsert_batches(session, base_url, key, "x_posts", projected_posts, "post_id"),
        "x_replies": upsert_batches(
            session, base_url, key, "x_replies", projected_replies, "reply_id"
        ),
    }
    print(json.dumps(counts, indent=2))
    from scripts.social_media_pipeline import (
        run_cleaner,
        run_environmental_filter,
        run_sentiment,
    )

    run_cleaner()
    run_environmental_filter()
    run_sentiment(platform=sentiment_platform, dry_run=sentiment_dry_run)
    return counts


def previous_month_window(reference: datetime | None = None) -> tuple[str, str]:
    """Return the previous calendar month as UTC ISO-8601 bounds."""
    current = reference or datetime.now(timezone.utc)
    first_current = current.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    previous_end = first_current
    previous_start = (first_current - timedelta(days=1)).replace(day=1)
    return previous_start.isoformat().replace("+00:00", "Z"), previous_end.isoformat().replace("+00:00", "Z")


def run_monthly_job(reference: datetime | None = None, *, ignore_day_guard: bool = False) -> None:
    """Collect the previous calendar month on the first day of the month."""
    current = reference or datetime.now(timezone.utc)
    if current.day != 1 and not ignore_day_guard:
        raise SystemExit("Monthly job skipped: it only runs on the first day of the month.")
    start_time, end_time = previous_month_window(current)
    collector = REPO_ROOT / "scripts" / "sources" / "twitter.py"
    command = [
        sys.executable,
        str(collector),
        "--archive",
        "--start-time",
        start_time,
        "--end-time",
        end_time,
        "--topic-month",
        start_time[:10],
        "--max-posts",
        str(MONTHLY_MAX_POSTS),
        "--max-spend",
        str(MONTHLY_MAX_SPEND_USD),
        "--max-reply-conversations",
        str(MONTHLY_REPLY_CONVERSATIONS),
        "--max-replies-per-post",
        str(MONTHLY_REPLIES_PER_CONVERSATION),
    ]
    print(f"Running monthly X collection for {start_time} through {end_time}...")
    try:
        subprocess.run(command, cwd=REPO_ROOT, check=True)
    except subprocess.CalledProcessError as error:
        raise SystemExit(
            f"Monthly X collection failed with exit code {error.returncode}; "
            "no monthly rows were uploaded by this run."
        ) from error


def run_x_collection(*, force: bool = True) -> None:
    """Call the X endpoint, then let the collector run storage and analysis."""
    collector = REPO_ROOT / "scripts" / "sources" / "twitter.py"
    command = [sys.executable, str(collector)]
    if force:
        command.append("--force")
    print("Calling the X endpoint before cleaning and sentiment derivation...")
    try:
        subprocess.run(command, cwd=REPO_ROOT, check=True)
    except subprocess.CalledProcessError as error:
        raise SystemExit(f"X collection failed with exit code {error.returncode}.") from error

if __name__ == "__main__":
    if "--monthly" in sys.argv[1:]:
        run_monthly_job(ignore_day_guard="--run-now" in sys.argv[1:])
    elif len(sys.argv) == 1 or sys.argv[1] == "--force":
        run_x_collection(force=True)
    else:
        target = Path(sys.argv[1])
        sync_x_jsonl(target)
