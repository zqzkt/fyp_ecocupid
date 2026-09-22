import requests
from bs4 import BeautifulSoup
import pandas as pd
import time
import re
import os

from datetime import datetime
from urllib.parse import urlparse, urlunparse, urljoin

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
    SUPABASE_KEY,
)

RAW_TABLE = "news_raw"
SOURCE_COUNTRY = "Philippines"


# ============================================================
# MONGABAY SETTINGS
# ============================================================

BASE_URL = "https://news.mongabay.com"
PHILIPPINES_ARCHIVE_URL = "https://news.mongabay.com/list/philippines/"
SOURCE_NAME = "Mongabay"


# ============================================================
# DATE RANGE
# ============================================================

START_DATE = datetime.strptime(
    os.getenv("NEWS_START_DATE", "2026-08-01"),
    "%Y-%m-%d",
)

END_DATE = datetime.strptime(
    os.getenv("NEWS_END_DATE", "2026-08-31"),
    "%Y-%m-%d",
)


# ============================================================
# PAGINATION SETTINGS
# ============================================================

# Safety limit. Pagination normally stops earlier once
# articles older than START_DATE are reached.
MAX_PAGES = 50


# ============================================================
# ENVIRONMENT KEYWORDS
# ============================================================
#
# These are metadata only.
# Mongabay is already an environmental publication, so an
# article is NOT required to contain one of these keywords.
# ============================================================

ENVIRONMENT_KEYWORDS = [
    # General
    "environment", "environmental", "sustainability",
    "sustainable", "nature",

    # Climate
    "climate", "climate change", "climate crisis", "global warming",
    "carbon", "carbon emissions", "emissions", "greenhouse gas",
    "greenhouse gases", "net zero",

    # Forest
    "forest", "forests", "deforestation", "reforestation",
    "rainforest", "rainforests", "forest fire", "wildfire",
    "wildfires", "peatland", "peatlands",

    # Biodiversity
    "biodiversity", "conservation", "wildlife", "endangered",
    "endangered species", "habitat", "habitats", "ecosystem",
    "ecosystems", "species", "protected area", "protected areas",

    # Pollution
    "pollution", "air pollution", "water pollution",
    "plastic pollution", "marine pollution", "oil spill",
    "sewage", "wastewater", "air quality",

    # Waste
    "waste", "solid waste", "plastic waste", "garbage",
    "recycling", "landfill", "waste management", "circular economy",

    # Energy
    "renewable energy", "clean energy", "solar", "solar energy",
    "wind energy", "hydropower", "geothermal", "fossil fuel",
    "coal", "energy transition",

    # Mining
    "mining", "nickel", "critical minerals", "mineral extraction",

    # Ocean / coast
    "ocean", "marine", "coastal", "coast", "coral", "coral reef",
    "coral reefs", "mangrove", "mangroves", "fisheries", "fishing",

    # Climate impacts / hazards
    "flood", "flooding", "drought", "landslide", "landslides",
    "heatwave", "heat wave", "extreme heat", "extreme weather",
    "typhoon", "tropical cyclone", "storm surge", "sea level rise",
    "el nino", "el niño", "la nina", "la niña",
]


# ============================================================
# TARGET ASEAN COUNTRIES
# ============================================================

TARGET_COUNTRIES = {
    "Malaysia", "Singapore", "Indonesia",
    "Thailand", "Philippines", "Brunei",
}


# ============================================================
# COUNTRY KEYWORDS
# ============================================================

COUNTRY_KEYWORDS = {
    "Philippines": [
        "philippines", "philippine", "filipino", "filipina",
        "metro manila", "manila", "luzon", "visayas", "mindanao",
        "cebu", "bohol", "iloilo", "leyte", "samar", "davao",
        "palawan", "cavite", "laguna", "batangas", "rizal",
        "bulacan", "pampanga", "pangasinan", "negros", "panay",
        "mindoro", "sierra madre", "manila bay", "laguna de bay",
        "pasig river", "denr", "pagasa",
    ],

    "Indonesia": [
        "indonesia", "indonesian", "jakarta", "sumatra", "sumatera",
        "java", "jawa", "kalimantan", "sulawesi", "papua", "bali",
        "raja ampat",
    ],

    "Malaysia": [
        "malaysia", "malaysian", "kuala lumpur", "putrajaya",
        "selangor", "johor", "sabah", "sarawak", "penang",
        "pulau pinang", "pahang", "kelantan", "terengganu",
        "perak", "kedah", "melaka", "kuching",
    ],

    "Singapore": [
        "singapore", "singaporean",
    ],

    "Thailand": [
        "thailand", "thai", "bangkok",
    ],

    "Brunei": [
        "brunei", "brunei darussalam", "bruneian",
        "bandar seri begawan",
    ],
}


