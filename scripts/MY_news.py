import requests
from bs4 import BeautifulSoup
import pandas as pd
import time
import re
import os
import json

from datetime import datetime
from urllib.parse import urljoin, urlparse, urlunparse


# ==========================================================
# SETTINGS
# ==========================================================

BASE_URL = "https://www.astroawani.com"

TOPIC_URL = (
    "https://www.astroawani.com/topic/alam-sekitar"
)

AJAX_URL = (
    "https://www.astroawani.com/fetch/data"
)

BLOCK_ID = "page_term_block_147242"


# ----------------------------------------------------------
# Date range
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
# Output
# ----------------------------------------------------------

SCRIPT_DIR = os.path.dirname(
    os.path.abspath(__file__)
)

OUTPUT_FILE = os.path.join(
    SCRIPT_DIR,
    "astro_awani_environment.csv"
)

# ----------------------------------------------------------
# Safety limit
#
# Prevent accidental infinite pagination
# ----------------------------------------------------------

MAX_AJAX_PAGES = 20


# ==========================================================
# ENVIRONMENT KEYWORDS
# Malay + English
# ==========================================================

ENVIRONMENT_KEYWORDS = [

    # General
    "alam sekitar",
    "alam sekeliling",
    "kelestarian",
    "kelestarian alam",
    "kelestarian alam sekitar",
    "sustainability",
    "environment",
    "environmental",

    # Climate
    "perubahan iklim",
    "krisis iklim",
    "pemanasan global",
    "tindakan iklim",
    "risiko iklim",
    "climate change",
    "global warming",
    "climate crisis",
    "climate action",

    # Carbon
    "pelepasan karbon",
    "karbon",
    "neutral karbon",
    "sifar bersih",
    "gas rumah hijau",
    "carbon emissions",
    "carbon neutral",
    "net zero",
    "greenhouse gas",

    # Energy
    "tenaga boleh diperbaharui",
    "tenaga bersih",
    "tenaga hijau",
    "tenaga solar",
    "tenaga angin",
    "hidrogen",
    "renewable energy",
    "clean energy",
    "solar energy",

    # Pollution
    "pencemaran",
    "pencemaran udara",
    "pencemaran air",
    "jerebu",
    "kualiti udara",
    "air quality",
    "pollution",
    "haze",

    # Waste
    "sisa",
    "sisa plastik",
    "sisa makanan",
    "sisa elektronik",
    "e-waste",
    "kitar semula",
    "pengurusan sisa",
    "recycling",
    "waste management",

    # Nature
    "biodiversiti",
    "kepelbagaian biologi",
    "pemuliharaan",
    "ekosistem",
    "hidupan liar",
    "penebangan hutan",
    "kebakaran hutan",
    "biodiversity",
    "conservation",
    "ecosystem",
    "wildlife",
    "deforestation",
    "forest fire",

    # Weather / disasters
    "banjir",
    "kemarau",
    "hakisan pantai",
    "kenaikan paras laut",
    "cuaca ekstrem",
    "gelombang haba",
    "flood",
    "drought",
    "sea level rise",
    "extreme weather",
    "heatwave",

    # Sustainability
    "bangunan hijau",
    "pengangkutan mampan",
    "kenderaan elektrik",
    "kewangan hijau",
    "green building",
    "electric vehicle",
    "green finance"
]


# ==========================================================
# ASEAN COUNTRY KEYWORDS
# ==========================================================

COUNTRY_KEYWORDS = {

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
        "pulau pinang",
        "kelantan",
        "terengganu",
        "pahang",
        "perak",
        "kedah",
        "melaka",
        "malacca",
        "negeri sembilan",
        "putrajaya"
    ],

    "Singapore": [
        "singapore",
        "singapura",
        "singaporean"
    ],

    "Indonesia": [
        "indonesia",
        "indonesian",
        "jakarta",
        "kalimantan",
        "sumatra",
        "jawa"
    ],

    "Philippines": [
        "philippines",
        "filipina",
        "philippine",
        "filipino",
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


# ==========================================================
# HEADERS
# ==========================================================

HEADERS = {

    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/151.0.0.0 Safari/537.36"
    ),

    "Accept": (
        "text/html,application/xhtml+xml,"
        "application/xml;q=0.9,*/*;q=0.8"
    ),

    "Referer":
        TOPIC_URL
}


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
# CHECK WHETHER URL IS AN ARTICLE
# ==========================================================

