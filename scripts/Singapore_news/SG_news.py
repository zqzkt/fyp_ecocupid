import requests
from bs4 import BeautifulSoup
import pandas as pd
import time
import re
import os

from datetime import datetime, timedelta
from urllib.parse import urljoin

#Settings
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

#Environment Keywords
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

#Asean Country Keywords
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

#Request Headers
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

#Convert API Date
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

#Get one API Page
def get_api_page(page_number):
    #Use the end date as the maximum date.
    #Add one day so that the full END_DATE is included
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

#Discover articles from API
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

            #public articles only
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

        # Stop when this page has already reached articles older than START_DATE
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

        #Optional additional stop using API total
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

#Extract article text

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

#Scrape article page
def scrape_article(article_info):
    url = article_info["url"]
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

        # Text
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
        print(
            e
        )
        return None

#Find environment keywords
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

#Find countries
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

#Main
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

    # STEP 1: Discover historical article URLs
    article_list = (
        get_article_urls()
    )
    if len(article_list) == 0:
        print(
            "No articles discovered."
        )
        return

    # STEP 2: Scrape article content
    results = []
    print()
    print(
        "======================================"
    )
    print(
        "SCRAPING ARTICLE CONTENT"
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

        # Keyword matching
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

        # Keep if environment + ASEAN country match
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

        # STEP 3: Save / Append CSV

    if len(results) == 0:
        print()
        print("No matching articles found.")
        return

    # Convert newly scraped results to DataFrame
    new_df = pd.DataFrame(results)

    # Remove duplicates within the current scraping run
    new_df.drop_duplicates(
        subset=["url"],
        inplace=True
    )

    SCRIPT_DIR = os.path.dirname(
        os.path.abspath(__file__)
    )

    OUTPUT_FILE = os.path.join(
        SCRIPT_DIR,
        "straits_times_environment.csv"
    )

    if os.path.exists(OUTPUT_FILE):

        print()
        print("Existing CSV found.")

        # Read existing CSV
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
            - len(combined_df)
        )

        print(
            f"{duplicates_removed} duplicate "
            "articles removed."
        )


        df = combined_df

    else:

        print()
        print(
            "No existing CSV found. "
            "Creating new CSV."
        )

        df = new_df

    df["published_at"] = pd.to_datetime(
        df["published_at"],
        errors="coerce"
    )

    df = df.sort_values(
        by="published_at",
        ascending=False
    )


    df["published_at"] = (
        df["published_at"]
        .dt.strftime("%Y-%m-%d")
    )

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
        f"{len(new_df)} articles found "
        "in this scraping run."
    )
    print(
        f"{len(df)} total unique articles "
        "are now in the CSV."
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
        ].head(20)
    )

#Run
if __name__ == "__main__":
    main()