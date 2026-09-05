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

BASE_URL = "https://www.pelitabrunei.gov.bn"

CATEGORY_URLS = {
    "Nasional":
        "https://www.pelitabrunei.gov.bn/berita/nasional"
}


# ----------------------------------------------------------
# Historical range
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
    "pelita_brunei_environment.csv"
)

MAX_PAGES = 20


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

    "Accept-Language": (
        "ms-MY,ms;q=0.9,en-US;q=0.8,en;q=0.7"
    ),

    "Connection": "keep-alive"
}


session = requests.Session()
session.headers.update(HEADERS)


# ==========================================================
# ENVIRONMENT KEYWORDS
#
# At least one environmental keyword must be present.
# ==========================================================

ENVIRONMENT_KEYWORDS = [

    # General
    "alam sekitar",
    "kelestarian",
    "lestari",
    "mampan",
    "kemampanan",
    "sustainability",
    "sustainable",
    "environment",
    "environmental",

    # Climate
    "perubahan iklim",
    "krisis iklim",
    "pemanasan global",
    "iklim global",
    "tindakan iklim",
    "ketahanan iklim",
    "adaptasi iklim",
    "mitigasi iklim",
    "cuaca ekstrem",
    "cuaca melampau",
    "climate change",
    "climate crisis",
    "global warming",

    # Carbon
    "karbon",
    "pelepasan karbon",
    "emisi karbon",
    "gas rumah hijau",
    "neutral karbon",
    "sifar bersih",
    "net zero",
    "carbon emissions",
    "greenhouse gas",

    # Forest
    "hutan",
    "kebakaran hutan",
    "kebakaran hutan dan lahan",
    "penebangan hutan",
    "penebangan pokok",
    "pembalakan",
    "pemulihan hutan",
    "penghutanan semula",
    "deforestasi",
    "deforestation",
    "forest fire",
    "wildfire",
    "reforestation",

    # Biodiversity
    "biodiversiti",
    "kepelbagaian biologi",
    "pemuliharaan",
    "konservasi",
    "hidupan liar",
    "spesies terancam",
    "habitat",
    "ekosistem",
    "kawasan perlindungan",
    "biodiversity",
    "conservation",
    "wildlife",
    "ecosystem",

    # Pollution
    "pencemaran",
    "pencemaran udara",
    "pencemaran air",
    "pencemaran laut",
    "kualiti udara",
    "jerebu",
    "asap jerebu",
    "pm2.5",
    "bahan pencemar",
    "pollution",
    "air pollution",
    "water pollution",
    "haze",

    # Waste
    "sisa",
    "sisa pepejal",
    "e-sisa",
    "sisa elektronik",
    "sampah",
    "sampah sarap",
    "sisa plastik",
    "plastik",
    "kitar semula",
    "pelupusan sisa",
    "pengurusan sisa",
    "waste",
    "plastic waste",
    "plastic pollution",
    "recycling",
    "e-waste",

    # Water
    "sumber air",
    "kualiti air",
    "keselamatan air",
    "pemuliharaan air",
    "sungai",
    "tasik",
    "air tercemar",
    "water conservation",
    "water security",

    # Marine
    "alam sekitar marin",
    "ekosistem marin",
    "marin",
    "laut",
    "lautan",
    "pesisir",
    "pantai",
    "hakisan pantai",
    "terumbu karang",
    "karang",
    "bakau",
    "paya bakau",
    "perikanan",
    "marine",
    "ocean",
    "coastal",
    "coral reef",
    "mangrove",

    # Energy
    "tenaga boleh diperbaharui",
    "tenaga diperbaharui",
    "tenaga bersih",
    "tenaga solar",
    "tenaga suria",
    "tenaga angin",
    "peralihan tenaga",
    "bahan api fosil",
    "arang batu",
    "renewable energy",
    "clean energy",
    "solar energy",
    "wind energy",
    "fossil fuel",

    # Disaster
    "banjir",
    "risiko banjir",
    "mitigasi banjir",
    "kemarau",
    "tanah runtuh",
    "gelombang haba",
    "kenaikan paras laut",
    "paras laut meningkat",
    "hakisan",
    "flood",
    "flooding",
    "drought",
    "landslide",
    "heatwave",
    "sea level rise",

    # Nature
    "flora",
    "fauna",
    "tumbuhan hijau",
    "sumber semula jadi",
    "sumber asli",
    "ekologi",
    "ecology",

    # Brunei environment agencies/programmes
    "jastre",
    "jabatan alam sekitar, taman dan rekreasi",
    "jabatan alam sekitar",
    "brunei climate change secretariat",
    "bccs",
    "brunei darussalam national council on climate change",
    "bdnccc"
]


