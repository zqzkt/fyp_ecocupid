import os
import re
import time
import html
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse, urlunparse

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from supabase import create_client, Client


# ============================================================
# CONFIGURATION
# ============================================================

START_DATE = datetime.strptime(
    os.getenv("NEWS_START_DATE", "2026-08-01"),
    "%Y-%m-%d"
).replace(tzinfo=timezone.utc)

END_DATE = datetime.strptime(
    os.getenv("NEWS_END_DATE", "2026-08-31"),
    "%Y-%m-%d"
).replace(
    hour=23,
    minute=59,
    second=59,
    tzinfo=timezone.utc
)

SOURCE_COUNTRY = "Philippines"
SOURCE_NAME = "GMA News Online"
RAW_TABLE = "news_raw"

GDELT_API = "https://api.gdeltproject.org/api/v2/doc/doc"

# IMPORTANT:
# GDELT is only being used to DISCOVER GMA URLs.
# The actual article content comes directly from GMA.
GDELT_DOMAIN = "gmanetwork.com"

GDELT_MAX_RECORDS = 250

# GDELT recommends leaving time between requests.
GDELT_REQUEST_DELAY = 5.5

# Delay between GMA article requests.
ARTICLE_REQUEST_DELAY = 1.0

MAX_RETRIES = 3
INSERT_BATCH_SIZE = 100


# ============================================================
# ENVIRONMENT SEARCH TERMS
# ============================================================

# These are used for GDELT discovery.
#
# We deliberately use broad environmental search terms.
# The article is checked again after downloading the full text.
SEARCH_TERMS = [
    "environment",
    "climate",
    "pollution",
    "waste",
    "biodiversity",
    "conservation",
    "renewable energy",
    "El Nino",
    "El Niño",
    "drought",
    "flood",
    "flooding",
    "landslide",
    "Habagat",
    "PAGASA",
    "DENR",
]


# ============================================================
# ENVIRONMENT KEYWORDS
# ============================================================

ENVIRONMENT_KEYWORDS = [

    # General
    "environment",
    "environmental",
    "climate",
    "climate change",
    "global warming",
    "sustainability",
    "sustainable",
    "green economy",

    # Pollution
    "pollution",
    "air pollution",
    "water pollution",
    "plastic pollution",
    "marine pollution",
    "oil spill",
    "sewage",
    "wastewater",

    # Waste
    "waste",
    "solid waste",
    "garbage",
    "trash",
    "recycling",
    "landfill",
    "waste management",
    "waste-to-energy",
    "circular economy",

    # Biodiversity / conservation
    "biodiversity",
    "conservation",
    "wildlife",
    "endangered",
    "endangered species",
    "forest",
    "forestation",
    "reforestation",
    "deforestation",
    "ecosystem",
    "habitat",
    "marine",
    "coral",
    "coral reef",
    "mangrove",

    # Energy
    "renewable energy",
    "clean energy",
    "solar",
    "solar energy",
    "wind energy",
    "hydropower",
    "geothermal",
    "fossil fuel",
    "coal",
    "carbon",
    "carbon emissions",
    "greenhouse gas",
    "greenhouse gases",

    # Climate / weather / hazards
    "el niño",
    "el nino",
    "la niña",
    "la nina",
    "drought",
    "heatwave",
    "heat wave",
    "extreme heat",
    "extreme rainfall",
    "heavy rainfall",
    "flood",
    "flooding",
    "flash flood",
    "landslide",
    "sea level rise",
    "typhoon",
    "tropical cyclone",
    "storm surge",
    "habagat",
    "southwest monsoon",

    # Philippine environmental institutions
    "denr",
    "department of environment and natural resources",
    "pagasa",
    "philippine atmospheric, geophysical and astronomical services administration",
]


# ============================================================
# COUNTRY KEYWORDS
# ============================================================