def is_article_url(url):

    parsed = urlparse(url)

    path = parsed.path.lower()


    # Ignore topic pages
    if "/topic/" in path:

        return False


    # Ignore empty/homepage
    if path == "" or path == "/":

        return False


    # Astro AWANI articles generally sit under
    # /berita-...
    #
    # We are NOT scraping all berita sections.
    # These URLs are only collected from
    # the alam-sekitar topic page.

    return "/berita-" in path


# ==========================================================
# EXTRACT ARTICLE URLS FROM HTML
# ==========================================================

def extract_article_urls_from_html(html):

    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    urls = []


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


        if not full_url.startswith(
            BASE_URL
        ):

            continue


        if not is_article_url(
            full_url
        ):

            continue


        if full_url not in urls:

            urls.append(
                full_url
            )


    return urls


# ==========================================================
# EXTRACT HTML FROM DRUPAL AJAX RESPONSE
# ==========================================================

def extract_html_from_ajax_response(response):

    """
    Astro AWANI's fetch/data endpoint uses a Drupal
    AJAX-style response.

    Depending on the response, article HTML may be
    inside JSON fields such as "data".

    This function extracts all HTML-looking strings
    from the response.
    """

    html_parts = []


    # ------------------------------------------------------
    # First try JSON
    # ------------------------------------------------------

    try:

        data = response.json()


        def find_html(obj):

            if isinstance(
                obj,
                dict
            ):

                for value in obj.values():

                    find_html(
                        value
                    )


            elif isinstance(
                obj,
                list
            ):

                for value in obj:

                    find_html(
                        value
                    )


            elif isinstance(
                obj,
                str
            ):

                if (
                    "<a" in obj
                    or "<div" in obj
                    or "<article" in obj
                ):

                    html_parts.append(
                        obj
                    )


        find_html(
            data
        )


    except Exception:

        pass


    # ------------------------------------------------------
    # If JSON parsing does not give HTML,
    # treat response as HTML directly
    # ------------------------------------------------------

    if len(
        html_parts
    ) == 0:

        html_parts.append(
            response.text
        )


    return "\n".join(
        html_parts
    )


# ==========================================================
# GET INITIAL TOPIC PAGE
# ==========================================================

def get_initial_page():

    print()
    print(
        "Loading initial alam-sekitar page..."
    )


    try:

        response = requests.get(
            TOPIC_URL,
            headers=HEADERS,
            timeout=20
        )


        print(
            "Status:",
            response.status_code
        )


        if response.status_code != 200:

            return []


        return extract_article_urls_from_html(
            response.text
        )


    except Exception as e:

        print(
            "Error loading initial page:",
            e
        )

        return []


# ==========================================================
# GET AJAX LOAD-MORE PAGE
# ==========================================================

def get_ajax_page(page_number):

    params = {

        "page_ajax":
            page_number,

        "block_id":
            BLOCK_ID,

        "_wrapper_format":
            "drupal_ajax"
    }


    try:

        response = requests.get(
            AJAX_URL,
            params=params,
            headers=HEADERS,
            timeout=20
        )


        print(
            f"AJAX page {page_number} "
            f"status: {response.status_code}"
        )


        if response.status_code != 200:

            return []


        html = (
            extract_html_from_ajax_response(
                response
            )
        )


        urls = (
            extract_article_urls_from_html(
                html
            )
        )


        return urls


    except Exception as e:

        print(
            f"Error loading AJAX "
            f"page {page_number}:",
            e
        )

        return []


