import requests
from bs4 import BeautifulSoup
import pandas as pd
import time
import re
import os

from datetime import datetime
from urllib.parse import urljoin, urlparse, urlunparse


# ==========================================================
# SETTINGS
# ==========================================================

BASE_URL = "https://www.inquirer.net"

ENVIRONMENT_URL = "https://www.inquirer.net/environment/"


# ----------------------------------------------------------
# Historical date range
# ----------------------------------------------------------
START_DATE = os.getenv(
    "NEWS_START_DATE",
    "2026-08-01"
)

END_DATE = os.getenv(
    "NEWS_END_DATE",
    "2026-08-30"
)

START_DATE = datetime.strptime(
    START_DATE,
    "%Y-%m-%d"
)

END_DATE = datetime.strptime(
    END_DATE,
    "%Y-%m-%d"
)


# ----------------------------------------------------------
# Output file
# ----------------------------------------------------------

SCRIPT_DIR = os.path.dirname(
    os.path.abspath(__file__)
)

OUTPUT_FILE = os.path.join(
    SCRIPT_DIR,
    "inquirer_environment.csv"
)


# ----------------------------------------------------------
# Maximum archive pages
# ----------------------------------------------------------

MAX_PAGES = 10


# ==========================================================
# ENVIRONMENT KEYWORDS
#
# These are metadata only.
#
# Articles are already discovered from Inquirer's
# Environment archive, so we do NOT require a keyword match
# in order to save an article.
# ==========================================================

ENVIRONMENT_KEYWORDS = [

    # General
    "environment",
    "environmental",
    "sustainability",
    "sustainable",
    "green economy",
    "green development",
    "nature",
    "natural resources",

    # Climate
    "climate change",
    "climate crisis",
    "global warming",
    "climate action",
    "climate adaptation",
    "climate mitigation",
    "climate resilience",
    "climate risk",
    "extreme weather",
    "el niño",
    "el nino",
    "la niña",
    "la nina",

    # Carbon
    "carbon",
    "carbon emissions",
    "greenhouse gas",
    "greenhouse gases",
    "net zero",
    "decarbonization",
    "decarbonisation",

    # Forest
    "forest",
    "forests",
    "deforestation",
    "reforestation",
    "forest fire",
    "forest fires",
    "wildfire",
    "wildfires",
    "watershed",
    "watersheds",

    # Biodiversity
    "biodiversity",
    "conservation",
    "wildlife",
    "ecosystem",
    "ecosystems",
    "habitat",
    "endangered species",
    "protected area",
    "protected areas",

    # Pollution
    "pollution",
    "air pollution",
    "water pollution",
    "air quality",
    "haze",
    "pm2.5",
    "particulate matter",

    # Waste
    "waste",
    "garbage",
    "plastic",
    "plastic waste",
    "plastic pollution",
    "recycling",
    "solid waste",
    "waste management",
    "marine litter",
    "e-waste",

    # Energy
    "renewable energy",
    "clean energy",
    "solar energy",
    "solar power",
    "wind energy",
    "wind power",
    "energy transition",
    "fossil fuel",
    "fossil fuels",
    "coal",

    # Marine
    "ocean",
    "oceans",
    "marine",
    "coastal",
    "coral reef",
    "coral reefs",
    "mangrove",
    "mangroves",
    "fisheries",
    "water conservation",
    "water security",
    "seagrass",

    # Disaster
    "flood",
    "flooding",
    "drought",
    "landslide",
    "heat wave",
    "heatwave",
    "sea level rise",
    "coastal erosion",
    "storm surge",

    # Ecology
    "ecological",
    "ecology"
]


# ==========================================================
# ASEAN COUNTRY KEYWORDS
#
# This is metadata only.
# It does NOT determine whether an article is saved.
# ==========================================================

