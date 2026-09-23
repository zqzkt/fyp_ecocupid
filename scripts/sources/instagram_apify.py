from datetime import datetime, timezone
import os
import sys
from pathlib import Path

import pandas as pd
from apify_client import ApifyClient
from lingua import Language, LanguageDetectorBuilder

APIFY_TOKEN = "apify_api_uk96vRreCQ05EaWGOAPhYDqauRAlgo13Vl4r"

ACTOR_ID = "khadinakbar/instagram-hashtag-scraper"

HASHTAG = "climatechangesg" #climate change topics in sg
TOPIC = "Climate Change"
COUNTRY = "Singapore"

POST_COLUMNS = [
    "topic",
    "country",
    "hashtag",
    "post_id",
    "post_url",
    "caption",
    "posted_at",
    "author_username",
    "author_full_name",
    "author_follower_count",
    "author_is_verified",
    "like_count",
    "comment_count",
    "engagement_count",
    "engagement_rate",
    "media_type",
    "is_reel",
    "play_count",
]

COMMENT_COLUMNS = [
    "topic",
    "country",
    "hashtag",
    "post_id",
    "post_url",
    "post_author_username",
    "comment_id",
    "comment_text",
    "comment_username",
    "comment_created_at",
    "comment_like_count",
]

# =====================================================
# DATE RANGE
# =====================================================


def previous_calendar_month() -> tuple[pd.Timestamp, pd.Timestamp]:
    today = datetime.now(timezone.utc).date()
    current_month_start = today.replace(day=1)

    previous_month_number = current_month_start.month - 1 or 12
    previous_month_year = current_month_start.year - (
        current_month_start.month == 1
    )

    previous_month_start = current_month_start.replace(
        year=previous_month_year,
        month=previous_month_number,
        day=1,
    )

    return (
        pd.Timestamp(previous_month_start, tz="UTC"),
        pd.Timestamp(current_month_start, tz="UTC"),
    )


MONTH_START, CURRENT_MONTH_START = previous_calendar_month()

# =====================================================
# CSV FILES
# =====================================================

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

POSTS_CSV = os.path.join(
    SCRIPT_DIR,
    "instagram_posts.csv"
)

COMMENTS_CSV = os.path.join(
    SCRIPT_DIR,
    "instagram_comments.csv"
)

# =====================================================
# RUN APIFY ACTOR
# =====================================================

client = ApifyClient(APIFY_TOKEN)

actor = client.actor(ACTOR_ID)

run_input = {
    "hashtags": [
        HASHTAG
    ],

    # The actor uses a rolling freshness window; the exact calendar-month
    # boundary is enforced after retrieval below.
    "datePosted": "last-month",

    # Use the actor's supported per-hashtag limit before local filtering.
    "maxPostsPerHashtag": 510,

    # Only keep posts with some meaningful engagement
    "minimumLikes": 10,

    # Include sampled comments
    "includeComments": True,

    # Return full metadata
    "outputMode": "full"
}

print("\n======================================")
print("INSTAGRAM HASHTAG SCRAPER")
print("======================================")

print(f"Hashtag: #{HASHTAG}")
print(f"Collecting posts from {MONTH_START.date()} through {(CURRENT_MONTH_START - pd.Timedelta(days=1)).date()}")
print("Starting Apify Actor...")

run = actor.call(
    run_input=run_input
)

print("\nScraping completed.")
print("Retrieving dataset...")

dataset_id = run.default_dataset_id

items = client.dataset(
    dataset_id
).list_items().items


print(
    f"Retrieved {len(items)} posts."
)

if not items:

    print(
        "\nNo Instagram posts were returned."
    )

    exit()

raw_df = pd.DataFrame(items)

if "posted_at" in raw_df.columns:
    posted_at = pd.to_datetime(raw_df["posted_at"], utc=True, errors="coerce")
    raw_df = raw_df[
        (posted_at >= MONTH_START) & (posted_at < CURRENT_MONTH_START)
    ].copy()
else:
    raw_df = raw_df.iloc[0:0].copy()

items = [
    item for item in items
    if pd.to_datetime(item.get("posted_at"), utc=True, errors="coerce") >= MONTH_START
    and pd.to_datetime(item.get("posted_at"), utc=True, errors="coerce") < CURRENT_MONTH_START
]

if raw_df.empty:
    print(
        "\nNo Instagram posts matched the exact previous-calendar-month filter."
    )
    print(
        "The actor returned candidates, but none were posted between "
        f"{MONTH_START.date()} and {(CURRENT_MONTH_START - pd.Timedelta(days=1)).date()}."
    )
    sys.exit(0)

print(
    f"\nRaw dataset contains "
    f"{len(raw_df.columns)} columns."
)

posts_df = raw_df.reindex(columns=POST_COLUMNS).copy()
posts_df["topic"] = TOPIC
posts_df["country"] = COUNTRY


