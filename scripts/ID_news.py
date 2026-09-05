import requests
from bs4 import BeautifulSoup
import pandas as pd
import time
import re
import os

from datetime import datetime


# ==========================================================
# SETTINGS
# ==========================================================

GRAPHQL_URL = "https://mongabay.co.id/graphql"

BASE_URL = "https://mongabay.co.id"


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
    "mongabay_indonesia_environment.csv"
)


# ----------------------------------------------------------
# Number of articles per GraphQL request
#
# Mongabay currently requests 24
# ----------------------------------------------------------

BATCH_SIZE = 24


# ----------------------------------------------------------
# Safety limit
#
# Prevent accidental infinite pagination
# ----------------------------------------------------------

MAX_BATCHES = 100


# ==========================================================
# ENVIRONMENT KEYWORDS
#
# These are stored as metadata.
#
# We do NOT use them to decide whether a Mongabay article
# is environmental because Mongabay Indonesia itself is
# an environmental publication.
# ==========================================================

ENVIRONMENT_KEYWORDS = [

    # General
    "lingkungan",
    "lingkungan hidup",
    "alam",
    "kelestarian",
    "berkelanjutan",
    "keberlanjutan",

    # Climate
    "perubahan iklim",
    "krisis iklim",
    "pemanasan global",
    "emisi",
    "emisi karbon",
    "karbon",
    "gas rumah kaca",
    "net zero",
    "nol emisi",

    # Forest
    "hutan",
    "deforestasi",
    "kebakaran hutan",
    "karhutla",
    "gambut",
    "restorasi hutan",

    # Biodiversity / wildlife
    "keanekaragaman hayati",
    "biodiversitas",
    "konservasi",
    "satwa liar",
    "habitat",
    "spesies",
    "ekosistem",
    "orangutan",
    "harimau",
    "gajah",
    "mangrove",

    # Pollution
    "pencemaran",
    "polusi",
    "polusi udara",
    "polusi air",
    "kualitas udara",
    "limbah",
    "sampah",
    "plastik",
    "mikroplastik",

    # Energy
    "energi terbarukan",
    "energi bersih",
    "energi fosil",
    "batubara",
    "batu bara",
    "pltu",
    "tenaga surya",
    "panel surya",
    "biodiesel",
    "transisi energi",

    # Mining
    "tambang",
    "pertambangan",
    "nikel",
    "tambang emas",
    "mineral kritis",

    # Agriculture
    "sawit",
    "kelapa sawit",
    "perkebunan",
    "pertanian",
    "ketahanan pangan",

    # Oceans / coastal
    "laut",
    "pesisir",
    "terumbu karang",
    "perikanan",
    "nelayan",
    "abrasi",

    # Disasters
    "banjir",
    "kekeringan",
    "longsor",
    "gelombang panas",
    "cuaca ekstrem",
    "el nino",
    "la nina"
]


# ==========================================================
# INDONESIA KEYWORDS
#
# Metadata only.
#
# We are NOT requiring every article to contain the word
# "Indonesia" because an article about Kalimantan, Papua,
# Riau, etc. is obviously still Indonesia-related.
# ==========================================================

INDONESIA_KEYWORDS = [

    "indonesia",
    "indonesian",

    "jakarta",

    "sumatera",
    "sumatra",

    "jawa",
    "kalimantan",
    "sulawesi",
    "papua",
    "maluku",

    "bali",

    "aceh",
    "riau",
    "jambi",
    "lampung",

    "jawa barat",
    "jawa tengah",
    "jawa timur",

    "kalimantan barat",
    "kalimantan tengah",
    "kalimantan selatan",
    "kalimantan timur",
    "kalimantan utara",

    "sulawesi utara",
    "sulawesi tengah",
    "sulawesi selatan",
    "sulawesi tenggara",

    "papua barat",

    "nusa tenggara",
    "ntt",
    "ntb"
]


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
        "application/json,text/plain,*/*"
    ),

    "Referer":
        "https://mongabay.co.id/"
}


# ==========================================================
# GRAPHQL QUERY
# ==========================================================