ASEAN_COUNTRY_KEYWORDS = {

    "Brunei": [
        "brunei",
        "bruneian",
        "bandar seri begawan"
    ],

    "Cambodia": [
        "cambodia",
        "cambodian",
        "phnom penh",
        "siem reap"
    ],

    "Indonesia": [
        "indonesia",
        "indonesian",
        "indonesians",
        "jakarta",
        "sumatra",
        "sumatera",
        "java",
        "jawa",
        "kalimantan",
        "sulawesi",
        "bali"
    ],

    "Laos": [
        "laos",
        "lao",
        "vientiane"
    ],

    "Malaysia": [
        "malaysia",
        "malaysian",
        "malaysians",
        "kuala lumpur",
        "selangor",
        "johor",
        "sabah",
        "sarawak",
        "penang",
        "pahang"
    ],

    "Myanmar": [
        "myanmar",
        "burma",
        "burmese",
        "yangon",
        "mandalay"
    ],

    "Philippines": [
        "philippines",
        "philippine",
        "filipino",
        "filipinos",

        "manila",
        "metro manila",

        "luzon",
        "visayas",
        "mindanao",

        "cebu",
        "palawan",
        "davao",
        "bohol",
        "batangas",
        "cavite",
        "laguna",
        "rizal",
        "bulacan",
        "pampanga",
        "pangasinan",
        "iloilo",
        "leyte",
        "samar",
        "zambales",
        "masbate",
        "sulu",
        "negros",
        "benguet",
        "baguio",

        # Government environmental bodies
        "denr",
        "pagasa"
    ],

    "Singapore": [
        "singapore",
        "singaporean"
    ],

    "Thailand": [
        "thailand",
        "thai",
        "bangkok",
        "chiang mai",
        "phuket"
    ],

    "Vietnam": [
        "vietnam",
        "vietnamese",
        "hanoi",
        "ho chi minh",
        "ho chi minh city"
    ]
}


# ==========================================================
# HEADERS
# ==========================================================

HEADERS = {

    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/152.0.0.0 Safari/537.36"
    ),

    "Accept": (
        "text/html,application/xhtml+xml,"
        "application/xml;q=0.9,*/*;q=0.8"
    ),

    "Accept-Language": "en-US,en;q=0.9",

    "Connection": "keep-alive"
}


# ==========================================================
# SESSION
# ==========================================================

session = requests.Session()

session.headers.update(
    HEADERS
)


# ==========================================================
# CLEAN URL
# ==========================================================

def clean_url(url):

    parsed = urlparse(url)

    cleaned = parsed._replace(
        query="",
        fragment=""
    )

    return urlunparse(
        cleaned
    ).rstrip("/")


# ==========================================================
# CHECK WHETHER URL IS AN INQUIRER ARTICLE
#
# Common examples:
#
# https://newsinfo.inquirer.net/2294767/...
#
# https://cebudailynews.inquirer.net/...
#
# We mainly expect newsinfo articles from the environment
# archive.
# ==========================================================

def is_article_url(url):

    parsed = urlparse(url)

    domain = parsed.netloc.lower()

    path = parsed.path.lower()


    # Main NewsInfo articles
    if (
        domain == "newsinfo.inquirer.net"
        and
        re.match(
            r"^/\d+/",
            path
        )
    ):
        return True


    # Inquirer articles sometimes live directly on
    # www.inquirer.net
    if (
        domain.endswith(
            "inquirer.net"
        )
        and
        "/environment/" not in path
        and
        re.search(
            r"/\d{4}/\d{2}/\d{2}/",
            path
        )
    ):
        return True


    return False


# ==========================================================
# EXTRACT ARTICLE URLS FROM ENVIRONMENT ARCHIVE
# ==========================================================

def extract_article_urls(html):

    soup = BeautifulSoup(
        html,
        "html.parser"
    )


    article_urls = []


    for link in soup.find_all(
        "a",
        href=True
    ):

        href = link.get(
            "href"
        )


        full_url = clean_url(
            urljoin(
                BASE_URL,
                href
            )
        )


        if not is_article_url(
            full_url
        ):
            continue


        if full_url not in article_urls:

            article_urls.append(
                full_url
            )


    return article_urls


# ==========================================================
# LOAD ENVIRONMENT ARCHIVE PAGE
#
# Page 1:
# https://www.inquirer.net/environment/
#
# Older pages are attempted as:
# https://www.inquirer.net/environment/page/2/
# ==========================================================

