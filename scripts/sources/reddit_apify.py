from apify_client import ApifyClient
from urllib.parse import quote_plus
from datetime import datetime, timedelta, timezone
import pandas as pd
import os
import sys
from pathlib import Path
from lingua import Language, LanguageDetectorBuilder
from dotenv import load_dotenv

# =====================================================
# CONFIGURATION
# =====================================================

REPO_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(REPO_ROOT / ".env")
APIFY_TOKEN = "apify_api_BVpQ54MVumBYBbbSW9aoTzhcI9p31L4qi8Kz"

MAX_POSTS = 2
MAX_COMMENTS = 2

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

for search_request in start_urls:
    run_input = {
        "startUrls": [{"url": search_request["url"]}],
        "fastMode": False,
        "maxPostsCount": MAX_POSTS,
        "maxCommentsPerPost": MAX_COMMENTS,
        "maxCommunitiesCount": 1,
        "crawlCommentsPerPost": True,
        "postedAfter": posted_after,
        "postedBefore": posted_before,
        "proxy": {
            "useApifyProxy": True,
            "apifyProxyGroups": ["RESIDENTIAL"]
        }
    }

    print(
        f"Starting actor for topic={search_request['topic']}, "
        f"country={search_request['country']}..."
    )
    run = client.actor("harshmaur/reddit-scraper").call(
        run_input=run_input
    )

    for item in client.dataset(run.default_dataset_id).iterate_items():
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
# KEEP ENGLISH CONTENT
# =====================================================

language_detector = (
    LanguageDetectorBuilder
    .from_all_languages()
    .with_minimum_relative_distance(0.25)
    .build()
)

def is_english(text):
    text = str(text or "").strip()
    if len(text) < 10:
        return False
    return language_detector.detect_language_of(text) == Language.ENGLISH

posts_df["language_text"] = (
    posts_df["title"].fillna("") + " " + posts_df["body"].fillna("")
)
comments_df["language_text"] = comments_df["body"].fillna("")

posts_df = posts_df[posts_df["language_text"].apply(is_english)].copy()

valid_post_ids = set(posts_df["post_id"].dropna())
comments_df = comments_df[
    comments_df["post_id"].isin(valid_post_ids)
].copy()

posts_df.drop(columns=["language_text"], inplace=True)
comments_df.drop(columns=["language_text"], inplace=True)

# =====================================================
# SAVE CSV FILES
# =====================================================

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
posts_file = os.path.join(SCRIPT_DIR, "reddit_posts.csv")
comments_file = os.path.join(SCRIPT_DIR, "reddit_comments.csv")

def append_unique_rows(new_df, csv_file, duplicate_column):
    if os.path.exists(csv_file):
        existing_df = pd.read_csv(csv_file)

        if duplicate_column == "post_id":
            existing_df["language_text"] = (
                existing_df["title"].fillna("")
                + " "
                + existing_df["body"].fillna("")
            )
        else:
            existing_df["language_text"] = existing_df["body"].fillna("")

        if duplicate_column == "post_id":
            existing_df = existing_df[
                existing_df["language_text"].apply(is_english)
            ].copy()
        existing_df.drop(columns=["language_text"], inplace=True)
        combined_df = pd.concat([existing_df, new_df], ignore_index=True)
    else:
        combined_df = new_df

    combined_df.drop_duplicates(
        subset=[duplicate_column],
        keep="last",
        inplace=True
    )
    combined_df.to_csv(
        csv_file,
        index=False,
        encoding="utf-8-sig"
    )
    return combined_df

posts_df = append_unique_rows(posts_df, posts_file, "post_id")
comments_df = append_unique_rows(comments_df, comments_file, "comment_id")

# Keep the CSV and Supabase datasets referentially consistent after merging
# previously collected rows.
valid_post_ids = set(posts_df["post_id"].dropna())
comments_df = comments_df[
    comments_df["post_id"].isin(valid_post_ids)
].copy()
comments_df.to_csv(
    comments_file,
    index=False,
    encoding="utf-8-sig"
)

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
print(f"Saved: {posts_file}")
print(f"Saved: {comments_file}")
