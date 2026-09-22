import requests
from bs4 import BeautifulSoup
import pandas as pd
import time
import re
import os

from datetime import datetime
from urllib.parse import urlparse, urlunparse

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
SOURCE_COUNTRY = "Indonesia"


# ============================================================
# MONGABAY SETTINGS
# ============================================================

GRAPHQL_URL = "https://mongabay.co.id/graphql"
BASE_URL = "https://mongabay.co.id"


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

BATCH_SIZE = 24
MAX_BATCHES = 100


# ============================================================
# ENVIRONMENT KEYWORDS
# ============================================================
#
# Used as metadata only. Mongabay Indonesia is already an
# environmental publication, so these are not an inclusion
# requirement.
# ============================================================

ENVIRONMENT_KEYWORDS = [
    # General environment
    "lingkungan", "lingkungan hidup", "alam", "kelestarian",
    "berkelanjutan", "keberlanjutan",

    # Climate
    "perubahan iklim", "krisis iklim", "pemanasan global",
    "emisi", "emisi karbon", "karbon", "gas rumah kaca",
    "net zero", "nol emisi",

    # Forests
    "hutan", "deforestasi", "kebakaran hutan", "karhutla",
    "gambut", "restorasi hutan", "reboisasi",

    # Biodiversity / wildlife
    "keanekaragaman hayati", "biodiversitas", "konservasi",
    "satwa liar", "habitat", "spesies", "ekosistem",
    "orangutan", "harimau", "gajah", "mangrove",

    # Pollution
    "pencemaran", "polusi", "polusi udara", "polusi air",
    "kualitas udara", "limbah", "sampah", "plastik",
    "mikroplastik",

    # Energy
    "energi terbarukan", "energi bersih", "energi fosil",
    "batubara", "batu bara", "pltu", "tenaga surya",
    "panel surya", "biodiesel", "transisi energi",

    # Mining
    "tambang", "pertambangan", "nikel", "tambang emas",
    "mineral kritis",

    # Agriculture
    "sawit", "kelapa sawit", "perkebunan", "pertanian",
    "ketahanan pangan",

    # Oceans / coastal
    "laut", "pesisir", "terumbu karang", "perikanan",
    "nelayan", "abrasi",

    # Natural hazards / climate impacts
    "banjir", "kekeringan", "longsor", "gelombang panas",
    "cuaca ekstrem", "el nino", "el niño", "la nina", "la niña",
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
    "Indonesia": [
        "indonesia", "indonesian", "jakarta",
        "sumatera", "sumatra", "jawa", "java", "kalimantan",
        "sulawesi", "papua", "maluku", "bali",
        "aceh", "sumatera utara", "sumatera barat",
        "sumatera selatan", "riau", "kepulauan riau",
        "jambi", "bengkulu", "lampung", "bangka belitung",
        "banten", "jawa barat", "jawa tengah", "jawa timur",
        "yogyakarta", "kalimantan barat", "kalimantan tengah",
        "kalimantan selatan", "kalimantan timur",
        "kalimantan utara", "sulawesi utara", "gorontalo",
        "sulawesi tengah", "sulawesi barat", "sulawesi selatan",
        "sulawesi tenggara", "papua barat", "papua barat daya",
        "papua tengah", "papua selatan", "papua pegunungan",
        "nusa tenggara", "nusa tenggara barat",
        "nusa tenggara timur", "ntb", "ntt", "raja ampat",
        "ternate", "halmahera", "lombok", "flores",
    ],

    "Malaysia": [
        "malaysia", "malaysian", "kuala lumpur", "putrajaya",
        "selangor", "johor", "sabah", "sarawak", "penang",
        "pulau pinang", "kelantan", "terengganu", "pahang",
        "perak", "kedah", "melaka", "malacca",
        "negeri sembilan", "kuching", "miri", "bintulu", "sibu",
    ],

    "Singapore": [
        "singapore", "singapura", "singaporean",
    ],

    "Thailand": [
        "thailand", "thai", "bangkok",
    ],

    "Philippines": [
        "philippines", "philippine", "filipino", "filipina",
        "manila", "luzon", "mindanao", "visayas",
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
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/152.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json,text/plain,*/*",
    "Referer": "https://mongabay.co.id/",
}

ARTICLE_HEADERS = {
    "User-Agent": HEADERS["User-Agent"],
    "Accept": (
        "text/html,application/xhtml+xml,"
        "application/xml;q=0.9,*/*;q=0.8"
    ),
    "Referer": "https://mongabay.co.id/",
}

