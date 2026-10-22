from apify_client import ApifyClient
from urllib.parse import quote_plus
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import pandas as pd
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

try:
    from lingua import Language, LanguageDetectorBuilder
except ImportError as error:
    from langdetect import DetectorFactory, LangDetectException, detect_langs

    DetectorFactory.seed = 0
    Language = None
    LanguageDetectorBuilder = None
    print(
        "Warning: lingua could not be loaded "
        f"({error}). Using langdetect as the English filter fallback."
    )

# =====================================================
# CONFIGURATION
# =====================================================

REPO_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(REPO_ROOT / ".env")
APIFY_TOKEN = os.getenv("APIFY_TOKEN")

APIFY_BUDGET_USD = Decimal("12")

# =====================================================
# RUN APIFY ACTOR
# =====================================================

# Select the complete previous calendar month in UTC.
today = datetime.now(timezone.utc).date()
current_month_start = today.replace(day=1)
previous_month_end = current_month_start - timedelta(days=1)
previous_month_start = previous_month_end.replace(day=1)

posted_after = previous_month_start.isoformat()
posted_before = previous_month_end.isoformat()

print(f"Collecting posts and comments from {posted_after} through {posted_before}")

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
from scripts.supabase.reddit_pipeline import topic_keyword_groups

keyword_groups = topic_keyword_groups(previous_month_start.isoformat())
start_urls = []
for country, keywords in keyword_groups.items():
    for keyword in keywords:
        search_query = f"{keyword} {country}"
        start_urls.append(
            {
                "url": f"https://www.reddit.com/search/?q={quote_plus(search_query)}",
                "topic": keyword,
                "country": country,
            }
        )

print(
    f"Loaded {sum(len(values) for values in keyword_groups.values())} top-three monthly keywords "
    f"across {len(keyword_groups)} countries"
)
print(f"Generated {len(start_urls)} search URLs")

client = ApifyClient(APIFY_TOKEN)

result_items = []
run_input = {
    "startUrls": [{"url": request["url"]} for request in start_urls],
    "fastMode": False,
    "maxCommunitiesCount": 1,
    "crawlCommentsPerPost": True,
    "postedAfter": posted_after,
    "postedBefore": posted_before,
    "proxy": {
        "useApifyProxy": True,
        "apifyProxyGroups": ["RESIDENTIAL"]
    }
}

print(f"Starting one Reddit actor run for {len(start_urls)} search URLs...")
run = client.actor("harshmaur/reddit-scraper").call(
    run_input=run_input,
    max_total_charge_usd=APIFY_BUDGET_USD,
)

# Refresh the completed run so usage_total_usd reflects the final Apify charge.
run = client.run(run.id).get() or run
spent_usd = Decimal(str(run.usage_total_usd or 0))
print(
    f"Reddit Apify usage: ${spent_usd:.2f} / "
    f"${APIFY_BUDGET_USD:.2f}"
)

search_requests_by_url = {
    request["url"]: request
    for request in start_urls
}
for item in client.dataset(run.default_dataset_id).iterate_items():
    source_url = (
        item.get("searchUrl")
        or item.get("sourceUrl")
        or item.get("startUrl")
    )
    search_request = search_requests_by_url.get(source_url)
    if search_request is None:
        search_request = {"topic": None, "country": None}
    result_items.append((
        item,
        search_request["topic"],
        search_request["country"],
    ))

print("Actor completed")

# =====================================================
# EXTRACT DATA
# =====================================================

posts_data = [] 
comments_data = []

for item, topic, country in result_items:
    item_type = item.get("dataType") or item.get("type")

    # Post record
    if item_type == "post" or item.get("postUrl") or item.get("title") is not None:
        posts_data.append({
            "post_id": item.get("id"),
            "post_url": item.get("postUrl"),
            "created_at": item.get("createdAt"),
            "author_name": item.get("authorName"),
            "title": item.get("title"),
            "body": item.get("body"),
            "community_name": item.get("communityName"),
            "data_type": item.get("dataType"),
            "flair": item.get("flair"),
            "comments_count": item.get("commentsCount"),
            "subreddit": item.get("subredditName"),
            "score": item.get("score"),
            "upvote_ratio": item.get("upvoteRatio"),
            "domain": item.get("domain"),
            "topic": topic,
            "country": country,
        })

    # Comment record
    if item_type == "comment" or item.get("parentId") is not None or item.get("body") and item.get("authorName") and item.get("parentId") is not None:
        comments_data.append({
            "comment_id": item.get("id"),
            "comment_url": item.get("url"),
            "comment_created_at": item.get("commentCreatedAt"),
            "author_name": item.get("authorName"),
            "post_id": item.get("postId") or item.get("parentId"),
            "post_title": item.get("postTitle"),
            "body": item.get("body"),
            "subreddit_name": item.get("subredditName"),
            "parent_id": item.get("parentId"),
            "data_type": item.get("dataType"),
            "score": item.get("score"),
            "parent_kind": item.get("parentKind"),
            "depth": item.get("depth"),
            "topic": topic,
            "country": country,
        })

    # Also handle nested comments on a post
    for comment in item.get("comments", []):
        comments_data.append({
            "comment_id": comment.get("id"),
            "comment_url": comment.get("url"),
            "comment_created_at": comment.get("commentCreatedAt"),
            "author_name": comment.get("authorName"),
            "post_id": item.get("id"),
            "post_title": item.get("title"),
            "body": comment.get("body"),
            "subreddit_name": item.get("subredditName"),
            "parent_id": comment.get("parentId"),
            "data_type": comment.get("dataType"),
            "score": comment.get("score"),
            "parent_kind": comment.get("parentKind"),
            "depth": comment.get("depth"),
            "topic": topic,
            "country": country,
        })

