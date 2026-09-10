import os
import json
import re
from pathlib import Path
from collections import Counter, defaultdict

from dotenv import load_dotenv
from apify_client import ApifyClient


# =========================================================
# PATHS + ENVIRONMENT
# =========================================================

# facebook.py is in:
# repo/scripts/sources/facebook.py
# Therefore parents[2] = repo root
REPO_ROOT = Path(__file__).resolve().parents[2]

load_dotenv(REPO_ROOT / ".env")

APIFY_TOKEN = os.getenv("APIFY_TOKEN")

if not APIFY_TOKEN:
    raise RuntimeError(
        "APIFY_TOKEN was not found. "
        "Make sure your .env file is in the repo root."
    )

client = ApifyClient(APIFY_TOKEN)


# =========================================================
# APIFY ACTORS
# =========================================================

POSTS_ACTOR = "apify/facebook-posts-scraper"
COMMENTS_ACTOR = "apify/facebook-comments-scraper"


# =========================================================
# SCRAPING CONFIGURATION
# =========================================================

# KEEP THESE SMALL WHILE TESTING
#
# Later for a full run, you can increase them.
POST_LIMIT_PER_PAGE = 10
COMMENT_LIMIT_PER_POST = 10

POST_DATE_RANGE = "30 days"

# Maximum number of posts from the SAME topic that
# can be selected for comment scraping.
MAX_POSTS_PER_TOPIC_FOR_COMMENTS = 3

# Maximum total number of posts whose comments we scrape.
MAX_TOTAL_POSTS_FOR_COMMENTS = 15


# =========================================================
# APIFY COST SAFETY
# =========================================================

# Keep these low during testing.
# Increase only when we are ready for the full run.

POST_RUN_MAX_COST_USD = 1.50
COMMENT_RUN_MAX_COST_USD = 0.50


# =========================================================
# CACHE SETTINGS
# =========================================================

# IMPORTANT:
# Once you successfully scrape posts, you can set this to True.
# Then the program will use the saved JSON instead of calling
# Apify again while you work on your classification logic.

USE_CACHED_POSTS = False
USE_CACHED_COMMENTS = False

DATA_DIR = REPO_ROOT / "data" / "raw"

POSTS_CACHE_FILE = DATA_DIR / "facebook_posts_raw.json"
COMMENTS_CACHE_FILE = DATA_DIR / "facebook_comments_raw.json"

ENVIRONMENTAL_POSTS_FILE = (
    DATA_DIR / "facebook_posts_environmental.json"
)

NORMALISED_COMMENTS_FILE = (
    DATA_DIR / "facebook_comments_normalised.json"
)


# =========================================================
# FACEBOOK SOURCES
# =========================================================

# For now we are testing Singapore.
#
# Add more sources/countries later.
#
# Having different types of pages reduces the risk of your
# dataset being dominated by one issue such as haze.

FACEBOOK_SOURCES = [
    # Singapore
    {
        "country": "Singapore",
        "source_name": "NEA Singapore",
        "url": "https://www.facebook.com/NEASingapore",
    },
    {
        "country": "Singapore",
        "source_name": "NParks",
        "url": "https://www.facebook.com/nparksbuzz",
    },

    # Malaysia
    {
        "country": "Malaysia",
        "source_name": "WWF Malaysia",
        "url": "https://www.facebook.com/wwfmy",
    },
    {
        "country": "Malaysia",
        "source_name": "Friends of the Earth Malaysia",
        "url": "https://www.facebook.com/FriendsoftheEarthMalaysia",
    },

    # Indonesia
    {
        "country": "Indonesia",
        "source_name": "WALHI",
        "url": "https://www.facebook.com/WALHI",
    },
    {
        "country": "Indonesia",
        "source_name": "WWF Indonesia",
        "url": "https://www.facebook.com/WWFIndonesia",
    },

    # Philippines
    {
        "country": "Philippines",
        "source_name": "DENR Philippines",
        "url": "https://www.facebook.com/DENROfficial",
    },
    {
        "country": "Philippines",
        "source_name": "Haribon Foundation",
        "url": "https://www.facebook.com/GoHaribon",
    },

    # Thailand
    {
        "country": "Thailand",
        "source_name": "Greenpeace Thailand",
        "url": "https://www.facebook.com/greenpeaceth",
    },
    {
        "country": "Thailand",
        "source_name": "WWF Thailand",
        "url": "https://www.facebook.com/wwfthailand",
    },

    # Vietnam
    {
        "country": "Vietnam",
        "source_name": "WWF Vietnam",
        "url": "https://www.facebook.com/VietnamWWF",
    },
    {
        "country": "Vietnam",
        "source_name": "GreenHub Vietnam",
        "url": "https://www.facebook.com/600459996771784",
    },

    # Myanmar
    {
        "country": "Myanmar",
        "source_name": "Myanmar Climate Change Alliance",
        "url": "https://www.facebook.com/myanmarccalliance",
    },
    {
        "country": "Myanmar",
        "source_name": "EHS Myanmar",
        "url": "https://www.facebook.com/ehsmyanmar",
    },
]


