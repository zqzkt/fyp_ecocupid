import os
import json
import re
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from collections import Counter, defaultdict

import pandas as pd
from dotenv import load_dotenv
from apify_client import ApifyClient
from lingua import Language, LanguageDetectorBuilder


# =========================================================
# PATHS + ENVIRONMENT
# =========================================================

# facebook.py is in:
# repo/scripts/sources/facebook.py
# Therefore parents[2] = repo root
REPO_ROOT = Path(__file__).resolve().parents[2]

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

load_dotenv(REPO_ROOT / ".env")

APIFY_TOKEN = os.getenv("APIFY_TOKEN")
client = ApifyClient(APIFY_TOKEN) if APIFY_TOKEN else None


# =========================================================
# APIFY ACTORS
# =========================================================

POSTS_ACTOR = "apify/facebook-posts-scraper"
COMMENTS_ACTOR = "apify/facebook-comments-scraper"


# =========================================================
# SCRAPING CONFIGURATION
# =========================================================

POST_LIMIT_PER_PAGE = 25
COMMENT_LIMIT_PER_POST = 10


def previous_calendar_month():
    """Return the exact previous calendar month as UTC timestamps."""

    today = datetime.now(timezone.utc).date()
    current_month_start = today.replace(day=1)
    previous_month_end = current_month_start - pd.Timedelta(days=1)
    previous_month_start = previous_month_end.replace(day=1)

    return (
        pd.Timestamp(previous_month_start, tz="UTC"),
        pd.Timestamp(current_month_start, tz="UTC"),
    )


MONTH_START, CURRENT_MONTH_START = previous_calendar_month()
POST_DATE_RANGE = MONTH_START.date().isoformat()

# Maximum number of selected posts from the same topic.
MAX_POSTS_PER_TOPIC_FOR_COMMENTS = 4

# Maximum total number of posts whose comments we scrape.
MAX_TOTAL_POSTS_FOR_COMMENTS = 25


# =========================================================
# APIFY COST SAFETY
# =========================================================

POST_RUN_MAX_COST_USD = 2.00
COMMENT_RUN_MAX_COST_USD = 1.00


# =========================================================
# TEST MODE
# =========================================================

# A small, paid Apify run of the keyword-filtered regional pages
# only. While on, the script:
#   - scrapes fresh posts (ignores the post cache),
#   - scrapes only the sources below, with their own post limits,
#   - keeps all scraped posts instead of only the previous month,
#   - skips comment scraping and the Supabase upload,
#   - writes every output under data/raw/test/.
# Set to False to run the normal pipeline.
TEST_MODE = False

TEST_SOURCE_POST_LIMITS = {
    "Mongabay": 40,
    "Greenpeace Southeast Asia": 15,
}


# =========================================================
# CACHE + UPLOAD SETTINGS
# =========================================================

# Keep these True while improving classification so that
# no additional Apify charges are incurred.
USE_CACHED_POSTS = True
USE_CACHED_COMMENTS = True

if TEST_MODE:
    USE_CACHED_POSTS = False

# Set FACEBOOK_OFFLINE_TEST=1 to run only against existing local caches.
# This mode refuses fresh Apify requests and skips Supabase uploads.
OFFLINE_TEST_MODE = os.getenv(
    "FACEBOOK_OFFLINE_TEST",
    "0",
).lower() in {"1", "true", "yes"}

# Supabase already contains the Facebook tables, so keeping
# this True will upsert the newly classified posts/comments.
UPLOAD_TO_SUPABASE = True

DATA_DIR = REPO_ROOT / "data" / "raw"

if TEST_MODE:
    DATA_DIR = DATA_DIR / "test"

POSTS_CACHE_FILE = DATA_DIR / "facebook_posts_raw.json"
COMMENTS_CACHE_FILE = DATA_DIR / "facebook_comments_raw.json"

ENVIRONMENTAL_POSTS_FILE = (
    DATA_DIR / "facebook_posts_environmental.json"
)

REJECTED_POSTS_FILE = (
    DATA_DIR / "facebook_posts_rejected.json"
)

NON_ENGLISH_POSTS_FILE = (
    DATA_DIR / "facebook_posts_non_english.json"
)

TOPIC_KEYWORDS_CACHE_FILE = (
    DATA_DIR / "facebook_topic_keywords.json"
)

NORMALISED_POSTS_FILE = (
    DATA_DIR / "facebook_posts_normalised.json"
)

NORMALISED_COMMENTS_FILE = (
    DATA_DIR / "facebook_comments_normalised.json"
)

SCRIPT_DIR = Path(__file__).resolve().parent
CSV_DIR = DATA_DIR if TEST_MODE else SCRIPT_DIR
POSTS_CSV = CSV_DIR / "facebook_posts.csv"
COMMENTS_CSV = CSV_DIR / "facebook_comments.csv"


# =========================================================
# FACEBOOK SOURCES
# =========================================================

# Regional pages cover more than one country. A source with
# "filter_keywords" keeps only posts that mention one of these
# terms (see split_posts_by_source_keywords).
#
# Terms shared with other countries are deliberately excluded:
# "borneo" (Malaysia, Brunei), "sunda" and "wallacea" (regional),
# "mekong" (Laos, Cambodia, Vietnam) and "andaman" (Myanmar, India).
INDONESIA_KEYWORDS = [
    "indonesia",
    "indonesian",
    "jakarta",
    "sumatra",
    "sumatran",
    "java",
    "javanese",
    "kalimantan",
    "sulawesi",
    "papua",
    "bali",
    "lombok",
    "komodo",
    "aceh",
    "riau",
    "maluku",
    "halmahera",
    "raja ampat",
    "nusantara",
    "nusa tenggara",
    "flores",
    "bantargebang",
]