COUNTRY_KEYWORDS = {

    "Philippines": [
        "philippines",
        "philippine",
        "filipino",

        "metro manila",
        "national capital region",
        "ncr",

        "luzon",
        "visayas",
        "mindanao",

        "manila",
        "quezon city",
        "makati",
        "pasig",
        "taguig",
        "parañaque",
        "paranaque",
        "muntinlupa",
        "caloocan",

        "bulacan",
        "cavite",
        "laguna",
        "rizal",
        "batangas",
        "pangasinan",
        "pampanga",
        "tarlac",
        "nueva ecija",
        "zambales",
        "bataan",

        "cebu",
        "bohol",
        "iloilo",
        "leyte",
        "samar",

        "davao",
        "palawan",

        "calabarzon",
        "mimaropa",
        "cagayan valley",
        "cordillera",

        "denr",
        "pagasa",
        "ndrrmc",

        "manila bay",
        "pasig river",
        "laguna lake",
        "laguna de bay",
        "sierra madre",

        "habagat",
        "amihan",
    ],

    "Singapore": [
        "singapore",
        "singaporean",
    ],

    "Malaysia": [
        "malaysia",
        "malaysian",
        "kuala lumpur",
        "sabah",
        "sarawak",
        "penang",
        "johor",
    ],

    "Indonesia": [
        "indonesia",
        "indonesian",
        "jakarta",
        "sumatra",
        "java",
        "kalimantan",
        "sulawesi",
        "bali",
    ],

    "Thailand": [
        "thailand",
        "thai",
        "bangkok",
    ],

    "Brunei": [
        "brunei",
        "brunei darussalam",
        "bandar seri begawan",
    ],
}


# ============================================================
# SUPABASE
# ============================================================

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError(
        "Missing SUPABASE_URL or SUPABASE_KEY in .env"
    )

supabase: Client = create_client(
    SUPABASE_URL,
    SUPABASE_KEY
)


# ============================================================
# REQUEST SESSION
# ============================================================

session = requests.Session()

session.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,"
        "application/xml;q=0.9,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
})


# ============================================================
# BASIC TEXT HELPERS
# ============================================================

def clean_whitespace(text):

    if not text:
        return ""

    text = html.unescape(text)

    text = re.sub(
        r"\s+",
        " ",
        text
    )

    return text.strip()


def normalize_for_matching(text):

    if not text:
        return ""

    text = text.lower()

    text = text.replace("’", "'")
    text = text.replace("–", "-")
    text = text.replace("—", "-")

    return text


def keyword_in_text(keyword, text):

    keyword = normalize_for_matching(
        keyword
    )

    text = normalize_for_matching(
        text
    )

    pattern = (
        r"(?<!\w)"
        + re.escape(keyword)
        + r"(?!\w)"
    )

    return (
        re.search(
            pattern,
            text,
            flags=re.IGNORECASE
        )
        is not None
    )


def find_environment_keywords(text):

    found = []

    for keyword in ENVIRONMENT_KEYWORDS:

        if keyword_in_text(
            keyword,
            text
        ):
            found.append(keyword)

    return list(
        dict.fromkeys(found)
    )


def detect_countries(text):

    detected = []

    for country, keywords in COUNTRY_KEYWORDS.items():

        for keyword in keywords:

            if keyword_in_text(
                keyword,
                text
            ):

                detected.append(
                    country
                )

                break

    return detected


# ============================================================
# URL HELPERS
# ============================================================

def clean_url(url):

    if not url:
        return None

    url = url.strip()

    parsed = urlparse(url)

    cleaned = urlunparse((
        parsed.scheme,
        parsed.netloc,
        parsed.path.rstrip("/"),
        "",
        "",
        ""
    ))

    return cleaned