# =========================================================
# ENVIRONMENTAL TOPICS
# =========================================================

# Instead of simply saying:
#
# environmental = True / False
#
# we classify environmental posts into topics.

ENVIRONMENT_TOPICS = {

    "air_pollution_haze": [
        "haze",
        "air pollution",
        "air quality",
        "pm2.5",
        "psi",
        "smoke haze",
        "smoke plume",
    ],

    "climate_change_heat": [
        "climate change",
        "global warming",
        "climate crisis",
        "extreme heat",
        "heatwave",
        "heat wave",
        "rising temperature",
        "climate adaptation",
        "climate resilience",
    ],

    "waste_recycling": [
        "recycling",
        "plastic waste",
        "food waste",
        "e-waste",
        "electronic waste",
        "single-use plastic",
        "single use plastic",
        "waste reduction",
        "zero waste",
        "circular economy",
    ],

    "biodiversity_conservation": [
        "biodiversity",
        "wildlife",
        "conservation",
        "habitat",
        "endangered",
        "ecosystem",
        "nature reserve",
        "species",
        "coral",
        "mangrove",
    ],

    "renewable_energy": [
        "renewable energy",
        "solar energy",
        "solar power",
        "solar panel",
        "clean energy",
        "green energy",
        "energy transition",
        "wind energy",
    ],

    "carbon_emissions": [
        "carbon emissions",
        "carbon emission",
        "carbon footprint",
        "greenhouse gas",
        "greenhouse gases",
        "net zero",
        "decarbonisation",
        "decarbonization",
        "carbon neutral",
    ],

    "water_flooding": [
        "water pollution",
        "water conservation",
        "water scarcity",
        "flooding",
        "flash flood",
        "flood",
        "drought",
        "water security",
    ],

    "deforestation_land_use": [
        "deforestation",
        "forest clearing",
        "land clearing",
        "land use",
        "forest fire",
        "forest fires",
        "peat fire",
        "peatland",
    ],

    "sustainable_consumption": [
        "sustainability",
        "sustainable living",
        "sustainable consumption",
        "green living",
        "eco-friendly",
        "eco friendly",
        "reuse",
        "reusable",
    ],
}


# =========================================================
# HELPER FUNCTIONS
# =========================================================

def canonicalise_url(url):
    """
    Standardise URLs so they are easier to compare.
    """

    if not url:
        return ""

    return url.rstrip("/").lower()


def safe_int(value):
    """
    Convert engagement fields safely to integers.
    """

    try:
        return int(value or 0)

    except (TypeError, ValueError):
        return 0


def get_page_name(post):
    """
    Apify may return pageName as either a string
    or an object.
    """

    page_name = post.get("pageName")

    if isinstance(page_name, dict):
        return (
            page_name.get("name")
            or page_name.get("title")
            or "Unknown"
        )

    return page_name or "Unknown"


