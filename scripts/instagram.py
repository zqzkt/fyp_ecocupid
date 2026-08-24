from apify_client import ApifyClient
import pandas as pd
import os

APIFY_TOKEN = "apify_api_uk96vRreCQ05EaWGOAPhYDqauRAlgo13Vl4r"

ACTOR_ID = "khadinakbar/instagram-hashtag-scraper"

HASHTAG = "climatechangesg" #climate change topics in sg

# Folder containing this Python file
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

POSTS_CSV = os.path.join(
    SCRIPT_DIR,
    "instagram_posts.csv"
)

COMMENTS_CSV = os.path.join(
    SCRIPT_DIR,
    "instagram_comments.csv"
)

#connecting to apify
client = ApifyClient(APIFY_TOKEN)

actor = client.actor(ACTOR_ID)

run_input = {
    "hashtags": [
        HASHTAG
    ],

    # Posts from approximately the past month
    "datePosted": "last-year",

    # Collect up to 20 posts
    "maxPosts": 20,

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

print(
    f"\nRaw dataset contains "
    f"{len(raw_df.columns)} columns."
)

post_columns = [
    "hashtag",
    "post_id",
    "shortcode",
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
    "video_view_count",
    "location_name",
    "is_ad",
    "is_paid_partnership",
    "display_url",
    "thumbnail_url",
    "scraped_at"
]


# Only keep fields that actually exist
available_post_columns = [
    column
    for column in post_columns
    if column in raw_df.columns
]


posts_df = raw_df[
    available_post_columns
].copy()

#add topic
posts_df.insert(
    0,
    "topic",
    "Climate Change"
)

#remove duplicate posts
if "post_id" in posts_df.columns:

    posts_df = posts_df.drop_duplicates(
        subset=["post_id"]
    )

elif "post_url" in posts_df.columns:

    posts_df = posts_df.drop_duplicates(
        subset=["post_url"]
    )


posts_df.to_csv(
    POSTS_CSV,
    index=False,
    encoding="utf-8-sig"
)


print(
    f"\nSaved {len(posts_df)} posts "
    f"to {POSTS_CSV}"
)

#normalize comments
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
                "Climate Change",

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

comments_df = pd.DataFrame(
    comments_rows
)

#remove duplicate comments
if not comments_df.empty:

    if "comment_id" in comments_df.columns:

        comments_df = (
            comments_df
            .drop_duplicates(
                subset=["comment_id"]
            )
        )

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

print("\n======================================")
print("SCRAPING COMPLETE")
print("======================================")

print(
    f"Total posts: "
    f"{len(posts_df)}"
)

print(
    f"Total sampled comments: "
    f"{len(comments_df)}"
)

print("\nPOST PREVIEW:")

preview_post_columns = [
    column
    for column in [
        "topic",
        "post_url",
        "author_username",
        "posted_at",
        "like_count",
        "comment_count"
    ]
    if column in posts_df.columns
]

print(
    posts_df[
        preview_post_columns
    ].head()
)

if not comments_df.empty:

    print("\nCOMMENT PREVIEW:")

    print(
        comments_df[
            [
                "post_id",
                "comment_username",
                "comment_text",
                "comment_like_count"
            ]
        ].head()
    )