def is_gma_article_url(url):

    if not url:
        return False

    url = clean_url(url)

    parsed = urlparse(url)

    domain = parsed.netloc.lower()

    if not (
        domain == "www.gmanetwork.com"
        or domain == "gmanetwork.com"
    ):
        return False

    # GMA News article URLs generally contain:
    #
    # /news/.../.../.../story
    #
    if "/news/" not in parsed.path:
        return False

    if "/story" not in parsed.path:
        return False

    return True


# ============================================================
# GENERIC REQUEST HELPER
# ============================================================

def get_page(url, label="Page"):

    for attempt in range(
        1,
        MAX_RETRIES + 1
    ):

        try:

            response = session.get(
                url,
                timeout=30
            )

            print(
                f"    {label} status: "
                f"{response.status_code}"
            )

            if response.status_code == 200:
                return response

            if response.status_code == 429:

                wait_time = (
                    attempt * 15
                )

                print(
                    f"    Rate limited. "
                    f"Waiting {wait_time}s..."
                )

                time.sleep(
                    wait_time
                )

                continue

            if response.status_code >= 500:

                wait_time = (
                    attempt * 5
                )

                print(
                    f"    Server error. "
                    f"Waiting {wait_time}s..."
                )

                time.sleep(
                    wait_time
                )

                continue

            print(
                f"    Request failed "
                f"with HTTP "
                f"{response.status_code}"
            )

            return None

        except requests.RequestException as e:

            print(
                f"    Request error "
                f"(attempt "
                f"{attempt}/{MAX_RETRIES}): "
                f"{e}"
            )

            if attempt < MAX_RETRIES:

                time.sleep(
                    attempt * 5
                )

    return None


# ============================================================
# SUPABASE EXISTING URLS
# ============================================================

def get_existing_urls():

    print(
        "\nLoading existing Philippine "
        "URLs from Supabase..."
    )

    existing = set()

    start = 0
    page_size = 1000

    while True:

        response = (
            supabase
            .table(RAW_TABLE)
            .select("url")
            .eq(
                "source_country",
                SOURCE_COUNTRY
            )
            .range(
                start,
                start + page_size - 1
            )
            .execute()
        )

        rows = (
            response.data
            or []
        )

        if not rows:
            break

        for row in rows:

            url = clean_url(
                row.get("url")
            )

            if url:
                existing.add(url)

        if len(rows) < page_size:
            break

        start += page_size

    print(
        f"Existing Philippine URLs "
        f"in Supabase: "
        f"{len(existing)}"
    )

    return existing


# ============================================================
# GDELT HELPERS
# ============================================================

def gdelt_datetime(dt):

    return dt.strftime(
        "%Y%m%d%H%M%S"
    )


def build_gdelt_query(term):

    """
    Search ONLY GMA Network.

    Example query:

        climate domain:gmanetwork.com
    """

    if " " in term:

        search_term = (
            f'"{term}"'
        )

    else:

        search_term = term

    return (
        f"{search_term} "
        f"domain:{GDELT_DOMAIN}"
    )


def request_gdelt(
    term,
    day_start,
    day_end
):

    query = build_gdelt_query(
        term
    )

    params = {
        "query":
            query,

        "mode":
            "artlist",

        "format":
            "json",

        "maxrecords":
            GDELT_MAX_RECORDS,

        "sort":
            "datedesc",

        "startdatetime":
            gdelt_datetime(
                day_start
            ),

        "enddatetime":
            gdelt_datetime(
                day_end
            ),
    }

    for attempt in range(
        1,
        MAX_RETRIES + 1
    ):

        try:

            response = session.get(
                GDELT_API,
                params=params,
                timeout=60
            )

            print(
                f"      GDELT status: "
                f"{response.status_code}"
            )

            if response.status_code == 429:

                wait_time = (
                    attempt * 15
                )

                print(
                    "      GDELT rate "
                    "limited."
                )

                print(
                    f"      Waiting "
                    f"{wait_time}s..."
                )

                time.sleep(
                    wait_time
                )

                continue

            if response.status_code != 200:

                print(
                    "      GDELT request "
                    "failed:"
                )

                print(
                    response.text[:300]
                )

                return []

            # Sometimes APIs return HTML
            # instead of JSON.
            content_type = (
                response.headers
                .get(
                    "content-type",
                    ""
                )
                .lower()
            )

            if "json" not in content_type:

                print(
                    "      WARNING: "
                    "GDELT did not "
                    "return JSON."
                )

                print(
                    response.text[:300]
                )

                return []

            data = response.json()

            articles = (
                data.get(
                    "articles",
                    []
                )
            )

            return articles

        except Exception as e:

            print(
                f"      GDELT error "
                f"(attempt "
                f"{attempt}/"
                f"{MAX_RETRIES}): "
                f"{e}"
            )

            if attempt < MAX_RETRIES:

                time.sleep(
                    attempt * 10
                )

    return []