def keyword_present(text, keyword):
    """
    Checks whether a keyword appears in the text.

    Regex boundaries reduce accidental partial matches.
    """

    pattern = (
        r"(?<!\w)"
        + re.escape(keyword.lower())
        + r"(?!\w)"
    )

    return re.search(
        pattern,
        text.lower()
    ) is not None


def save_json(data, filepath):
    """
    Save results locally so we do not need to repeatedly
    pay Apify while debugging.
    """

    filepath.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    with open(
        filepath,
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            data,
            file,
            indent=2,
            ensure_ascii=False
        )

    print(f"Saved: {filepath}")


def load_json(filepath):
    """
    Load previously scraped data.
    """

    with open(
        filepath,
        "r",
        encoding="utf-8"
    ) as file:

        return json.load(file)


# =========================================================
# POST SCRAPING
# =========================================================

def fetch_facebook_posts(
    sources,
    limit=POST_LIMIT_PER_PAGE
):

    page_urls = [
        {
            "url": source["url"]
        }
        for source in sources
    ]

    run_input = {

        "startUrls": page_urls,

        "resultsLimit": limit,

        "onlyPostsNewerThan": POST_DATE_RANGE,

        "captionText": False,
    }

    print(
        f"\nStarting Facebook post scraper "
        f"for {len(page_urls)} page(s)..."
    )

    run = client.actor(
        POSTS_ACTOR
    ).call(

        run_input=run_input,

        max_total_charge_usd=(
            POST_RUN_MAX_COST_USD
        ),
    )

    if run is None:

        print(
            "Facebook post scraper failed "
            "to start."
        )

        return []

    dataset_id = run.default_dataset_id

    items = (
        client
        .dataset(dataset_id)
        .list_items()
        .items
    )

    # -----------------------------------------------------
    # Attach source/country information
    # -----------------------------------------------------

    source_lookup = {
        canonicalise_url(source["url"]): source
        for source in sources
    }

    enriched_posts = []

    seen_post_ids = set()

    for item in items:

        post = dict(item)

        post_id = str(
            post.get("postId") or ""
        )

        # Avoid duplicate posts
        if post_id:

            if post_id in seen_post_ids:
                continue

            seen_post_ids.add(post_id)

        facebook_page_url = canonicalise_url(
            post.get("facebookUrl")
        )

        source_info = source_lookup.get(
            facebook_page_url
        )

        if source_info:

            post["country"] = (
                source_info["country"]
            )

            post["source_name"] = (
                source_info["source_name"]
            )

        else:

            post["country"] = "Unknown"

            post["source_name"] = (
                get_page_name(post)
            )

        enriched_posts.append(post)

    return enriched_posts


# =========================================================
# ENVIRONMENTAL CLASSIFICATION
# =========================================================

def classify_environmental_post(post):
    """
    Identify which environmental topics appear
    in a Facebook post.
    """

    text_parts = [
        post.get("text") or "",
        post.get("previewTitle") or "",
        post.get("previewDescription") or "",
    ]

    combined_text = " ".join(
        text_parts
    ).lower()

    matched_topics = {}

    for topic, keywords in (
        ENVIRONMENT_TOPICS.items()
    ):

        matches = [
            keyword
            for keyword in keywords
            if keyword_present(
                combined_text,
                keyword
            )
        ]

        if matches:

            matched_topics[topic] = matches

    # Not environmental according to our rules
    if not matched_topics:
        return None

    # -----------------------------------------------------
    # Choose primary topic
    #
    # First:
    # topic with most keyword matches
    #
    # Tie-breaker:
    # topic containing more specific/longer keywords
    # -----------------------------------------------------

    primary_topic = max(

        matched_topics,

        key=lambda topic: (

            len(
                matched_topics[topic]
            ),

            sum(
                len(keyword)
                for keyword
                in matched_topics[topic]
            ),
        ),
    )

    classified_post = dict(post)

    classified_post[
        "primary_topic"
    ] = primary_topic

    classified_post[
        "matched_topics"
    ] = matched_topics

    return classified_post


