import requests
from bs4 import BeautifulSoup
import pandas as pd
import time
import re
import os

from datetime import datetime
from urllib.parse import urljoin, urlparse, urlunparse

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
SOURCE_COUNTRY = "Malaysia"


# ============================================================
# SETTINGS
# ============================================================

BASE_URL = "https://www.astroawani.com"


# ============================================================
# ENVIRONMENTAL TOPIC PAGES
# ============================================================
#
# Used only to discover potentially relevant articles.
# Articles must still pass the date, environmental keyword,
# and ASEAN country filters.
# ============================================================

TOPIC_SLUGS = [
    # General environment
    "alam-sekitar", "alam-sekitar-0", "jabatan-alam-sekitar",

    # Climate / sustainability
    "perubahan-iklim", "pemanasan-global", "krisis-iklim",
    "kelestarian",

    # Pollution
    "pencemaran", "pencemaran-alam-sekitar",
    "pencemaran-udara", "pencemaran-air",

    # Haze / air quality
    "jerebu", "jerebu-malaysia", "jerebu-di-sarawak",

    # Nature
    "biodiversiti", "pemuliharaan", "hidupan-liar", "ekosistem",

    # Forests / fires
    "kebakaran-hutan", "penebangan-hutan",

    # Waste
    "sisa", "sisa-plastik", "kitar-semula",

    # Energy
    "tenaga-boleh-diperbaharui", "tenaga-hijau",
    "tenaga-bersih", "tenaga-solar",

    # Carbon
    "karbon", "pelepasan-karbon",

    # Weather / hazards
    "banjir", "kemarau", "gelombang-haba", "cuaca-ekstrem",
    "cuaca", "panas",

    # Green development
    "kenderaan-elektrik", "bangunan-hijau", "kewangan-hijau",

    # Other environment-related topics
    "operasi-pembenihan-awan",
]


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
# ENVIRONMENT KEYWORDS
# ============================================================

ENVIRONMENT_KEYWORDS = [
    # General
    "alam sekitar", "alam sekeliling", "kelestarian",
    "kelestarian alam", "kelestarian alam sekitar",
    "sustainability", "sustainable", "environment", "environmental",

    # Climate
    "perubahan iklim", "krisis iklim", "pemanasan global",
    "tindakan iklim", "risiko iklim", "climate change",
    "global warming", "climate crisis", "climate action",

    # Carbon
    "pelepasan karbon", "karbon", "neutral karbon", "sifar bersih",
    "gas rumah hijau", "carbon emissions", "carbon emission",
    "carbon neutral", "net zero", "greenhouse gas", "greenhouse gases",

    # Energy
    "tenaga boleh diperbaharui", "tenaga bersih", "tenaga hijau",
    "tenaga solar", "tenaga angin", "hidrogen", "renewable energy",
    "clean energy", "green energy", "solar energy", "wind energy",

    # Pollution / haze
    "pencemaran", "pencemaran udara", "pencemaran air", "pencemar",
    "jerebu", "jerebu rentas sempadan", "kualiti udara", "ipu",
    "indeks pencemaran udara", "air quality", "air pollution",
    "pollution", "haze", "transboundary haze",

    # Fire / hotspots
    "kebakaran hutan", "kebakaran tanah", "pembakaran terbuka",
    "titik panas", "hotspot", "hotspots", "forest fire",
    "forest fires", "wildfire", "wildfires", "open burning",

    # Waste
    "sisa", "sisa plastik", "sisa makanan", "sisa elektronik",
    "e-waste", "kitar semula", "pengurusan sisa", "recycling",
    "waste management", "plastic waste", "food waste",

    # Nature
    "biodiversiti", "kepelbagaian biologi", "pemuliharaan",
    "ekosistem", "hidupan liar", "penebangan hutan",
    "biodiversity", "conservation", "ecosystem", "wildlife",
    "deforestation",

    # Weather / disasters
    "banjir", "banjir kilat", "kemarau", "hakisan pantai",
    "kenaikan paras laut", "cuaca ekstrem", "gelombang haba",
    "el nino", "el niño", "la nina", "la niña", "flood",
    "flooding", "drought", "sea level rise", "extreme weather",
    "heatwave",

    # Green development
    "bangunan hijau", "pengangkutan mampan", "kenderaan elektrik",
    "kewangan hijau", "green building", "sustainable transport",
    "electric vehicle", "electric vehicles", "green finance",
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
    "Malaysia": [
        "malaysia", "malaysian", "malaysians", "kuala lumpur",
        "putrajaya", "selangor", "johor", "sabah", "sarawak",
        "penang", "pulau pinang", "kelantan", "terengganu",
        "pahang", "perak", "kedah", "melaka", "malacca",
        "negeri sembilan", "kuching", "miri", "bintulu", "sibu",
        "serian", "samarahan", "sri aman", "sarikei", "mukah",
        "limbang",
    ],

    "Singapore": [
        "singapore", "singapura", "singaporean",
    ],

    "Indonesia": [
        "indonesia", "indonesian", "jakarta", "kalimantan",
        "sumatra", "sumatera", "jawa", "java", "kalimantan barat",
        "kalimantan tengah", "kalimantan selatan",
    ],

    "Philippines": [
        "philippines", "philippine", "filipino", "filipina", "manila",
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
# REQUEST SETTINGS
# ============================================================

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/151.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,"
        "application/xml;q=0.9,*/*;q=0.8"
    ),
}