# ============================================================
# REQUEST HEADERS
# ============================================================

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/152.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,"
        "application/xml;q=0.9,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://news.mongabay.com/",
}

SESSION = requests.Session()
SESSION.headers.update(HEADERS)


# ============================================================
# CLEAN URL
# ============================================================

def clean_url(url):
    if not url:
        return None

    url = urljoin(BASE_URL, url)
    parsed = urlparse(url)
    cleaned = parsed._replace(query="", fragment="")

    return urlunparse(cleaned).rstrip("/")


# ============================================================
# FIND ENVIRONMENT KEYWORDS
# ============================================================

def find_environment_keywords(text):
    if not text:
        return []

    text = text.lower()
    matches = []

    for keyword in ENVIRONMENT_KEYWORDS:
        pattern = (
            r"(?<!\w)"
            + re.escape(keyword.lower())
            + r"(?!\w)"
        )

        if re.search(pattern, text):
            matches.append(keyword)

    return list(dict.fromkeys(matches))


# ============================================================
# FIND ASEAN COUNTRIES
# ============================================================

def find_countries(text):
    if not text:
        return []

    text = text.lower()
    countries_found = []

    for country, keywords in COUNTRY_KEYWORDS.items():
        for keyword in keywords:
            pattern = (
                r"(?<!\w)"
                + re.escape(keyword.lower())
                + r"(?!\w)"
            )

            if re.search(pattern, text):
                countries_found.append(country)
                break

    return countries_found


# ============================================================
# GET EXISTING MONGABAY PHILIPPINES URLS FROM SUPABASE
# ============================================================

def get_existing_urls():
    print()
    print("======================================")
    print("CHECKING EXISTING ARTICLES IN SUPABASE")
    print("======================================")

    existing_urls = set()
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
                    SOURCE_COUNTRY,
                )
                .range(
                    start,
                    start + batch_size - 1,
                )
                .execute()
            )

            rows = response.data or []

            for row in rows:
                url = row.get("url")

                if url:
                    existing_urls.add(
                        clean_url(url)
                    )

            if len(rows) < batch_size:
                break

            start += batch_size

        print(
            f"{len(existing_urls)} existing "
            "Philippines URLs found."
        )

        return existing_urls

    except Exception as e:
        print(
            "Error reading existing URLs "
            "from Supabase:"
        )
        print(e)
        raise


# ============================================================
# BUILD ARCHIVE PAGE URL
# ============================================================

def build_archive_url(page_number):
    if page_number == 1:
        return PHILIPPINES_ARCHIVE_URL

    return (
        PHILIPPINES_ARCHIVE_URL
        + f"page/{page_number}/"
    )


# ============================================================
# CHECK WHETHER URL LOOKS LIKE A MONGABAY ARTICLE
# ============================================================

def is_article_url(url):
    if not url:
        return False

    url = clean_url(url)
    parsed = urlparse(url)

    domain = (
        parsed.netloc
        .lower()
        .replace("www.", "")
    )

    if domain != "news.mongabay.com":
        return False

    # Mongabay article URLs use /YYYY/MM/...
    if not re.search(
        r"/20\d{2}/\d{2}/",
        parsed.path,
    ):
        return False

    return True


# ============================================================
# EXTRACT ARTICLE URLS FROM ARCHIVE
# ============================================================

def extract_archive_articles(html):
    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    articles = []
    seen_urls = set()

    # Do not rely on <article> tags. Instead, retain links
    # matching Mongabay's /YYYY/MM/... article URL structure.
    for link in soup.find_all("a", href=True):
        href = link.get("href")
        url = clean_url(href)

        if not is_article_url(url):
            continue

        if url in seen_urls:
            continue

        seen_urls.add(url)

        link_text = link.get_text(
            " ",
            strip=True,
        )

        articles.append({
            "url": url,
            "archive_title": link_text,
        })

    return articles


# ============================================================
# FETCH ARCHIVE PAGE
# ============================================================

def fetch_archive_page(page_number):
    url = build_archive_url(page_number)

    print()
    print("Archive URL:", url)

    try:
        response = SESSION.get(
            url,
            timeout=30,
        )

        print(
            "Archive status:",
            response.status_code,
        )
        print(
            "Archive HTML length:",
            len(response.text),
        )

        if response.status_code != 200:
            print(response.text[:500])
            return []

        articles = extract_archive_articles(
            response.text
        )

        print(
            "Article URLs found:",
            len(articles),
        )

        if articles:
            print(
                "First article URL:",
                articles[0]["url"],
            )
            print(
                "Last article URL:",
                articles[-1]["url"],
            )

        return articles

    except Exception as e:
        print(
            "Archive request error:",
            e,
        )
        return []