def get_environment_page(page_number):

    if page_number == 1:

        url = ENVIRONMENT_URL

    else:

        url = (
            f"{ENVIRONMENT_URL}"
            f"page/{page_number}/"
        )


    print()
    print(
        f"Loading Inquirer Environment page {page_number}..."
    )

    print(
        url
    )


    try:

        response = session.get(
            url,
            headers={
                "Referer":
                    ENVIRONMENT_URL
            },
            timeout=30
        )


        print(
            "Status:",
            response.status_code
        )


        if response.status_code != 200:

            print(
                "Environment archive request failed."
            )

            print(
                response.text[:300]
            )

            return []


        article_urls = (
            extract_article_urls(
                response.text
            )
        )


        print(
            "Article URLs found:",
            len(article_urls)
        )


        return article_urls


    except Exception as e:

        print(
            "Environment page error:",
            e
        )

        return []


# ==========================================================
# EXTRACT TITLE
# ==========================================================

def extract_title(soup):

    h1 = soup.find(
        "h1"
    )


    if h1:

        title = h1.get_text(
            " ",
            strip=True
        )


        if title:
            return title


    meta = soup.find(
        "meta",
        attrs={
            "property":
                "og:title"
        }
    )


    if (
        meta
        and
        meta.get("content")
    ):

        return (
            meta[
                "content"
            ]
            .strip()
        )


    return ""


# ==========================================================
# EXTRACT PUBLISHED DATE
# ==========================================================

def extract_published_date(soup):


    # ------------------------------------------------------
    # 1. article:published_time
    # ------------------------------------------------------

    meta_candidates = [

        soup.find(
            "meta",
            attrs={
                "property":
                    "article:published_time"
            }
        ),

        soup.find(
            "meta",
            attrs={
                "name":
                    "date"
            }
        ),

        soup.find(
            "meta",
            attrs={
                "itemprop":
                    "datePublished"
            }
        )
    ]


    for meta in meta_candidates:

        if (
            meta
            and
            meta.get(
                "content"
            )
        ):

            try:

                dt = pd.to_datetime(
                    meta[
                        "content"
                    ]
                )


                return (
                    dt
                    .to_pydatetime()
                    .replace(
                        tzinfo=None
                    )
                )


            except Exception:

                pass


    # ------------------------------------------------------
    # 2. <time datetime="">
    # ------------------------------------------------------

    time_tag = soup.find(
        "time"
    )


    if time_tag:

        value = time_tag.get(
            "datetime"
        )


        if value:

            try:

                dt = pd.to_datetime(
                    value
                )


                return (
                    dt
                    .to_pydatetime()
                    .replace(
                        tzinfo=None
                    )
                )


            except Exception:

                pass


    # ------------------------------------------------------
    # 3. Visible Inquirer date
    #
    # Examples:
    #
    # INQUIRER.net / 05:14 PM August 29, 2026
    #
    # August 20, 2026
    # ------------------------------------------------------

    page_text = soup.get_text(
        " ",
        strip=True
    )


    date_pattern = (

        r"\b("
        r"January|February|March|April|May|June|"
        r"July|August|September|October|November|December"
        r")"

        r"\s+"

        r"(\d{1,2})"

        r",\s+"

        r"(\d{4})"
    )


    match = re.search(
        date_pattern,
        page_text,
        re.IGNORECASE
    )


    if match:

        date_string = (

            f"{match.group(1)} "

            f"{match.group(2)}, "

            f"{match.group(3)}"
        )


        try:

            return datetime.strptime(
                date_string,
                "%B %d, %Y"
            )


        except Exception:

            pass


    return None


# ==========================================================
# EXTRACT AUTHOR
# ==========================================================

def extract_author(soup):


    # ------------------------------------------------------
    # Meta
    # ------------------------------------------------------

    meta = soup.find(
        "meta",
        attrs={
            "name":
                "author"
        }
    )


    if (
        meta
        and
        meta.get(
            "content"
        )
    ):

        return (
            meta[
                "content"
            ]
            .strip()
        )


    # ------------------------------------------------------
    # Look for common Inquirer byline text
    # ------------------------------------------------------

    page_text = soup.get_text(
        "\n",
        strip=True
    )


    patterns = [

        r"WRITTEN BY:\s*([^\n]+)",

        r"By:\s*([^\n]+)",

        r"(?:^|\n)By\s+([^\n]+)"
    ]


    for pattern in patterns:

        match = re.search(
            pattern,
            page_text,
            re.IGNORECASE
        )


        if match:

            author = (
                match.group(1)
                .strip()
            )


            # Remove social handle if included
            author = re.sub(
                r"\s*/\s*@.*$",
                "",
                author
            )


            if len(author) < 150:

                return author


    return ""


