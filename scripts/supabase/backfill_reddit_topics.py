"""One-off backfill of Reddit search keywords lost by reddit_apify.py.

The scraper matched results back to their search by the URL the actor echoed,
which stopped working, so posts were stored with topic = NULL and
clean_social.py dropped their comments. This tags each untagged raw post with
the first of its country's monthly keywords found in its title/body, gives raw
comments their post's keyword, and sets matched_keywords on the Reddit rows
already in clean_posts (which clean_social.py skips on re-runs).

Previews by default; pass --apply to write. Afterwards run clean_social.py
(without --full-refresh) to add the now-tagged comments, then
sentiment_analysis.py --all and posts_comments_summary.py.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import requests

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.cleaning.clean_social import credentials, headers
from scripts.sentiment.sentiment_analysis import normalize_country
from scripts.supabase.reddit_pipeline import keyword_in_text

PAGE_SIZE = 1000


def fetch_all(
    session: requests.Session, base_url: str, key: str, table: str, params: dict[str, str]
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    while True:
        response = session.get(
            f"{base_url}/rest/v1/{table}",
            params={**params, "limit": PAGE_SIZE, "offset": len(rows)},
            headers=headers(key),
            timeout=60,
        )
        response.raise_for_status()
        page = response.json()
        rows.extend(page)
        if len(page) < PAGE_SIZE:
            return rows


def keyword_groups(
    session: requests.Session, base_url: str, key: str
) -> dict[tuple[str, str], list[str]]:
    """(month 'YYYY-MM', country) -> top-3 topic keywords in rank order, as the scraper searched them."""
    groups: dict[tuple[str, str], list[str]] = {}
    rows = fetch_all(
        session, base_url, key, "monthly_topic_stats",
        {"select": "month,country,monthly_keywords", "topic_rank": "lte.3", "order": "month,country,topic_rank"},
    )
    for row in rows:
        keywords = groups.setdefault((str(row["month"])[:7], row["country"]), [])
        raw = row.get("monthly_keywords") or ""
        for value in raw if isinstance(raw, list) else str(raw).split(","):
            keyword = str(value).strip()
            if keyword and keyword.casefold() not in {k.casefold() for k in keywords}:
                keywords.append(keyword)
    return groups


def patch(
    session: requests.Session, base_url: str, key: str, table: str,
    filters: dict[str, str], values: dict[str, Any],
) -> int:
    """Returns the number of rows changed; RLS blocks writes silently, so callers check it."""
    response = session.patch(
        f"{base_url}/rest/v1/{table}",
        params=filters,
        json=values,
        headers={**headers(key), "Prefer": "return=representation"},
        timeout=60,
    )
    response.raise_for_status()
    return len(response.json())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true", help="Write the changes; otherwise only preview them.")
    args = parser.parse_args()

    base_url, key = credentials()
    session = requests.Session()

    posts = fetch_all(session, base_url, key, "reddit_posts", {"select": "post_id,title,body,country,created_at,topic"})
    groups = keyword_groups(session, base_url, key)
    clean_posts = fetch_all(
        session, base_url, key, "clean_posts",
        {"select": "source_id,inferred_country,matched_keywords", "platform": "eq.reddit"},
    )
    # Many raw posts have no country; clean_social.py infers one from the text.
    clean_country = {
        str(row["source_id"]).split(":", 2)[-1]: normalize_country(row.get("inferred_country"))
        for row in clean_posts
    }
    new_topics: dict[str, str] = {}
    outcome: Counter[tuple[str, str]] = Counter()
    for post in posts:
        if post.get("topic") or not post.get("post_id"):
            continue
        month = str(post.get("created_at") or "")[:7]
        country = post.get("country") or clean_country.get(str(post["post_id"]), "")
        keywords = groups.get((month, country), [])
        topic = keyword_in_text(f"{post.get('title') or ''} {post.get('body') or ''}", keywords)
        result = "tagged" if topic else ("no keyword in text" if keywords else "no keywords for month")
        outcome[(month, result)] += 1
        if topic:
            new_topics[str(post["post_id"])] = topic

    topic_by_post = {
        str(post["post_id"]): post["topic"] for post in posts if post.get("topic") and post.get("post_id")
    } | new_topics
    comments = fetch_all(session, base_url, key, "reddit_comments", {"select": "post_id", "topic": "is.null"})
    comment_posts = Counter(str(c["post_id"]) for c in comments if str(c.get("post_id")) in topic_by_post)
    untagged_clean = [row for row in clean_posts if not row.get("matched_keywords")]
    clean_updates = {
        row["source_id"]: topic_by_post[raw_id]
        for row in untagged_clean
        if (raw_id := str(row["source_id"]).split(":", 2)[-1]) in topic_by_post
    }

    print("Untagged raw Reddit posts:")
    for (month, result), count in sorted(outcome.items()):
        print(f"  {month}  {result}: {count}")
    print(f"Raw comments to tag from their post: {sum(comment_posts.values())} across {len(comment_posts)} posts")
    print(f"clean_posts rows to set matched_keywords: {len(clean_updates)} of {len(untagged_clean)} untagged")
    print("Keywords assigned:", Counter(new_topics.values()).most_common(10))

    if not args.apply:
        print("Preview only; pass --apply to write.")
        return

    written = Counter()
    for post_id, topic in new_topics.items():
        written["reddit_posts"] += patch(
            session, base_url, key, "reddit_posts",
            {"post_id": f"eq.{post_id}", "topic": "is.null"}, {"topic": topic},
        )
    for post_id in comment_posts:
        written["reddit_comments"] += patch(
            session, base_url, key, "reddit_comments",
            {"post_id": f"eq.{post_id}", "topic": "is.null"}, {"topic": topic_by_post[post_id]},
        )
    for source_id, topic in clean_updates.items():
        written["clean_posts"] += patch(
            session, base_url, key, "clean_posts",
            {"source_id": f"eq.{source_id}", "matched_keywords": "is.null"}, {"matched_keywords": [topic]},
        )
    expected = {
        "reddit_posts": len(new_topics),
        "reddit_comments": sum(comment_posts.values()),
        "clean_posts": len(clean_updates),
    }
    for table, count in expected.items():
        note = "" if written[table] == count else "  <- check RLS update policies / use a service key"
        print(f"{table}: updated {written[table]} of {count}{note}")


if __name__ == "__main__":
    main()