SESSION = requests.Session()
SESSION.headers.update(HEADERS)


# ============================================================
# URL HELPERS
# ============================================================

def clean_url(url):
    parsed = urlparse(url)
    cleaned = parsed._replace(query="", fragment="")
    return urlunparse(cleaned).rstrip("/")


def is_article_url(url):
    parsed = urlparse(url)
    path = parsed.path.lower()

    excluded_parts = [
        "/topic/", "/video/", "/search", "/foto/",
        "/infografik/", "/rancangan/",
    ]

    for excluded in excluded_parts:
        if excluded in path:
            return False

    path_parts = [
        part
        for part in path.split("/")
        if part
    ]

    # Category: /berita-malaysia
    # Article:  /berita-malaysia/article-title
    if len(path_parts) < 2:
        return False

    if not path_parts[0].startswith("berita-"):
        return False

    return True


# ============================================================
# DATE HELPERS
# ============================================================

def parse_listing_date(text):
    if not text:
        return None

    match = re.search(
        r"\b(\d{2}/\d{2}/\d{4})\b",
        text,
    )

    if not match:
        return None

    try:
        return datetime.strptime(
            match.group(1),
            "%d/%m/%Y",
        )

    except ValueError:
        return None


def find_listing_date(link):
    # Check the link and progressively larger parent containers.
    candidates = [link]
    parent = link.parent
    levels = 0

    while parent is not None and levels < 6:
        candidates.append(parent)
        parent = parent.parent
        levels += 1

    for element in candidates:
        try:
            text = element.get_text(" ", strip=True)
        except Exception:
            continue

        listing_date = parse_listing_date(text)

        if listing_date is not None:
            return listing_date

    # Backup: inspect nearby siblings.
    parent = link.parent

    if parent is not None:
        for sibling in list(parent.previous_siblings)[:4]:
            try:
                if hasattr(sibling, "get_text"):
                    text = sibling.get_text(" ", strip=True)
                else:
                    text = str(sibling)

                listing_date = parse_listing_date(text)

                if listing_date:
                    return listing_date

            except Exception:
                pass

        for sibling in list(parent.next_siblings)[:4]:
            try:
                if hasattr(sibling, "get_text"):
                    text = sibling.get_text(" ", strip=True)
                else:
                    text = str(sibling)

                listing_date = parse_listing_date(text)

                if listing_date:
                    return listing_date

            except Exception:
                pass

    return None


# ============================================================
# EXTRACT DATE-FILTERED ARTICLE URLS
# ============================================================