SESSION = requests.Session()


# ============================================================
# URL / GRAPHQL HELPERS
# ============================================================

def clean_url(url):
    if not url:
        return None

    parsed = urlparse(url)
    cleaned = parsed._replace(
        query="",
        fragment="",
    )

    return urlunparse(cleaned).rstrip("/")


def build_graphql_query(cursor=None):
    if cursor is None:
        after_value = "null"
    else:
        safe_cursor = (
            cursor
            .replace("\\", "\\\\")
            .replace('"', '\\"')
        )

        after_value = f'"{safe_cursor}"'

    query = f"""
    query {{
        contentNodes(
            where: {{
                status: PUBLISH,
                contentTypes: [POST, CUSTOM_STORY]
            }}
            first: {BATCH_SIZE}
            after: {after_value}
        ) {{
            pageInfo {{
                endCursor
                hasNextPage
                hasPreviousPage
                startCursor
                total
            }}

            edges {{
                node {{
                    ... on Post {{
                        __typename
                        title
                        link
                        date

                        byline {{
                            nodes {{
                                name
                            }}
                        }}
                    }}

                    ... on CustomStory {{
                        __typename
                        title
                        link
                        date

                        byline {{
                            nodes {{
                                name
                            }}
                        }}
                    }}
                }}
            }}
        }}
    }}
    """

    return query


def fetch_graphql_batch(cursor=None):
    query = build_graphql_query(cursor)

    try:
        response = SESSION.get(
            GRAPHQL_URL,
            params={"query": query},
            headers=HEADERS,
            timeout=30,
        )

        print("GraphQL status:", response.status_code)

        if response.status_code != 200:
            print(response.text[:500])
            return None

        data = response.json()

        if "errors" in data:
            print("GraphQL errors:")
            print(data["errors"])
            return None

        content_nodes = (
            data
            .get("data", {})
            .get("contentNodes")
        )

        if not content_nodes:
            return None

        return content_nodes

    except Exception as e:
        print("GraphQL request error:", e)
        return None


def parse_graphql_date(date_value):
    if not date_value:
        return None

    try:
        dt = pd.to_datetime(date_value)
        return dt.to_pydatetime().replace(tzinfo=None)

    except Exception:
        return None


# ============================================================
# METADATA DETECTION
# ============================================================

def find_environment_keywords(text):
    if not text:
        return []

    text = text.lower()
    matches = []

    for keyword in ENVIRONMENT_KEYWORDS:
        pattern = r"\b" + re.escape(keyword.lower()) + r"\b"

        if re.search(pattern, text):
            matches.append(keyword)

    return matches


def find_countries(text):
    if not text:
        return []

    text = text.lower()
    countries_found = []

    for country, keywords in COUNTRY_KEYWORDS.items():
        for keyword in keywords:
            pattern = r"\b" + re.escape(keyword.lower()) + r"\b"

            if re.search(pattern, text):
                countries_found.append(country)
                break

    return countries_found


# ============================================================
# ARTICLE SCRAPING
# ============================================================

