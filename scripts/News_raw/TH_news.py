import requests
from bs4 import BeautifulSoup
import pandas as pd
import time
import re
import os
import json

from datetime import datetime
from urllib.parse import urljoin, urlparse, urlunparse

from dotenv import load_dotenv
from supabase import create_client, Client


# ==========================================================
# SETTINGS
# ==========================================================

BASE_URL = "https://www.thaipbs.or.th"
CATEGORY_URL = "https://www.thaipbs.or.th/news/categories/environment"
ARCHIVE_URL = "https://www.thaipbs.or.th/news/categories/environment/archive"


# ----------------------------------------------------------
# Historical date range
# ----------------------------------------------------------

START_DATE = os.getenv("NEWS_START_DATE", "2026-08-01")
END_DATE = os.getenv("NEWS_END_DATE", "2026-08-31")

START_DATE = datetime.strptime(START_DATE, "%Y-%m-%d")
END_DATE = datetime.strptime(END_DATE, "%Y-%m-%d")


# ----------------------------------------------------------
# Supabase
# ----------------------------------------------------------

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

RAW_TABLE = "news_raw"
SOURCE_COUNTRY = "Thailand"
MAX_PAGES = 20
INSERT_BATCH_SIZE = 100


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
    "Accept-Language": "th-TH,th;q=0.9,en-US;q=0.8,en;q=0.7",
    "Connection": "keep-alive"
}

session = requests.Session()
session.headers.update(HEADERS)


# ==========================================================
# ENVIRONMENT KEYWORDS
#
# Metadata only.
#
# Articles are NOT removed if no keyword is found because
# they already come from Thai PBS's Environment category.
# ==========================================================

ENVIRONMENT_KEYWORDS = [
    # Thai - general environment
    "สิ่งแวดล้อม", "ธรรมชาติ", "ทรัพยากรธรรมชาติ", "ระบบนิเวศ",
    "นิเวศ", "ความยั่งยืน", "การพัฒนาที่ยั่งยืน",

    # Climate
    "การเปลี่ยนแปลงสภาพภูมิอากาศ", "สภาพภูมิอากาศ", "โลกร้อน",
    "โลกเดือด", "วิกฤตสภาพภูมิอากาศ", "ก๊าซเรือนกระจก",
    "คาร์บอน", "คาร์บอนสุทธิเป็นศูนย์",

    # Forest
    "ป่า", "ป่าไม้", "ป่าชุมชน", "ป่าสงวน", "ป่าอนุรักษ์",
    "บุกรุกป่า", "ตัดไม้", "ไฟป่า", "เผาป่า", "ฟื้นฟูป่า",

    # Biodiversity
    "ความหลากหลายทางชีวภาพ", "อนุรักษ์", "สัตว์ป่า",
    "สัตว์ใกล้สูญพันธุ์", "พื้นที่คุ้มครอง", "อุทยานแห่งชาติ",

    # Pollution
    "มลพิษ", "มลพิษทางอากาศ", "มลพิษทางน้ำ", "น้ำเสีย",
    "สารพิษ", "สารปนเปื้อน", "ฝุ่น", "ฝุ่นพิษ", "PM2.5", "หมอกควัน",

    # Waste
    "ขยะ", "ขยะพลาสติก", "พลาสติก", "รีไซเคิล",
    "ขยะอุตสาหกรรม", "ของเสีย", "ขยะอิเล็กทรอนิกส์",

    # Water / marine
    "แม่น้ำ", "น้ำ", "ทะเล", "มหาสมุทร", "ชายฝั่ง", "ปะการัง",
    "ปะการังฟอกขาว", "ป่าชายเลน", "ประมง", "พะยูน", "วาฬ", "เต่าทะเล",

    # Energy
    "พลังงานหมุนเวียน", "พลังงานสะอาด", "พลังงานแสงอาทิตย์",
    "พลังงานลม", "ถ่านหิน", "เชื้อเพลิงฟอสซิล",

    # Disaster / weather
    "น้ำท่วม", "ภัยแล้ง", "ดินถล่ม", "คลื่นความร้อน",
    "ระดับน้ำทะเล", "กัดเซาะชายฝั่ง",

    # English - sometimes appears in Thai articles
    "environment", "environmental", "climate change", "global warming",
    "climate crisis", "sustainability", "sustainable", "biodiversity",
    "conservation", "pollution", "air pollution", "water pollution",
    "deforestation", "forest fire", "wildfire", "renewable energy",
    "clean energy", "carbon emissions", "greenhouse gas", "flood",
    "flooding", "drought", "haze", "waste", "plastic pollution"
]


