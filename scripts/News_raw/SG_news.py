import requests
from bs4 import BeautifulSoup
import pandas as pd
import time
import re
import os

from datetime import datetime, timedelta
from urllib.parse import urljoin

from supabase import create_client, Client
from dotenv import load_dotenv


# ============================================================
# SUPABASE CONNECTION
# ============================================================

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError(
        "SUPABASE_URL or SUPABASE_KEY is missing. "
        "Check your .env file."
    )

supabase: Client = create_client(
    SUPABASE_URL,
    SUPABASE_KEY
)

RAW_TABLE = "news_raw"
SOURCE_COUNTRY = "Singapore"


# ============================================================
# SETTINGS
# ============================================================

BASE_URL = "https://www.straitstimes.com"

API_URL = (
    "https://www.straitstimes.com/"
    "_plat/api/v1/articlesListing"
)

SEARCH_PARAM = "singapore_environment"


# Change these as needed
START_DATE = os.getenv(
    "NEWS_START_DATE",
    "2026-08-01"
)

END_DATE = os.getenv(
    "NEWS_END_DATE",
    "2026-08-31"
)


START_DATE = datetime.strptime(
    START_DATE,
    "%Y-%m-%d"
)

END_DATE = datetime.strptime(
    END_DATE,
    "%Y-%m-%d"
)


# ============================================================
# ENVIRONMENT KEYWORDS
# ============================================================

ENVIRONMENT_KEYWORDS = [

    "environment",
    "environmental",
    "sustainability",
    "sustainable development",

    "climate change",
    "global warming",
    "climate crisis",
    "climate action",
    "climate risk",

    "carbon emissions",
    "carbon emission",
    "carbon footprint",
    "carbon neutral",
    "carbon neutrality",
    "decarbonisation",
    "decarbonization",
    "net zero",
    "greenhouse gas",
    "greenhouse gases",

    "renewable energy",
    "clean energy",
    "green energy",
    "solar energy",
    "solar power",
    "wind energy",
    "hydrogen",
    "low-carbon energy",

    "pollution",
    "air pollution",
    "water pollution",
    "haze",
    "air quality",

    "plastic waste",
    "food waste",
    "electronic waste",
    "e-waste",
    "recycling",
    "waste management",
    "circular economy",

    "biodiversity",
    "conservation",
    "ecosystem",
    "wildlife",
    "deforestation",
    "forest fires",
    "marine biodiversity",

    "flooding",
    "flood",
    "floods",
    "sea level rise",
    "coastal erosion",
    "drought",
    "extreme weather",
    "heatwave",
    "heat wave",

    "green building",
    "green buildings",
    "sustainable transport",
    "electric vehicle",
    "electric vehicles",
    "green finance"
]


# ============================================================
# ASEAN COUNTRY KEYWORDS
# ============================================================

COUNTRY_KEYWORDS = {

    "Singapore": [
        "singapore",
        "singaporean",
        "singaporeans",
        "s'pore",
        "spore"
    ],

    "Malaysia": [
        "malaysia",
        "malaysian",
        "malaysians",
        "kuala lumpur",
        "johor",
        "selangor"
    ],

    "Indonesia": [
        "indonesia",
        "indonesian",
        "indonesians",
        "jakarta",
        "sumatra",
        "kalimantan"
    ],

    "Philippines": [
        "philippines",
        "philippine",
        "filipino",
        "filipinos",
        "manila"
    ],

    "Thailand": [
        "thailand",
        "thai",
        "bangkok"
    ],

    "Brunei": [
        "brunei",
        "bruneian",
        "bandar seri begawan"
    ]
}


# ============================================================
# REQUEST HEADERS
# ============================================================

HEADERS = {

    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/151.0.0.0 Safari/537.36"
    ),

    "Accept": (
        "text/html,application/xhtml+xml,"
        "application/json;q=0.9,*/*;q=0.8"
    )
}


# ============================================================
# CONVERT API DATE
# ============================================================

def parse_api_date(date_string):

    if not date_string:
        return None

    try:

        dt = pd.to_datetime(
            date_string,
            utc=True
        )

        return dt.to_pydatetime().replace(
            tzinfo=None
        )

    except Exception:
        return None


# ============================================================
# GET ONE API PAGE
# ============================================================