# ==========================================================
# EXTRACT PUBLISHED DATE
# ==========================================================

def extract_published_date(soup):

    # ------------------------------------------------------
    # METHOD 1:
    # article:published_time
    # ------------------------------------------------------

    meta = soup.find(
        "meta",
        attrs={
            "property":
                "article:published_time"
        }
    )


    if meta and meta.get(
        "content"
    ):

        try:

            dt = pd.to_datetime(
                meta["content"]
            )

            return (
                dt.to_pydatetime()
                .replace(
                    tzinfo=None
                )
            )

        except Exception:

            pass


    # ------------------------------------------------------
    # METHOD 2:
    # <time datetime="">
    # ------------------------------------------------------

    time_tag = soup.find(
        "time"
    )


    if time_tag:

        datetime_value = (
            time_tag.get(
                "datetime"
            )
        )


        if datetime_value:

            try:

                dt = pd.to_datetime(
                    datetime_value
                )

                return (
                    dt.to_pydatetime()
                    .replace(
                        tzinfo=None
                    )
                )

            except Exception:

                pass


    # ------------------------------------------------------
    # METHOD 3:
    #
    # Astro AWANI visible format:
    #
    # 29/08/2026 | 08:45 MYT
    # ------------------------------------------------------

    page_text = soup.get_text(
        " ",
        strip=True
    )


    match = re.search(
        r"\b(\d{2}/\d{2}/\d{4})"
        r"\s*\|\s*"
        r"\d{1,2}:\d{2}"
        r"\s*MYT\b",
        page_text
    )


    if match:

        try:

            return datetime.strptime(
                match.group(1),
                "%d/%m/%Y"
            )

        except Exception:

            pass


    # ------------------------------------------------------
    # Backup
    # ------------------------------------------------------

    match = re.search(
        r"\b(\d{2}/\d{2}/\d{4})\b",
        page_text
    )


    if match:

        try:

            return datetime.strptime(
                match.group(1),
                "%d/%m/%Y"
            )

        except Exception:

            pass


    return None


# ==========================================================
# EXTRACT ARTICLE TEXT
# ==========================================================

def extract_article_text(soup):

    paragraphs = []


    # ------------------------------------------------------
    # Try article container first
    # ------------------------------------------------------

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

        "dapatkan berita terkini",

        "newsletter",

        "advertisement",

        "hak cipta",

        "all rights reserved",

        "topic berkaitan",

        "must watch video",

        "astro awani network",

        "ikuti kami",

        "langgan"
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


        paragraphs.append(
            text
        )


    return " ".join(
        paragraphs
    )


# ==========================================================
# SCRAPE ONE ARTICLE
# ==========================================================