# ==========================================================
# TARGET COUNTRY KEYWORDS
#
# ONLY the six countries included in this project:
#
# - Singapore
# - Malaysia
# - Indonesia
# - Thailand
# - Philippines
# - Brunei
#
# Country detection is metadata only.
# Articles are NOT filtered based on country.
# ==========================================================

ASEAN_COUNTRY_KEYWORDS = {
    "Brunei": [
        "brunei", "bruneian", "brunei darussalam", "bandar seri begawan",
        "บรูไน", "บรูไนดารุสซาลาม", "บันดาร์เสรีเบกาวัน"
    ],

    "Indonesia": [
        "indonesia", "indonesian", "jakarta", "sumatra", "kalimantan",
        "java", "bali", "sulawesi", "อินโดนีเซีย", "จาการ์ตา",
        "สุมาตรา", "กาลิมันตัน", "ชวา", "บาหลี", "สุลาเวสี"
    ],

    "Malaysia": [
        "malaysia", "malaysian", "kuala lumpur", "sarawak", "sabah",
        "johor", "penang", "มาเลเซีย", "กัวลาลัมเปอร์", "ซาราวัก",
        "ซาบาห์", "ยะโฮร์", "ปีนัง"
    ],

    "Philippines": [
        "philippines", "philippine", "filipino", "manila", "luzon",
        "visayas", "mindanao", "ฟิลิปปินส์", "มะนิลา", "ลูซอน",
        "วิซายัส", "มินดาเนา"
    ],

    "Singapore": [
        "singapore", "singaporean", "สิงคโปร์"
    ],

    "Thailand": [
        "thailand", "thai", "bangkok", "ประเทศไทย", "ไทย",
        "กรุงเทพ", "กรุงเทพฯ", "กรุงเทพมหานคร"
    ]
}


# ==========================================================
# THAI MONTHS
# ==========================================================