def extract_candidate_urls_from_topic(html):
    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    candidates = {}

    article_links_found = 0
    links_with_date = 0
    in_range = 0

    for link in soup.find_all("a", href=True):
        href = link.get("href")

        if not href:
            continue

        full_url = clean_url(
            urljoin(BASE_URL, href)
        )

        if not full_url.startswith(BASE_URL):
            continue

        if not is_article_url(full_url):
            continue

        article_links_found += 1

        # Determine the date from the topic page before downloading
        # the full article.
        listing_date = find_listing_date(link)

        if listing_date is None:
            continue

        links_with_date += 1

        if not START_DATE <= listing_date <= END_DATE:
            continue

        in_range += 1

        # URL dictionary key automatically deduplicates candidates.
        candidates[full_url] = listing_date

    return (
        candidates,
        article_links_found,
        links_with_date,
        in_range,
    )


# ============================================================
# DISCOVER ARTICLES FROM TOPIC PAGES
# ============================================================

def discover_topic_articles():
    print()
    print("======================================")
    print("DISCOVERING MONTHLY CANDIDATES")
    print("======================================")

    all_candidates = {}
    successful_topics = 0

    for index, slug in enumerate(
        TOPIC_SLUGS,
        start=1,
    ):
        topic_url = f"{BASE_URL}/topic/{slug}"

        print()
        print(f"[{index}/{len(TOPIC_SLUGS)}] Topic: {slug}")

        try:
            response = SESSION.get(
                topic_url,
                timeout=20,
            )

            print("  Status:", response.status_code)

            if response.status_code != 200:
                print("  Topic unavailable - skipped")
                continue

            (
                candidates,
                total_links,
                links_with_date,
                in_range,
            ) = extract_candidate_urls_from_topic(
                response.text
            )

            print(f"  Article links visible: {total_links}")
            print(f"  Links with listing date: {links_with_date}")
            print(f"  Articles in requested month: {in_range}")

            if total_links > 0:
                successful_topics += 1

            before = len(all_candidates)
            all_candidates.update(candidates)
            added = len(all_candidates) - before

            print(f"  New unique monthly candidates: {added}")

            time.sleep(0.25)

        except Exception as e:
            print("  Error:", e)

    print()
    print("======================================")
    print("DISCOVERY COMPLETE")
    print("======================================")
    print("Working topic pages:", successful_topics)
    print(
        "Unique articles in requested month:",
        len(all_candidates),
    )

    return all_candidates


# ============================================================
# EXTRACT FULL ARTICLE DATE
# ============================================================

def extract_published_date(soup):
    # article:published_time
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

    # <time datetime="">
    time_tag = soup.find("time")

    if time_tag:
        datetime_value = time_tag.get("datetime")

        if datetime_value:
            try:
                dt = pd.to_datetime(datetime_value)

                return (
                    dt
                    .to_pydatetime()
                    .replace(tzinfo=None)
                )

            except Exception:
                pass

    # Text date.
    page_text = soup.get_text(
        " ",
        strip=True,
    )

    match = re.search(
        r"\b(\d{2}/\d{2}/\d{4})"
        r"\s*\|\s*"
        r"\d{1,2}:\d{2}"
        r"\s*MYT\b",
        page_text,
    )

    if match:
        try:
            return datetime.strptime(
                match.group(1),
                "%d/%m/%Y",
            )

        except Exception:
            pass

    match = re.search(
        r"\b(\d{2}/\d{2}/\d{4})\b",
        page_text,
    )

    if match:
        try:
            return datetime.strptime(
                match.group(1),
                "%d/%m/%Y",
            )

        except Exception:
            pass

    return None


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
        "dapatkan berita terkini", "newsletter", "advertisement",
        "hak cipta", "all rights reserved", "topic berkaitan",
        "must watch video", "astro awani network", "ikuti kami",
        "langgan",
    ]

    for p in paragraph_tags:
        text = p.get_text(" ", strip=True)

        if len(text) < 30:
            continue

        lower_text = text.lower()

        if any(
            phrase in lower_text
            for phrase in unwanted_phrases
        ):
            continue

        paragraphs.append(text)

    return " ".join(paragraphs)