THAILAND_KEYWORDS = [
    "thailand",
    "thai",
    "bangkok",
    "chiang mai",
    "phuket",
    "krabi",
    "songkhla",
    "hat yai",
    "isan",
]

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
    {
        "country": "Singapore",
        "source_name": "Eco-Business",
        "url": "https://www.facebook.com/ecobusinesscom",
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
    {
        "country": "Malaysia",
        "source_name": "Malaysian Nature Society",
        "url": "https://www.facebook.com/MalaysianNatureSociety.Official",
    },

    # Indonesia
    # WALHI, WWF Indonesia and Mongabay Indonesia were removed because
    # they post mainly in Indonesian. The global Mongabay page posts in
    # English but covers every region, so keep Indonesian stories only.
    {
        "country": "Indonesia",
        "source_name": "Mongabay",
        "url": "https://www.facebook.com/mongabay",
        "filter_keywords": INDONESIA_KEYWORDS,
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
    {
        "country": "Philippines",
        "source_name": "Climate Change Commission",
        "url": "https://www.facebook.com/CCCPhl",
    },
    {
        "country": "Philippines",
        "source_name": "Greenpeace Philippines",
        "url": "https://www.facebook.com/greenpeaceph",
    },

    # Thailand
    # Greenpeace Thailand, WWF Thailand and EnLAW were removed because
    # they post mainly in Thai. Greenpeace Southeast Asia posts in
    # English across the region, so keep Thai stories only.
    {
        "country": "Thailand",
        "source_name": "Greenpeace Southeast Asia",
        "url": "https://www.facebook.com/GreenpeaceSEA",
        "filter_keywords": THAILAND_KEYWORDS,
    },

    # Brunei
    {
        "country": "Brunei",
        "source_name": "Brunei Nature Society",
        "url": "https://www.facebook.com/BruneiNatureSociety",
    },
    {
        "country": "Brunei",
        "source_name": "Green Brunei",
        "url": "https://www.facebook.com/GreenBrunei",
    },
    {
        "country": "Brunei",
        "source_name": "Beach Bunch",
        "url": "https://www.facebook.com/beachbunch",
    },
]

# Sources actually scraped in this run. A source may carry an
# optional "post_limit" that overrides POST_LIMIT_PER_PAGE.
if TEST_MODE:
    SCRAPE_SOURCES = [
        {
            **source,
            "post_limit": TEST_SOURCE_POST_LIMITS[source["source_name"]],
        }
        for source in FACEBOOK_SOURCES
        if source["source_name"] in TEST_SOURCE_POST_LIMITS
    ]

    if len(SCRAPE_SOURCES) != len(TEST_SOURCE_POST_LIMITS):
        raise SystemExit(
            "TEST_SOURCE_POST_LIMITS names a source that is not in "
            "FACEBOOK_SOURCES: "
            f"{sorted(TEST_SOURCE_POST_LIMITS)}"
        )
else:
    SCRAPE_SOURCES = FACEBOOK_SOURCES


# =========================================================
# HELPER FUNCTIONS
# =========================================================

def canonicalise_url(url):
    """Standardise URLs so they are easier to compare."""

    if not url:
        return ""

    return str(url).rstrip("/").lower()


def safe_int(value):
    """Convert engagement fields safely to integers."""

    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def is_in_previous_calendar_month(value):
    """Return True when a timestamp falls inside the reporting month."""

    timestamp = pd.to_datetime(value, utc=True, errors="coerce")
    if pd.isna(timestamp):
        return False

    return MONTH_START <= timestamp < CURRENT_MONTH_START


def keep_reporting_month(posts):
    """
    Keep error records and posts from the previous calendar month.

    Test mode keeps every scraped post: the actor returns the newest
    posts first, so a small test would otherwise lose most of them.
    """

    if TEST_MODE:
        return posts

    return [
        post
        for post in posts
        if not post.get("postId")
        or is_in_previous_calendar_month(post.get("time"))
    ]


def get_page_name(post):
    """Apify may return pageName as either a string or object."""

    page_name = post.get("pageName")

    if isinstance(page_name, dict):
        return (
            page_name.get("name")
            or page_name.get("title")
            or "Unknown"
        )

    return page_name or "Unknown"


def normalise_text(value):
    """Normalise Unicode consistently before keyword matching."""

    return unicodedata.normalize(
        "NFKC",
        str(value or "")
    ).lower()


def keyword_present(text, keyword):
    """
    Check whether a keyword appears in text.

    Latin-script terms use regex boundaries to reduce accidental
    partial matches. For non-ASCII terms (for example Thai and
    Vietnamese), substring matching is more reliable because some
    scripts do not separate words in the same way as English.
    """

    text = normalise_text(text)
    keyword = normalise_text(keyword)

    if not keyword:
        return False

    if any(ord(character) > 127 for character in keyword):
        return keyword in text

    pattern = (
        r"(?<!\w)"
        + re.escape(keyword)
        + r"(?!\w)"
    )

    return re.search(pattern, text) is not None


def collect_ocr_text(value):
    """
    Recursively collect Apify/Facebook OCR text from media objects.

    This helps classify image-heavy posts whose caption contains
    little or no useful text.
    """

    collected = []

    if isinstance(value, dict):
        ocr_text = value.get("ocrText")

        if isinstance(ocr_text, str) and ocr_text.strip():
            collected.append(ocr_text)

        for child in value.values():
            if isinstance(child, (dict, list)):
                collected.extend(
                    collect_ocr_text(child)
                )

    elif isinstance(value, list):
        for child in value:
            collected.extend(
                collect_ocr_text(child)
            )

    return collected


def build_classification_text(post):
    """
    Build a richer text representation of a Facebook post.

    In addition to the main caption, this includes preview text,
    shared-post text, and media OCR text. These fields were important
    in the cached ASEAN data, especially for Thai image-based posts.
    """

    text_parts = []

    for field in (
        "text",
        "previewTitle",
        "previewDescription",
        "title",
    ):
        value = post.get(field)

        if isinstance(value, str) and value.strip():
            text_parts.append(value)

    shared_post = post.get("sharedPost")

    if isinstance(shared_post, dict):
        for field in (
            "text",
            "previewTitle",
            "previewDescription",
            "title",
        ):
            value = shared_post.get(field)

            if isinstance(value, str) and value.strip():
                text_parts.append(value)

        text_parts.extend(
            collect_ocr_text(
                shared_post.get("media")
            )
        )

    text_parts.extend(
        collect_ocr_text(
            post.get("media")
        )
    )

    return " ".join(text_parts)


# =========================================================
# PER-SOURCE KEYWORD FILTER
# =========================================================

# Fields checked for a source's filter_keywords: the caption, the
# shared link's title, and the shared link URL (article slugs such
# as "indonesia-deforestation-surges" often name the country).
SOURCE_FILTER_FIELDS = (
    "text",
    "previewTitle",
    "link",
)


def compile_source_keyword_pattern(keywords):
    """Compile one case-insensitive, word-bounded regex for a source."""

    # Longest first so "nusa tenggara" wins over shorter overlaps.
    terms = sorted(
        {normalise_text(keyword) for keyword in keywords if keyword},
        key=len,
        reverse=True,
    )

    return re.compile(
        r"(?<!\w)(?:"
        + "|".join(re.escape(term) for term in terms)
        + r")(?!\w)",
        re.IGNORECASE,
    )


def build_source_filter_text(post):
    """Combine the fields used for per-source keyword matching."""

    text_parts = [
        post.get(field)
        for field in SOURCE_FILTER_FIELDS
        if isinstance(post.get(field), str)
    ]

    # NFKC also folds Facebook's bold/italic Unicode letters to ASCII.
    haystack = normalise_text(" ".join(text_parts))

    return haystack.replace("-", " ").replace("_", " ")


def find_source_for_post(post, sources_by_url):
    """Match a post to its configured source via facebookUrl/inputUrl."""

    for source_url in (
        post.get("facebookUrl"),
        post.get("inputUrl"),
    ):
        source = sources_by_url.get(
            canonicalise_url(source_url)
        )

        if source:
            return source

    return None


def print_raw_source_urls(url_counts, limit=10):
    """Print the raw facebookUrl/inputUrl pairs behind a warning."""

    for (facebook_url, input_url), count in url_counts.most_common(limit):
        print(
            f"    {count} post(s): facebookUrl={facebook_url!r}, "
            f"inputUrl={input_url!r}"
        )


def split_posts_by_source_keywords(posts, sources):
    """
    Split posts into (kept, dropped) using each source's filter_keywords.

    Sources without "filter_keywords" keep all posts. Error records
    (no postId) are kept so source errors are still reported. Posts
    that cannot be matched to a configured source are kept, but a
    warning is printed because the filter could not be applied.
    """

    patterns = {
        source["source_name"]: compile_source_keyword_pattern(
            source["filter_keywords"]
        )
        for source in sources
        if source.get("filter_keywords")
    }

    if not patterns:
        return posts, []

    sources_by_url = {
        canonicalise_url(source["url"]): source
        for source in sources
    }

    kept_posts = []
    dropped_posts = []
    kept_counts = Counter()
    dropped_counts = Counter()
    seen_urls = Counter()
    unmatched_urls = Counter()

    for post in posts:
        if not post.get("postId"):
            kept_posts.append(post)
            continue

        raw_urls = (
            post.get("facebookUrl"),
            post.get("inputUrl"),
        )
        seen_urls[raw_urls] += 1

        source = find_source_for_post(post, sources_by_url)

        if source is None:
            unmatched_urls[raw_urls] += 1
            kept_posts.append(post)
            continue

        source_name = source["source_name"]
        pattern = patterns.get(source_name)

        if pattern is None:
            kept_posts.append(post)
        elif pattern.search(build_source_filter_text(post)):
            kept_posts.append(post)
            kept_counts[source_name] += 1
        else:
            dropped_posts.append(post)
            dropped_counts[source_name] += 1

    print("\nPer-source keyword filter:")

    for source_name in patterns:
        print(
            f"{source_name}: kept {kept_counts[source_name]}, "
            f"dropped {dropped_counts[source_name]}"
        )

    if unmatched_urls:
        print(
            f"\n!!! WARNING: {sum(unmatched_urls.values())} post(s) "
            "could not be matched to a configured source, so the "
            "keyword filter was NOT applied to them (they were kept). "
            "Fix the source URL matching. Raw URLs seen:"
        )
        print_raw_source_urls(unmatched_urls)

    for source_name in patterns:
        if kept_counts[source_name] + dropped_counts[source_name] == 0:
            print(
                f"\n!!! WARNING: keyword-filtered source "
                f"{source_name!r} has 0 recognised posts. Check that "
                "its configured URL matches what Apify returns. "
                "Raw URLs seen:"
            )

            if seen_urls:
                print_raw_source_urls(seen_urls)
            else:
                print("    (no posts with a postId)")

    return kept_posts, dropped_posts


def print_keyword_filter_samples(
    kept_posts,
    dropped_posts,
    sources,
    sample_size=5
):
    """Print sample kept/dropped posts for each keyword-filtered source."""

    for source in sources:
        if not source.get("filter_keywords"):
            continue

        source_name = source["source_name"]

        for label, group in (
            ("KEPT", kept_posts),
            ("DROPPED", dropped_posts),
        ):
            samples = [
                post
                for post in group
                if post.get("postId")
                and post.get("source_name") == source_name
            ][:sample_size]

            print(
                f"\n--- {source_name}: sample {label} posts "
                f"({len(samples)}) ---"
            )

            for post in samples:
                text = " ".join(str(post.get("text") or "").split())

                print(f"* {text[:150] or '(no text)'}")
                print(f"  link: {post.get('link') or '(none)'}")


def print_source_run_summary(
    sources,
    scraped_posts,
    dropped_posts,
    rejected_posts,
    english_posts,
    non_english_posts
):
    """
    Print scraped / keyword-filter / language counts per source.

    Language detection runs on environmental posts only, so
    "No topic" posts are not counted as English or non-English.
    """

    def count_by_source(posts):
        return Counter(
            post.get("source_name") or "Unknown"
            for post in posts
            if post.get("postId")
        )

    scraped = count_by_source(scraped_posts)
    dropped = count_by_source(dropped_posts)
    rejected = count_by_source(rejected_posts)
    english = count_by_source(english_posts)
    non_english = count_by_source(non_english_posts)

    source_names = [source["source_name"] for source in sources]
    source_names += sorted(set(scraped) - set(source_names))

    print("\n==============================")
    print("PER-SOURCE SUMMARY")
    print("==============================")
    print(
        f"{'Source':32} {'Scraped':>7} {'KW kept':>7} "
        f"{'KW drop':>7} {'No topic':>8} {'English':>7} {'Non-EN':>7}"
    )

    for source_name in source_names:
        print(
            f"{source_name[:32]:32} "
            f"{scraped[source_name]:>7} "
            f"{scraped[source_name] - dropped[source_name]:>7} "
            f"{dropped[source_name]:>7} "
            f"{rejected[source_name]:>8} "
            f"{english[source_name]:>7} "
            f"{non_english[source_name]:>7}"
        )


language_detector = (
    LanguageDetectorBuilder
    .from_all_languages()
    .with_minimum_relative_distance(0.25)
    .build()
)


def is_english(text):
    """Return True when the post text is confidently detected as English."""

    text = str(text or "").strip()
    if len(text) < 10:
        return False
    return language_detector.detect_language_of(text) == Language.ENGLISH


def split_english_posts(posts):
    """Return (english_posts, non_english_posts) based on post text only."""

    english_posts = []
    non_english_posts = []

    for post in posts:
        if is_english(post.get("text")):
            english_posts.append(post)
        else:
            non_english_posts.append(post)

    return english_posts, non_english_posts


def save_json(data, filepath):
    """Save local cache/output without repeated Apify calls."""

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
    """Load previously saved JSON data."""

    with open(
        filepath,
        "r",
        encoding="utf-8"
    ) as file:
        return json.load(file)


def require_apify_client():
    """Only require an Apify token when a paid scrape is requested."""

    if client is None:
        raise RuntimeError(
            "APIFY_TOKEN was not found. Add it to the repo-root "
            ".env file before running a fresh Apify scrape."
        )

    return client


# =========================================================
# POST SCRAPING
# =========================================================

def fetch_facebook_posts(
    sources,
    limit=POST_LIMIT_PER_PAGE
):

    apify_client = require_apify_client()

    # resultsLimit applies to every page in a run, so sources with a
    # different "post_limit" are scraped in separate runs. The cost cap
    # is split across those runs so the total never exceeds it.
    sources_by_limit = defaultdict(list)

    for source in sources:
        sources_by_limit[
            source.get("post_limit", limit)
        ].append(source)

    if not sources_by_limit:
        return []

    run_max_cost_usd = (
        POST_RUN_MAX_COST_USD
        / len(sources_by_limit)
    )

    items = []

    for post_limit, limit_sources in sources_by_limit.items():
        page_urls = [
            {"url": source["url"]}
            for source in limit_sources
        ]

        run_input = {
            "startUrls": page_urls,
            "resultsLimit": post_limit,
            "onlyPostsNewerThan": POST_DATE_RANGE,
            "onlyPostsOlderThan": CURRENT_MONTH_START.date().isoformat(),
            "captionText": False,
        }

        print(
            f"\nStarting Facebook post scraper "
            f"for {len(page_urls)} page(s), "
            f"up to {post_limit} post(s) each..."
        )

        run = apify_client.actor(
            POSTS_ACTOR
        ).call(
            run_input=run_input,
            max_total_charge_usd=(
                run_max_cost_usd
            ),
        )

        if run is None:
            print(
                "Facebook post scraper failed "
                "to start."
            )
            continue

        dataset_id = run.default_dataset_id

        items.extend(
            apify_client
            .dataset(dataset_id)
            .list_items()
            .items
        )

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

        if post_id:
            if post_id in seen_post_ids:
                continue

            seen_post_ids.add(post_id)

        # inputUrl is particularly useful for error records.
        source_url_candidates = [
            post.get("facebookUrl"),
            post.get("inputUrl"),
            post.get("url"),
        ]

        source_info = None

        for source_url in source_url_candidates:
            source_info = source_lookup.get(
                canonicalise_url(source_url)
            )

            if source_info:
                break

        if source_info:
            post["country"] = source_info["country"]
            post["source_name"] = source_info["source_name"]
        else:
            post["country"] = post.get("country") or "Unknown"
            post["source_name"] = (
                post.get("source_name")
                or get_page_name(post)
            )

        enriched_posts.append(post)

    # The actor accepts a lower boundary only. Enforce both boundaries
    # locally so the output contains exactly the previous calendar month.
    return keep_reporting_month(enriched_posts)


# =========================================================
# MONTHLY TOPIC CLASSIFICATION
# =========================================================

# Posts are classified with the same keywords the X, Reddit,
# Instagram and YouTube collectors search for: the top three
# monthly_topic_stats topics per country, written by
# scripts/News_processed/News_topic.py.

def load_monthly_topic_keywords():
    """
    Return {country: {topic_name: [keywords]}} for the reporting month.

    Keywords are read from Supabase and cached locally so offline
    runs can reuse them without contacting Supabase.
    """

    if OFFLINE_TEST_MODE:
        if not TOPIC_KEYWORDS_CACHE_FILE.exists():
            raise SystemExit(
                "Offline test requires the cached topic keywords file: "
                f"{TOPIC_KEYWORDS_CACHE_FILE}"
            )

        print("\nUsing cached monthly topic keywords...")
        keyword_specs = load_json(TOPIC_KEYWORDS_CACHE_FILE)
    else:
        from scripts.supabase.instagram_pipeline import (
            monthly_keyword_specs,
        )

        keyword_specs = monthly_keyword_specs(
            MONTH_START.date().isoformat()
        )
        save_json(keyword_specs, TOPIC_KEYWORDS_CACHE_FILE)

    topic_keywords = defaultdict(lambda: defaultdict(list))

    for spec in keyword_specs:
        topic_keywords[spec["country"]][spec["topic"]].append(
            spec["keyword"]
        )

    return {
        country: dict(topics)
        for country, topics in topic_keywords.items()
    }


def print_monthly_topic_keywords(topic_keywords, sources):
    """Show the keywords in use and warn about uncovered countries."""

    print("\n==============================")
    print(f"MONTHLY TOPIC KEYWORDS ({MONTH_START.date().isoformat()})")
    print("==============================")

    for country in sorted({source["country"] for source in sources}):
        topics = topic_keywords.get(country)

        if not topics:
            print(
                f"!!! WARNING: {country} has no monthly topic keywords; "
                "all of its posts will be rejected."
            )
            continue

        print(country)

        for topic, keywords in topics.items():
            print(f"    {topic}: {', '.join(keywords)}")


def classify_environmental_post(post, topic_keywords):
    """
    Match one Facebook post against its country's monthly keywords.

    Returns the post with primary_topic, matched_topics and
    matched_keywords added, or None when no keyword matches.
    """

    # Error/no-item records are useful diagnostics but are not posts.
    if not post.get("postId"):
        return None

    combined_text = build_classification_text(post)

    matched_topics = {}

    for topic, keywords in topic_keywords.get(
        post.get("country"),
        {}
    ).items():
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

    if not matched_topics:
        return None

    # Choose the topic with the most evidence. If tied, favour the
    # topic whose matched terms are more specific/longer overall.
    primary_topic = max(
        matched_topics,
        key=lambda topic: (
            len(matched_topics[topic]),
            sum(
                len(keyword)
                for keyword in matched_topics[topic]
            ),
        ),
    )

    classified_post = dict(post)
    classified_post["primary_topic"] = primary_topic
    classified_post["matched_topics"] = matched_topics
    # Same field name as the other platforms; clean_social.py reads it.
    classified_post["matched_keywords"] = list(
        dict.fromkeys(
            keyword
            for keywords in matched_topics.values()
            for keyword in keywords
        )
    )

    return classified_post


def split_environmental_posts(posts, topic_keywords):
    """Return (topic_matched_posts, rejected_posts)."""

    environmental_posts = []
    rejected_posts = []

    for post in posts:
        # Keep source errors separate from rejected real posts.
        if not post.get("postId"):
            continue

        classified_post = (
            classify_environmental_post(post, topic_keywords)
        )

        if classified_post:
            environmental_posts.append(
                classified_post
            )
        else:
            rejected_posts.append(post)

    return environmental_posts, rejected_posts


# =========================================================
# ANALYSIS / DIAGNOSTICS
# =========================================================

def print_topic_distribution(posts):
    if not posts:
        print("\nNo environmental posts available.")
        return

    counts = Counter(
        post["primary_topic"]
        for post in posts
    )

    total = len(posts)

    print("\n==============================")
    print("MONTHLY TOPIC DISTRIBUTION")
    print("==============================")

    for topic, count in counts.most_common():
        percentage = (count / total) * 100

        print(
            f"{topic}: "
            f"{count} "
            f"({percentage:.1f}%)"
        )


def print_country_distribution(posts, heading):
    counts = Counter(
        post.get("country") or "Unknown"
        for post in posts
    )

    print("\n==============================")
    print(heading)
    print("==============================")

    for country, count in counts.most_common():
        print(f"{country}: {count}")


def print_source_coverage(posts):
    counts = Counter(
        post.get("source_name") or "Unknown"
        for post in posts
        if post.get("postId")
    )

    print("\n==============================")
    print("SOURCE COVERAGE")
    print("==============================")

    for source in SCRAPE_SOURCES:
        source_name = source["source_name"]
        print(
            f"{source_name}: "
            f"{counts.get(source_name, 0)} usable post(s)"
        )


def print_source_errors(posts):
    errors = [
        post
        for post in posts
        if not post.get("postId")
        and post.get("error")
    ]

    if not errors:
        return

    print("\n==============================")
    print("SOURCE ERRORS")
    print("==============================")

    for post in errors:
        print(
            f"{post.get('source_name', 'Unknown')}: "
            f"{post.get('error')} - "
            f"{post.get('errorDescription', '')}"
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
    Select a country- and topic-diverse set of posts for comments.

    The raw topic distribution is never altered. This function only
    determines where the paid comment-scraping budget is spent.

    Selection goals:
      1. Exclude posts with zero reported comments.
      2. Rotate across countries so Malaysia/Thailand are not crowded
         out by countries with more high-engagement posts.
      3. Limit the number of selected posts from one topic.
      4. Within those constraints, prefer engagement.
    """

    candidates = [
        post
        for post in posts
        if safe_int(post.get("comments")) > 0
        and post.get("country")
        and post.get("country") != "Unknown"
    ]

    if not candidates:
        return []

    grouped_by_country = defaultdict(list)

    for post in candidates:
        grouped_by_country[
            post["country"]
        ].append(post)

    # Highest engagement first within each country.
    for country in grouped_by_country:
        grouped_by_country[country].sort(
            key=lambda post: (
                safe_int(post.get("comments")),
                safe_int(post.get("likes")),
                safe_int(post.get("shares")),
            ),
            reverse=True
        )

    candidate_topic_counts = Counter(
        post["primary_topic"]
        for post in candidates
    )

    # Countries with fewer available candidates go first so they
    # are less likely to be excluded by the overall max_total cap.
    country_order = sorted(
        grouped_by_country,
        key=lambda country: (
            len(grouped_by_country[country]),
            country,
        )
    )

    selected = []
    selected_post_ids = set()
    selected_topic_counts = Counter()

    while len(selected) < max_total:
        progress_made = False

        for country in country_order:
            if len(selected) >= max_total:
                break

            available = [
                post
                for post in grouped_by_country[country]
                if str(post.get("postId"))
                not in selected_post_ids
                and selected_topic_counts[
                    post["primary_topic"]
                ] < max_per_topic
            ]

            if not available:
                continue

            # Prefer topics not yet represented. If still tied,
            # favour rarer topics, then higher engagement.
            available.sort(
                key=lambda post: (
                    selected_topic_counts[
                        post["primary_topic"]
                    ],
                    candidate_topic_counts[
                        post["primary_topic"]
                    ],
                    -safe_int(post.get("comments")),
                    -safe_int(post.get("likes")),
                    -safe_int(post.get("shares")),
                )
            )

            chosen = available[0]
            chosen_id = str(
                chosen.get("postId")
            )

            selected.append(chosen)
            selected_post_ids.add(chosen_id)
            selected_topic_counts[
                chosen["primary_topic"]
            ] += 1

            progress_made = True

        if not progress_made:
            break

    return selected


# =========================================================
# COMMENT SCRAPING + ENRICHMENT
# =========================================================

def refresh_comment_metadata(comments, posts):
    """
    Reattach current parent-post metadata to comments.

    This is useful after reclassifying cached posts because the cached
    comments may still contain the old primary_topic value.
    """

    post_lookup = {
        canonicalise_url(post["url"]): post
        for post in posts
        if post.get("url")
    }

    enriched_comments = []

    for item in comments:
        comment = dict(item)

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
                parent_post.get("source_name")
            )
            comment["primary_topic"] = (
                parent_post.get("primary_topic")
            )
            comment["matched_keywords"] = (
                parent_post.get("matched_keywords", [])
            )

        enriched_comments.append(comment)

    return enriched_comments


def fetch_facebook_comments(
    posts,
    limit=COMMENT_LIMIT_PER_POST
):

    post_urls = [
        {"url": post["url"]}
        for post in posts
        if post.get("url")
    ]

    if not post_urls:
        print(
            "\nNo post URLs available "
            "for comment scraping."
        )
        return []

    apify_client = require_apify_client()

    run_input = {
        "startUrls": post_urls,
        "resultsLimit": limit,
        "includeNestedComments": False,
    }

    print(
        f"\nStarting comment scraper "
        f"for {len(post_urls)} post(s)..."
    )

    run = apify_client.actor(
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
        apify_client
        .dataset(dataset_id)
        .list_items()
        .items
    )

    unique_comments = []
    seen_comment_ids = set()

    for item in items:
        comment = dict(item)

        comment_id = str(
            comment.get("commentId") or ""
        )

        if comment_id:
            if comment_id in seen_comment_ids:
                continue

            seen_comment_ids.add(comment_id)

        unique_comments.append(comment)

    return refresh_comment_metadata(
        unique_comments,
        posts
    )


def print_cached_comment_coverage(
    comments,
    selected_posts
):
    """Explain whether the old cached comments match the new selection."""

    cached_urls = {
        canonicalise_url(
            comment.get("facebookUrl")
        )
        for comment in comments
        if comment.get("facebookUrl")
    }

    selected_urls = {
        canonicalise_url(post.get("url"))
        for post in selected_posts
        if post.get("url")
    }

    overlap = len(
        cached_urls.intersection(selected_urls)
    )

    print(
        f"Cached comments currently cover "
        f"{overlap}/{len(selected_urls)} "
        f"of the newly selected post URLs."
    )

    if overlap < len(selected_urls):
        print(
            "This is expected after changing the classifier/selection. "
            "No new Apify comment scrape was run because "
            "USE_CACHED_COMMENTS=True."
        )
        print(
            "When you are ready to collect comments for the new balanced "
            "selection, set USE_CACHED_COMMENTS=False."
        )


# =========================================================
# NORMALISATION
# =========================================================

def normalise_facebook_post(post):
    return {
        "platform": "facebook",
        "post_id": post.get("postId"),
        "country": post.get("country"),
        "source_name": post.get("source_name"),
        "page_name": get_page_name(post),
        "published_at": post.get("time"),
        "url": post.get("url"),
        "text": post.get("text"),
        "likes": safe_int(post.get("likes")),
        "comments_count": safe_int(
            post.get("comments")
        ),
        "shares": safe_int(post.get("shares")),
        "primary_topic": post.get("primary_topic"),
        "matched_topics": post.get(
            "matched_topics",
            {}
        ),
        "matched_keywords": post.get(
            "matched_keywords",
            []
        ),
    }


def normalise_facebook_comment(comment):
    return {
        "platform": "facebook",
        "comment_id": comment.get("commentId"),
        "parent_post_id": comment.get(
            "parent_post_id"
        ),
        "post_url": comment.get("facebookUrl"),
        "country": comment.get("country"),
        "source_name": comment.get("source_name"),
        "primary_topic": comment.get(
            "primary_topic"
        ),
        "matched_keywords": comment.get(
            "matched_keywords",
            []
        ),
        "published_at": comment.get("date"),
        "text": comment.get("text"),
        "likes": safe_int(
            comment.get("likesCount")
        ),
    }


def save_csv(rows, filepath, json_columns=None):
    """Save normalised rows using the same UTF-8 CSV format as other sources."""

    dataframe = pd.DataFrame(rows)

    for column in json_columns or []:
        if column in dataframe.columns:
            dataframe[column] = dataframe[column].apply(
                lambda value: json.dumps(value, ensure_ascii=False)
                if isinstance(value, (dict, list))
                else value
            )

    dataframe.to_csv(filepath, index=False, encoding="utf-8-sig")
    print(f"Saved {len(dataframe)} rows to {filepath}")


def sync_to_supabase(posts, comments):
    """Sync cleaned Facebook records through the existing pipeline."""

    url = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
    key = (
        os.environ.get("SUPABASE_SECRET_KEY")
        or os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
        or os.environ.get("SUPABASE_KEY")
        or ""
    ).strip()

    if not url or not key:
        print("✗ Missing SUPABASE_URL or Supabase server key in .env")
        return None

    if key.startswith("sb_publishable_") or key.startswith("sb_anon_"):
        print("✗ Supabase key must be a server-only secret/service-role key")
        return None

    try:
        from scripts.supabase.facebook_pipeline import sync_facebook_rows

        print("Syncing to Supabase...")
        counts = sync_facebook_rows(posts, comments)
        print("✓ Supabase sync successful")
        print(f"Upserted: {counts}")
        return counts
    except ImportError as error:
        print(f"✗ Import error: {error}")
    except Exception as error:
        print(f"✗ Supabase sync failed: {error}")
        import traceback

        traceback.print_exc()

    return None


# =========================================================
# MAIN PROGRAM
# =========================================================

if __name__ == "__main__":

    print("\n==============================")
    print("FACEBOOK ENVIRONMENT PIPELINE")
    print("==============================")

    if OFFLINE_TEST_MODE:
        print(
            "Offline test mode enabled: "
            "using local caches only; "
            "Apify and Supabase are disabled."
        )

    if TEST_MODE:
        print(
            "TEST MODE: scraping "
            + ", ".join(
                f"{source['source_name']} "
                f"(up to {source['post_limit']} posts)"
                for source in SCRAPE_SOURCES
            )
            + f"; outputs go to {DATA_DIR}"
        )

    # =====================================================
    # STEP 1: LOAD MONTHLY TOPIC KEYWORDS
    # =====================================================

    # Loaded before scraping so a missing month stops the run
    # before any Apify charges are incurred.
    topic_keywords = load_monthly_topic_keywords()

    print_monthly_topic_keywords(
        topic_keywords,
        SCRAPE_SOURCES
    )

    # =====================================================
    # STEP 1B: COLLECT / LOAD POSTS
    # =====================================================

    if OFFLINE_TEST_MODE and not POSTS_CACHE_FILE.exists():
        raise SystemExit(
            "Offline test requires the cached posts file: "
            f"{POSTS_CACHE_FILE}"
        )

    if (
        (USE_CACHED_POSTS or OFFLINE_TEST_MODE)
        and POSTS_CACHE_FILE.exists()
    ):
        print("\nUsing cached Facebook posts...")
        posts = load_json(POSTS_CACHE_FILE)
    else:
        posts = fetch_facebook_posts(
            SCRAPE_SOURCES
        )
        save_json(posts, POSTS_CACHE_FILE)

    scraped_posts = posts

    # Regional pages (e.g. Mongabay) must mention their assigned
    # country. The raw cache stays unfiltered so keyword lists can be
    # tuned offline without another Apify run.
    (
        posts,
        keyword_dropped_posts,
    ) = split_posts_by_source_keywords(
        posts,
        SCRAPE_SOURCES
    )

    if TEST_MODE:
        print_keyword_filter_samples(
            posts,
            keyword_dropped_posts,
            SCRAPE_SOURCES
        )

    # Apply the exact month boundary to both fresh and cached records.
    posts = keep_reporting_month(posts)

    usable_posts = [
        post
        for post in posts
        if post.get("postId")
    ]

    source_error_records = [
        post
        for post in posts
        if not post.get("postId")
    ]

    print(
        f"\nRaw scraper records: "
        f"{len(posts)}"
    )
    print(
        f"Usable Facebook posts: "
        f"{len(usable_posts)}"
    )
    print(
        f"Non-post/error records: "
        f"{len(source_error_records)}"
    )

    print_source_coverage(posts)
    print_source_errors(posts)

    # =====================================================
    # STEP 2: CLASSIFY BY MONTHLY TOPIC KEYWORDS
    # =====================================================

    (
        environmental_posts,
        rejected_posts,
    ) = split_environmental_posts(
        posts,
        topic_keywords
    )

    print(
        f"\nPosts matching monthly topic keywords: "
        f"{len(environmental_posts)}"
    )

    if usable_posts:
        classification_rate = (
            len(environmental_posts)
            / len(usable_posts)
            * 100
        )

        print(
            f"Monthly topic match rate: "
            f"{classification_rate:.1f}% "
            f"of usable posts"
        )

    print(
        f"Rejected usable posts: "
        f"{len(rejected_posts)}"
    )

    save_json(
        environmental_posts,
        ENVIRONMENTAL_POSTS_FILE
    )

    save_json(
        rejected_posts,
        REJECTED_POSTS_FILE
    )

    # Posts are not translated downstream (clean_social.py only
    # translates comments), so keep English posts only. This runs
    # before comment selection so no Apify budget is spent on
    # comments for posts that would be dropped.
    (
        environmental_posts,
        non_english_posts,
    ) = split_english_posts(environmental_posts)

    print(
        f"\nEnglish environmental posts kept: "
        f"{len(environmental_posts)}"
    )
    print(
        f"Non-English environmental posts dropped: "
        f"{len(non_english_posts)}"
    )

    print_country_distribution(
        non_english_posts,
        "NON-ENGLISH POSTS DROPPED BY COUNTRY"
    )

    save_json(
        non_english_posts,
        NON_ENGLISH_POSTS_FILE
    )

    print_source_run_summary(
        SCRAPE_SOURCES,
        scraped_posts,
        keyword_dropped_posts,
        rejected_posts,
        environmental_posts,
        non_english_posts
    )

    # =====================================================
    # STEP 3: DISTRIBUTIONS
    # =====================================================

    print_topic_distribution(
        environmental_posts
    )

    print_country_distribution(
        environmental_posts,
        "ENVIRONMENTAL POSTS BY COUNTRY"
    )

    # =====================================================
    # STEP 4: SELECT BALANCED POSTS FOR COMMENTS
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
        f"Selected {len(selected_posts)} "
        f"post(s)."
    )

    print_country_distribution(
        selected_posts,
        "SELECTED COMMENT POSTS BY COUNTRY"
    )

    # =====================================================
    # STEP 5: SCRAPE / LOAD COMMENTS
    # =====================================================

    if TEST_MODE:
        print(
            "\nTEST MODE: comment scraping skipped"
        )
        comments = []
    elif selected_posts:
        if OFFLINE_TEST_MODE and not COMMENTS_CACHE_FILE.exists():
            raise SystemExit(
                "Offline test requires the cached comments file: "
                f"{COMMENTS_CACHE_FILE}"
            )

        if (
            (USE_CACHED_COMMENTS or OFFLINE_TEST_MODE)
            and COMMENTS_CACHE_FILE.exists()
        ):
            print(
                "\nUsing cached Facebook comments..."
            )

            comments = load_json(
                COMMENTS_CACHE_FILE
            )

            # Refresh topic/country metadata using the newly
            # classified parent posts without calling Apify.
            comments = refresh_comment_metadata(
                comments,
                environmental_posts
            )

            print_cached_comment_coverage(
                comments,
                selected_posts
            )
        else:
            comments = fetch_facebook_comments(
                selected_posts
            )

            save_json(
                comments,
                COMMENTS_CACHE_FILE
            )
    else:
        comments = []

    # Remove duplicates and keep comments attached to accepted posts only.
    unique_comments = []
    seen_comment_ids = set()
    valid_post_ids = {
        str(post.get("postId"))
        for post in environmental_posts
        if post.get("postId")
    }

    for comment in comments:
        comment_id = str(comment.get("commentId") or "")
        parent_post_id = str(comment.get("parent_post_id") or "")

        if comment_id and comment_id in seen_comment_ids:
            continue
        if parent_post_id not in valid_post_ids:
            continue
        if comment_id:
            seen_comment_ids.add(comment_id)
        unique_comments.append(comment)

    comments = unique_comments

    print(
        f"\nComments available: "
        f"{len(comments)}"
    )

    # =====================================================
    # STEP 6: NORMALISE + SAVE
    # =====================================================

    normalised_posts = [
        normalise_facebook_post(post)
        for post in environmental_posts
    ]

    normalised_comments = [
        normalise_facebook_comment(comment)
        for comment in comments
    ]

    save_json(
        normalised_posts,
        NORMALISED_POSTS_FILE
    )

    save_json(
        normalised_comments,
        NORMALISED_COMMENTS_FILE
    )

    save_csv(
        normalised_posts,
        POSTS_CSV,
        json_columns=["matched_topics", "matched_keywords"],
    )

    save_csv(
        normalised_comments,
        COMMENTS_CSV,
        json_columns=["matched_keywords"],
    )

    # =====================================================
    # STEP 7: SUPABASE SYNC
    # =====================================================

    if TEST_MODE:
        print("\nTEST MODE: Supabase upload skipped")
    elif UPLOAD_TO_SUPABASE and not OFFLINE_TEST_MODE:
        print("\n==============================")
        print("SYNCING TO SUPABASE")
        print("==============================")

        sync_counts = sync_to_supabase(
            normalised_posts,
            normalised_comments
        )

        if sync_counts is not None:
            print(
                "\nSupabase sync completed:",
                sync_counts
            )
    else:
        print("\nSupabase upload disabled.")

    # =====================================================
    # SUMMARY
    # =====================================================

    print("\n==============================")
    print("PIPELINE SUMMARY")
    print("==============================")

    print(
        "Raw scraper records:",
        len(posts)
    )
    print(
        "Usable posts:",
        len(usable_posts)
    )
    print(
        "English environmental posts:",
        len(environmental_posts)
    )
    print(
        "Rejected usable posts:",
        len(rejected_posts)
    )
    print(
        "Non-English posts dropped:",
        len(non_english_posts)
    )
    print(
        "Posts selected for comments:",
        len(selected_posts)
    )
    print(
        "Comments available:",
        len(comments)
    )

    print("Saved:", POSTS_CSV)
    print("Saved:", COMMENTS_CSV)

    print("\nDone.")