# ============================================================
# GDELT HISTORICAL DISCOVERY
# ============================================================

def discover_candidate_urls():

    print("\n")
    print("=" * 70)
    print("DISCOVERING HISTORICAL GMA ARTICLES WITH GDELT")
    print("=" * 70)

    print(
        f"Target range: "
        f"{START_DATE.date()} "
        f"to "
        f"{END_DATE.date()}"
    )

    all_urls = set()

    # Keep some GDELT metadata
    # for debugging.
    discovery_metadata = {}

    current_day = START_DATE.replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0
    )

    final_day = END_DATE.replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0
    )

    day_number = 0

    while current_day <= final_day:

        day_number += 1

        day_end = (
            current_day
            + timedelta(days=1)
            - timedelta(seconds=1)
        )

        print("\n")
        print("#" * 70)
        print(
            f"DATE {day_number}: "
            f"{current_day.date()}"
        )
        print("#" * 70)

        day_urls = set()

        for term_number, term in enumerate(
            SEARCH_TERMS,
            start=1
        ):

            print(
                f"\n  "
                f"[{term_number}/"
                f"{len(SEARCH_TERMS)}] "
                f"{term}"
            )

            articles = request_gdelt(
                term,
                current_day,
                day_end
            )

            print(
                f"      Results returned: "
                f"{len(articles)}"
            )

            new_for_term = 0

            for article in articles:

                url = clean_url(
                    article.get(
                        "url"
                    )
                )

                if not url:
                    continue

                if not is_gma_article_url(
                    url
                ):
                    continue

                day_urls.add(url)

                if url not in all_urls:

                    all_urls.add(url)

                    new_for_term += 1

                    discovery_metadata[
                        url
                    ] = {
                        "gdelt_title":
                            article.get(
                                "title"
                            ),

                        "gdelt_date":
                            article.get(
                                "seendate"
                            ),

                        "gdelt_domain":
                            article.get(
                                "domain"
                            ),

                        "found_by":
                            term,
                    }

            print(
                f"      New unique "
                f"GMA URLs: "
                f"{new_for_term}"
            )

            # Important:
            # avoid hammering GDELT.
            time.sleep(
                GDELT_REQUEST_DELAY
            )

        print("\n  --------------------------------")
        print(
            f"  Unique GMA URLs for "
            f"{current_day.date()}: "
            f"{len(day_urls)}"
        )

        print(
            f"  Running total: "
            f"{len(all_urls)}"
        )
        print("  --------------------------------")

        current_day += timedelta(
            days=1
        )

    print("\n")
    print("=" * 70)
    print(
        "TOTAL UNIQUE HISTORICAL "
        "GMA CANDIDATE URLS: "
        f"{len(all_urls)}"
    )
    print("=" * 70)

    # Print sample URLs
    if all_urls:

        print(
            "\nSample discovered URLs:"
        )

        for url in list(
            sorted(all_urls)
        )[:10]:

            meta = (
                discovery_metadata
                .get(
                    url,
                    {}
                )
            )

            print(
                "\n  "
                + str(
                    meta.get(
                        "gdelt_title",
                        ""
                    )
                )
            )

            print(
                "  "
                + url
            )

            print(
                "  Found by: "
                + str(
                    meta.get(
                        "found_by",
                        ""
                    )
                )
            )

    return all_urls