def get_api_page(page_number):

    # Use the end date as the maximum date.
    # Add one day so that the full END_DATE is included.
    api_max_date = (
        END_DATE
        + timedelta(days=1)
    ).strftime(
        "%Y-%m-%dT00:00:00.000Z"
    )

    params = {

        "pageType":
            "sub_section",

        "searchParam":
            SEARCH_PARAM,

        "page":
            page_number,

        "maxDate":
            api_max_date
    }

    try:

        response = requests.get(
            API_URL,
            params=params,
            headers=HEADERS,
            timeout=20
        )

        print(
            f"API page {page_number} "
            f"status: {response.status_code}"
        )

        if response.status_code != 200:
            return None

        return response.json()

    except Exception as e:

        print(
            "API error:",
            e
        )

        return None


# ============================================================
# DISCOVER ARTICLES FROM API
# ============================================================

def get_article_urls():

    print()
    print(
        "DISCOVERING ARTICLES FROM ST API"
    )

    articles_found = []
    seen_urls = set()
    page = 1

    while True:

        data = get_api_page(
            page
        )

        if data is None:

            print(
                "Could not retrieve API page."
            )

            break

        cards = data.get(
            "cards",
            []
        )

        if len(cards) == 0:

            print(
                "No more cards returned."
            )

            break

        print(
            f"Page {page}: "
            f"{len(cards)} cards"
        )

        oldest_date_on_page = None

        for card in cards:

            article_card = card.get(
                "articleCard"
            )

            if not article_card:
                continue

            title = article_card.get(
                "title"
            )

            url_path = article_card.get(
                "urlPath"
            )

            published_string = (
                article_card.get(
                    "publishedDate"
                )
            )

            is_premium = article_card.get(
                "isPremium",
                False
            )

            published_date = (
                parse_api_date(
                    published_string
                )
            )

            if (
                not url_path
                or not published_date
            ):
                continue

            # Track oldest article on this API page
            if (
                oldest_date_on_page is None
                or published_date
                < oldest_date_on_page
            ):

                oldest_date_on_page = (
                    published_date
                )

            article_date = (
                published_date.replace(
                    hour=0,
                    minute=0,
                    second=0,
                    microsecond=0
                )
            )

            if article_date > END_DATE:
                continue

            if article_date < START_DATE:
                continue

            # Public articles only
            if is_premium:

                print(
                    "Skipping premium:",
                    title
                )

                continue

            full_url = urljoin(
                BASE_URL,
                url_path
            )

            # Prevent duplicate URLs within
            # the current API discovery run
            if full_url in seen_urls:
                continue

            seen_urls.add(
                full_url
            )

            articles_found.append(
                {
                    "title":
                        title,

                    "url":
                        full_url,

                    "published_at":
                        published_date
                }
            )

        # Stop when this page has already reached
        # articles older than START_DATE
        if (
            oldest_date_on_page
            and
            oldest_date_on_page < START_DATE
        ):

            print()

            print(
                "Reached articles older than "
                f"{START_DATE.date()}."
            )

            print(
                "Stopping pagination."
            )

            break

        # Optional additional stop using API total
        total = data.get(
            "total"
        )

        if total:

            print(
                "API reports total:",
                total
            )

            if len(seen_urls) >= total:

                print(
                    "Reached API total."
                )

                break

        page += 1

        # Prevent runaway loop if API changes
        if page > 100:

            print(
                "Safety stop reached."
            )

            break

        time.sleep(1)

    print()

    print(
        f"Found {len(articles_found)} "
        "public articles within date range."
    )

    return articles_found


# ============================================================
# GET EXISTING URLS FROM SUPABASE
# ============================================================

def get_existing_urls():

    print()
    print(
        "CHECKING EXISTING ARTICLES IN SUPABASE"
    )

    existing_urls = set()

    # Supabase/PostgREST responses may be paginated,
    # so retrieve URLs in batches.
    batch_size = 1000
    start = 0

    try:

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
                    start + batch_size - 1
                )
                .execute()
            )

            rows = response.data or []

            for row in rows:

                url = row.get(
                    "url"
                )

                if url:
                    existing_urls.add(
                        url
                    )

            if len(rows) < batch_size:
                break

            start += batch_size

        print(
            f"{len(existing_urls)} existing "
            f"{SOURCE_COUNTRY} URLs found."
        )

        return existing_urls

    except Exception as e:

        print()
        print(
            "Error reading existing URLs "
            "from Supabase:"
        )

        print(e)

        raise


# ============================================================
# EXTRACT ARTICLE TEXT
# ============================================================