def filter_environmental_posts(posts):

    environmental_posts = []

    for post in posts:

        classified_post = (
            classify_environmental_post(post)
        )

        if classified_post:

            environmental_posts.append(
                classified_post
            )

    return environmental_posts


# =========================================================
# TOPIC ANALYSIS
# =========================================================

def print_topic_distribution(posts):

    if not posts:

        print(
            "\nNo environmental posts "
            "available."
        )

        return

    counts = Counter(

        post["primary_topic"]
        for post in posts

    )

    total = len(posts)

    print("\n==============================")
    print("ENVIRONMENTAL TOPIC DISTRIBUTION")
    print("==============================")

    for topic, count in (
        counts.most_common()
    ):

        percentage = (
            count / total
        ) * 100

        print(
            f"{topic}: "
            f"{count} "
            f"({percentage:.1f}%)"
        )


# =========================================================
# SELECT DIVERSE POSTS FOR COMMENTS
# =========================================================

def select_diverse_posts_for_comments(
    posts,
    max_per_topic=(
        MAX_POSTS_PER_TOPIC_FOR_COMMENTS
    ),
    max_total=(
        MAX_TOTAL_POSTS_FOR_COMMENTS
    ),
):

    """
    Creates a diversified sample for comment scraping.

    Important:
    We DO NOT remove overrepresented topics from the raw
    dataset.

    Example:
    If haze represents 70% of all posts, the raw topic
    distribution still shows 70%.

    This function only prevents us from spending most of
    the comment-scraping budget on haze posts.
    """

    grouped_posts = defaultdict(list)

    for post in posts:

        comment_count = safe_int(
            post.get("comments")
        )

        # There is little point paying the Comments Actor
        # for a post Facebook reports as having 0 comments.
        if comment_count <= 0:
            continue

        topic = post["primary_topic"]

        grouped_posts[topic].append(
            post
        )

    # -----------------------------------------------------
    # Within each topic:
    # prioritise posts generating more discussion
    # -----------------------------------------------------

    for topic in grouped_posts:

        grouped_posts[topic].sort(

            key=lambda post: (

                safe_int(
                    post.get("comments")
                ),

                safe_int(
                    post.get("likes")
                ),

                safe_int(
                    post.get("shares")
                ),

            ),

            reverse=True
        )

    if not grouped_posts:

        return []

    # -----------------------------------------------------
    # Put less common topics first.
    #
    # This reduces the chance that one dominant topic
    # uses the entire comment scraping budget.
    # -----------------------------------------------------

    topic_order = sorted(

        grouped_posts.keys(),

        key=lambda topic: (
            len(grouped_posts[topic]),
            topic
        )
    )

    selected = []

    # -----------------------------------------------------
    # Round-robin selection.
    #
    # Round 1:
    # 1 post from every available topic.
    #
    # Round 2:
    # another post from every available topic.
    #
    # etc.
    # -----------------------------------------------------

    for position in range(
        max_per_topic
    ):

        for topic in topic_order:

            if len(selected) >= max_total:
                break

            topic_posts = (
                grouped_posts[topic]
            )

            if position < len(topic_posts):

                selected.append(
                    topic_posts[position]
                )

        if len(selected) >= max_total:
            break

    return selected


# =========================================================
# COMMENT SCRAPING
# =========================================================