# ============================================================
# GMA TITLE EXTRACTION
# ============================================================

def extract_title(soup):

    tag = soup.find(
        "meta",
        property="og:title"
    )

    if (
        tag
        and tag.get("content")
    ):

        return clean_whitespace(
            tag["content"]
        )

    h1 = soup.find("h1")

    if h1:

        return clean_whitespace(
            h1.get_text(
                " ",
                strip=True
            )
        )

    if soup.title:

        return clean_whitespace(
            soup.title.get_text(
                " ",
                strip=True
            )
        )

    return ""


# ============================================================
# DATE EXTRACTION
# ============================================================

def parse_date_string(value):

    if not value:
        return None

    value = value.strip()

    # --------------------------------------------------------
    # ISO
    # --------------------------------------------------------

    try:

        iso_value = value.replace(
            "Z",
            "+00:00"
        )

        dt = datetime.fromisoformat(
            iso_value
        )

        if dt.tzinfo is None:

            dt = dt.replace(
                tzinfo=timezone.utc
            )

        return dt.astimezone(
            timezone.utc
        )

    except Exception:
        pass

    # --------------------------------------------------------
    # Visible date formats
    # --------------------------------------------------------

    formats = [
        "%B %d, %Y %I:%M%p",
        "%B %d, %Y %I:%M %p",
        "%B %d, %Y %H:%M",
        "%B %d, %Y",

        "%b %d, %Y %I:%M%p",
        "%b %d, %Y %I:%M %p",
        "%b %d, %Y",
    ]

    cleaned = re.sub(
        r"(?i)^published\s*",
        "",
        value
    )

    cleaned = re.sub(
        r"(?i)^updated\s*",
        "",
        cleaned
    )

    cleaned = clean_whitespace(
        cleaned
    )

    for fmt in formats:

        try:

            dt = datetime.strptime(
                cleaned,
                fmt
            )

            return dt.replace(
                tzinfo=timezone.utc
            )

        except ValueError:
            continue

    return None


def extract_published_date(soup):

    # --------------------------------------------------------
    # Metadata
    # --------------------------------------------------------

    metadata_candidates = [

        (
            "meta",
            {
                "property":
                "article:published_time"
            }
        ),

        (
            "meta",
            {
                "name":
                "article:published_time"
            }
        ),

        (
            "meta",
            {
                "itemprop":
                "datePublished"
            }
        ),

        (
            "meta",
            {
                "name":
                "date"
            }
        ),
    ]

    for (
        tag_name,
        attrs
    ) in metadata_candidates:

        tag = soup.find(
            tag_name,
            attrs=attrs
        )

        if tag:

            value = (
                tag.get("content")
                or tag.get(
                    "datetime"
                )
            )

            dt = parse_date_string(
                value
            )

            if dt:
                return dt

    # --------------------------------------------------------
    # <time>
    # --------------------------------------------------------

    for tag in soup.find_all(
        "time"
    ):

        value = (
            tag.get(
                "datetime"
            )
            or tag.get_text(
                " ",
                strip=True
            )
        )

        dt = parse_date_string(
            value
        )

        if dt:
            return dt

    # --------------------------------------------------------
    # JSON-LD
    # --------------------------------------------------------

    for script in soup.find_all(
        "script",
        type="application/ld+json"
    ):

        script_text = (
            script.string
            or script.get_text()
        )

        if not script_text:
            continue

        match = re.search(
            r'"datePublished"\s*'
            r':\s*"([^"]+)"',
            script_text
        )

        if match:

            dt = parse_date_string(
                match.group(1)
            )

            if dt:
                return dt

    # --------------------------------------------------------
    # Visible text
    # --------------------------------------------------------

    page_text = soup.get_text(
        " ",
        strip=True
    )

    patterns = [

        (
            r"Published\s+"
            r"([A-Z][a-z]+ "
            r"\d{1,2}, "
            r"\d{4} "
            r"\d{1,2}:\d{2}"
            r"(?:am|pm))"
        ),

        (
            r"Published\s+"
            r"([A-Z][a-z]+ "
            r"\d{1,2}, "
            r"\d{4})"
        ),
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            page_text,
            flags=re.IGNORECASE
        )

        if match:

            dt = parse_date_string(
                match.group(1)
            )

            if dt:
                return dt

    return None