def extract_article_text(soup):

    paragraphs = []

    article_container = soup.find(
        "article"
    )

    if article_container:

        paragraph_tags = (
            article_container.find_all(
                "p"
            )
        )

    else:

        paragraph_tags = soup.find_all(
            "p"
        )

    unwanted_phrases = [

        "sign up now",
        "get st's newsletters",
        "subscribe",
        "advertise with us",
        "terms & conditions",
        "personal data protection",
        "download the app",
        "set as preferred source",
        "unlock this article",
        "enjoy unlimited access"
    ]

    for p in paragraph_tags:

        text = p.get_text(
            " ",
            strip=True
        )

        if len(text) < 30:
            continue

        lower_text = text.lower()

        if any(
            phrase in lower_text
            for phrase in unwanted_phrases
        ):
            continue

        paragraphs.append(
            text
        )

    return " ".join(
        paragraphs
    )


# ============================================================
# SCRAPE ARTICLE PAGE
# ============================================================

def scrape_article(article_info):

    url = article_info[
        "url"
    ]

    try:

        response = requests.get(
            url,
            headers=HEADERS,
            timeout=20
        )

        if response.status_code != 200:

            print(
                "Skipped:",
                response.status_code,
                url
            )

            return None

        soup = BeautifulSoup(
            response.text,
            "html.parser"
        )

        # Title
        h1 = soup.find(
            "h1"
        )

        if h1:

            title = h1.get_text(
                " ",
                strip=True
            )

        else:

            # Use title already supplied by API
            title = article_info[
                "title"
            ]

        # Article text
        article_text = (
            extract_article_text(
                soup
            )
        )

        if len(article_text) < 300:

            print(
                "Too little usable text:",
                title
            )

            return None

        published_date = (
            article_info[
                "published_at"
            ]
        )

        return {

            "title":
                title,

            "source":
                "The Straits Times",

            "published_at":
                published_date.strftime(
                    "%Y-%m-%d"
                ),

            "url":
                url,

            "article_text":
                article_text
        }

    except Exception as e:

        print(
            "Error scraping:",
            url
        )

        print(e)

        return None


# ============================================================
# FIND ENVIRONMENT KEYWORDS
# ============================================================

def find_environment_keywords(text):

    text = text.lower()

    matches = []

    for keyword in ENVIRONMENT_KEYWORDS:

        pattern = (
            r"\b"
            + re.escape(
                keyword.lower()
            )
            + r"\b"
        )

        if re.search(
            pattern,
            text
        ):

            matches.append(
                keyword
            )

    return matches


# ============================================================
# FIND COUNTRIES
# ============================================================

def find_countries(text):

    text = text.lower()

    countries_found = []

    for (
        country,
        keywords
    ) in COUNTRY_KEYWORDS.items():

        for keyword in keywords:

            pattern = (
                r"\b"
                + re.escape(
                    keyword.lower()
                )
                + r"\b"
            )

            if re.search(
                pattern,
                text
            ):

                countries_found.append(
                    country
                )

                break

    return countries_found


# ============================================================
# INSERT ARTICLES INTO SUPABASE
# ============================================================

def insert_articles_to_supabase(results):

    if len(results) == 0:

        print()
        print(
            "No matching new articles found."
        )

        return 0

    # --------------------------------------------------------
    # Remove duplicate URLs within the current scraping run
    # --------------------------------------------------------

    unique_results = {}

    for article in results:

        unique_results[
            article["url"]
        ] = article

    results = list(
        unique_results.values()
    )

    # --------------------------------------------------------
    # Prepare rows
    # --------------------------------------------------------

    rows_to_insert = []

    for article in results:

        row = {

            "source_country":
                SOURCE_COUNTRY,

            "title":
                article["title"],

            "source":
                article["source"],

            "published_at":
                article["published_at"],

            "countries":
                article["countries"],

            "environment_keywords":
                article[
                    "environment_keywords"
                ],

            "article_text":
                article["article_text"],

            "url":
                article["url"]
        }

        rows_to_insert.append(
            row
        )

    print()
    print(
        "======================================"
    )
    print(
        "SAVING TO SUPABASE"
    )
    print(
        "======================================"
    )
    print()

    print(
        f"{len(rows_to_insert)} new articles "
        "ready for insertion."
    )

    # --------------------------------------------------------
    # Insert in batches
    # --------------------------------------------------------

    batch_size = 100
    inserted_count = 0

    try:

        for start in range(
            0,
            len(rows_to_insert),
            batch_size
        ):

            batch = rows_to_insert[
                start:
                start + batch_size
            ]

            response = (
                supabase
                .table(RAW_TABLE)
                .insert(batch)
                .execute()
            )

            if response.data:

                inserted_count += len(
                    response.data
                )

            print(
                f"Inserted "
                f"{min(start + batch_size, len(rows_to_insert))}"
                f"/{len(rows_to_insert)}"
            )

    except Exception as e:

        print()
        print(
            "Error inserting articles "
            "into Supabase:"
        )

        print(e)

        raise

    return inserted_count