# ==========================================================
# EXTRACT ARTICLE TEXT
# ==========================================================

def extract_article_text(soup):


    # ------------------------------------------------------
    # Inquirer has used several article-body layouts.
    # Try specific containers first.
    # ------------------------------------------------------

    selectors = [

        "#article_content",

        ".article-content",

        ".article_content",

        ".entry-content",

        ".article-body",

        "[itemprop='articleBody']",

        "article"
    ]


    container = None


    for selector in selectors:

        container = soup.select_one(
            selector
        )


        if container:
            break


    if container:

        paragraph_tags = (
            container.find_all(
                "p"
            )
        )

    else:

        paragraph_tags = (
            soup.find_all(
                "p"
            )
        )


    paragraphs = []


    unwanted_phrases = [

        "article continues after this advertisement",

        "featured stories",

        "don't miss out",

        "don’t miss out",

        "subscribe to our daily newsletter",

        "subscribe to our newsletter",

        "inquirer.net",
        
        "all rights reserved",

        "copyright",

        "read next",

        "read more",

        "related stories",

        "advertisement",

        "follow us",

        "facebook",

        "twitter",

        "instagram"
    ]


    for p in paragraph_tags:

        text = p.get_text(
            " ",
            strip=True
        )


        if len(text) < 30:

            continue


        lower_text = (
            text.lower()
        )


        if any(
            phrase in lower_text
            for phrase in unwanted_phrases
        ):

            continue


        # Avoid duplicate paragraphs
        if text not in paragraphs:

            paragraphs.append(
                text
            )


    return " ".join(
        paragraphs
    )


# ==========================================================
# FIND ENVIRONMENT KEYWORDS
# ==========================================================

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


# ==========================================================
# FIND ASEAN COUNTRIES
# ==========================================================

def find_asean_countries(text):

    text = text.lower()

    countries = []


    for country, keywords in (
        ASEAN_COUNTRY_KEYWORDS.items()
    ):


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

                countries.append(
                    country
                )

                break


    return countries


# ==========================================================
# SCRAPE ONE ARTICLE
# ==========================================================

def scrape_article(url):

    print()
    print(
        url
    )


    try:

        response = session.get(
            url,
            headers={
                "Referer":
                    ENVIRONMENT_URL
            },
            timeout=30
        )


        print(
            "  Status:",
            response.status_code
        )


        if response.status_code != 200:

            print(
                "  Article request failed."
            )

            return None


        soup = BeautifulSoup(
            response.text,
            "html.parser"
        )


        # --------------------------------------------------
        # TITLE
        # --------------------------------------------------

        title = extract_title(
            soup
        )


        if not title:

            print(
                "  No title - skipped"
            )

            return None


        # --------------------------------------------------
        # DATE
        # --------------------------------------------------

        published_date = (
            extract_published_date(
                soup
            )
        )


        if published_date is None:

            print(
                "  No date - skipped"
            )

            return None


        # --------------------------------------------------
        # TEXT
        # --------------------------------------------------

        article_text = (
            extract_article_text(
                soup
            )
        )


        if len(article_text) < 250:

            print(
                "  Too little article text:",
                len(article_text)
            )

            return None


        # --------------------------------------------------
        # AUTHOR
        # --------------------------------------------------

        author = extract_author(
            soup
        )


        return {

            "title":
                title,

            "source":
                "Inquirer",

            "published_at":
                published_date,

            "author":
                author,

            "article_text":
                article_text,

            "url":
                clean_url(
                    url
                )
        }


    except Exception as e:

        print(
            "  Error:",
            e
        )

        return None


# ==========================================================
# GET EXISTING URLS
# ==========================================================

def get_existing_urls():

    if not os.path.exists(
        OUTPUT_FILE
    ):

        return set()


    try:

        existing_df = pd.read_csv(
            OUTPUT_FILE
        )


        if "url" not in existing_df.columns:

            return set()


        return set(

            existing_df[
                "url"
            ]

            .dropna()

            .astype(str)

            .apply(
                clean_url
            )
        )


    except Exception as e:

        print(
            "Could not read existing CSV:",
            e
        )

        return set()