# ============================================================
# ARTICLE TEXT EXTRACTION
# ============================================================

def extract_article_text(soup):

    selectors = [
        "div.story_main",
        "div.story_main_content",
        "div.article-body",
        "div.article_body",
        "div.story-body",
        "div.story_body",
        "article",
    ]

    best_text = ""

    for selector in selectors:

        container = soup.select_one(
            selector
        )

        if not container:
            continue

        paragraphs = []

        for p in container.find_all(
            "p"
        ):

            text = clean_whitespace(
                p.get_text(
                    " ",
                    strip=True
                )
            )

            if len(text) >= 20:

                paragraphs.append(
                    text
                )

        combined = "\n\n".join(
            paragraphs
        )

        if len(combined) > len(
            best_text
        ):

            best_text = combined

    # --------------------------------------------------------
    # Fallback
    # --------------------------------------------------------

    if len(best_text) < 200:

        paragraphs = []

        for p in soup.find_all("p"):

            text = clean_whitespace(
                p.get_text(
                    " ",
                    strip=True
                )
            )

            if len(text) < 40:
                continue

            lower = text.lower()

            noise_phrases = [
                "subscribe",
                "follow us",
                "copyright",
                "all rights reserved",
                "privacy policy",
                "terms of use",
                "advertisement",
                "read more",
            ]

            if any(
                phrase in lower
                for phrase
                in noise_phrases
            ):
                continue

            paragraphs.append(
                text
            )

        fallback = "\n\n".join(
            paragraphs
        )

        if len(fallback) > len(
            best_text
        ):

            best_text = fallback

    return best_text.strip()


# ============================================================
# SCRAPE ONE GMA ARTICLE
# ============================================================