def build_graphql_query(cursor=None):

    # ------------------------------------------------------
    # First request:
    #
    # after: null
    #
    # Later requests:
    #
    # after: "YXJyYXlj..."
    # ------------------------------------------------------

    if cursor is None:

        after_value = "null"

    else:

        # Escape quotes just in case
        safe_cursor = (
            cursor
            .replace("\\", "\\\\")
            .replace('"', '\\"')
        )

        after_value = (
            f'"{safe_cursor}"'
        )


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


# ==========================================================
# FETCH ONE GRAPHQL BATCH
# ==========================================================

def fetch_graphql_batch(cursor=None):

    query = build_graphql_query(
        cursor
    )


    try:

        response = requests.get(

            GRAPHQL_URL,

            params={
                "query": query
            },

            headers=HEADERS,

            timeout=30
        )


        print(
            "GraphQL status:",
            response.status_code
        )


        if response.status_code != 200:

            print(
                response.text[:500]
            )

            return None


        data = response.json()


        # --------------------------------------------------
        # GraphQL may return HTTP 200 but still contain errors
        # --------------------------------------------------

        if "errors" in data:

            print(
                "GraphQL errors:"
            )

            print(
                data["errors"]
            )

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

        print(
            "GraphQL request error:",
            e
        )

        return None


# ==========================================================
# PARSE GRAPHQL DATE
# ==========================================================

def parse_graphql_date(date_value):

    if not date_value:

        return None


    try:

        dt = pd.to_datetime(
            date_value
        )


        return (
            dt
            .to_pydatetime()
            .replace(
                tzinfo=None
            )
        )


    except Exception:

        return None


# ==========================================================
# ENVIRONMENT KEYWORDS
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
# INDONESIA REFERENCES
# ==========================================================

def find_indonesia_references(text):

    text = text.lower()

    matches = []


    for keyword in INDONESIA_KEYWORDS:

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
# EXTRACT ARTICLE TEXT
# ==========================================================

def extract_article_text(soup):

    paragraphs = []


    # ------------------------------------------------------
    # Try <article> first
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

        paragraph_tags = (
            soup.find_all(
                "p"
            )
        )


    unwanted_phrases = [

        "mongabay indonesia",

        "ikuti mongabay",

        "newsletter",

        "donasi",

        "copyright",

        "hak cipta",

        "artikel terkait",

        "baca juga",

        "featured image",

        "foto utama",

        "subscribe"
    ]


    for p in paragraph_tags:

        text = p.get_text(
            " ",
            strip=True
        )


        if len(
            text
        ) < 30:

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
# SCRAPE FULL ARTICLE
# ==========================================================

def scrape_article(url):

    try:

        response = requests.get(

            url,

            headers={
                "User-Agent":
                    HEADERS["User-Agent"],

                "Accept":
                    "text/html,application/xhtml+xml,"
                    "application/xml;q=0.9,*/*;q=0.8"
            },

            timeout=30
        )


        if response.status_code != 200:

            print(
                "  Article status:",
                response.status_code
            )

            return None


        soup = BeautifulSoup(
            response.text,
            "html.parser"
        )


        article_text = (
            extract_article_text(
                soup
            )
        )


        if len(
            article_text
        ) < 250:

            print(
                "  Too little usable article text."
            )

            return None


        return article_text


    except Exception as e:

        print(
            "  Article request error:",
            e
        )

        return None


# ==========================================================
# LOAD EXISTING CSV URLS
#
# This means articles already stored will NOT be scraped
# again unnecessarily.
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
        )


    except Exception:

        return set()


# ==========================================================
# PROCESS GRAPHQL NODES
# ==========================================================