THAI_MONTHS = {
    "ม.ค.": 1, "มกราคม": 1,
    "ก.พ.": 2, "กุมภาพันธ์": 2,
    "มี.ค.": 3, "มีนาคม": 3,
    "เม.ย.": 4, "เมษายน": 4,
    "พ.ค.": 5, "พฤษภาคม": 5,
    "มิ.ย.": 6, "มิถุนายน": 6,
    "ก.ค.": 7, "กรกฎาคม": 7,
    "ส.ค.": 8, "สิงหาคม": 8,
    "ก.ย.": 9, "กันยายน": 9,
    "ต.ค.": 10, "ตุลาคม": 10,
    "พ.ย.": 11, "พฤศจิกายน": 11,
    "ธ.ค.": 12, "ธันวาคม": 12
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
# VALID ARTICLE URL
# ==========================================================

def is_article_url(url):
    parsed = urlparse(url)

    return bool(
        re.match(
            r"^/news/content/\d+$",
            parsed.path
        )
    )


# ==========================================================
# EXTRACT URLS FROM CATEGORY PAGE
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
# CATEGORY / ARCHIVE PAGE
# ==========================================================

def get_environment_page(page_number):
    if page_number == 1:
        url = CATEGORY_URL
        params = None

    else:
        url = ARCHIVE_URL

        params = {
            "page": page_number
        }

    print()
    print(
        f"Loading Thai PBS Environment page {page_number}..."
    )

    try:
        response = session.get(
            url,
            params=params,
            timeout=30
        )

        print(
            "Status:",
            response.status_code
        )

        if response.status_code != 200:
            print(
                "Environment page request failed."
            )

            print(
                response.text[:300]
            )

            return []

        article_urls = extract_article_urls(
            response.text
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
# CONVERT THAI BUDDHIST YEAR
# ==========================================================

def thai_year_to_gregorian(year):
    year = int(year)

    # 69 -> 2569
    if year < 100:
        year += 2500

    # 2569 -> 2026
    if year > 2400:
        year -= 543

    return year


# ==========================================================
# PARSE THAI DATE
# ==========================================================

def parse_thai_date(text):
    if not text:
        return None

    month_pattern = "|".join(
        sorted(
            map(
                re.escape,
                THAI_MONTHS.keys()
            ),
            key=len,
            reverse=True
        )
    )

    pattern = (
        r"(\d{1,2})"
        r"\s*"
        r"("
        + month_pattern
        + r")"
        r"\s*"
        r"(\d{2,4})"
    )

    match = re.search(
        pattern,
        text
    )

    if not match:
        return None

    try:
        day = int(
            match.group(1)
        )

        month_text = match.group(2)

        month = THAI_MONTHS[
            month_text
        ]

        year = thai_year_to_gregorian(
            match.group(3)
        )

        return datetime(
            year,
            month,
            day
        )

    except Exception:
        return None


# ==========================================================
# JSON-LD HELPERS
# ==========================================================

def get_json_ld_objects(soup):
    objects = []

    scripts = soup.find_all(
        "script",
        attrs={
            "type": "application/ld+json"
        }
    )

    for script in scripts:
        try:
            data = json.loads(
                script.string
                or script.get_text()
            )

            if isinstance(
                data,
                list
            ):
                objects.extend(
                    data
                )

            else:
                objects.append(
                    data
                )

        except Exception:
            continue

    return objects


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

    if (
        meta
        and meta.get("content")
    ):
        return (
            meta["content"]
            .strip()
        )

    return ""


# ==========================================================
# PUBLISHED DATE
# ==========================================================

def extract_published_date(soup):
    # ------------------------------------------------------
    # 1. Standard metadata
    # ------------------------------------------------------

    candidates = [
        soup.find(
            "meta",
            attrs={
                "property": "article:published_time"
            }
        ),

        soup.find(
            "meta",
            attrs={
                "itemprop": "datePublished"
            }
        ),

        soup.find(
            "meta",
            attrs={
                "name": "date"
            }
        )
    ]

    for meta in candidates:
        if (
            meta
            and meta.get(
                "content"
            )
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

    # ------------------------------------------------------
    # 2. JSON-LD datePublished
    # ------------------------------------------------------

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

    # ------------------------------------------------------
    # 3. <time>
    # ------------------------------------------------------

    for time_tag in soup.find_all(
        "time"
    ):
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
    # 4. Visible Thai date
    # ------------------------------------------------------

    page_text = soup.get_text(
        " ",
        strip=True
    )

    return parse_thai_date(
        page_text
    )


# ==========================================================
# ARTICLE BODY FROM JSON-LD
# ==========================================================

def extract_json_ld_article_body(soup):
    for obj in get_json_ld_objects(
        soup
    ):
        for item in walk_json(
            obj
        ):
            article_body = item.get(
                "articleBody"
            )

            if (
                isinstance(
                    article_body,
                    str
                )
                and len(article_body) > 200
            ):
                return (
                    BeautifulSoup(
                        article_body,
                        "html.parser"
                    )
                    .get_text(
                        " ",
                        strip=True
                    )
                )

    return ""


# ==========================================================
# ARTICLE TEXT
# ==========================================================

def extract_article_text(soup):
    # ------------------------------------------------------
    # Best case: JSON-LD articleBody
    # ------------------------------------------------------

    json_text = extract_json_ld_article_body(
        soup
    )

    if len(
        json_text
    ) >= 250:
        return json_text

    # ------------------------------------------------------
    # HTML containers
    # ------------------------------------------------------

    selectors = [
        "[itemprop='articleBody']",
        ".article-content",
        ".news-content",
        ".content-detail",
        ".content-body",
        ".entry-content",
        "article",
        "main"
    ]

    best_paragraphs = []

    unwanted_phrases = [
        "อ่านข่าว :", "อ่านข่าว:", "แท็กที่เกี่ยวข้อง",
        "ข่าวเด่นวันนี้", "ข่าวสิ่งแวดล้อม", "ดูทั้งหมด",
        "อัปเดตข่าวสาร", "ดาวน์โหลดแอปพลิเคชัน",
        "ติดต่อเว็บมาสเตอร์", "จำนวนผู้ชม", "ฟังข่าว",
        "แชร์", "ผู้ช่วย ai", "อ่านให้ฟัง",
        "all rights reserved", "copyright", "subscribe",
        "related news", "related stories", "advertisement"
    ]

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

            lower_text = text.lower()

            if any(
                phrase.lower() in lower_text
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

    # ------------------------------------------------------
    # Fallback: all paragraphs
    # ------------------------------------------------------

    if not best_paragraphs:
        for p in soup.find_all(
            "p"
        ):
            text = p.get_text(
                " ",
                strip=True
            )

            if len(text) < 30:
                continue

            lower_text = text.lower()

            if any(
                phrase.lower() in lower_text
                for phrase in unwanted_phrases
            ):
                continue

            if text not in best_paragraphs:
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
    matches = []

    for keyword in ENVIRONMENT_KEYWORDS:
        if keyword.lower() in lower_text:
            matches.append(
                keyword
            )

    return matches


# ==========================================================
# TARGET COUNTRY DETECTION
#
# Because ASEAN_COUNTRY_KEYWORDS contains only six countries,
# this function can only return those six countries.
# ==========================================================

def find_asean_countries(text):
    lower_text = text.lower()
    countries = []

    for country, keywords in ASEAN_COUNTRY_KEYWORDS.items():
        for keyword in keywords:
            keyword_lower = keyword.lower()

            # Thai text does not use spaces consistently,
            # so simple containment works better here.
            if keyword_lower in lower_text:
                countries.append(
                    country
                )

                break

    return countries


# ==========================================================
# SCRAPE ARTICLE
# ==========================================================

def scrape_article(url):
    print()
    print(url)

    try:
        response = session.get(
            url,
            headers={
                "Referer": CATEGORY_URL
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
        # Title
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
        # Date
        # --------------------------------------------------

        published_date = extract_published_date(
            soup
        )

        if published_date is None:
            print(
                "  No published date - skipped"
            )

            return None

        # --------------------------------------------------
        # Text
        # --------------------------------------------------

        article_text = extract_article_text(
            soup
        )

        if len(article_text) < 200:
            print(
                "  Too little article text:",
                len(article_text)
            )

            return None

        return {
            "title": title,
            "source": "Thai PBS",
            "published_at": published_date,
            "article_text": article_text,
            "url": clean_url(url)
        }

    except Exception as e:
        print(
            "  Error:",
            e
        )

        return None


# ==========================================================
# LOAD EXISTING THAILAND URLS FROM SUPABASE
# ==========================================================

def load_existing_urls():
    print()
    print(
        "Loading existing Thailand URLs from Supabase..."
    )

    existing_urls = set()

    start = 0
    page_size = 1000

    while True:
        try:
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
                url = row.get(
                    "url"
                )

                if url:
                    existing_urls.add(
                        clean_url(url)
                    )

            if len(rows) < page_size:
                break

            start += page_size

        except Exception as e:
            print(
                "Error loading existing Supabase URLs:",
                e
            )

            break

    print(
        "Existing Thailand URLs:",
        len(existing_urls)
    )

    return existing_urls


# ==========================================================
# INSERT ARTICLES INTO SUPABASE
# ==========================================================

def insert_articles(articles):
    if not articles:
        print()
        print(
            "No new articles to insert."
        )

        return 0

    inserted = 0

    for i in range(
        0,
        len(articles),
        INSERT_BATCH_SIZE
    ):
        batch = articles[
            i:i + INSERT_BATCH_SIZE
        ]

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

            print(
                f"Inserted batch of "
                f"{len(batch)} articles."
            )

        except Exception as e:
            print()
            print(
                "Batch insert failed:",
                e
            )

            print(
                "Trying articles one-by-one..."
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
                    print()
                    print(
                        "FAILED INSERT:"
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


# ==========================================================
# PROCESS URLS
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
        # Duplicate within this run
        # --------------------------------------------------

        if url in seen_urls:
            continue

        seen_urls.add(
            url
        )

        # --------------------------------------------------
        # Already in Supabase
        # --------------------------------------------------

        if url in existing_urls:
            stats[
                "already_exists"
            ] += 1

            print(
                "Already in Supabase:",
                url
            )

            continue

        # --------------------------------------------------
        # Scrape
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

        # --------------------------------------------------
        # Date filter
        # --------------------------------------------------

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

        # --------------------------------------------------
        # Country + environmental metadata
        # --------------------------------------------------

        combined_text = (
            article["title"]
            + " "
            + article["article_text"]
        )

        target_countries = find_asean_countries(
            combined_text
        )

        environment_matches = find_environment_keywords(
            combined_text
        )

        # --------------------------------------------------
        # Map to shared news_raw Supabase schema
        #
        # IMPORTANT:
        # news_id and scraped_at are NOT supplied.
        # Supabase generates them automatically.
        # --------------------------------------------------

        supabase_article = {
            "source_country": SOURCE_COUNTRY,
            "title": article["title"],
            "source": article["source"],
            "published_at": article_date.isoformat(),
            "countries": ", ".join(
                target_countries
            ),
            "environment_keywords": ", ".join(
                environment_matches
            ),
            "article_text": article["article_text"],
            "url": article["url"]
        }

        # --------------------------------------------------
        # IMPORTANT:
        #
        # Do NOT require Thailand.
        #
        # Thai PBS Environment may contain regional/global
        # environmental stories. "countries" is metadata.
        #
        # However, countries can now ONLY contain:
        # Singapore, Malaysia, Indonesia, Thailand,
        # Philippines or Brunei.
        # --------------------------------------------------

        results.append(
            supabase_article
        )

        stats[
            "saved"
        ] += 1

        print(
            "  READY FOR SUPABASE"
        )

        print(
            "  Target countries:",
            supabase_article[
                "countries"
            ]
            if supabase_article[
                "countries"
            ]
            else "None"
        )

        print(
            "  Environment keywords:",
            supabase_article[
                "environment_keywords"
            ]
            if supabase_article[
                "environment_keywords"
            ]
            else "None"
        )

        time.sleep(1)

    if not page_dates:
        return None

    return min(
        page_dates
    )


# ==========================================================
# MAIN
# ==========================================================

def main():
    print()
    print("======================================")
    print("THAI PBS ENVIRONMENT SCRAPER")
    print("======================================")

    print(
        "Start:",
        START_DATE.date()
    )

    print(
        "End:",
        END_DATE.date()
    )

    print(
        "Source country:",
        SOURCE_COUNTRY
    )

    print(
        "Destination:",
        "Supabase news_raw"
    )

    # ------------------------------------------------------
    # Existing Supabase URLs
    # ------------------------------------------------------

    existing_urls = load_existing_urls()

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
    # PAGINATION
    # ======================================================

    for page_number in range(
        1,
        MAX_PAGES + 1
    ):
        urls = get_environment_page(
            page_number
        )

        if not urls:
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
        # Stop once archive has passed START_DATE
        # --------------------------------------------------

        if (
            oldest_date is not None
            and oldest_date < START_DATE
        ):
            print()
            print(
                "Reached articles older than START_DATE."
            )

            print(
                "Stopping pagination."
            )

            break

        time.sleep(1)

    # ======================================================
    # REMOVE DUPLICATES WITHIN CURRENT RUN
    # ======================================================

    unique_results = {}

    for article in results:
        unique_results[
            article["url"]
        ] = article

    results = list(
        unique_results.values()
    )

    # ======================================================
    # INSERT INTO SUPABASE
    # ======================================================

    print()
    print("======================================")
    print("INSERTING INTO SUPABASE")
    print("======================================")

    inserted = insert_articles(
        results
    )

    # ======================================================
    # SUMMARY
    # ======================================================

    print()
    print("======================================")
    print("SCRAPING SUMMARY")
    print("======================================")

    print(
        "Unique URLs encountered:",
        len(seen_urls)
    )

    print(
        "Successfully scraped:",
        stats["scraped"]
    )

    print(
        "Failed:",
        stats["failed"]
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
        "Already in Supabase:",
        stats["already_exists"]
    )

    print(
        "Valid articles:",
        stats["saved"]
    )

    print(
        "Inserted into Supabase:",
        inserted
    )

    print()
    print("======================================")
    print("FINISHED")
    print("======================================")


# ==========================================================
# RUN
# ==========================================================

if __name__ == "__main__":
    main()