# ============================================================
# PARSE ARTICLE DATE FROM URL
# ============================================================

def parse_date_from_url(url):
    if not url:
        return None

    match = re.search(
        r"/(20\d{2})/(\d{2})/",
        url,
    )

    if not match:
        return None

    try:
        year = int(match.group(1))
        month = int(match.group(2))

        # URL gives only year/month, so this is used only
        # for early month-level filtering.
        return year, month

    except Exception:
        return None


# ============================================================
# PARSE ARTICLE DATE
# ============================================================

def parse_article_date(soup, url):
    # --------------------------------------------------------
    # 1. article:published_time
    # --------------------------------------------------------

    meta = soup.find(
        "meta",
        attrs={"property": "article:published_time"},
    )

    if meta and meta.get("content"):
        try:
            dt = pd.to_datetime(meta["content"])

            return (
                dt
                .to_pydatetime()
                .replace(tzinfo=None)
            )

        except Exception:
            pass

    # --------------------------------------------------------
    # 2. datePublished metadata
    # --------------------------------------------------------

    meta = soup.find(
        "meta",
        attrs={"itemprop": "datePublished"},
    )

    if meta and meta.get("content"):
        try:
            dt = pd.to_datetime(meta["content"])

            return (
                dt
                .to_pydatetime()
                .replace(tzinfo=None)
            )

        except Exception:
            pass

    # --------------------------------------------------------
    # 3. JSON-LD
    # --------------------------------------------------------

    scripts = soup.find_all(
        "script",
        attrs={"type": "application/ld+json"},
    )

    for script in scripts:
        text = (
            script.string
            or script.get_text()
            or ""
        )

        match = re.search(
            r'"datePublished"\s*:\s*"([^"]+)"',
            text,
        )

        if match:
            try:
                dt = pd.to_datetime(
                    match.group(1)
                )

                return (
                    dt
                    .to_pydatetime()
                    .replace(tzinfo=None)
                )

            except Exception:
                pass

    # --------------------------------------------------------
    # 4. Visible <time> element
    # --------------------------------------------------------

    for tag in soup.find_all("time"):
        value = (
            tag.get("datetime")
            or tag.get_text(" ", strip=True)
        )

        if not value:
            continue

        try:
            dt = pd.to_datetime(value)

            return (
                dt
                .to_pydatetime()
                .replace(tzinfo=None)
            )

        except Exception:
            continue

    print(
        "  Could not determine exact "
        "publication date:",
        url,
    )

    return None


# ============================================================
# EXTRACT TITLE
# ============================================================

def extract_title(soup):
    meta = soup.find(
        "meta",
        attrs={"property": "og:title"},
    )

    if meta and meta.get("content"):
        return meta["content"].strip()

    h1 = soup.find("h1")

    if h1:
        return h1.get_text(
            " ",
            strip=True,
        )

    return ""


# ============================================================
# EXTRACT ARTICLE TEXT
# ============================================================

def extract_article_text(soup):
    paragraphs = []

    article_container = soup.find("article")

    if article_container:
        paragraph_tags = article_container.find_all("p")
    else:
        paragraph_tags = soup.find_all("p")

    unwanted_phrases = [
        "subscribe", "newsletter", "copyright", "all rights reserved",
        "related articles", "related article", "read more",
        "featured image", "share this article", "mongabay is a",
        "mongabay's journalism", "republish this article",
    ]

    for p in paragraph_tags:
        text = p.get_text(
            " ",
            strip=True,
        )

        text = re.sub(
            r"\s+",
            " ",
            text,
        ).strip()

        if len(text) < 30:
            continue

        lower_text = text.lower()

        if any(
            phrase in lower_text
            for phrase in unwanted_phrases
        ):
            continue

        paragraphs.append(text)

    # Remove duplicate paragraphs.
    unique_paragraphs = []
    seen_paragraphs = set()

    for paragraph in paragraphs:
        normalized = re.sub(
            r"\s+",
            " ",
            paragraph,
        ).strip()

        if normalized in seen_paragraphs:
            continue

        seen_paragraphs.add(normalized)
        unique_paragraphs.append(normalized)

    return " ".join(unique_paragraphs)


# ============================================================
# SCRAPE FULL ARTICLE
# ============================================================