# ============================================================
# MAIN
# ============================================================

def main():

    print()
    print(
        "======================================"
    )
    print(
        "STRAITS TIMES ENVIRONMENT SCRAPER"
    )
    print(
        "======================================"
    )

    print(
        "Start date:",
        START_DATE.date()
    )

    print(
        "End date:",
        END_DATE.date()
    )

    print(
        "Source country:",
        SOURCE_COUNTRY
    )

    # ========================================================
    # STEP 0:
    # Retrieve URLs already stored in Supabase
    # ========================================================

    existing_urls = (
        get_existing_urls()
    )

    # ========================================================
    # STEP 1:
    # Discover historical article URLs
    # ========================================================

    article_list = (
        get_article_urls()
    )

    if len(article_list) == 0:

        print(
            "No articles discovered."
        )

        return

    # --------------------------------------------------------
    # Remove URLs that already exist in Supabase
    # BEFORE scraping the full article pages.
    # --------------------------------------------------------

    discovered_count = len(
        article_list
    )

    article_list = [

        article

        for article in article_list

        if article["url"]
        not in existing_urls
    ]

    already_existing = (
        discovered_count
        - len(article_list)
    )

    print()
    print(
        "======================================"
    )
    print(
        "NEW ARTICLE CHECK"
    )
    print(
        "======================================"
    )

    print(
        f"Discovered: "
        f"{discovered_count}"
    )

    print(
        f"Already in Supabase: "
        f"{already_existing}"
    )

    print(
        f"New URLs to scrape: "
        f"{len(article_list)}"
    )

    if len(article_list) == 0:

        print()
        print(
            "No new articles to process."
        )

        return

    # ========================================================
    # STEP 2:
    # Scrape content only for new URLs
    # ========================================================

    results = []

    print()
    print(
        "======================================"
    )
    print(
        "SCRAPING NEW ARTICLE CONTENT"
    )
    print(
        "======================================"
    )
    print()

    for number, article_info in enumerate(
        article_list,
        start=1
    ):

        print(
            f"[{number}/{len(article_list)}] "
            f"{article_info['title']}"
        )

        article = scrape_article(
            article_info
        )

        if article is None:

            time.sleep(1)

            continue

        # ----------------------------------------------------
        # Combine title and article text for matching
        # ----------------------------------------------------

        combined_text = (
            article["title"]
            + " "
            + article["article_text"]
        )

        # ----------------------------------------------------
        # Environment keyword matching
        # ----------------------------------------------------

        environment_matches = (
            find_environment_keywords(
                combined_text
            )
        )

        # ----------------------------------------------------
        # ASEAN country matching
        # ----------------------------------------------------

        country_matches = (
            find_countries(
                combined_text
            )
        )

        # ----------------------------------------------------
        # Keep article only if:
        #
        # 1. At least one environmental keyword is found
        # 2. At least one target ASEAN country is found
        # ----------------------------------------------------

        if (
            len(environment_matches) > 0
            and
            len(country_matches) > 0
        ):

            article[
                "environment_keywords"
            ] = ", ".join(
                environment_matches
            )

            article[
                "countries"
            ] = ", ".join(
                country_matches
            )

            results.append(
                article
            )

            print(
                "  MATCH"
            )

            print(
                "  Date:",
                article[
                    "published_at"
                ]
            )

            print(
                "  Countries:",
                ", ".join(
                    country_matches
                )
            )

            print(
                "  Environment:",
                ", ".join(
                    environment_matches
                )
            )

        else:

            print(
                "  No keyword match"
            )

        time.sleep(1)

    # ========================================================
    # STEP 3:
    # Save new matching articles to Supabase
    # ========================================================

    inserted_count = (
        insert_articles_to_supabase(
            results
        )
    )

    # ========================================================
    # FINAL SUMMARY
    # ========================================================

    print()
    print(
        "======================================"
    )
    print(
        "SCRAPING FINISHED"
    )
    print(
        "======================================"
    )

    print(
        f"URLs discovered: "
        f"{discovered_count}"
    )

    print(
        f"Already in Supabase: "
        f"{already_existing}"
    )

    print(
        f"New URLs checked: "
        f"{len(article_list)}"
    )

    print(
        f"New matching articles: "
        f"{len(results)}"
    )

    print(
        f"Articles inserted: "
        f"{inserted_count}"
    )

    print(
        "Supabase table:",
        RAW_TABLE
    )

    print()


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":
    main()