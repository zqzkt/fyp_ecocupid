"""X (Twitter) collection for EcoInsights (RFC-X-001), cost-capped.

X pay-per-use (approx.):
  post read  $0.005
  user read  $0.010  (author expansions)
  media read $0.005  (media expansions)

Use the newest post stored in Supabase as the daily checkpoint. The default
collection includes a small reply sample and does not store author profiles.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(REPO_ROOT / ".env")

API_BASE = "https://api.x.com/2"
SEARCH_RECENT = f"{API_BASE}/tweets/search/recent"
SEARCH_ALL = f"{API_BASE}/tweets/search/all"

POST_READ_USD = 0.005
USER_READ_USD = 0.010
DETAIL_POST_READ_USD = 0.005
DEFAULT_MAX_SPEND_USD = 5.00
HARD_MAX_POSTS = 250

# One query only. The six primary ASEAN countries are in the same request.
ASEAN_QUERY_TERMS = (
    "Singapore OR Malaysia OR Indonesia OR Philippines OR Thailand OR "
    'Brunei OR "Brunei Darussalam"'
)
KEYWORD_QUERY = (
    '("climate change" OR sustainability OR "renewable energy" OR "plastic pollution") '
    f"lang:en -is:retweet ({ASEAN_QUERY_TERMS})"
)
MATCH_KEYWORDS = (
    "climate change",
    "sustainability",
    "renewable energy",
    "plastic pollution",
)

COUNTRY_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("Singapore", re.compile(r"\b(singapore|sgp?|lion city|nus|ntu|smu)\b", re.I)),
    ("Malaysia", re.compile(r"\b(malaysia|kuala lumpur|\bkl\b|selangor|johor|penang|sabah|sarawak)\b", re.I)),
    ("Indonesia", re.compile(r"\b(indonesia|jakarta|bandung|surabaya|bali|yogyakarta)\b", re.I)),
    ("Philippines", re.compile(r"\b(philippines|\bph\b|manila|cebu|davao|quezon)\b", re.I)),
    ("Thailand", re.compile(r"\b(thailand|bangkok|chiang mai|phuket)\b", re.I)),
    ("Brunei", re.compile(r"\b(brunei|brunei darussalam|bandar seri begawan)\b", re.I)),
]

# P0 fields only. Extra tweet.fields are free; expansions are not.
TWEET_FIELDS = ",".join(
    [
        "id",
        "text",
        "created_at",
        "lang",
        "author_id",
        "conversation_id",
        "public_metrics",
        "entities",
        "referenced_tweets",
        "attachments",
        "geo",
    ]
)
USER_FIELDS = "id,username,name,description,location,created_at,public_metrics"


def _client() -> requests.Session:
    token = os.environ.get("TWITTER_BEARER_TOKEN", "").strip()
    if not token:
        raise SystemExit("TWITTER_BEARER_TOKEN is missing in .env")
    session = requests.Session()
    session.headers.update(
        {
            "Authorization": f"Bearer {token}",
            "User-Agent": "EcoInsights-FYP-NinjaTurtles/1.0",
        }
    )
    return session


def _get(session: requests.Session, url: str, params: dict[str, Any]) -> dict[str, Any]:
    response = session.get(url, params=params, timeout=60)
    if response.status_code == 429:
        raise SystemExit("Rate limited (429). Stopped without retry to avoid extra billed reads.")
    if response.status_code == 401:
        raise SystemExit("X API 401 Unauthorized. Check TWITTER_BEARER_TOKEN.")
    if response.status_code == 402:
        raise SystemExit("X API 402 credits depleted. Stop calling the API.")
    if response.status_code == 403:
        raise SystemExit(f"X API 403 Forbidden: {response.text[:800]}")
    response.raise_for_status()
    return response.json()


def _fetch_missing_impressions(session: requests.Session, posts: list[dict[str, Any]]) -> None:
    for post in posts:
        if post.get("impression_count") is not None or not post.get("post_id"):
            continue
        payload = _get(
            session,
            f"{API_BASE}/tweets/{post['post_id']}",
            {"tweet.fields": "public_metrics"},
        )
        metrics = (payload.get("data") or {}).get("public_metrics") or {}
        post["impression_count"] = metrics.get("impression_count")


def infer_country(location: str | None, text: str | None, place_country: str | None) -> str | None:
    if place_country:
        mapping = {
            "Singapore": "Singapore",
            "Malaysia": "Malaysia",
            "Indonesia": "Indonesia",
            "Philippines": "Philippines",
            "Thailand": "Thailand",
            "Brunei Darussalam": "Brunei",
            "Brunei": "Brunei",
            "Cambodia": "Cambodia",
            "Lao People's Democratic Republic": "Laos",
            "Laos": "Laos",
            "Myanmar": "Myanmar",
            "Burma": "Myanmar",
            "Viet Nam": "Vietnam",
            "Vietnam": "Vietnam",
            "Timor-Leste": "Timor-Leste",
            "East Timor": "Timor-Leste",
        }
        if place_country in mapping:
            return mapping[place_country]
    blob = " ".join(part for part in [location or "", text or ""] if part)
    for country, pattern in COUNTRY_PATTERNS:
        if pattern.search(blob):
            return country
    return None


def _entity_tags(entities: dict[str, Any] | None, key: str, field: str) -> list[str]:
    if not entities:
        return []
    return [item.get(field, "") for item in entities.get(key, []) if item.get(field)]


def _matched_keywords(text: str | None) -> list[str]:
    normalized = (text or "").casefold()
    return [keyword for keyword in MATCH_KEYWORDS if keyword in normalized]


def flatten_post(
    tweet: dict[str, Any],
    users_by_id: dict[str, dict[str, Any]],
    collected_at: str,
    query_used: str,
    is_reply: bool,
) -> dict[str, Any]:
    metrics = tweet.get("public_metrics") or {}
    entities = tweet.get("entities") or {}
    geo = tweet.get("geo") or {}
    media_keys = (tweet.get("attachments") or {}).get("media_keys") or []
    referenced = tweet.get("referenced_tweets") or []
    parent_ids = [ref.get("id") for ref in referenced if ref.get("type") == "replied_to"]
    author = users_by_id.get(tweet.get("author_id", ""), {})
    country = infer_country(author.get("location"), tweet.get("text"), None)

    like_count = metrics.get("like_count", 0) or 0
    reply_count = metrics.get("reply_count", 0) or 0
    repost_count = metrics.get("retweet_count", 0) or 0
    quote_count = metrics.get("quote_count", 0) or 0
    total_engagement = like_count + reply_count + repost_count + quote_count

    return {
        "post_id": tweet.get("id"),
        "author_id": tweet.get("author_id"),
        "conversation_id": tweet.get("conversation_id"),
        "text": tweet.get("text"),
        "lang": tweet.get("lang"),
        "created_at": tweet.get("created_at"),
        "like_count": like_count,
        "reply_count": reply_count,
        "repost_count": repost_count,
        "quote_count": quote_count,
        "impression_count": metrics.get("impression_count"),
        "matched_keywords": _matched_keywords(tweet.get("text")),
        "hashtags": _entity_tags(entities, "hashtags", "tag"),
        "mentions": _entity_tags(entities, "mentions", "username"),
        "urls": _entity_tags(entities, "urls", "expanded_url") or _entity_tags(entities, "urls", "url"),
        "media_keys": media_keys,
        "media_types": [],
        "referenced_tweets": referenced,
        "parent_tweet_id": parent_ids[0] if parent_ids else None,
        "geo": geo or None,
        "inferred_country": country,
        "is_reply": is_reply,
        "total_engagement": total_engagement,
        "discussion_ratio": (reply_count / like_count) if like_count else None,
        "amplification_ratio": ((repost_count + quote_count) / total_engagement) if total_engagement else None,
        "query": query_used,
        "collected_at": collected_at,
    }


def flatten_user(user: dict[str, Any], collected_at: str) -> dict[str, Any]:
    metrics = user.get("public_metrics") or {}
    location = user.get("location")
    return {
        "author_id": user.get("id"),
        "username": user.get("username"),
        "name": user.get("name"),
        "description": user.get("description"),
        "location": location,
        "created_at": user.get("created_at"),
        "followers_count": metrics.get("followers_count"),
        "following_count": metrics.get("following_count"),
        "tweet_count": metrics.get("tweet_count"),
        "listed_count": metrics.get("listed_count"),
        "inferred_country": infer_country(location, user.get("description"), None),
        "collected_at": collected_at,
    }


def search_pages(
    session: requests.Session,
    query: str,
    max_results_total: int,
    collected_at: str,
    is_reply: bool,
    include_users: bool,
    since_id: str | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
    search_url: str = SEARCH_RECENT,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    posts: list[dict[str, Any]] = []
    users_out: dict[str, dict[str, Any]] = {}
    next_token: str | None = None

    while len(posts) < max_results_total:
        page_size = min(100, max(10, max_results_total - len(posts)))
        params: dict[str, Any] = {
            "query": query,
            "max_results": page_size,
            "tweet.fields": TWEET_FIELDS,
        }
        if include_users:
            params["expansions"] = "author_id"
            params["user.fields"] = USER_FIELDS
        if since_id:
            params["since_id"] = since_id
        if start_time:
            params["start_time"] = start_time
        if end_time:
            params["end_time"] = end_time
        if next_token:
            params["next_token"] = next_token

        try:
            payload = _get(session, search_url, params)
        except requests.HTTPError as error:
            response = error.response
            if not since_id or response is None or response.status_code != 400 or "since_id" not in response.text:
                raise
            print("Supabase checkpoint is outside X's recent-search window; retrying without since_id.")
            params.pop("since_id", None)
            payload = _get(session, search_url, params)
        includes = payload.get("includes") or {}
        users_by_id = {u["id"]: u for u in includes.get("users", []) if "id" in u}
        if include_users:
            for user in users_by_id.values():
                users_out[user["id"]] = flatten_user(user, collected_at)

        page = payload.get("data") or []
        if not page:
            break
        for tweet in page:
            posts.append(flatten_post(tweet, users_by_id, collected_at, query, is_reply))
            if len(posts) >= max_results_total:
                break

        next_token = (payload.get("meta") or {}).get("next_token")
        if not next_token:
            break
        time.sleep(0.3)

    return posts, users_out


def collect_replies(
    session: requests.Session,
    seed_posts: list[dict[str, Any]],
    max_conversations: int,
    max_replies_per_post: int,
    collected_at: str,
    include_users: bool,
    start_time: str | None = None,
    end_time: str | None = None,
    search_url: str = SEARCH_RECENT,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    candidates = [p for p in seed_posts if (p.get("reply_count") or 0) > 0 and p.get("conversation_id")]
    candidates.sort(key=lambda p: (p.get("reply_count") or 0, p.get("total_engagement") or 0), reverse=True)
    selected = candidates[:max_conversations]

    replies: list[dict[str, Any]] = []
    users: dict[str, dict[str, Any]] = {}
    seen_ids: set[str] = {p["post_id"] for p in seed_posts}

    for post in selected:
        cid = post["conversation_id"]
        query = f"conversation_id:{cid} is:reply lang:en"
        page, page_users = search_pages(
            session,
            query,
            max_replies_per_post,
            collected_at,
            True,
            include_users,
            start_time=start_time,
            end_time=end_time,
            search_url=search_url,
        )
        users.update(page_users)
        for reply in page:
            if reply["post_id"] in seen_ids or reply["post_id"] == post["post_id"]:
                continue
            reply["source_post_id"] = post["post_id"]
            if not reply.get("parent_tweet_id"):
                reply["parent_tweet_id"] = post["post_id"]
            seen_ids.add(reply["post_id"])
            replies.append(reply)

    return replies, users


def merge_by_id(existing: list[dict[str, Any]], incoming: list[dict[str, Any]], id_key: str) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for row in existing + incoming:
        key = row.get(id_key)
        if key:
            by_id[str(key)] = row
    return list(by_id.values())


def dedupe_posts(posts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return merge_by_id([], posts, "post_id")


def summarize(posts: list[dict[str, Any]], replies: list[dict[str, Any]], users: list[dict[str, Any]]) -> dict[str, Any]:
    countries: dict[str, int] = {}
    for post in posts:
        key = post.get("inferred_country") or "unspecified"
        countries[key] = countries.get(key, 0) + 1
    with_replies = sum(1 for p in posts if (p.get("reply_count") or 0) > 0)
    return {
        "posts": len(posts),
        "replies": len(replies),
        "users": len(users),
        "posts_with_reply_count": with_replies,
        "inferred_country_counts": dict(sorted(countries.items(), key=lambda kv: (-kv[1], kv[0]))),
        "mean_likes": round(sum(p.get("like_count") or 0 for p in posts) / len(posts), 2) if posts else 0,
        "mean_replies": round(sum(p.get("reply_count") or 0 for p in posts) / len(posts), 2) if posts else 0,
    }


def estimate_cost_usd(max_posts: int, include_users: bool, with_replies: bool, reply_budget: int) -> float:
    posts = max_posts + (reply_budget if with_replies else 0)
    users = posts if include_users else 0
    return round(posts * (POST_READ_USD + DETAIL_POST_READ_USD) + users * USER_READ_USD, 4)


def _sync_supabase(
    users: list[dict[str, Any]],
    posts: list[dict[str, Any]],
    replies: list[dict[str, Any]],
) -> None:
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    from scripts.supabase.twitter_pipeline import sync_x_rows

    print("Upserting fresh rows into Supabase...")
    sync_x_rows(users, posts, replies)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Collect EcoInsights X data and upsert it directly into Supabase."
    )
    parser.add_argument("--max-posts", type=int, default=40, help="New posts to fetch. Min billed page is 10.")
    parser.add_argument("--max-spend", type=float, default=DEFAULT_MAX_SPEND_USD, help="Abort if estimate exceeds this USD.")
    parser.add_argument(
        "--with-replies",
        action="store_true",
        default=True,
        help="Collect a small reply sample (enabled by default; billed extra).",
    )
    parser.add_argument(
        "--with-users",
        action="store_true",
        default=False,
        help="Deprecated compatibility option; user rows are no longer stored.",
    )
    parser.add_argument("--no-replies", dest="with_replies", action="store_false", help="Skip reply collection.")
    parser.add_argument("--no-users", dest="with_users", action="store_false", help="Skip author expansions.")
    parser.add_argument(
        "--max-reply-conversations",
        type=int,
        default=5,
        help="Conversations to sample for replies; highest reply counts are selected.",
    )
    parser.add_argument(
        "--max-replies-per-post",
        type=int,
        default=10,
        help="Maximum replies to fetch per selected conversation.",
    )
    parser.add_argument("--force", action="store_true", help="Ignore the Supabase checkpoint and search recent posts again.")
    parser.add_argument("--start-time", help="Inclusive UTC ISO-8601 start time for a bounded archive search.")
    parser.add_argument("--end-time", help="Exclusive UTC ISO-8601 end time for a bounded archive search.")
    parser.add_argument("--archive", action="store_true", help="Use X full-archive search instead of recent search.")
    parser.add_argument("--dry-run", action="store_true", help="Print cost estimate only. No API call.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if args.max_posts > HARD_MAX_POSTS:
        raise SystemExit(f"--max-posts {args.max_posts} exceeds hard cap {HARD_MAX_POSTS} (cost control).")
    if args.max_posts < 10:
        args.max_posts = 10

    reply_budget = args.max_reply_conversations * args.max_replies_per_post if args.with_replies else 0
    estimate = estimate_cost_usd(args.max_posts, args.with_users, args.with_replies, reply_budget)
    print(
        f"Estimated max cost: ${estimate:.4f} "
        f"({args.max_posts} posts"
        f"{f' + up to {reply_budget} replies' if args.with_replies else ''}"
        f"{' + user expansions' if args.with_users else ''})"
    )
    if args.dry_run:
        return
    if estimate > args.max_spend:
        raise SystemExit(
            f"Estimate ${estimate:.4f} exceeds --max-spend ${args.max_spend:.4f}. "
            "Lower --max-posts or raise --max-spend."
        )

    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    from scripts.supabase.twitter_pipeline import latest_post_id

    since_id = None if args.force or args.archive else latest_post_id()
    if since_id:
        print(f"Searching for posts newer than Supabase checkpoint {since_id}...")
    else:
        print("No Supabase checkpoint found; searching recent posts...")

    session = _client()
    collected_at = datetime.now(timezone.utc).isoformat()
    print(f"Searching (up to {args.max_posts} new posts), single query...")
    seed_posts, all_users = search_pages(
        session,
        KEYWORD_QUERY,
        args.max_posts,
        collected_at,
        False,
        args.with_users,
        since_id,
        args.start_time,
        args.end_time,
        SEARCH_ALL if args.archive else SEARCH_RECENT,
    )
    seed_posts = [p for p in dedupe_posts(seed_posts) if not p.get("is_reply")]
    _fetch_missing_impressions(session, seed_posts)

    reply_rows: list[dict[str, Any]] = []
    if args.with_replies:
        replies, reply_users = collect_replies(
            session,
            seed_posts,
            args.max_reply_conversations,
            args.max_replies_per_post,
            collected_at,
            args.with_users,
            args.start_time,
            args.end_time,
            SEARCH_ALL if args.archive else SEARCH_RECENT,
        )
        all_users.update(reply_users)
        for reply in replies:
            reply_rows.append(
                {
                    "reply_id": reply["post_id"],
                    "post_id": reply.get("source_post_id") or reply.get("conversation_id"),
                    "parent_tweet_id": reply.get("parent_tweet_id"),
                    "conversation_id": reply.get("conversation_id"),
                    "author_id": reply.get("author_id"),
                    "text": reply.get("text"),
                    "lang": reply.get("lang"),
                    "created_at": reply.get("created_at"),
                    "like_count": reply.get("like_count"),
                    "reply_count": reply.get("reply_count"),
                    "repost_count": reply.get("repost_count"),
                    "quote_count": reply.get("quote_count"),
                    "hashtags": reply.get("hashtags"),
                    "mentions": reply.get("mentions"),
                    "urls": reply.get("urls"),
                    "inferred_country": reply.get("inferred_country"),
                    "collected_at": collected_at,
                }
            )

    users = list(all_users.values())
    stats = summarize(seed_posts, reply_rows, users)
    billed_posts = len(seed_posts) + len(reply_rows)
    stats["approx_billed_usd"] = round(billed_posts * POST_READ_USD + len(users) * USER_READ_USD, 4)
    print(json.dumps(stats, indent=2))
    _sync_supabase(users, seed_posts, reply_rows)


if __name__ == "__main__":
    main()
