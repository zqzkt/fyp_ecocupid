from apify_client import ApifyClient
from urllib.parse import quote_plus
import pandas as pd
import os

# =====================================================
# CONFIGURATION
# =====================================================

APIFY_TOKEN = "apify_api_BVpQ54MVumBYBbbSW9aoTzhcI9p31L4qi8Kz"

topics = [
    # "sustainability",
    # "environment",
    # "climate change",
    # "pollution",
    "haze",
    # "renewable energy",
    # "waste management",
    # "carbon emissions"
]

countries = [
    "Singapore",
    # "Malaysia",
    # "Indonesia",
    # "Philippines",
    # "Brunei",
    # "Thailand"
]

MAX_POSTS = 3
MAX_COMMENTS = 2

# =====================================================
# GENERATE REDDIT SEARCH URLS
# =====================================================

start_urls = []

for topic in topics:
    for country in countries:

        search_query = f"{topic} {country}"

        start_urls.append(
            {
                "url": f"https://www.reddit.com/search/?q={quote_plus(search_query)}",
                "userData": {
                    "topic": topic,
                    "country": country
                }
            }
        )

print(f"Generated {len(start_urls)} search URLs")

# =====================================================
# RUN APIFY ACTOR
# =====================================================

client = ApifyClient(APIFY_TOKEN)

run_input = {
    # "searchPosts": True,
    # "searchComments": True,
    "startUrls": start_urls,
    "fastMode": False,
    "maxPostsCount": MAX_POSTS,
    "maxCommentsPerPost": MAX_COMMENTS,
    "maxCommunitiesCount": 1,
    "crawlCommentsPerPost": True,
    "postedAfter": "2021-01-01",
    "proxy": {
        "useApifyProxy": True,
        "apifyProxyGroups": ["RESIDENTIAL"]
    }
}

print("Starting actor...")

run = client.actor("harshmaur/reddit-scraper").call(
    run_input=run_input
)

print("Actor completed")

# =====================================================
# EXTRACT DATA
# =====================================================

dataset_id = run.default_dataset_id

posts_data = [] 
comments_data = []

for item in client.dataset(dataset_id).iterate_items():
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
        })

# =====================================================
# CREATE DATAFRAMES
# =====================================================

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
# SAVE CSV FILES
# =====================================================

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
posts_file = os.path.join(SCRIPT_DIR, "reddit_posts.csv")
comments_file = os.path.join(SCRIPT_DIR, "reddit_comments.csv")

def append_unique_rows(new_df, csv_file, duplicate_column):
    if os.path.exists(csv_file):
        existing_df = pd.read_csv(csv_file)
        combined_df = pd.concat([existing_df, new_df], ignore_index=True)
    else:
        combined_df = new_df

    combined_df.drop_duplicates(
        subset=[duplicate_column],
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

# =====================================================
# SUMMARY
# =====================================================

print("\n===== SCRAPING COMPLETE =====")
print(f"Posts collected: {len(posts_df)}")
print(f"Comments collected: {len(comments_df)}")
print(f"Saved: {posts_file}")
print(f"Saved: {comments_file}")