def scrape_article(url):
    try:
        response = SESSION.get(
            url,
            timeout=30,
        )

        print(
            "  Article status:",
            response.status_code,
        )

        if response.status_code != 200:
            return None

        soup = BeautifulSoup(
            response.text,
            "html.parser",
        )

        title = extract_title(soup)

        article_date = parse_article_date(
            soup,
            url,
        )

        article_text = extract_article_text(
            soup
        )

        print(
            "  Extracted text length:",
            len(article_text),
        )

        if len(article_text) < 250:
            print(
                "  Too little usable article text."
            )
            return None

        return {
            "title": title,
            "published_at": article_date,
            "article_text": article_text,
        }

    except Exception as e:
        print(
            "  Article request error:",
            e,
        )
        return None


# ============================================================
# PROCESS ARCHIVE ARTICLES
# ============================================================

def process_archive_articles(
    archive_articles,
    existing_urls,
    seen_urls,
    results,
    stats,
):
    page_dates = []

    for item in archive_articles:
        url = clean_url(
            item.get("url")
        )

        archive_title = (
            item.get("archive_title")
            or ""
        )

        if not url:
            continue

        # ----------------------------------------------------
        # DUPLICATE DURING CURRENT RUN
        # ----------------------------------------------------

        if url in seen_urls:
            continue

        seen_urls.add(url)
        stats["archive_urls"] += 1

        print()
        print(
            archive_title
            if archive_title
            else url
        )
        print("  URL:", url)

        # ----------------------------------------------------
        # EARLY MONTH FILTER USING URL
        # ----------------------------------------------------

        url_date = parse_date_from_url(url)

        if url_date:
            url_year, url_month = url_date

            start_month = (
                START_DATE.year,
                START_DATE.month,
            )

            end_month = (
                END_DATE.year,
                END_DATE.month,
            )

            article_month = (
                url_year,
                url_month,
            )

            if article_month > end_month:
                stats["too_new"] += 1

                print(
                    "  Newer than END_DATE month - skipped"
                )
                continue

            if article_month < start_month:
                stats["too_old"] += 1

                print(
                    "  Older than START_DATE month - skipped"
                )

                # Allows archive pagination to determine that
                # it has reached articles older than START_DATE.
                page_dates.append(
                    datetime(
                        url_year,
                        url_month,
                        1,
                    )
                )
                continue

        # ----------------------------------------------------
        # ALREADY IN SUPABASE
        # ----------------------------------------------------

        if url in existing_urls:
            stats["already_exists"] += 1

            print(
                "  Already in Supabase - skipped"
            )
            continue

        # ----------------------------------------------------
        # SCRAPE FULL ARTICLE
        # ----------------------------------------------------

        print("  Scraping full article...")

        article = scrape_article(url)

        if article is None:
            stats["failed"] += 1
            continue

        stats["scraped"] += 1

        article_date = article["published_at"]

        if article_date is None:
            stats["no_date"] += 1

            print(
                "  No valid publication date - skipped"
            )
            continue

        page_dates.append(article_date)

        print(
            "  Date:",
            article_date.date(),
        )

        # ----------------------------------------------------
        # EXACT DATE FILTER
        # ----------------------------------------------------

        if article_date > END_DATE:
            stats["too_new"] += 1

            print(
                "  Newer than END_DATE - skipped"
            )
            continue

        if article_date < START_DATE:
            stats["too_old"] += 1

            print(
                "  Older than START_DATE - skipped"
            )
            continue

        # ----------------------------------------------------
        # COMBINE TITLE + TEXT
        # ----------------------------------------------------

        combined_text = (
            (
                article["title"]
                or archive_title
                or ""
            )
            + " "
            + article["article_text"]
        )

        # ----------------------------------------------------
        # ENVIRONMENT KEYWORDS
        # Metadata only.
        # ----------------------------------------------------

        environment_matches = find_environment_keywords(
            combined_text
        )

        # ----------------------------------------------------
        # COUNTRY DETECTION
        # ----------------------------------------------------

        country_matches = find_countries(
            combined_text
        )

        # ----------------------------------------------------
        # REQUIRE PHILIPPINES
        # ----------------------------------------------------
        #
        # Archive is tagged Philippines, but Philippine
        # relevance is still verified from the article text.
        # ----------------------------------------------------

        if "Philippines" not in country_matches:
            stats["not_philippines"] += 1

            print(
                "  Philippines not detected "
                "in article text - skipped"
            )
            continue

        # ----------------------------------------------------
        # PREPARE RAW ARTICLE
        # ----------------------------------------------------

        results.append({
            "source_country": SOURCE_COUNTRY,
            "title": (
                article["title"]
                or archive_title
            ),
            "source": SOURCE_NAME,
            "published_at": article_date.strftime("%Y-%m-%d"),
            "countries": ", ".join(country_matches),
            "environment_keywords": ", ".join(environment_matches),
            "article_text": article["article_text"],
            "url": url,
        })

        stats["saved"] += 1

        print("  MATCH")
        print(
            "  Countries:",
            ", ".join(country_matches),
        )
        print(
            "  Environment keywords:",
            ", ".join(environment_matches)
            if environment_matches
            else "None detected",
        )

        time.sleep(0.5)

    if not page_dates:
        return None

    return min(page_dates)