# ==========================================================
# PROCESS ARTICLE URLS
# ==========================================================

def process_urls(
    urls,
    existing_urls,
    seen_urls,
    results,
    stats
):


    page_dates = []


    for url in urls:


        url = clean_url(
            url
        )


        # --------------------------------------------------
        # DUPLICATE DURING CURRENT RUN
        # --------------------------------------------------

        if url in seen_urls:

            continue


        seen_urls.add(
            url
        )


        # --------------------------------------------------
        # EXISTING CSV
        # --------------------------------------------------

        if url in existing_urls:

            stats[
                "already_exists"
            ] += 1


            print(
                "Already in CSV:",
                url
            )

            continue


        # --------------------------------------------------
        # SCRAPE
        # --------------------------------------------------

        article = scrape_article(
            url
        )


        if article is None:

            stats[
                "failed"
            ] += 1

            continue


        stats[
            "scraped"
        ] += 1


        article_date = (
            article[
                "published_at"
            ]
        )


        page_dates.append(
            article_date
        )


        print(
            "  Date:",
            article_date.date()
        )


        # --------------------------------------------------
        # NEWER THAN RANGE
        # --------------------------------------------------

        if article_date > END_DATE:

            stats[
                "too_new"
            ] += 1

            print(
                "  Newer than END_DATE"
            )

            continue


        # --------------------------------------------------
        # OLDER THAN RANGE
        # --------------------------------------------------

        if article_date < START_DATE:

            stats[
                "too_old"
            ] += 1

            print(
                "  Older than START_DATE"
            )

            continue


        # --------------------------------------------------
        # ANALYSE ARTICLE
        # --------------------------------------------------

        combined_text = (

            article[
                "title"
            ]

            + " "

            + article[
                "article_text"
            ]
        )


        environment_matches = (
            find_environment_keywords(
                combined_text
            )
        )


        asean_countries = (
            find_asean_countries(
                combined_text
            )
        )


        article[
            "published_at"
        ] = article_date.strftime(
            "%Y-%m-%d"
        )


        article[
            "asean_countries"
        ] = ", ".join(
            asean_countries
        )


        article[
            "environment_keywords"
        ] = ", ".join(
            environment_matches
        )


        # --------------------------------------------------
        # IMPORTANT:
        #
        # Keep ALL articles from Inquirer's Environment
        # archive in the date range.
        #
        # We do NOT require Philippines to be mentioned.
        # --------------------------------------------------

        results.append(
            article
        )


        stats[
            "saved"
        ] += 1


        print(
            "  SAVED"
        )


        print(
            "  ASEAN countries:",
            article[
                "asean_countries"
            ]
            if article[
                "asean_countries"
            ]
            else "None"
        )


        print(
            "  Environment keywords:",
            article[
                "environment_keywords"
            ]
            if article[
                "environment_keywords"
            ]
            else "None"
        )


        time.sleep(1)


    if len(page_dates) == 0:

        return None


    return min(
        page_dates
    )


# ==========================================================
# MAIN
# ==========================================================