# ==========================================================
# ASEAN COUNTRY KEYWORDS
#
# Brunei MUST be detected for the article to be saved.
# Other ASEAN countries are still recorded as metadata.
# ==========================================================

ASEAN_COUNTRY_KEYWORDS = {

    "Brunei": [
        "brunei",
        "brunei darussalam",
        "negara brunei darussalam",
        "nbd",
        "bruneian",
        "bandar seri begawan",
        "tutong",
        "temburong",
        "belait",
        "kuala belait",
        "seria",
        "muara",
        "berakas",
        "jerudong"
    ],

    "Cambodia": [
        "cambodia",
        "cambodian",
        "kemboja",
        "phnom penh"
    ],

    "Indonesia": [
        "indonesia",
        "indonesian",
        "jakarta",
        "sumatra",
        "sumatera",
        "kalimantan",
        "jawa",
        "java",
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
        "kuala lumpur",
        "johor",
        "selangor",
        "sabah",
        "sarawak",
        "penang",
        "pulau pinang",
        "pahang",
        "kelantan",
        "terengganu",
        "perak",
        "kedah",
        "melaka"
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
        "filipina",
        "manila",
        "luzon",
        "visayas",
        "mindanao",
        "cebu",
        "palawan",
        "davao"
    ],

    "Singapore": [
        "singapore",
        "singapura",
        "singaporean"
    ],

    "Thailand": [
        "thailand",
        "thai",
        "bangkok"
    ],

    "Vietnam": [
        "vietnam",
        "vietnamese",
        "hanoi",
        "ho chi minh"
    ]
}


# ==========================================================
# MALAY MONTHS
# ==========================================================