# ============================================================
# INSERT RESULTS INTO SUPABASE
# ============================================================

def insert_articles_to_supabase(results):
    if len(results) == 0:
        print()
        print("No new articles to insert.")
        return 0

    # Final in-memory URL deduplication.
    unique_results = {}

    for article in results:
        url = clean_url(
            article["url"]
        )

        article["url"] = url
        unique_results[url] = article

    rows_to_insert = list(
        unique_results.values()
    )

    print()
    print("======================================")
    print("SAVING TO SUPABASE")
    print("======================================")
    print(
        f"{len(rows_to_insert)} new articles "
        "ready for insertion."
    )

    inserted_count = 0
    batch_size = 100

    try:
        for start in range(
            0,
            len(rows_to_insert),
            batch_size,
        ):
            batch = rows_to_insert[
                start:start + batch_size
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
            else:
                inserted_count += len(batch)

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
    print("======================================")
    print("MONGABAY PHILIPPINES ENVIRONMENT SCRAPER")
    print("======================================")
    print("Start date:", START_DATE.date())
    print("End date:", END_DATE.date())
    print("Source country:", SOURCE_COUNTRY)
    print("Archive:", PHILIPPINES_ARCHIVE_URL)
    print(
        "Target countries:",
        ", ".join(sorted(TARGET_COUNTRIES)),
    )

    # ========================================================
    # STEP 1: EXISTING SUPABASE DATA
    # ========================================================

    existing_urls = get_existing_urls()

    # ========================================================
    # STEP 2: TRACKING
    # ========================================================

    seen_urls = set()
    results = []

    stats = {
        "archive_pages": 0,
        "archive_urls": 0,
        "too_new": 0,
        "too_old": 0,
        "no_date": 0,
        "already_exists": 0,
        "scraped": 0,
        "failed": 0,
        "not_philippines": 0,
        "saved": 0,
    }

    # ========================================================
    # STEP 3: ARCHIVE PAGINATION
    # ========================================================

    for page_number in range(
        1,
        MAX_PAGES + 1,
    ):
        print()
        print("======================================")
        print(f"ARCHIVE PAGE {page_number}")
        print("======================================")

        archive_articles = fetch_archive_page(
            page_number
        )

        stats["archive_pages"] += 1

        if not archive_articles:
            print("No article URLs returned.")
            break

        oldest_date = process_archive_articles(
            archive_articles,
            existing_urls,
            seen_urls,
            results,
            stats,
        )

        print()
        print(
            "Oldest date detected on page:",
            oldest_date.date()
            if oldest_date
            else "Unknown",
        )

        # Mongabay archive is newest -> oldest.
        # Stop once the archive reaches articles before START_DATE.
        if (
            oldest_date is not None
            and oldest_date < START_DATE
        ):
            print()
            print(
                "Reached articles older "
                "than START_DATE."
            )
            print("Stopping pagination.")
            break

        time.sleep(1)

    # ========================================================
    # STEP 4: SUMMARY BEFORE INSERT
    # ========================================================

    print()
    print("======================================")
    print("SCRAPING SUMMARY")
    print("======================================")
    print("Archive pages processed:", stats["archive_pages"])
    print("Unique article URLs encountered:", stats["archive_urls"])
    print("Newer than END_DATE:", stats["too_new"])
    print("Older than START_DATE:", stats["too_old"])
    print("No valid date:", stats["no_date"])
    print("Already in Supabase:", stats["already_exists"])
    print("Full articles scraped:", stats["scraped"])
    print("Failed article scrapes:", stats["failed"])
    print("Not Philippines-related:", stats["not_philippines"])
    print("New articles ready:", stats["saved"])

    # ========================================================
    # STEP 5: INSERT INTO SUPABASE
    # ========================================================

    inserted_count = insert_articles_to_supabase(
        results
    )

    # ========================================================
    # FINAL SUMMARY
    # ========================================================

    print()
    print("======================================")
    print("FINISHED")
    print("======================================")
    print("New articles found:", len(results))
    print(
        "New articles inserted into Supabase:",
        inserted_count,
    )
    print("Supabase table:", RAW_TABLE)
    print()


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":
    main()