#remove duplicate posts
if "post_id" in posts_df.columns:

    posts_df = posts_df.drop_duplicates(
        subset=["post_id"]
    )

elif "post_url" in posts_df.columns:

    posts_df = posts_df.drop_duplicates(
        subset=["post_url"]
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


posts_df = posts_df[
    posts_df["caption"].apply(is_english)
].copy()

valid_post_ids = set(
    posts_df.get("post_id", pd.Series(dtype="object")).dropna()
)
items = [
    item for item in items
    if item.get("post_id") in valid_post_ids
]


posts_df.to_csv(
    POSTS_CSV,
    index=False,
    encoding="utf-8-sig"
)


print(
    f"\nSaved {len(posts_df)} posts "
    f"to {POSTS_CSV}"
)

# =====================================================
# EXTRACT COMMENTS
# =====================================================

comments_rows = []


for item in items:

    post_id = item.get(
        "post_id"
    )

    post_url = item.get(
        "post_url"
    )

    author_username = item.get(
        "author_username"
    )

    comments = item.get(
        "comments",
        []
    )


    # Sometimes comments may be missing
    if not comments:

        continue


    for comment in comments:

        comments_rows.append({

            "topic":
                TOPIC,

            "country":
                COUNTRY,

            "hashtag":
                HASHTAG,

            "post_id":
                post_id,

            "post_url":
                post_url,

            "post_author_username":
                author_username,

            "comment_id":
                comment.get(
                    "id"
                ),

            "comment_text":
                comment.get(
                    "text"
                ),

            "comment_username":
                comment.get(
                    "owner_username"
                ),

            "comment_owner_id":
                comment.get(
                    "owner_id"
                ),

            "comment_owner_is_verified":
                comment.get(
                    "owner_is_verified"
                ),

            "comment_created_at":
                comment.get(
                    "created_at"
                ),

            "comment_like_count":
                comment.get(
                    "like_count"
                )
        })

comments_df = pd.DataFrame(comments_rows, columns=COMMENT_COLUMNS)

#remove duplicate comments
if not comments_df.empty:

    if "comment_id" in comments_df.columns:

        comments_df = (
            comments_df
            .drop_duplicates(
                subset=["comment_id"]
            )
        )

comments_df = comments_df[
    comments_df["comment_text"].apply(is_english)
].copy()
comments_df = comments_df[
    comments_df["post_id"].isin(valid_post_ids)
].copy()

if not comments_df.empty:

    comments_df.to_csv(
        COMMENTS_CSV,
        index=False,
        encoding="utf-8-sig"
    )

    print(
        f"Saved {len(comments_df)} comments "
        f"to {COMMENTS_CSV}"
    )

else:

    print(
        "\nNo sampled comments "
        "were returned by the Actor."
    )

# =====================================================
# SUMMARY
# =====================================================

print(
    f"Total posts: "
    f"{len(posts_df)}"
)

print(
    f"Total sampled comments: "
    f"{len(comments_df)}"
)

# =====================================================
# SYNC TO SUPABASE
# =====================================================

def _sync_supabase(posts: list[dict], comments: list[dict]) -> None:
    """Sync cleaned Instagram data to Supabase."""
    repo_root = Path(__file__).resolve().parents[2]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    try:
        from dotenv import load_dotenv
        load_dotenv(repo_root / ".env")

        url = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
        key = (
            os.environ.get("SUPABASE_SECRET_KEY")
            or os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
            or os.environ.get("SUPABASE_KEY")
            or ""
        ).strip()

        if not url or not key:
            print("✗ Missing SUPABASE_URL or Supabase server key in .env")
            return

        if key.startswith("sb_publishable_") or key.startswith("sb_anon_"):
            print("✗ Supabase key must be a server-only secret/service-role key")
            return

        from scripts.supabase.instagram_pipeline import sync_instagram_data
        print("Syncing to Supabase...")

        posts_dict = (
            pd.DataFrame(posts)
            .where(pd.notna(pd.DataFrame(posts)), None)
            .to_dict("records")
        )
        comments_dict = (
            pd.DataFrame(comments)
            .where(pd.notna(pd.DataFrame(comments)), None)
            .to_dict("records")
        )

        counts = sync_instagram_data(posts_dict, comments_dict)
        print("✓ Supabase sync successful")
        print(f"Upserted: {counts}")
    except ImportError as error:
        print(f"✗ Import error: {error}")
    except Exception as error:
        print(f"✗ Supabase sync failed: {error}")
        import traceback
        traceback.print_exc()


_sync_supabase(posts_df.to_dict("records"), comments_df.to_dict("records"))

print("\n======================================")
print("SCRAPING COMPLETE")
print("======================================")
print(f"Total Posts collected: {len(posts_df)}")
print(f"Total Comments collected: {len(comments_df)}")
print(f"Saved: {POSTS_CSV}")
print(f"Saved: {COMMENTS_CSV}")