# =====================================================
# CREATE DATAFRAMES
# =====================================================

# Comments use the country assigned to their linked post, even when the
# scraper returned the comment as a separate top-level item.
post_country_by_id = {
    row["post_id"]: row.get("country")
    for row in posts_data
    if row.get("post_id")
}
for comment in comments_data:
    comment["country"] = post_country_by_id.get(comment.get("post_id"), comment.get("country"))

posts_df = pd.DataFrame(posts_data)
comments_df = pd.DataFrame(comments_data)

# =====================================================
# REMOVE DUPLICATES
# =====================================================

posts_df.drop_duplicates(
    subset=["post_id"],
    inplace=True)

comments_df.drop_duplicates(
    subset=["comment_id"],
    inplace=True
)

# =====================================================
# KEEP ENGLISH POSTS (AND THEIR COMMENTS)
# =====================================================

if LanguageDetectorBuilder is not None:
    language_detector = (
        LanguageDetectorBuilder
        .from_all_languages()
        .with_minimum_relative_distance(0.25)
        .build()
    )
else:
    language_detector = None

def is_english(text):
    text = str(text or "").strip()
    if len(text) < 10:
        return False
    if language_detector is not None:
        return language_detector.detect_language_of(text) == Language.ENGLISH

    try:
        detected = detect_langs(text)
    except LangDetectException:
        return False
    return bool(
        detected
        and detected[0].lang == "en"
        and detected[0].prob >= 0.75
    )

def english_posts_only(df):
    """Keep only posts whose title + body is detected as English."""
    language_text = df["title"].fillna("") + " " + df["body"].fillna("")
    return df[language_text.apply(is_english)].copy()

# Filter posts by language only.
posts_df = english_posts_only(posts_df)

# Keep every comment (any language) whose post survived the filter.
# Comments under non-English posts are dropped.
valid_post_ids = set(posts_df["post_id"].dropna())
comments_df = comments_df[comments_df["post_id"].isin(valid_post_ids)].copy()

# =====================================================
# SYNC TO SUPABASE
# =====================================================

def _sync_supabase(posts: list[dict], comments: list[dict]) -> None:
    """Sync cleaned Reddit data to Supabase."""
    repo_root = Path(__file__).resolve().parents[2]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    
    try:
        from dotenv import load_dotenv
        load_dotenv(repo_root / ".env")
        
        # DEBUG: Check credentials
        url = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
        key = os.environ.get("SUPABASE_KEY", "").strip()
        print(f"\nDEBUG: SUPABASE_URL = '{url}'")
        print(f"DEBUG: SUPABASE_KEY = {'[SET]' if key else '[EMPTY]'} (length: {len(key)})")
        
        if not url or not key:
            print("✗ Missing SUPABASE_URL or SUPABASE_KEY in .env")
            return
        
        from scripts.supabase.reddit_pipeline import sync_reddit_data
        print("Syncing to Supabase...")
        # Convert NaN to None for JSON serialization
        posts_dict = pd.DataFrame(posts).where(pd.notna(pd.DataFrame(posts)), None).to_dict('records')
        comments_dict = pd.DataFrame(comments).where(pd.notna(pd.DataFrame(comments)), None).to_dict('records')
        counts = sync_reddit_data(posts_dict, comments_dict)
        print("✓ Supabase sync successful")
        print(f"Upserted: {counts}")
    except ImportError as e:
        print(f"✗ Import error: {e}")
    except Exception as e:
        print(f"✗ Supabase sync failed: {e}")
        import traceback
        traceback.print_exc()

_sync_supabase(posts_df.to_dict('records'), comments_df.to_dict('records'))

# =====================================================
# SUMMARY
# =====================================================

print("\n===== SCRAPING COMPLETE =====")
print(f"Total Posts collected: {len(posts_df)}")
print(f"Total Comments collected: {len(comments_df)}")