def fetch_facebook_comments(
    posts,
    limit=COMMENT_LIMIT_PER_POST
):

    post_urls = [
        {
            "url": post["url"]
        }
        for post in posts
        if post.get("url")
    ]

    if not post_urls:

        print(
            "\nNo post URLs available "
            "for comment scraping."
        )

        return []

    run_input = {

        "startUrls": post_urls,

        "resultsLimit": limit,

        # Replies also count as individual results.
        # Keep False for now to control cost.
        "includeNestedComments": False,
    }

    print(
        f"\nStarting comment scraper "
        f"for {len(post_urls)} post(s)..."
    )

    run = client.actor(
        COMMENTS_ACTOR
    ).call(

        run_input=run_input,

        max_total_charge_usd=(
            COMMENT_RUN_MAX_COST_USD
        ),
    )

    if run is None:

        print(
            "Comment scraper failed "
            "to start."
        )

        return []

    dataset_id = run.default_dataset_id

    items = (
        client
        .dataset(dataset_id)
        .list_items()
        .items
    )

    # -----------------------------------------------------
    # Attach parent post metadata to comments
    # -----------------------------------------------------

    post_lookup = {

        canonicalise_url(post["url"]): post

        for post in posts

        if post.get("url")
    }

    enriched_comments = []

    seen_comment_ids = set()

    for item in items:

        comment = dict(item)

        comment_id = str(
            comment.get("commentId") or ""
        )

        if comment_id:

            if (
                comment_id
                in seen_comment_ids
            ):
                continue

            seen_comment_ids.add(
                comment_id
            )

        parent_url = canonicalise_url(
            comment.get("facebookUrl")
        )

        parent_post = post_lookup.get(
            parent_url
        )

        if parent_post:

            comment["parent_post_id"] = (
                parent_post.get("postId")
            )

            comment["country"] = (
                parent_post.get("country")
            )

            comment["source_name"] = (
                parent_post.get(
                    "source_name"
                )
            )

            comment["primary_topic"] = (
                parent_post.get(
                    "primary_topic"
                )
            )

        enriched_comments.append(
            comment
        )

    return enriched_comments


# =========================================================
# NORMALISATION
# =========================================================

def normalise_facebook_post(post):

    return {

        "platform": "facebook",

        "post_id": post.get(
            "postId"
        ),

        "country": post.get(
            "country"
        ),

        "source_name": post.get(
            "source_name"
        ),

        "page_name": get_page_name(
            post
        ),

        "published_at": post.get(
            "time"
        ),

        "url": post.get(
            "url"
        ),

        "text": post.get(
            "text"
        ),

        "likes": safe_int(
            post.get("likes")
        ),

        "comments_count": safe_int(
            post.get("comments")
        ),

        "shares": safe_int(
            post.get("shares")
        ),

        "primary_topic": post.get(
            "primary_topic"
        ),

        "matched_topics": post.get(
            "matched_topics",
            {}
        ),
    }


def normalise_facebook_comment(comment):

    return {

        "platform": "facebook",

        "comment_id": comment.get(
            "commentId"
        ),

        "parent_post_id": comment.get(
            "parent_post_id"
        ),

        "post_url": comment.get(
            "facebookUrl"
        ),

        "country": comment.get(
            "country"
        ),

        "source_name": comment.get(
            "source_name"
        ),

        "primary_topic": comment.get(
            "primary_topic"
        ),

        "published_at": comment.get(
            "date"
        ),

        "text": comment.get(
            "text"
        ),

        "likes": safe_int(
            comment.get("likesCount")
        ),
    }


# =========================================================
# MAIN PROGRAM
# =========================================================