# ============================================================
# SCRAPE FULL ARTICLE
# ============================================================

def scrape_article(url):
    try:
        response = SESSION.get(
            url,
            timeout=20,
        )

        if response.status_code != 200:
            print(
                "  HTTP error:",
                response.status_code,
            )
            return None

        soup = BeautifulSoup(
            response.text,
            "html.parser",
        )

        # ----------------------------------------------------
        # TITLE
        # ----------------------------------------------------

        h1 = soup.find("h1")

        if not h1:
            print("  No title found")
            return None

        title = h1.get_text(
            " ",
            strip=True,
        )

        # ----------------------------------------------------
        # DATE
        # ----------------------------------------------------

        published_date = extract_published_date(
            soup
        )

        if published_date is None:
            print("  No publication date found")
            return None

        # ----------------------------------------------------
        # TEXT
        # ----------------------------------------------------

        article_text = extract_article_text(
            soup
        )

        if len(article_text) < 250:
            print("  Too little usable article text")
            return None

        return {
            "title": title,
            "source": "Astro AWANI",
            "published_at": published_date,
            "url": clean_url(url),
            "article_text": article_text,
        }

    except Exception as e:
        print(
            "  Error scraping article:",
            e,
        )
        return None


# ============================================================
# ENVIRONMENT AND COUNTRY DETECTION
# ============================================================

def find_environment_keywords(text):
    text = text.lower()
    matches = []

    for keyword in ENVIRONMENT_KEYWORDS:
        pattern = (
            r"\b"
            + re.escape(keyword.lower())
            + r"\b"
        )

        if re.search(pattern, text):
            matches.append(keyword)

    return matches


def find_countries(text):
    text = text.lower()
    countries_found = []

    for country, keywords in COUNTRY_KEYWORDS.items():
        for keyword in keywords:
            pattern = (
                r"\b"
                + re.escape(keyword.lower())
                + r"\b"
            )

            if re.search(pattern, text):
                countries_found.append(country)
                break

    return countries_found


# ============================================================
# GET EXISTING URLS FROM SUPABASE
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
            "Astro AWANI URLs found."
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
# PROCESS MONTHLY CANDIDATES
# ============================================================

def process_candidates(
    candidates,
    existing_urls,
):
    results = []

    # Remove URLs already in Supabase before downloading them.
    new_candidates = {
        url: listing_date
        for url, listing_date in candidates.items()
        if url not in existing_urls
    }

    already_existing = (
        len(candidates)
        - len(new_candidates)
    )

    print()
    print("======================================")
    print("PROCESSING MONTHLY CANDIDATES")
    print("======================================")
    print("Monthly candidates discovered:", len(candidates))
    print("Already in Supabase:", already_existing)
    print(
        "Full articles that need downloading:",
        len(new_candidates),
    )

    no_environment = 0
    no_country = 0
    failed = 0
    date_mismatch = 0

    total = len(new_candidates)

    for index, (
        url,
        listing_date,
    ) in enumerate(
        new_candidates.items(),
        start=1,
    ):
        print()
        print(f"[{index}/{total}]")
        print(url)
        print(
            "  Listing date:",
            listing_date.date(),
        )

        article = scrape_article(url)

        if article is None:
            failed += 1
            time.sleep(0.3)
            continue

        published_date = article["published_at"]

        print(
            "  Verified article date:",
            published_date.date(),
        )

        # Verify the date again using the actual article.
        if not START_DATE <= published_date <= END_DATE:
            print(
                "  Listing/article date mismatch "
                "- skipped"
            )

            date_mismatch += 1
            time.sleep(0.3)
            continue

        combined_text = (
            article["title"]
            + " "
            + article["article_text"]
        )

        environment_matches = find_environment_keywords(
            combined_text
        )

        country_matches = find_countries(
            combined_text
        )

        # ----------------------------------------------------
        # ENVIRONMENT FILTER
        # ----------------------------------------------------

        if len(environment_matches) == 0:
            print(
                "  No environmental keyword match"
            )

            no_environment += 1
            time.sleep(0.3)
            continue

        # ----------------------------------------------------
        # COUNTRY FILTER
        # ----------------------------------------------------

        target_country_matches = [
            country
            for country in country_matches
            if country in TARGET_COUNTRIES
        ]

        if len(target_country_matches) == 0:
            print(
                "  No target ASEAN country match"
            )

            no_country += 1
            time.sleep(0.3)
            continue

        # ----------------------------------------------------
        # MATCH
        # ----------------------------------------------------

        article["published_at"] = (
            published_date.strftime("%Y-%m-%d")
        )

        article["environment_keywords"] = ", ".join(
            environment_matches
        )

        article["countries"] = ", ".join(
            target_country_matches
        )

        results.append(article)

        print("  MATCH")
        print(
            "  Countries:",
            ", ".join(target_country_matches),
        )
        print(
            "  Environment:",
            ", ".join(environment_matches),
        )

        time.sleep(0.3)

    print()
    print("======================================")
    print("PROCESSING SUMMARY")
    print("======================================")
    print("Monthly candidates:", len(candidates))
    print("Already in Supabase:", already_existing)
    print("Downloaded:", total)
    print("Failed to scrape:", failed)
    print("Date mismatches:", date_mismatch)
    print("No environment match:", no_environment)
    print("No ASEAN country match:", no_country)
    print("Final matches:", len(results))

    return results