def scrape_article(url):

    print("\n")
    print("=" * 70)
    print("ARTICLE")
    print("=" * 70)

    print(url)

    response = get_page(
        url,
        label="Article"
    )

    if response is None:

        return {
            "status":
                "failed"
        }

    soup = BeautifulSoup(
        response.text,
        "html.parser"
    )

    title = extract_title(
        soup
    )

    published_at = (
        extract_published_date(
            soup
        )
    )

    print(
        f"    Title: "
        f"{title}"
    )

    if published_at:

        print(
            f"    Published: "
            f"{published_at.isoformat()}"
        )

    else:

        print(
            "    Published: "
            "NOT FOUND"
        )

    # ========================================================
    # DATE FILTER
    # ========================================================

    if published_at is None:

        print(
            "    SKIP - no valid "
            "publication date"
        )

        return {
            "status":
                "no_date"
        }

    if (
        published_at < START_DATE
        or
        published_at > END_DATE
    ):

        print(
            "    SKIP - outside "
            "target date range"
        )

        return {
            "status":
                "outside_date"
        }

    # ========================================================
    # ARTICLE TEXT
    # ========================================================

    article_text = (
        extract_article_text(
            soup
        )
    )

    print(
        f"    Article text length: "
        f"{len(article_text)}"
    )

    if len(article_text) < 200:

        print(
            "    SKIP - article "
            "text too short"
        )

        return {
            "status":
                "no_text"
        }

    combined_text = (
        f"{title}\n\n"
        f"{article_text}"
    )

    # ========================================================
    # ENVIRONMENT FILTER
    # ========================================================

    environment_keywords = (
        find_environment_keywords(
            combined_text
        )
    )

    if environment_keywords:

        print(
            "    Environment keywords: "
            + ", ".join(
                environment_keywords
            )
        )

    else:

        print(
            "    Environment keywords: "
            "NONE"
        )

        print(
            "    SKIP - not environmental"
        )

        return {
            "status":
                "not_environment"
        }

    # ========================================================
    # COUNTRY DETECTION
    # ========================================================

    countries = detect_countries(
        combined_text
    )

    if countries:

        print(
            "    Countries detected: "
            + ", ".join(countries)
        )

    else:

        print(
            "    Countries detected: "
            "NONE"
        )

    # IMPORTANT:
    # GMA is a Philippine source,
    # but it also publishes international news.
    #
    # We therefore REQUIRE actual
    # Philippine relevance.
    if "Philippines" not in countries:

        print(
            "    SKIP - environmental "
            "but not Philippines-related"
        )

        return {
            "status":
                "not_philippines"
        }

    # ========================================================
    # KEEP
    # ========================================================

    article = {

        "source_country":
            SOURCE_COUNTRY,

        "title":
            title,

        "source":
            SOURCE_NAME,

        "published_at":
            published_at.isoformat(),

        "countries":
            ", ".join(countries),

        "environment_keywords":
            ", ".join(
                environment_keywords
            ),

        "article_text":
            article_text,

        "url":
            clean_url(url),
    }

    print(
        "    KEEP - valid Philippine "
        "environmental article"
    )

    return {
        "status":
            "keep",

        "article":
            article
    }


# ============================================================
# INSERT INTO SUPABASE
# ============================================================

def insert_articles_to_supabase(
    articles
):

    if not articles:

        print(
            "\nNo new articles "
            "to insert."
        )

        return 0

    # --------------------------------------------------------
    # In-memory URL deduplication
    # --------------------------------------------------------

    unique = {}

    for article in articles:

        url = clean_url(
            article.get(
                "url"
            )
        )

        if not url:
            continue

        article["url"] = url

        unique[url] = article

    articles = list(
        unique.values()
    )

    print(
        f"\nUnique articles "
        f"ready for insert: "
        f"{len(articles)}"
    )

    inserted = 0

    for i in range(
        0,
        len(articles),
        INSERT_BATCH_SIZE
    ):

        batch = articles[
            i:
            i + INSERT_BATCH_SIZE
        ]

        print(
            f"Inserting batch "
            f"{i // INSERT_BATCH_SIZE + 1} "
            f"({len(batch)} articles)..."
        )

        try:

            (
                supabase
                .table(RAW_TABLE)
                .insert(batch)
                .execute()
            )

            inserted += len(
                batch
            )

        except Exception as e:

            print(
                f"Batch insert error: "
                f"{e}"
            )

            print(
                "Trying articles "
                "one-by-one..."
            )

            for article in batch:

                try:

                    (
                        supabase
                        .table(RAW_TABLE)
                        .insert(article)
                        .execute()
                    )

                    inserted += 1

                except Exception as inner_e:

                    print(
                        "\nFAILED INSERT:"
                    )

                    print(
                        article.get(
                            "title"
                        )
                    )

                    print(
                        article.get(
                            "url"
                        )
                    )

                    print(
                        inner_e
                    )

    return inserted


# ============================================================
# MAIN
# ============================================================

