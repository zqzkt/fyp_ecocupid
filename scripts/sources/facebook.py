import os
import html
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

POST_LIMIT_PER_PAGE = 100
COMMENT_LIMIT_PER_POST = 20


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


# =========================================================
# APIFY COST SAFETY
# =========================================================

# Total Apify budget for one pipeline run. Post scraping spends it
# first; the comment run is capped at whatever is left.
TOTAL_MAX_COST_USD = 20.00


# =========================================================
# TEST MODE
# =========================================================

# A small, paid Apify run of selected pages only. While on, the script:
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
# OFFLINE + UPLOAD SETTINGS
# =========================================================

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

# Cloud Translation results keyed by postId, so re-runs against
# cached posts do not pay to translate the same text again.
POST_TRANSLATIONS_CACHE_FILE = (
    DATA_DIR / "facebook_post_translations.json"
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

# =========================================================
# FACEBOOK SOURCES
# =========================================================

# Regional pages cover more than one country. A source with
# "country_keywords" assigns each post to the first country whose
# terms it mentions (see split_posts_by_source_keywords).
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

# "sulu" is excluded because the Sulu Sea is shared with Malaysia.
PHILIPPINES_KEYWORDS = [
    "philippines",
    "philippine",
    "filipino",
    "filipinos",
    "manila",
    "quezon city",
    "luzon",
    "visayas",
    "mindanao",
    "mindoro",
    "palawan",
    "cebu",
    "davao",
    "bohol",
    "iloilo",
    "negros",
    "leyte",
    "samar",
    "boracay",
]

# Facebook sources chosen for EcoCupid: a Singapore-based environmental
# media platform that tells stories about grassroots eco-projects across
# Southeast Asia. Pages that surface community projects, volunteer drives
# and regional environmental news are preferred over pure announcement
# pages.

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
        "source_name": "Green Nudge",
        "url": "https://www.facebook.com/greennudgesg",
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
    {
        "country": "Malaysia",
        "source_name": "Reef Check Malaysia",
        "url": "https://www.facebook.com/reefcheckmalaysia",
    },


    # Indonesia
    # Mongabay Indonesia posts mainly in Indonesian; its posts are
    # translated to English before topic classification. Mongabay and
    # Greenpeace Southeast Asia are under "Regional" below.
    {
        "country": "Indonesia",
        "source_name": "Mongabay Indonesia",
        "url": "https://www.facebook.com/MongabayIndonesia",
    },
    {
        "country": "Indonesia",
        "source_name": "Trash Hero Indonesia",
        "url": "https://www.facebook.com/trashheroindonesia",
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
    {
        "country": "Philippines",
        "source_name": "Oceana Philippines",
        "url": "https://www.facebook.com/oceana.ph",
    },

    # Thailand
    # Greenpeace Thailand, WWF Thailand and EnLAW were removed because
    # they post mainly in Thai. Trash Hero Thailand and Bangkok Tribune
    # are Thailand-based and post in English. Greenpeace Southeast Asia,
    # Mongabay and Eco-Business are under "Regional" below.
    {
        "country": "Thailand",
        "source_name": "Trash Hero Thailand",
        "url": "https://www.facebook.com/trashherothailand",
    },
    {
        "country": "Thailand",
        "source_name": "Bangkok Tribune",
        "url": "https://www.facebook.com/BangkokTribune",
    },

    # Brunei
    {
        "country": "Brunei",
        "source_name": "Ecobin Brunei",
        "url": "https://www.facebook.com/ecobin.bn",
    },
    {
        "country": "Brunei",
        "source_name": "Green Brunei",
        "url": "https://www.facebook.com/GreenBrunei",
    },

    # Regional
    # These pages post in English across Southeast Asia. Each page is
    # listed once so it is scraped once; its posts are assigned to a
    # country by "country_keywords". Posts that match no country go to
    # the source's "country" if it has one, otherwise they are dropped.
    {
        "source_name": "Mongabay",
        "url": "https://www.facebook.com/mongabay",
        "country_keywords": {
            "Indonesia": INDONESIA_KEYWORDS,
            "Thailand": THAILAND_KEYWORDS,
            "Philippines": PHILIPPINES_KEYWORDS,
        },
    },
    {
        "source_name": "Greenpeace Southeast Asia",
        "url": "https://www.facebook.com/GreenpeaceSEA",
        "country_keywords": {
            "Indonesia": INDONESIA_KEYWORDS,
            "Thailand": THAILAND_KEYWORDS,
            "Philippines": PHILIPPINES_KEYWORDS,
        },
    },
    {
        # Singapore-based, so posts about other countries stay Singapore
        # unless they name Thailand.
        "country": "Singapore",
        "source_name": "Eco-Business",
        "url": "https://www.facebook.com/EcoBusinessMedia",
        "country_keywords": {
            "Thailand": THAILAND_KEYWORDS,
        },
    },
]

# Posts are matched back to their source by page URL, so a page listed
# twice would silently take only the last entry's settings.
_duplicate_urls = [
    url
    for url, count in Counter(
        str(source["url"]).rstrip("/").lower()
        for source in FACEBOOK_SOURCES
    ).items()
    if count > 1
]

if _duplicate_urls:
    raise SystemExit(
        "FACEBOOK_SOURCES lists these pages more than once; use one "
        f"entry with country_keywords instead: {_duplicate_urls}"
    )

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


def source_countries(source):
    """Return every country a source's posts can be assigned to."""

    countries = list(source.get("country_keywords", {}))

    if source.get("country"):
        countries.append(source["country"])

    return countries


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

# Fields checked for a source's country_keywords: the caption, the
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
    Assign regional posts to a country and drop unmatched ones.

    For a source with "country_keywords", each post gets the first
    country whose keywords it mentions, else the source's own
    "country", else it is dropped. Returns (kept, dropped). Other
    sources keep all posts. Error records (no postId) are kept so
    source errors are still reported. Posts that cannot be matched
    to a configured source are kept, but a warning is printed
    because the filter could not be applied.
    """

    patterns = {
        source["source_name"]: [
            (country, compile_source_keyword_pattern(keywords))
            for country, keywords in source["country_keywords"].items()
        ]
        for source in sources
        if source.get("country_keywords")
    }

    if not patterns:
        return posts, []

    sources_by_url = {
        canonicalise_url(source["url"]): source
        for source in sources
    }

    kept_posts = []
    dropped_posts = []
    kept_counts = defaultdict(Counter)
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
        country_patterns = patterns.get(source_name)

        if country_patterns is None:
            kept_posts.append(post)
            continue

        filter_text = build_source_filter_text(post)

        country = next(
            (
                country
                for country, pattern in country_patterns
                if pattern.search(filter_text)
            ),
            source.get("country"),
        )

        if country:
            post = dict(post)
            post["country"] = country
            kept_posts.append(post)
            kept_counts[source_name][country] += 1
        else:
            dropped_posts.append(post)
            dropped_counts[source_name] += 1

    print("\nPer-source keyword filter:")

    for source_name in patterns:
        kept_by_country = ", ".join(
            f"{country} {count}"
            for country, count in kept_counts[source_name].items()
        )

        print(
            f"{source_name}: kept {kept_by_country or 0}, "
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

    source_errors = {
        post.get("source_name"): post
        for post in posts
        if not post.get("postId") and post.get("error")
    }

    for source_name in patterns:
        if not kept_counts[source_name] and not dropped_counts[source_name]:
            error = source_errors.get(source_name)

            # A scraper error explains the missing posts; the URL list
            # is only useful when the posts exist but did not match.
            if error:
                print(
                    f"\n!!! WARNING: keyword-filtered source "
                    f"{source_name!r} has 0 posts because Apify "
                    f"returned {error.get('error')!r}: "
                    f"{error.get('errorDescription')}"
                )
                continue

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
        if not source.get("country_keywords"):
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

                country = (
                    f"[{post.get('country')}] " if label == "KEPT" else ""
                )

                print(f"* {country}{text[:150] or '(no text)'}")
                print(f"  link: {post.get('link') or '(none)'}")


def print_source_run_summary(
    sources,
    scraped_posts,
    dropped_posts,
    rejected_posts,
    environmental_posts
):
    """
    Print scraped / keyword-filter / topic / translation counts per source.

    "Transl." counts topic-matched posts whose text was translated
    to English before classification.
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
    environmental = count_by_source(environmental_posts)
    translated = count_by_source(
        post
        for post in environmental_posts
        if post.get("original_text")
    )

    source_names = [source["source_name"] for source in sources]
    source_names += sorted(set(scraped) - set(source_names))

    print("\n==============================")
    print("PER-SOURCE SUMMARY")
    print("==============================")
    print(
        f"{'Source':32} {'Scraped':>7} {'KW kept':>7} "
        f"{'KW drop':>7} {'No topic':>8} {'Topic':>7} {'Transl.':>7}"
    )

    for source_name in source_names:
        print(
            f"{source_name[:32]:32} "
            f"{scraped[source_name]:>7} "
            f"{scraped[source_name] - dropped[source_name]:>7} "
            f"{dropped[source_name]:>7} "
            f"{rejected[source_name]:>8} "
            f"{environmental[source_name]:>7} "
            f"{translated[source_name]:>7}"
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


def apply_post_translation(post, translated_text, language):
    """Store the translation on the post, keeping the original text."""

    post["lang"] = language

    if str(language).lower() != "en":
        post["original_text"] = post.get("text")
        post["text"] = translated_text


def translate_non_english_posts(posts):
    """
    Translate non-English post text to English before classification.

    Uses the same Cloud Translation batching as clean_social.py, so
    the English monthly topic keywords can match translated posts.
    Translated posts keep their source text in original_text and the
    detected language in lang. In offline test mode only cached
    translations are used.
    """

    if POST_TRANSLATIONS_CACHE_FILE.exists():
        cache = load_json(POST_TRANSLATIONS_CACHE_FILE)
    else:
        cache = {}

    translated_posts = []
    pending_posts = []

    for post in posts:
        post = dict(post)
        translated_posts.append(post)

        text = str(post.get("text") or "").strip()

        if not post.get("postId") or not text:
            continue

        if is_english(text):
            post["lang"] = "en"
            continue

        cached = cache.get(str(post["postId"]))

        if cached and cached.get("original_text") == post["text"]:
            apply_post_translation(
                post,
                cached["text"],
                cached["lang"]
            )
        else:
            pending_posts.append(post)

    if pending_posts and OFFLINE_TEST_MODE:
        print(
            f"\nOffline test mode: {len(pending_posts)} non-English "
            "post(s) have no cached translation and stay untranslated."
        )
    elif pending_posts:
        from scripts.cleaning.clean_social import translate_comments_batch

        print(
            f"\nTranslating {len(pending_posts)} non-English "
            "post(s) with Cloud Translation..."
        )

        results = translate_comments_batch(
            [{"text": post["text"]} for post in pending_posts]
        )

        for post, (translated_text, language) in zip(
            pending_posts,
            results
        ):
            # Cloud Translation returns HTML-escaped text.
            translated_text = html.unescape(translated_text)

            # "und" means the batch failed and the original was kept,
            # so leave it out of the cache to retry on the next run.
            if language != "und":
                cache[str(post["postId"])] = {
                    "original_text": post["text"],
                    "text": translated_text,
                    "lang": language,
                }

            apply_post_translation(
                post,
                translated_text,
                language
            )

        save_json(cache, POST_TRANSLATIONS_CACHE_FILE)

    return translated_posts


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


def run_cost_usd(run, run_max_cost_usd):
    """Return a finished run's cost, assuming the full cap if unknown."""

    cost = getattr(run, "usage_total_usd", None)

    if cost is None:
        print(
            "Apify did not report this run's cost; counting "
            f"its full ${run_max_cost_usd:.2f} cap against the budget."
        )
        return run_max_cost_usd

    print(f"Apify run cost: ${cost:.2f}")

    return cost


# =========================================================
# POST SCRAPING
# =========================================================

def fetch_facebook_posts(
    sources,
    limit=POST_LIMIT_PER_PAGE
):
    """
    Scrape posts and return (posts, Apify cost in USD).

    resultsLimit applies to every page in a run, so sources with a
    different "post_limit" are scraped in separate runs. Each run is
    capped at the budget the earlier runs left over.
    """

    apify_client = require_apify_client()

    sources_by_limit = defaultdict(list)

    for source in sources:
        sources_by_limit[
            source.get("post_limit", limit)
        ].append(source)

    if not sources_by_limit:
        return [], 0.0

    items = []
    spent_usd = 0.0

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

        run_max_cost_usd = TOTAL_MAX_COST_USD - spent_usd

        if run_max_cost_usd <= 0:
            print(
                "Apify budget used up; skipping "
                f"{len(page_urls)} page(s)."
            )
            continue

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

        spent_usd += run_cost_usd(run, run_max_cost_usd)

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
            # Regional sources without a "country" are assigned one by
            # split_posts_by_source_keywords.
            post["country"] = source_info.get("country") or "Unknown"
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
    return keep_reporting_month(enriched_posts), spent_usd


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

    for country in sorted({
        country
        for source in sources
        for country in source_countries(source)
    }):
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
# SELECT POSTS FOR COMMENTS
# =========================================================

def select_posts_for_comments(posts):
    """
    Select every post worth scraping comments for.

    Excludes posts with zero reported comments or no known country,
    and orders the rest by engagement.
    """

    candidates = [
        post
        for post in posts
        if safe_int(post.get("comments")) > 0
        and post.get("country")
        and post.get("country") != "Unknown"
    ]

    return sorted(
        candidates,
        key=lambda post: (
            safe_int(post.get("comments")),
            safe_int(post.get("likes")),
            safe_int(post.get("shares")),
        ),
        reverse=True
    )


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
    max_cost_usd,
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

    if max_cost_usd <= 0:
        print(
            "\nApify budget used up by post scraping; "
            "skipping comment scraping."
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
        f"for {len(post_urls)} post(s), "
        f"capped at ${max_cost_usd:.2f}..."
    )

    run = apify_client.actor(
        COMMENTS_ACTOR
    ).call(
        run_input=run_input,
        max_total_charge_usd=(
            max_cost_usd
        ),
    )

    if run is None:
        print(
            "Comment scraper failed "
            "to start."
        )
        return []

    run_cost_usd(run, max_cost_usd)

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
    """Explain whether the cached comments match the current selection."""

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
            "Offline test mode does not run a new Apify comment scrape."
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
        "original_text": post.get("original_text"),
        "lang": post.get("lang"),
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
        raise SystemExit("SUPABASE_URL and a server-side Supabase key are required.")

    if key.startswith("sb_publishable_") or key.startswith("sb_anon_"):
        raise SystemExit("Facebook upload requires a server-side Supabase key.")

    try:
        from scripts.supabase.facebook_pipeline import sync_facebook_rows

        print("Syncing to Supabase...")
        counts = sync_facebook_rows(posts, comments)
        print("✓ Supabase sync successful")
        print(f"Upserted: {counts}")
        return counts
    except Exception as error:
        raise SystemExit(f"Facebook Supabase sync failed: {error}") from error


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

    if OFFLINE_TEST_MODE:
        print("\nUsing cached Facebook posts...")
        posts = load_json(POSTS_CACHE_FILE)
        post_cost_usd = 0.0
    else:
        posts, post_cost_usd = fetch_facebook_posts(
            SCRAPE_SOURCES
        )
        save_json(posts, POSTS_CACHE_FILE)

    scraped_posts = posts

    # Regional pages (e.g. Mongabay) are assigned a country by keyword.
    # The raw cache stays unfiltered so keyword lists can be tuned
    # offline without another Apify run.
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

    # Translate before classification so the English monthly topic
    # keywords also match non-English posts.
    posts = translate_non_english_posts(posts)

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
        f"{len(scraped_posts)}"
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

    translated_posts = [
        post
        for post in environmental_posts
        if post.get("original_text")
    ]

    print(
        f"\nTranslated environmental posts: "
        f"{len(translated_posts)}"
    )

    print_country_distribution(
        translated_posts,
        "TRANSLATED POSTS BY COUNTRY"
    )

    print_source_run_summary(
        SCRAPE_SOURCES,
        scraped_posts,
        keyword_dropped_posts,
        rejected_posts,
        environmental_posts
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
    # STEP 4: SELECT POSTS FOR COMMENTS
    # =====================================================

    selected_posts = select_posts_for_comments(
        environmental_posts
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

        if OFFLINE_TEST_MODE:
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
                selected_posts,
                TOTAL_MAX_COST_USD - post_cost_usd
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
        len(scraped_posts)
    )
    print(
        "Usable posts:",
        len(usable_posts)
    )
    print(
        "Environmental posts:",
        len(environmental_posts)
    )
    print(
        "Rejected usable posts:",
        len(rejected_posts)
    )
    print(
        "Translated environmental posts:",
        len(translated_posts)
    )
    print(
        "Posts selected for comments:",
        len(selected_posts)
    )
    print(
        "Comments available:",
        len(comments)
    )

    print("\nDone.")