def scrape_article(url):

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


        # --------------------------------------------------
        # TITLE
        # --------------------------------------------------

        h1 = soup.find(
            "h1"
        )


        if not h1:

            print(
                "No title found:",
                url
            )

            return None


        title = h1.get_text(
            " ",
            strip=True
        )


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
                "No date found:",
                title
            )

            return None


        # --------------------------------------------------
        # ARTICLE TEXT
        # --------------------------------------------------

        article_text = (
            extract_article_text(
                soup
            )
        )


        if len(
            article_text
        ) < 250:

            print(
                "Too little usable text:",
                title
            )

            return None


        return {

            "title":
                title,

            "source":
                "Astro AWANI",

            "published_at":
                published_date,

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

        print(
            e
        )

        return None


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
# FIND COUNTRIES
# ==========================================================

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


# ==========================================================
# PROCESS ONE BATCH OF URLS
# ==========================================================

def process_batch(
    urls,
    seen_urls,
    results
):

    """
    Scrape one group of URLs.

    Returns the oldest publication date found
    in this batch.
    """

    oldest_date = None


    for url in urls:

        # --------------------------------------------------
        # Skip URLs already encountered
        # --------------------------------------------------

        if url in seen_urls:

            continue


        seen_urls.add(
            url
        )


        print()
        print(
            url
        )


        article = scrape_article(
            url
        )


        if article is None:

            time.sleep(1)

            continue


        published_date = (
            article[
                "published_at"
            ]
        )


        # --------------------------------------------------
        # Keep track of oldest date
        # --------------------------------------------------

        if (
            oldest_date is None
            or published_date < oldest_date
        ):

            oldest_date = (
                published_date
            )


        print(
            "  Date:",
            published_date.date()
        )


        # --------------------------------------------------
        # Too new
        # --------------------------------------------------

        if published_date > END_DATE:

            print(
                "  Too new - skipped"
            )

            time.sleep(1)

            continue


        # --------------------------------------------------
        # Too old
        # --------------------------------------------------

        if published_date < START_DATE:

            print(
                "  Older than START_DATE"
            )

            time.sleep(1)

            continue


        # --------------------------------------------------
        # Keyword detection
        # --------------------------------------------------

        combined_text = (
            article["title"]
            + " "
            + article["article_text"]
        )


        environment_matches = (
            find_environment_keywords(
                combined_text
            )
        )


        country_matches = (
            find_countries(
                combined_text
            )
        )


        # --------------------------------------------------
        # Keep Malaysian environmental stories
        # --------------------------------------------------

        if (
            len(environment_matches) > 0
            and
            "Malaysia" in country_matches
        ):

            article[
                "published_at"
            ] = published_date.strftime(
                "%Y-%m-%d"
            )


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
                "  No Malaysia + "
                "environment match"
            )


        time.sleep(1)


    return oldest_date


# ==========================================================
# MAIN
# ==========================================================