def process_nodes(
    edges,
    existing_urls,
    seen_urls,
    results,
    stats
):

    batch_dates = []


    for edge in edges:

        node = edge.get(
            "node"
        )


        if not node:

            continue


        url = node.get(
            "link"
        )


        title = node.get(
            "title"
        )


        date_value = node.get(
            "date"
        )


        typename = node.get(
            "__typename"
        )


        if not url:

            continue


        # --------------------------------------------------
        # Avoid duplicates during this run
        # --------------------------------------------------

        if url in seen_urls:

            continue


        seen_urls.add(
            url
        )


        # --------------------------------------------------
        # Parse date supplied directly by GraphQL
        # --------------------------------------------------

        article_date = (
            parse_graphql_date(
                date_value
            )
        )


        if article_date is None:

            stats[
                "no_date"
            ] += 1

            print()
            print(
                "No valid date:",
                title
            )

            continue


        batch_dates.append(
            article_date
        )


        print()
        print(
            title
        )

        print(
            "  Date:",
            article_date.date()
        )

        print(
            "  Type:",
            typename
        )


        # --------------------------------------------------
        # NEWER THAN REQUESTED RANGE
        # --------------------------------------------------

        if article_date > END_DATE:

            stats[
                "too_new"
            ] += 1

            print(
                "  Newer than END_DATE - skipped"
            )

            continue


        # --------------------------------------------------
        # OLDER THAN REQUESTED RANGE
        # --------------------------------------------------

        if article_date < START_DATE:

            stats[
                "too_old"
            ] += 1

            print(
                "  Older than START_DATE - skipped"
            )

            continue


        # --------------------------------------------------
        # Already saved previously
        #
        # Important:
        # We skip the article page request completely.
        # --------------------------------------------------

        if url in existing_urls:

            stats[
                "already_exists"
            ] += 1

            print(
                "  Already in CSV - skipped"
            )

            continue


        # --------------------------------------------------
        # SCRAPE FULL TEXT
        # --------------------------------------------------

        print(
            "  Scraping full article..."
        )


        article_text = (
            scrape_article(
                url
            )
        )


        if article_text is None:

            stats[
                "failed"
            ] += 1

            continue


        stats[
            "scraped"
        ] += 1


        # --------------------------------------------------
        # Metadata
        # --------------------------------------------------

        combined_text = (

            (title or "")

            + " "

            + article_text
        )


        environment_matches = (
            find_environment_keywords(
                combined_text
            )
        )


        indonesia_matches = (
            find_indonesia_references(
                combined_text
            )
        )


        # --------------------------------------------------
        # Author
        # --------------------------------------------------

        author_names = []


        byline = node.get(
            "byline"
        )


        if byline:

            for author in (
                byline.get(
                    "nodes",
                    []
                )
            ):

                name = author.get(
                    "name"
                )


                if (
                    name
                    and
                    name not in author_names
                ):

                    author_names.append(
                        name
                    )


        # --------------------------------------------------
        # Save
        #
        # We are NOT rejecting articles for missing
        # environment keywords.
        # --------------------------------------------------

        results.append({

            "title":
                title,

            "source":
                "Mongabay Indonesia",

            "published_at":
                article_date.strftime(
                    "%Y-%m-%d"
                ),

            "authors":
                ", ".join(
                    author_names
                ),

            "content_type":
                typename,

            "indonesia_reference":
                len(
                    indonesia_matches
                ) > 0,

            "indonesia_keywords":
                ", ".join(
                    indonesia_matches
                ),

            "environment_keywords":
                ", ".join(
                    environment_matches
                ),

            "article_text":
                article_text,

            "url":
                url
        })


        stats[
            "saved"
        ] += 1


        print(
            "  SAVED"
        )


        print(
            "  Environment keywords:",
            ", ".join(
                environment_matches
            )
            if environment_matches
            else "None"
        )


        print(
            "  Indonesia references:",
            ", ".join(
                indonesia_matches
            )
            if indonesia_matches
            else "None"
        )


        time.sleep(1)


    # ------------------------------------------------------
    # Return oldest date in this GraphQL batch
    # ------------------------------------------------------

    if len(
        batch_dates
    ) == 0:

        return None


    return min(
        batch_dates
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
        "MONGABAY INDONESIA SCRAPER"
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
        "Batch size:",
        BATCH_SIZE
    )


    # ======================================================
    # EXISTING DATA
    # ======================================================

    existing_urls = (
        get_existing_urls()
    )


    print()
    print(
        "Existing URLs in CSV:",
        len(existing_urls)
    )


    # ======================================================
    # TRACKING
    # ======================================================

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

        "saved": 0
    }


    cursor = None

    batch_number = 1


    # ======================================================
    # GRAPHQL PAGINATION
    # ======================================================

    while batch_number <= MAX_BATCHES:


        print()
        print(
            "======================================"
        )

        print(
            f"GRAPHQL BATCH {batch_number}"
        )

        print(
            "======================================"
        )


        content_nodes = (
            fetch_graphql_batch(
                cursor
            )
        )


        if content_nodes is None:

            print(
                "No GraphQL data returned."
            )

            break


        edges = content_nodes.get(
            "edges",
            []
        )


        page_info = content_nodes.get(
            "pageInfo",
            {}
        )


        if len(
            edges
        ) == 0:

            print(
                "No articles returned."
            )

            break


        stats[
            "graphql_nodes"
        ] += len(
            edges
        )


        print(
            "Articles returned:",
            len(edges)
        )


        print(
            "Has next page:",
            page_info.get(
                "hasNextPage"
            )
        )


        print(
            "End cursor:",
            page_info.get(
                "endCursor"
            )
        )


        # --------------------------------------------------
        # Process this batch
        # --------------------------------------------------

        oldest_date = (
            process_nodes(

                edges,

                existing_urls,

                seen_urls,

                results,

                stats
            )
        )


        print()
        print(
            "Oldest date in batch:",
            oldest_date.date()
            if oldest_date
            else "Unknown"
        )


        # ==================================================
        # STOP CONDITION 1
        #
        # Once a batch contains an article older than
        # START_DATE, we have gone far enough backwards.
        # ==================================================

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


        # ==================================================
        # STOP CONDITION 2
        #
        # Mongabay says there is no next page.
        # ==================================================

        has_next_page = (
            page_info.get(
                "hasNextPage",
                False
            )
        )


        if not has_next_page:

            print()
            print(
                "GraphQL reports no next page."
            )

            break


        # ==================================================
        # GET NEXT CURSOR
        # ==================================================

        new_cursor = (
            page_info.get(
                "endCursor"
            )
        )


        if not new_cursor:

            print(
                "No endCursor returned."
            )

            break


        # --------------------------------------------------
        # Prevent an accidental cursor loop
        # --------------------------------------------------

        if new_cursor == cursor:

            print(
                "Cursor did not change."
            )

            print(
                "Stopping to prevent infinite loop."
            )

            break


        cursor = new_cursor

        batch_number += 1


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
        "GraphQL batches processed:",
        batch_number
    )


    print(
        "GraphQL articles encountered:",
        stats[
            "graphql_nodes"
        ]
    )


    print(
        "Unique URLs encountered:",
        len(
            seen_urls
        )
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
        "No valid date:",
        stats[
            "no_date"
        ]
    )


    print(
        "Already in CSV:",
        stats[
            "already_exists"
        ]
    )


    print(
        "Full articles scraped:",
        stats[
            "scraped"
        ]
    )


    print(
        "Failed article scrapes:",
        stats[
            "failed"
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

    if len(
        results
    ) == 0:

        print()
        print(
            "No new articles to append."
        )

        return


    # ======================================================
    # NEW DATAFRAME
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
            "Existing articles:",
            len(
                existing_df
            )
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

            subset=["url"],

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

        print()
        print(
            "No existing CSV."
        )

        print(
            "Creating new CSV."
        )


        df = new_df


    # ======================================================
    # SORT BY DATE
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

    desired_columns = [

        "title",

        "source",

        "published_at",

        "authors",

        "content_type",

        "indonesia_reference",

        "indonesia_keywords",

        "environment_keywords",

        "article_text",

        "url"
    ]


    # ------------------------------------------------------
    # This prevents errors if an older CSV is missing
    # one of the newer columns.
    # ------------------------------------------------------

    for column in desired_columns:

        if column not in df.columns:

            df[
                column
            ] = ""


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
        "Total unique articles stored:",
        len(
            df
        )
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
                "indonesia_reference"
            ]
        ]

        .head(
            20
        )
    )


# ==========================================================
# RUN
# ==========================================================

if __name__ == "__main__":

    main()