def extract_article_text(soup):
    paragraphs = []

    article_container = soup.find("article")

    if article_container:
        paragraph_tags = article_container.find_all("p")
    else:
        paragraph_tags = soup.find_all("p")

    unwanted_phrases = [
        "mongabay indonesia", "ikuti mongabay", "newsletter",
        "donasi", "copyright", "hak cipta", "artikel terkait",
        "baca juga", "featured image", "foto utama", "subscribe",
        "bagikan artikel ini",
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


def scrape_article(url):
    try:
        response = SESSION.get(
            url,
            headers=ARTICLE_HEADERS,
            timeout=30,
        )

        if response.status_code != 200:
            print(
                "  Article status:",
                response.status_code,
            )
            return None

        soup = BeautifulSoup(
            response.text,
            "html.parser",
        )

        article_text = extract_article_text(soup)

        if len(article_text) < 250:
            print("  Too little usable article text.")
            return None

        return article_text

    except Exception as e:
        print("  Article request error:", e)
        return None


# ============================================================
# SUPABASE HELPERS
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
            "Mongabay Indonesia URLs found."
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
# PROCESS GRAPHQL NODES
# ============================================================

def process_nodes(
    edges,
    existing_urls,
    seen_urls,
    results,
    stats,
):
    batch_dates = []

    for edge in edges:
        node = edge.get("node")

        if not node:
            continue

        url = clean_url(
            node.get("link")
        )

        title = node.get("title")
        date_value = node.get("date")
        typename = node.get("__typename")

        if not url:
            continue

        # ----------------------------------------------------
        # DUPLICATE DURING THIS RUN
        # ----------------------------------------------------

        if url in seen_urls:
            continue

        seen_urls.add(url)

        # ----------------------------------------------------
        # DATE FROM GRAPHQL
        # ----------------------------------------------------

        article_date = parse_graphql_date(
            date_value
        )

        if article_date is None:
            stats["no_date"] += 1

            print()
            print(
                "No valid date:",
                title,
            )

            continue

        batch_dates.append(article_date)

        print()
        print(title)
        print(
            "  Date:",
            article_date.date(),
        )
        print(
            "  Type:",
            typename,
        )

        # ----------------------------------------------------
        # DATE FILTER
        # ----------------------------------------------------

        if article_date > END_DATE:
            stats["too_new"] += 1
            print("  Newer than END_DATE - skipped")
            continue

        if article_date < START_DATE:
            stats["too_old"] += 1
            print("  Older than START_DATE - skipped")
            continue

        # ----------------------------------------------------
        # ALREADY IN SUPABASE
        # ----------------------------------------------------

        if url in existing_urls:
            stats["already_exists"] += 1
            print("  Already in Supabase - skipped")
            continue

        # ----------------------------------------------------
        # SCRAPE FULL ARTICLE
        # ----------------------------------------------------

        print("  Scraping full article...")

        article_text = scrape_article(url)

        if article_text is None:
            stats["failed"] += 1
            continue

        stats["scraped"] += 1

        # ----------------------------------------------------
        # METADATA DETECTION
        # ----------------------------------------------------

        combined_text = (title or "") + " " + article_text

        environment_matches = find_environment_keywords(
            combined_text
        )

        country_matches = find_countries(
            combined_text
        )

        # Mongabay Indonesia is an Indonesia-focused publication.
        # Default to Indonesia if no explicit target country is found.
        if len(country_matches) == 0:
            country_matches = ["Indonesia"]

        # ----------------------------------------------------
        # AUTHORS
        # ----------------------------------------------------

        author_names = []
        byline = node.get("byline")

        if byline:
            for author in byline.get("nodes", []):
                name = author.get("name")

                if (
                    name
                    and name not in author_names
                ):
                    author_names.append(name)

        # ----------------------------------------------------
        # PREPARE RAW ARTICLE
        # ----------------------------------------------------

        results.append({
            "source_country": SOURCE_COUNTRY,
            "title": title or "",
            "source": "Mongabay Indonesia",
            "published_at": article_date.strftime(
                "%Y-%m-%d"
            ),
            "countries": ", ".join(
                country_matches
            ),
            "environment_keywords": ", ".join(
                environment_matches
            ),
            "article_text": article_text,
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
        print(
            "  Authors:",
            ", ".join(author_names)
            if author_names
            else "None detected",
        )

        time.sleep(0.4)

    # --------------------------------------------------------
    # OLDEST DATE IN THIS GRAPHQL BATCH
    # --------------------------------------------------------

    if len(batch_dates) == 0:
        return None

    return min(batch_dates)


# ============================================================
# INSERT RESULTS INTO SUPABASE
# ============================================================

def insert_articles_to_supabase(results):
    if len(results) == 0:
        print()
        print("No new articles to insert.")
        return 0

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
    print("MONGABAY INDONESIA ENVIRONMENT SCRAPER")
    print("======================================")
    print("Start date:", START_DATE.date())
    print("End date:", END_DATE.date())
    print("Source country:", SOURCE_COUNTRY)
    print("Batch size:", BATCH_SIZE)
    print(
        "Target countries:",
        ", ".join(
            sorted(TARGET_COUNTRIES)
        ),
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
        "graphql_nodes": 0,
        "too_new": 0,
        "too_old": 0,
        "no_date": 0,
        "already_exists": 0,
        "scraped": 0,
        "failed": 0,
        "saved": 0,
    }

    cursor = None
    batch_number = 1

    # ========================================================
    # STEP 3: GRAPHQL PAGINATION
    # ========================================================

    while batch_number <= MAX_BATCHES:
        print()
        print("======================================")
        print(f"GRAPHQL BATCH {batch_number}")
        print("======================================")

        content_nodes = fetch_graphql_batch(
            cursor
        )

        if content_nodes is None:
            print("No GraphQL data returned.")
            break

        edges = content_nodes.get(
            "edges",
            [],
        )

        page_info = content_nodes.get(
            "pageInfo",
            {},
        )

        if len(edges) == 0:
            print("No articles returned.")
            break

        stats["graphql_nodes"] += len(edges)

        print(
            "Articles returned:",
            len(edges),
        )
        print(
            "Has next page:",
            page_info.get("hasNextPage"),
        )
        print(
            "End cursor:",
            page_info.get("endCursor"),
        )

        # ----------------------------------------------------
        # PROCESS CURRENT BATCH
        # ----------------------------------------------------

        oldest_date = process_nodes(
            edges,
            existing_urls,
            seen_urls,
            results,
            stats,
        )

        print()
        print(
            "Oldest date in batch:",
            oldest_date.date()
            if oldest_date
            else "Unknown",
        )

        # ====================================================
        # STOP CONDITION 1
        # ====================================================

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

        # ====================================================
        # STOP CONDITION 2
        # ====================================================

        has_next_page = page_info.get(
            "hasNextPage",
            False,
        )

        if not has_next_page:
            print()
            print("GraphQL reports no next page.")
            break

        # ====================================================
        # NEXT CURSOR
        # ====================================================

        new_cursor = page_info.get(
            "endCursor"
        )

        if not new_cursor:
            print("No endCursor returned.")
            break

        if new_cursor == cursor:
            print("Cursor did not change.")
            print(
                "Stopping to prevent "
                "infinite loop."
            )
            break

        cursor = new_cursor
        batch_number += 1

        time.sleep(0.5)

    # ========================================================
    # STEP 4: SUMMARY BEFORE INSERT
    # ========================================================

    print()
    print("======================================")
    print("SCRAPING SUMMARY")
    print("======================================")
    print(
        "GraphQL batches processed:",
        batch_number,
    )
    print(
        "GraphQL articles encountered:",
        stats["graphql_nodes"],
    )
    print(
        "Unique URLs encountered:",
        len(seen_urls),
    )
    print(
        "Newer than END_DATE:",
        stats["too_new"],
    )
    print(
        "Older than START_DATE:",
        stats["too_old"],
    )
    print(
        "No valid date:",
        stats["no_date"],
    )
    print(
        "Already in Supabase:",
        stats["already_exists"],
    )
    print(
        "Full articles scraped:",
        stats["scraped"],
    )
    print(
        "Failed article scrapes:",
        stats["failed"],
    )
    print(
        "New articles ready:",
        stats["saved"],
    )

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
    print(
        "New articles found:",
        len(results),
    )
    print(
        "New articles inserted into Supabase:",
        inserted_count,
    )
    print(
        "Supabase table:",
        RAW_TABLE,
    )
    print()


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":
    main()