def main():

    print()
    print(
        "======================================"
    )

    print(
        "ASTRO AWANI ENVIRONMENT SCRAPER"
    )

    print(
        "======================================"
    )


    print(
        "Topic:",
        TOPIC_URL
    )


    print(
        "Start date:",
        START_DATE.date()
    )


    print(
        "End date:",
        END_DATE.date()
    )


    results = []

    seen_urls = set()


    # ======================================================
    # STEP 1:
    # INITIAL ALAM-SEKITAR PAGE
    # ======================================================

    initial_urls = (
        get_initial_page()
    )


    print()
    print(
        f"{len(initial_urls)} article URLs "
        "found on initial page."
    )


    if len(
        initial_urls
    ) == 0:

        print(
            "No articles found."
        )

        return


    print()
    print(
        "======================================"
    )

    print(
        "PROCESSING INITIAL PAGE"
    )

    print(
        "======================================"
    )


    oldest_date = process_batch(
        initial_urls,
        seen_urls,
        results
    )


    # ======================================================
    # STEP 2:
    # LOAD MORE USING AJAX
    # ======================================================

    # ------------------------------------------------------
    # If the initial page already goes earlier than
    # START_DATE, there is no need to load more.
    # ------------------------------------------------------

    if (
        oldest_date is not None
        and
        oldest_date < START_DATE
    ):

        print()
        print(
            "Initial page already reached "
            "articles older than START_DATE."
        )

        print(
            "No AJAX Load More required."
        )


    else:

        print()
        print(
            "======================================"
        )

        print(
            "LOADING OLDER ARTICLES"
        )

        print(
            "======================================"
        )


        # --------------------------------------------------
        # Astro AWANI AJAX pagination
        #
        # page_ajax increases:
        #
        # page_ajax=1
        # page_ajax=2
        # page_ajax=3
        # ...
        #
        # The endpoint observed in Chrome was:
        #
        # /fetch/data
        # ?page_ajax=4
        # &block_id=page_term_block_147242
        # &_wrapper_format=drupal_ajax
        # --------------------------------------------------

        page_ajax = 1


        while (
            page_ajax <= MAX_AJAX_PAGES
        ):

            print()
            print(
                "--------------------------------------"
            )

            print(
                f"Loading AJAX page "
                f"{page_ajax}"
            )

            print(
                "--------------------------------------"
            )


            ajax_urls = (
                get_ajax_page(
                    page_ajax
                )
            )


            # --------------------------------------------------
            # No URLs returned
            # --------------------------------------------------

            if len(
                ajax_urls
            ) == 0:

                print(
                    "No article URLs returned."
                )

                print(
                    "Stopping pagination."
                )

                break


            # --------------------------------------------------
            # Remove URLs already seen
            # --------------------------------------------------

            new_urls = [

                url

                for url in ajax_urls

                if url not in seen_urls
            ]


            print(
                f"{len(ajax_urls)} URLs returned."
            )


            print(
                f"{len(new_urls)} are new."
            )


            # --------------------------------------------------
            # If AJAX page contains nothing new,
            # stop to avoid looping forever.
            # --------------------------------------------------

            if len(
                new_urls
            ) == 0:

                print(
                    "No new URLs found."
                )

                print(
                    "Stopping pagination."
                )

                break


            batch_oldest_date = (
                process_batch(
                    new_urls,
                    seen_urls,
                    results
                )
            )


            # --------------------------------------------------
            # Stop once this batch has reached
            # earlier than START_DATE
            # --------------------------------------------------

            if (
                batch_oldest_date
                is not None
                and
                batch_oldest_date
                < START_DATE
            ):

                print()
                print(
                    "Reached articles older "
                    "than START_DATE."
                )

                print(
                    "Stopping Load More."
                )

                break


            page_ajax += 1


            time.sleep(1)


    # ======================================================
    # STEP 3:
    # SAVE / APPEND CSV
    # ======================================================

    if len(
        results
    ) == 0:

        print()
        print(
            "No matching articles found."
        )

        return


    new_df = pd.DataFrame(
        results
    )


    # ------------------------------------------------------
    # Deduplicate current run
    # ------------------------------------------------------

    new_df.drop_duplicates(
        subset=["url"],
        inplace=True
    )


    # ======================================================
    # EXISTING CSV
    # ======================================================

    if os.path.exists(
        OUTPUT_FILE
    ):

        print()
        print(
            "Existing CSV found."
        )


        existing_df = pd.read_csv(
            OUTPUT_FILE
        )


        print(
            f"Existing CSV contains "
            f"{len(existing_df)} articles."
        )


        combined_df = pd.concat(
            [
                existing_df,
                new_df
            ],
            ignore_index=True
        )


        before_duplicates = len(
            combined_df
        )


        combined_df.drop_duplicates(
            subset=["url"],
            keep="first",
            inplace=True
        )


        duplicates_removed = (
            before_duplicates
            - len(
                combined_df
            )
        )


        print(
            f"{duplicates_removed} duplicate "
            "articles removed."
        )


        df = combined_df


    else:

        print()
        print(
            "No existing CSV found."
        )

        print(
            "Creating new CSV."
        )


        df = new_df


    # ======================================================
    # DATE FORMAT
    # ======================================================

    df[
        "published_at"
    ] = pd.to_datetime(
        df[
            "published_at"
        ],
        errors="coerce"
    )


    # ======================================================
    # SORT NEWEST FIRST
    # ======================================================

    df = (
        df
        .sort_values(
            by="published_at",
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

    df = df[
        [
            "title",
            "source",
            "published_at",
            "countries",
            "environment_keywords",
            "article_text",
            "url"
        ]
    ]


    # ======================================================
    # SAVE
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
        "SCRAPING FINISHED"
    )

    print(
        "======================================"
    )


    print(
        f"{len(new_df)} matching articles "
        "found this run."
    )


    print(
        f"{len(df)} total unique articles "
        "stored."
    )


    print(
        "File:",
        OUTPUT_FILE
    )


    print()


    print(
        df[
            [
                "published_at",
                "title",
                "countries"
            ]
        ].head(
            20
        )
    )


# ==========================================================
# RUN
# ==========================================================

if __name__ == "__main__":

    main()