# ============================================================
# INSERT INTO SUPABASE
# ============================================================

def insert_articles_to_supabase(results):
    if len(results) == 0:
        print()
        print("No matching new articles found.")
        return 0

    # Final in-memory URL deduplication.
    unique_results = {}

    for article in results:
        url = clean_url(
            article["url"]
        )

        article["url"] = url
        unique_results[url] = article

    results = list(
        unique_results.values()
    )

    rows_to_insert = []

    for article in results:
        rows_to_insert.append({
            "source_country": SOURCE_COUNTRY,
            "title": article["title"],
            "source": article["source"],
            "published_at": article["published_at"],
            "countries": article["countries"],
            "environment_keywords": article["environment_keywords"],
            "article_text": article["article_text"],
            "url": article["url"],
        })

    print()
    print("======================================")
    print("SAVING TO SUPABASE")
    print("======================================")
    print(
        f"{len(rows_to_insert)} new articles "
        "ready for insertion."
    )

    batch_size = 100
    inserted_count = 0

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
    print("ASTRO AWANI ASEAN ENVIRONMENT SCRAPER")
    print("======================================")
    print("Start date:", START_DATE.date())
    print("End date:", END_DATE.date())
    print("Source country:", SOURCE_COUNTRY)
    print("Topic pages checked:", len(TOPIC_SLUGS))
    print(
        "Target countries:",
        ", ".join(sorted(TARGET_COUNTRIES)),
    )

    # ========================================================
    # STEP 1: GET EXISTING SUPABASE URLS
    # ========================================================

    existing_urls = get_existing_urls()

    # ========================================================
    # STEP 2: DISCOVER MONTHLY ARTICLES
    # ========================================================

    candidates = discover_topic_articles()

    if len(candidates) == 0:
        print()
        print(
            "No articles in the requested date range "
            "were discovered from the topic pages."
        )
        return

    # ========================================================
    # STEP 3: DOWNLOAD AND FILTER NEW ARTICLES
    # ========================================================

    results = process_candidates(
        candidates,
        existing_urls,
    )

    # ========================================================
    # STEP 4: INSERT MATCHES
    # ========================================================

    inserted_count = insert_articles_to_supabase(
        results
    )

    # ========================================================
    # FINAL SUMMARY
    # ========================================================

    print()
    print("======================================")
    print("SCRAPING FINISHED")
    print("======================================")
    print(
        "Monthly candidate URLs discovered:",
        len(candidates),
    )
    print(
        "Matching new environmental articles:",
        len(results),
    )
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