MALAY_MONTHS = {
    "jan": 1,
    "januari": 1,
    "feb": 2,
    "februari": 2,
    "mac": 3,
    "apr": 4,
    "april": 4,
    "mei": 5,
    "jun": 6,
    "jul": 7,
    "julai": 7,
    "og": 8,
    "ogos": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "okt": 10,
    "oktober": 10,
    "nov": 11,
    "november": 11,
    "dis": 12,
    "disember": 12
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
# CHECK ARTICLE URL
# ==========================================================

def is_article_url(url):

    path = urlparse(
        url
    ).path.lower().rstrip("/")

    prefixes = [
        "/berita/nasional/",
        "/berita/global/",
        "/berita/rencana/"
    ]

    return any(
        path.startswith(prefix)
        and
        len(path) > len(prefix)

        for prefix in prefixes
    )


# ==========================================================
# EXTRACT ARTICLE URLS
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

        full_url = clean_url(
            urljoin(
                BASE_URL,
                link["href"]
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
# LOAD CATEGORY PAGE
# ==========================================================

def get_category_page(
    category_name,
    category_url,
    page_number
):

    print()
    print(
        f"Loading {category_name} page {page_number}..."
    )


    try:

        response = session.get(
            category_url,
            params={
                "page": page_number
            },
            timeout=30
        )


        print(
            "Status:",
            response.status_code
        )


        if response.status_code != 200:

            print(
                "Category request failed."
            )

            return []


        urls = extract_article_urls(
            response.text
        )


        print(
            "Article URLs found:",
            len(urls)
        )


        return urls


    except Exception as e:

        print(
            "Category page error:",
            e
        )

        return []


# ==========================================================
# TITLE
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
            "property": "og:title"
        }
    )


    if meta and meta.get(
        "content"
    ):

        return meta[
            "content"
        ].strip()


    return ""


# ==========================================================
# JSON-LD
# ==========================================================

def get_json_ld_objects(soup):

    results = []


    for script in soup.find_all(
        "script",
        attrs={
            "type": "application/ld+json"
        }
    ):

        try:

            data = json.loads(
                script.string
                or
                script.get_text()
            )

            if isinstance(
                data,
                list
            ):
                results.extend(
                    data
                )

            else:
                results.append(
                    data
                )

        except Exception:
            continue


    return results


def walk_json(data):

    if isinstance(
        data,
        dict
    ):

        yield data

        for value in data.values():

            yield from walk_json(
                value
            )


    elif isinstance(
        data,
        list
    ):

        for value in data:

            yield from walk_json(
                value
            )


# ==========================================================
# MALAY DATE
# ==========================================================

def parse_malay_date(text):

    if not text:
        return None


    pattern = (
        r"\b"
        r"(\d{1,2})"
        r"\s+"
        r"([A-Za-z]+)"
        r"\s+"
        r"(\d{4})"
        r"\b"
    )


    for match in re.finditer(
        pattern,
        text
    ):

        month_text = (
            match.group(2)
            .lower()
        )


        if month_text not in (
            MALAY_MONTHS
        ):
            continue


        try:

            return datetime(
                int(match.group(3)),
                MALAY_MONTHS[
                    month_text
                ],
                int(match.group(1))
            )

        except Exception:
            continue


    return None


# ==========================================================
# PUBLISHED DATE
# ==========================================================

def extract_published_date(soup):

    candidates = [

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
                "itemprop":
                    "datePublished"
            }
        ),

        soup.find(
            "meta",
            attrs={
                "name":
                    "date"
            }
        )
    ]


    for meta in candidates:

        if (
            meta
            and
            meta.get("content")
        ):

            try:

                dt = pd.to_datetime(
                    meta["content"]
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


    for obj in get_json_ld_objects(
        soup
    ):

        for item in walk_json(
            obj
        ):

            value = item.get(
                "datePublished"
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


    page_text = soup.get_text(
        " ",
        strip=True
    )

    return parse_malay_date(
        page_text
    )


# ==========================================================
# AUTHOR
# ==========================================================

def extract_author(soup):

    meta = soup.find(
        "meta",
        attrs={
            "name": "author"
        }
    )


    if meta and meta.get(
        "content"
    ):

        return meta[
            "content"
        ].strip()


    page_text = soup.get_text(
        "\n",
        strip=True
    )


    patterns = [
        r"Oleh\s*:\s*([^\n]+)",
        r"Siaran Akhbar dan Foto\s*:\s*([^\n]+)",
        r"Siaran Akhbar\s*:\s*([^\n]+)"
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

            if len(author) < 200:

                return author


    return ""


# ==========================================================
# ARTICLE TEXT
# ==========================================================

def extract_article_text(soup):

    selectors = [
        "[itemprop='articleBody']",
        ".article-content",
        ".article-body",
        ".news-content",
        ".entry-content",
        ".content-body",
        "article",
        "main"
    ]


    unwanted_phrases = [
        "bagi siaran akhbar",
        "bagi liputan",
        "bagi rencana",
        "bagi iklan",
        "pelita.brunei@information.gov.bn",
        "bahagian pelita brunei",
        "jabatan penerangan",
        "copyright ©",
        "all rights reserved",
        "jawatan kosong",
        "iklan tawaran",
        "berita terkini"
    ]


    best_paragraphs = []


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

            text = p.get_text(
                " ",
                strip=True
            )

            if len(text) < 25:
                continue


            if any(
                phrase in text.lower()
                for phrase in unwanted_phrases
            ):
                continue


            if text not in paragraphs:

                paragraphs.append(
                    text
                )


        if len(
            " ".join(paragraphs)
        ) > len(
            " ".join(best_paragraphs)
        ):

            best_paragraphs = paragraphs


    if not best_paragraphs:

        for p in soup.find_all(
            "p"
        ):

            text = p.get_text(
                " ",
                strip=True
            )

            if len(text) >= 25:

                best_paragraphs.append(
                    text
                )


    return " ".join(
        best_paragraphs
    )


# ==========================================================
# ENVIRONMENT KEYWORDS
# ==========================================================

def find_environment_keywords(text):

    lower_text = text.lower()

    return [
        keyword

        for keyword in ENVIRONMENT_KEYWORDS

        if keyword.lower()
        in lower_text
    ]


# ==========================================================
# ASEAN COUNTRIES
# ==========================================================

def find_asean_countries(text):

    lower_text = text.lower()

    countries = []


    for country, keywords in (
        ASEAN_COUNTRY_KEYWORDS.items()
    ):

        if any(
            keyword.lower()
            in lower_text

            for keyword in keywords
        ):

            countries.append(
                country
            )


    return countries


# ==========================================================
# SCRAPE ARTICLE
#
# NEW RULE:
#
# 1. Must be environmental
# 2. Must relate to Brunei
# ==========================================================

def scrape_article(
    url,
    category
):

    print()
    print(
        url
    )


    try:

        response = session.get(
            url,
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


        title = extract_title(
            soup
        )


        if not title:

            print(
                "  No title - skipped"
            )

            return None


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


        article_text = (
            extract_article_text(
                soup
            )
        )


        if len(article_text) < 200:

            print(
                "  Too little article text:",
                len(article_text)
            )

            return None


        # ==================================================
        # CHECK ENVIRONMENT + BRUNEI RELEVANCE
        # ==================================================

        combined_text = (
            title
            + " "
            + article_text
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


        # --------------------------------------------------
        # Must be environmental
        # --------------------------------------------------

        if not environment_matches:

            print(
                "  Not environmental - skipped"
            )

            return {
                "keep": False,
                "reason": "not_environmental",
                "published_at": published_date
            }


        # --------------------------------------------------
        # Must relate to Brunei
        # --------------------------------------------------

        if "Brunei" not in asean_countries:

            print(
                "  Environmental but not related "
                "to Brunei - skipped"
            )

            return {
                "keep": False,
                "reason": "not_brunei",
                "published_at": published_date
            }


        # --------------------------------------------------
        # Article qualifies
        # --------------------------------------------------

        author = extract_author(
            soup
        )


        return {

            "keep": True,

            "title":
                title,

            "source":
                "Pelita Brunei",

            "category":
                category,

            "published_at":
                published_date,

            "author":
                author,

            "asean_countries":
                ", ".join(
                    asean_countries
                ),

            "environment_keywords":
                ", ".join(
                    environment_matches
                ),

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
# EXISTING CSV
# ==========================================================

def load_existing_data():

    if not os.path.exists(
        OUTPUT_FILE
    ):

        return (
            pd.DataFrame(),
            set()
        )


    try:

        existing_df = pd.read_csv(
            OUTPUT_FILE
        )


        if "url" not in (
            existing_df.columns
        ):

            return (
                existing_df,
                set()
            )


        existing_urls = set(

            existing_df[
                "url"
            ]

            .dropna()

            .astype(str)

            .apply(
                clean_url
            )
        )


        return (
            existing_df,
            existing_urls
        )


    except Exception as e:

        print(
            "Could not read existing CSV:",
            e
        )

        return (
            pd.DataFrame(),
            set()
        )


# ==========================================================
# MAIN
# ==========================================================

def main():

    print()
    print(
        "========================================"
    )

    print(
        "PELITA BRUNEI ENVIRONMENT SCRAPER"
    )

    print(
        "========================================"
    )

    print(
        "Start:",
        START_DATE.date()
    )

    print(
        "End:",
        END_DATE.date()
    )


    output_directory = os.path.dirname(
        OUTPUT_FILE
    )


    if output_directory:

        os.makedirs(
            output_directory,
            exist_ok=True
        )


    (
        existing_df,
        existing_urls

    ) = load_existing_data()


    print(
        "Existing URLs:",
        len(existing_urls)
    )


    results = []
    seen_urls = set()


    stats = {
        "scraped": 0,
        "saved": 0,
        "not_environmental": 0,
        "not_brunei": 0,
        "too_new": 0,
        "too_old": 0,
        "failed": 0,
        "already_exists": 0
    }


    # ======================================================
    # EACH CATEGORY
    # ======================================================

    for category_name, category_url in (
        CATEGORY_URLS.items()
    ):

        print()
        print(
            "========================================"
        )

        print(
            "CATEGORY:",
            category_name
        )

        print(
            "========================================"
        )


        for page_number in range(
            1,
            MAX_PAGES + 1
        ):

            urls = get_category_page(
                category_name,
                category_url,
                page_number
            )


            if not urls:

                print(
                    "No article URLs returned."
                )

                break


            page_dates = []


            for url in urls:

                url = clean_url(
                    url
                )


                if url in seen_urls:
                    continue


                seen_urls.add(
                    url
                )


                if url in existing_urls:

                    stats[
                        "already_exists"
                    ] += 1

                    print(
                        "Already in CSV:",
                        url
                    )

                    continue


                article = scrape_article(
                    url,
                    category_name
                )


                if article is None:

                    stats[
                        "failed"
                    ] += 1

                    continue


                stats[
                    "scraped"
                ] += 1


                article_date = article[
                    "published_at"
                ]


                page_dates.append(
                    article_date
                )


                print(
                    "  Date:",
                    article_date.date()
                )


                # ------------------------------------------
                # DATE FILTER
                # ------------------------------------------

                if article_date > END_DATE:

                    stats[
                        "too_new"
                    ] += 1

                    print(
                        "  Newer than END_DATE"
                    )

                    continue


                if article_date < START_DATE:

                    stats[
                        "too_old"
                    ] += 1

                    print(
                        "  Older than START_DATE"
                    )

                    continue


                # ------------------------------------------
                # RELEVANCE FILTER
                # ------------------------------------------

                if not article.get(
                    "keep"
                ):

                    reason = article.get(
                        "reason"
                    )


                    if reason == (
                        "not_environmental"
                    ):

                        stats[
                            "not_environmental"
                        ] += 1


                    elif reason == (
                        "not_brunei"
                    ):

                        stats[
                            "not_brunei"
                        ] += 1


                    continue


                # ------------------------------------------
                # SAVE
                # ------------------------------------------

                article[
                    "published_at"
                ] = article_date.strftime(
                    "%Y-%m-%d"
                )


                article.pop(
                    "keep",
                    None
                )


                article.pop(
                    "reason",
                    None
                )


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
                )


                print(
                    "  Environment keywords:",
                    article[
                        "environment_keywords"
                    ]
                )


                time.sleep(1)


            # ----------------------------------------------
            # STOP IF PAGE IS ALREADY OLDER THAN START DATE
            # ----------------------------------------------

            if page_dates:

                oldest_date = min(
                    page_dates
                )


                print()
                print(
                    "Oldest date on page:",
                    oldest_date.date()
                )


                if oldest_date < START_DATE:

                    print(
                        "Reached articles older "
                        "than START_DATE."
                    )

                    print(
                        "Stopping this category."
                    )

                    break


            time.sleep(1)


    # ======================================================
    # SUMMARY
    # ======================================================

    print()
    print(
        "========================================"
    )

    print(
        "SCRAPING SUMMARY"
    )

    print(
        "========================================"
    )


    print(
        "Unique URLs encountered:",
        len(seen_urls)
    )

    print(
        "Successfully scraped:",
        stats["scraped"]
    )

    print(
        "Not environmental:",
        stats["not_environmental"]
    )

    print(
        "Environmental but not Brunei:",
        stats["not_brunei"]
    )

    print(
        "Newer than END_DATE:",
        stats["too_new"]
    )

    print(
        "Older than START_DATE:",
        stats["too_old"]
    )

    print(
        "Already in CSV:",
        stats["already_exists"]
    )

    print(
        "Failed:",
        stats["failed"]
    )

    print(
        "New Brunei environment articles:",
        stats["saved"]
    )


    # ======================================================
    # NOTHING NEW
    # ======================================================

    if not results:

        print()
        print(
            "No new Brunei-related "
            "environmental articles to append."
        )

        return


    # ======================================================
    # DATAFRAME
    # ======================================================

    new_df = pd.DataFrame(
        results
    )


    new_df.drop_duplicates(
        subset=["url"],
        keep="first",
        inplace=True
    )


    # ======================================================
    # APPEND EXISTING
    # ======================================================

    if not existing_df.empty:

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
            subset=["url"],
            keep="first",
            inplace=True
        )


        print(
            "Duplicates removed:",
            before
            - len(combined_df)
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
        df["published_at"],
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
        df["published_at"]
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
        "category",
        "published_at",
        "author",
        "asean_countries",
        "environment_keywords",
        "article_text",
        "url"
    ]


    for column in desired_columns:

        if column not in df.columns:

            df[column] = ""


    df = df[
        desired_columns
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
        "========================================"
    )

    print(
        "FINISHED"
    )

    print(
        "========================================"
    )


    print(
        "New articles this run:",
        len(new_df)
    )

    print(
        "Total unique articles:",
        len(df)
    )

    print(
        "Saved:",
        OUTPUT_FILE
    )


if __name__ == "__main__":

    main()