if __name__ == "__main__":

    print("\n==============================")
    print("FACEBOOK ENVIRONMENT PIPELINE")
    print("==============================")


    # =====================================================
    # STEP 1: COLLECT POSTS
    # =====================================================

    if (
        USE_CACHED_POSTS
        and POSTS_CACHE_FILE.exists()
    ):

        print(
            "\nUsing cached Facebook posts..."
        )

        posts = load_json(
            POSTS_CACHE_FILE
        )

    else:

        posts = fetch_facebook_posts(
            FACEBOOK_SOURCES
        )

        save_json(
            posts,
            POSTS_CACHE_FILE
        )


    print(
        f"\nRaw posts collected: "
        f"{len(posts)}"
    )


    # =====================================================
    # STEP 2: CLASSIFY ENVIRONMENTAL POSTS
    # =====================================================

    environmental_posts = (
        filter_environmental_posts(
            posts
        )
    )

    print(
        f"Environmental posts found: "
        f"{len(environmental_posts)}"
    )

    save_json(
        environmental_posts,
        ENVIRONMENTAL_POSTS_FILE
    )


    # =====================================================
    # STEP 3: DISPLAY TOPIC DISTRIBUTION
    # =====================================================

    print_topic_distribution(
        environmental_posts
    )


    # =====================================================
    # STEP 4: SHOW ENVIRONMENTAL POSTS
    # =====================================================

    print("\n==============================")
    print("ENVIRONMENTAL POSTS")
    print("==============================")

    for i, post in enumerate(
        environmental_posts,
        start=1
    ):

        print(
            f"\n--- Environmental Post {i} ---"
        )

        print(
            "Country:",
            post.get("country")
        )

        print(
            "Source:",
            post.get("source_name")
        )

        print(
            "Topic:",
            post.get("primary_topic")
        )

        print(
            "Matched topics:",
            post.get("matched_topics")
        )

        print(
            "Comments:",
            post.get("comments")
        )

        print(
            "Likes:",
            post.get("likes")
        )

        print(
            "URL:",
            post.get("url")
        )

        print(
            "Text:",
            post.get("text")
        )


    # =====================================================
    # STEP 5: SELECT DIVERSE POSTS FOR COMMENTS
    # =====================================================

    selected_posts = (
        select_diverse_posts_for_comments(
            environmental_posts
        )
    )

    print("\n==============================")
    print("POSTS SELECTED FOR COMMENTS")
    print("==============================")

    print(
        f"Selected "
        f"{len(selected_posts)} "
        f"post(s)."
    )

    for post in selected_posts:

        print(
            f"\nTopic: "
            f"{post.get('primary_topic')}"
        )

        print(
            f"Source: "
            f"{post.get('source_name')}"
        )

        print(
            f"Facebook comment count: "
            f"{post.get('comments')}"
        )

        print(
            f"URL: "
            f"{post.get('url')}"
        )


    # =====================================================
    # STEP 6: SCRAPE COMMENTS
    # =====================================================

    if selected_posts:

        if (
            USE_CACHED_COMMENTS
            and COMMENTS_CACHE_FILE.exists()
        ):

            print(
                "\nUsing cached "
                "Facebook comments..."
            )

            comments = load_json(
                COMMENTS_CACHE_FILE
            )

        else:

            comments = (
                fetch_facebook_comments(
                    selected_posts
                )
            )

            save_json(
                comments,
                COMMENTS_CACHE_FILE
            )

    else:

        comments = []


    print(
        f"\nComments collected: "
        f"{len(comments)}"
    )


    # =====================================================
    # STEP 7: DISPLAY COMMENTS
    # =====================================================

    for i, comment in enumerate(
        comments,
        start=1
    ):

        print(
            f"\n--- Comment {i} ---"
        )

        print(
            "Country:",
            comment.get("country")
        )

        print(
            "Topic:",
            comment.get(
                "primary_topic"
            )
        )

        print(
            "Date:",
            comment.get("date")
        )

        print(
            "Text:",
            comment.get("text")
        )

        print(
            "Likes:",
            comment.get(
                "likesCount"
            )
        )

        print(
            "Post URL:",
            comment.get(
                "facebookUrl"
            )
        )


    # =====================================================
    # STEP 8: NORMALISE DATA
    # =====================================================

    normalised_posts = [

        normalise_facebook_post(
            post
        )

        for post
        in environmental_posts
    ]

    normalised_comments = [

        normalise_facebook_comment(
            comment
        )

        for comment
        in comments
    ]


    save_json(
        normalised_comments,
        NORMALISED_COMMENTS_FILE
    )


    # =====================================================
    # SUMMARY
    # =====================================================

    print("\n==============================")
    print("PIPELINE SUMMARY")
    print("==============================")

    print(
        "Raw posts:",
        len(posts)
    )

    print(
        "Environmental posts:",
        len(environmental_posts)
    )

    print(
        "Posts selected for comments:",
        len(selected_posts)
    )

    print(
        "Comments collected:",
        len(comments)
    )

    print("\nDone.")