def main():

    print()
    print(
        "======================================"
    )

    print(
        "INQUIRER ENVIRONMENT SCRAPER"
    )

    print(
        "======================================"
    )


    print(
        "Start:",
        START_DATE.date()
    )

    print(
        "End:",
        END_DATE.date()
    )


    # ------------------------------------------------------
    # Ensure output folder exists
    # ------------------------------------------------------

    output_directory = os.path.dirname(
        OUTPUT_FILE
    )


    if output_directory:

        os.makedirs(
            output_directory,
            exist_ok=True
        )


    # ------------------------------------------------------
    # Existing CSV
    # ------------------------------------------------------

    existing_urls = (
        get_existing_urls()
    )


    print(
        "Existing URLs:",
        len(existing_urls)
    )


    results = []

    seen_urls = set()


    stats = {

        "scraped": 0,

        "failed": 0,

        "too_new": 0,

        "too_old": 0,

        "already_exists": 0,

        "saved": 0
    }


    # ======================================================
    # PAGE THROUGH ENVIRONMENT ARCHIVE
    # ======================================================

    for page_number in range(
        1,
        MAX_PAGES + 1
    ):


        urls = get_environment_page(
            page_number
        )


        if len(urls) == 0:

            print()
            print(
                "No article URLs returned."
            )

            break


        oldest_date = process_urls(

            urls,

            existing_urls,

            seen_urls,

            results,

            stats
        )


        print()
        print(
            "Oldest date on page:",
            oldest_date.date()
            if oldest_date
            else "Unknown"
        )


        # --------------------------------------------------
        # Environment archive is newest -> oldest.
        #
        # Once we encounter articles earlier than START_DATE,
        # we can stop.
        # --------------------------------------------------

        if (
            oldest_date is not None
            and
            oldest_date < START_DATE
        ):

            print()
            print(
                "Reached articles older "
                "than START_DATE."
            )

            print(
                "Stopping pagination."
            )

            break


        time.sleep(1)


    # ======================================================
    # SUMMARY
    # ======================================================

    print()
    print(
        "======================================"
    )

    print(
        "SCRAPING SUMMARY"
    )

    print(
        "======================================"
    )


    print(
        "Unique URLs encountered:",
        len(seen_urls)
    )

    print(
        "Successfully scraped:",
        stats[
            "scraped"
        ]
    )

    print(
        "Failed:",
        stats[
            "failed"
        ]
    )

    print(
        "Newer than END_DATE:",
        stats[
            "too_new"
        ]
    )

    print(
        "Older than START_DATE:",
        stats[
            "too_old"
        ]
    )

    print(
        "Already in CSV:",
        stats[
            "already_exists"
        ]
    )

    print(
        "New articles saved:",
        stats[
            "saved"
        ]
    )


    # ======================================================
    # NOTHING NEW
    # ======================================================

    if len(results) == 0:

        print()
        print(
            "No new articles to append."
        )

        return


    # ======================================================
    # NEW DATA
    # ======================================================

    new_df = pd.DataFrame(
        results
    )


    new_df.drop_duplicates(

        subset=[
            "url"
        ],

        keep="first",

        inplace=True
    )


    # ======================================================
    # APPEND TO OLD CSV
    # ======================================================

    if os.path.exists(
        OUTPUT_FILE
    ):


        existing_df = pd.read_csv(
            OUTPUT_FILE
        )


        print()
        print(
            "Existing articles:",
            len(existing_df)
        )


        combined_df = pd.concat(

            [
                existing_df,
                new_df
            ],

            ignore_index=True
        )


        before = len(
            combined_df
        )


        combined_df.drop_duplicates(

            subset=[
                "url"
            ],

            keep="first",

            inplace=True
        )


        print(
            "Duplicates removed:",
            before
            - len(
                combined_df
            )
        )


        df = combined_df


    else:

        df = new_df


    # ======================================================
    # SORT
    # ======================================================

    df[
        "published_at"
    ] = pd.to_datetime(

        df[
            "published_at"
        ],

        errors="coerce"
    )


    df = (

        df

        .sort_values(
            "published_at",
            ascending=False
        )

        .reset_index(
            drop=True
        )
    )


    df[
        "published_at"
    ] = (

        df[
            "published_at"
        ]

        .dt.strftime(
            "%Y-%m-%d"
        )
    )


    # ======================================================
    # COLUMN ORDER
    # ======================================================

    desired_columns = [

        "title",

        "source",

        "published_at",

        "author",

        "asean_countries",

        "environment_keywords",

        "article_text",

        "url"
    ]


    for column in desired_columns:

        if column not in df.columns:

            df[
                column
            ] = ""


    df = df[
        desired_columns
    ]


    # ======================================================
    # SAVE CSV
    # ======================================================

    df.to_csv(

        OUTPUT_FILE,

        index=False,

        encoding="utf-8-sig"
    )


    print()
    print(
        "======================================"
    )

    print(
        "FINISHED"
    )

    print(
        "======================================"
    )


    print(
        "New articles this run:",
        len(
            new_df
        )
    )

    print(
        "Total unique articles:",
        len(
            df
        )
    )

    print(
        "Saved:",
        OUTPUT_FILE
    )


# ==========================================================
# RUN
# ==========================================================

if __name__ == "__main__":

    main()