def main():

    print("\n")
    print("=" * 70)
    print(
        "GMA NEWS PHILIPPINES "
        "ENVIRONMENT SCRAPER"
    )
    print("=" * 70)

    print(
        f"Date range: "
        f"{START_DATE.date()} "
        f"to "
        f"{END_DATE.date()}"
    )

    print(
        f"Source country: "
        f"{SOURCE_COUNTRY}"
    )

    print(
        f"Source: "
        f"{SOURCE_NAME}"
    )

    print(
        "Discovery: "
        "GDELT DOC API"
    )

    # ========================================================
    # STEP 1
    # Existing Supabase URLs
    # ========================================================

    existing_urls = (
        get_existing_urls()
    )

    # ========================================================
    # STEP 2
    # Historical GMA discovery
    # ========================================================

    candidate_urls = (
        discover_candidate_urls()
    )

    # ========================================================
    # STEP 3
    # Remove existing URLs BEFORE
    # downloading GMA articles
    # ========================================================

    new_candidate_urls = []

    already_existing = 0

    for url in candidate_urls:

        cleaned = clean_url(
            url
        )

        if cleaned in existing_urls:

            already_existing += 1

            continue

        new_candidate_urls.append(
            cleaned
        )

    print("\n")
    print("=" * 70)
    print("PRE-SCRAPE DEDUPLICATION")
    print("=" * 70)

    print(
        f"Candidate URLs discovered: "
        f"{len(candidate_urls)}"
    )

    print(
        f"Already in Supabase: "
        f"{already_existing}"
    )

    print(
        "New URLs requiring "
        "article scrape: "
        f"{len(new_candidate_urls)}"
    )

    # ========================================================
    # STEP 4
    # Download + filter
    # ========================================================

    stats = {

        "processed": 0,

        "keep": 0,

        "outside_date": 0,

        "no_date": 0,

        "no_text": 0,

        "not_environment": 0,

        "not_philippines": 0,

        "failed": 0,
    }

    articles_to_insert = []

    total = len(
        new_candidate_urls
    )

    for index, url in enumerate(
        sorted(
            new_candidate_urls
        ),
        start=1
    ):

        print("\n")
        print(
            f"PROCESSING "
            f"{index}/{total}"
        )

        try:

            result = scrape_article(
                url
            )

            stats[
                "processed"
            ] += 1

            status = result.get(
                "status"
            )

            if status in stats:

                stats[
                    status
                ] += 1

            if status == "keep":

                articles_to_insert.append(
                    result[
                        "article"
                    ]
                )

        except Exception as e:

            print(
                "Unexpected article "
                f"error: {e}"
            )

            stats[
                "failed"
            ] += 1

        time.sleep(
            ARTICLE_REQUEST_DELAY
        )

    # ========================================================
    # STEP 5
    # INSERT
    # ========================================================

    inserted = (
        insert_articles_to_supabase(
            articles_to_insert
        )
    )

    # ========================================================
    # SUMMARY
    # ========================================================

    print("\n")
    print("=" * 70)
    print("FINAL SUMMARY")
    print("=" * 70)

    print(
        f"Search terms used: "
        f"{len(SEARCH_TERMS)}"
    )

    print(
        "Unique historical GMA "
        "candidate URLs: "
        f"{len(candidate_urls)}"
    )

    print(
        f"Already in Supabase: "
        f"{already_existing}"
    )

    print(
        f"New URLs processed: "
        f"{stats['processed']}"
    )

    print(
        f"Outside Aug 1-31: "
        f"{stats['outside_date']}"
    )

    print(
        "No valid publication date: "
        f"{stats['no_date']}"
    )

    print(
        "No usable article text: "
        f"{stats['no_text']}"
    )

    print(
        f"Not environmental: "
        f"{stats['not_environment']}"
    )

    print(
        "Environmental but not "
        "Philippines-related: "
        f"{stats['not_philippines']}"
    )

    print(
        "Failed requests/extraction: "
        f"{stats['failed']}"
    )

    print(
        f"Valid articles ready: "
        f"{stats['keep']}"
    )

    print(
        f"Inserted into Supabase: "
        f"{inserted}"
    )

    print("=" * 70)


if __name__ == "__main__":
    main()