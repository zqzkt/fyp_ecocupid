import os
import json
import re
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from collections import Counter, defaultdict

import pandas as pd
from dotenv import load_dotenv
from apify_client import ApifyClient


# =========================================================
# PATHS + ENVIRONMENT
# =========================================================

# facebook.py is in:
# repo/scripts/sources/facebook.py
# Therefore parents[2] = repo root
REPO_ROOT = Path(__file__).resolve().parents[2]

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

load_dotenv(REPO_ROOT / ".env")

APIFY_TOKEN = os.getenv("APIFY_TOKEN")
client = ApifyClient(APIFY_TOKEN) if APIFY_TOKEN else None


# =========================================================
# APIFY ACTORS
# =========================================================

POSTS_ACTOR = "apify/facebook-posts-scraper"
COMMENTS_ACTOR = "apify/facebook-comments-scraper"


# =========================================================
# SCRAPING CONFIGURATION
# =========================================================

POST_LIMIT_PER_PAGE = 25
COMMENT_LIMIT_PER_POST = 10


def previous_calendar_month():
    """Return the exact previous calendar month as UTC timestamps."""

    today = datetime.now(timezone.utc).date()
    current_month_start = today.replace(day=1)
    previous_month_end = current_month_start - pd.Timedelta(days=1)
    previous_month_start = previous_month_end.replace(day=1)

    return (
        pd.Timestamp(previous_month_start, tz="UTC"),
        pd.Timestamp(current_month_start, tz="UTC"),
    )


MONTH_START, CURRENT_MONTH_START = previous_calendar_month()
POST_DATE_RANGE = MONTH_START.date().isoformat()

# Maximum number of selected posts from the same topic.
MAX_POSTS_PER_TOPIC_FOR_COMMENTS = 4

# Maximum total number of posts whose comments we scrape.
MAX_TOTAL_POSTS_FOR_COMMENTS = 25


# =========================================================
# APIFY COST SAFETY
# =========================================================

POST_RUN_MAX_COST_USD = 2.00
COMMENT_RUN_MAX_COST_USD = 1.00


# =========================================================
# CACHE + UPLOAD SETTINGS
# =========================================================

# Keep these True while improving classification so that
# no additional Apify charges are incurred.
USE_CACHED_POSTS = True
USE_CACHED_COMMENTS = True

# Set FACEBOOK_OFFLINE_TEST=1 to run only against existing local caches.
# This mode refuses fresh Apify requests and skips Supabase uploads.
OFFLINE_TEST_MODE = os.getenv(
    "FACEBOOK_OFFLINE_TEST",
    "0",
).lower() in {"1", "true", "yes"}

# Supabase already contains the Facebook tables, so keeping
# this True will upsert the newly classified posts/comments.
UPLOAD_TO_SUPABASE = True

DATA_DIR = REPO_ROOT / "data" / "raw"

POSTS_CACHE_FILE = DATA_DIR / "facebook_posts_raw.json"
COMMENTS_CACHE_FILE = DATA_DIR / "facebook_comments_raw.json"

ENVIRONMENTAL_POSTS_FILE = (
    DATA_DIR / "facebook_posts_environmental.json"
)

REJECTED_POSTS_FILE = (
    DATA_DIR / "facebook_posts_rejected.json"
)

NORMALISED_POSTS_FILE = (
    DATA_DIR / "facebook_posts_normalised.json"
)

NORMALISED_COMMENTS_FILE = (
    DATA_DIR / "facebook_comments_normalised.json"
)

SCRIPT_DIR = Path(__file__).resolve().parent
POSTS_CSV = SCRIPT_DIR / "facebook_posts.csv"
COMMENTS_CSV = SCRIPT_DIR / "facebook_comments.csv"


# =========================================================
# FACEBOOK SOURCES
# =========================================================

FACEBOOK_SOURCES = [
    # Singapore
    {
        "country": "Singapore",
        "source_name": "NEA Singapore",
        "url": "https://www.facebook.com/NEASingapore",
    },
    {
        "country": "Singapore",
        "source_name": "NParks",
        "url": "https://www.facebook.com/nparksbuzz",
    },
    {
        "country": "Singapore",
        "source_name": "Eco-Business",
        "url": "https://www.facebook.com/ecobusinesscom",
    },

    # Malaysia
    {
        "country": "Malaysia",
        "source_name": "WWF Malaysia",
        "url": "https://www.facebook.com/wwfmy",
    },
    {
        "country": "Malaysia",
        "source_name": "Friends of the Earth Malaysia",
        "url": "https://www.facebook.com/FriendsoftheEarthMalaysia",
    },
    {
        "country": "Malaysia",
        "source_name": "Malaysian Nature Society",
        "url": "https://www.facebook.com/MalaysianNatureSociety.Official",
    },

    # Indonesia
    {
        "country": "Indonesia",
        "source_name": "WALHI",
        "url": "https://www.facebook.com/WALHI",
    },
    {
        "country": "Indonesia",
        "source_name": "WWF Indonesia",
        "url": "https://www.facebook.com/WWFIndonesia",
    },
    {
        "country": "Indonesia",
        "source_name": "Mongabay Indonesia",
        "url": "https://www.facebook.com/MongabayIndonesia",
    },

    # Philippines
    {
        "country": "Philippines",
        "source_name": "DENR Philippines",
        "url": "https://www.facebook.com/DENROfficial",
    },
    {
        "country": "Philippines",
        "source_name": "Haribon Foundation",
        "url": "https://www.facebook.com/GoHaribon",
    },
    {
        "country": "Philippines",
        "source_name": "Climate Change Commission",
        "url": "https://www.facebook.com/CCCPhl",
    },

    # Thailand
    {
        "country": "Thailand",
        "source_name": "Greenpeace Thailand",
        "url": "https://www.facebook.com/greenpeaceth",
    },
    {
        "country": "Thailand",
        "source_name": "WWF Thailand",
        "url": "https://www.facebook.com/wwfthailand",
    },
    {
        "country": "Thailand",
        "source_name": "EnLAW",
        "url": "https://www.facebook.com/Enlawthai2001",
    },

    # Brunei
    {
        "country": "Brunei",
        "source_name": "Brunei Nature Society",
        "url": "https://www.facebook.com/BruneiNatureSociety",
    },
    {
        "country": "Brunei",
        "source_name": "Green Brunei",
        "url": "https://www.facebook.com/GreenBrunei",
    },
    {
        "country": "Brunei",
        "source_name": "Beach Bunch",
        "url": "https://www.facebook.com/beachbunch",
    },
]


# =========================================================
# ENVIRONMENTAL TOPICS
# =========================================================

# The original classifier was mainly English-only. This version
# includes terms observed in the cached ASEAN Facebook data,
# especially Malay/Indonesian, Thai and Vietnamese.
#
# Important: these are classification keywords, not translations
# shown to end users.

ENVIRONMENT_TOPICS = {

    "air_pollution_haze": [
        # English
        "haze",
        "air pollution",
        "air quality",
        "pm2.5",
        "psi",
        "smoke haze",
        "smoke plume",
        "clean air",

        # Malay / Indonesian
        "jerebu",
        "pencemaran udara",
        "kualiti udara",
        "kabut asap",
        "polusi udara",
        "udara bersih",
        "asap karhutla",

        # Thai
        "มลพิษทางอากาศ",
        "ฝุ่น pm2.5",
        "ฝุ่นพิษ",
        "อากาศสะอาด",
        "หมอกควัน",

        # Vietnamese
        "ô nhiễm không khí",
        "chất lượng không khí",
        "không khí sạch",

        # Filipino
        "polusyon sa hangin",
        "malinis na hangin",
    ],

    "climate_change_heat": [
        # English
        "climate change",
        "global warming",
        "climate crisis",
        "climate emergency",
        "climate action",
        "extreme heat",
        "heatwave",
        "heat wave",
        "rising temperature",
        "climate adaptation",
        "climate resilience",
        "extreme weather",

        # Malay / Indonesian
        "perubahan iklim",
        "pemanasan global",
        "krisis iklim",
        "cuaca ekstrem",
        "gelombang haba",
        "gelombang panas",

        # Thai
        "การเปลี่ยนแปลงสภาพภูมิอากาศ",
        "ภาวะโลกร้อน",
        "โลกร้อน",
        "วิกฤตสภาพภูมิอากาศ",
        "คลื่นความร้อน",

        # Vietnamese
        "biến đổi khí hậu",
        "nóng lên toàn cầu",
        "khủng hoảng khí hậu",
        "nắng nóng cực đoan",

        # Filipino
        "pagbabago ng klima",
    ],

    "waste_recycling": [
        # English
        "recycling",
        "recycle",
        "plastic waste",
        "plastic pollution",
        "food waste",
        "e-waste",
        "electronic waste",
        "single-use plastic",
        "single use plastic",
        "waste reduction",
        "zero waste",
        "circular economy",
        "litter",
        "littering",
        "trash",
        "marine debris",

        # Malay / Indonesian
        "kitar semula",
        "sisa plastik",
        "sampah plastik",
        "sisa makanan",
        "pencemaran plastik",
        "plastik sekali guna",
        "daur ulang",
        "limbah plastik",
        "sampah makanan",
        "polusi plastik",
        "plastik sekali pakai",
        "sampah",

        # Thai
        "ขยะ",
        "รีไซเคิล",
        "มลพิษพลาสติก",
        "ขยะพลาสติก",
        "พลาสติกใช้ครั้งเดียว",

        # Vietnamese
        "rác thải",
        "tái chế",
        "rác thải nhựa",
        "ô nhiễm nhựa",
        "nhựa dùng một lần",

        # Filipino
        "basura",
        "pagre-recycle",
        "polusyon sa plastik",
    ],

    "biodiversity_conservation": [
        # English
        "biodiversity",
        "wildlife",
        "conservation",
        "habitat",
        "endangered",
        "ecosystem",
        "nature reserve",
        "species",
        "threatened species",
        "pollinator",
        "pollination",
        "native tree",
        "native trees",
        "forest restoration",
        "ecological restoration",
        "coral",
        "mangrove",
        "seagrass",
        "hornbill",
        "orchid",
        "orangutan",
        "whale shark",
        "fungi",

        # Malay
        "biodiversiti",
        "hidupan liar",
        "pemuliharaan",
        "spesies terancam",
        "bakau",
        "pemulihan hutan",
        "khazanah alam",

        # Indonesian
        "keanekaragaman hayati",
        "satwa liar",
        "konservasi",
        "spesies terancam",
        "restorasi hutan",
        "orangutan",
        "hiu paus",

        # Thai
        "ความหลากหลายทางชีวภาพ",
        "สัตว์ป่า",
        "อนุรักษ์",
        "ระบบนิเวศ",
        "ถิ่นอาศัย",
        "สูญพันธุ์",
        "ป่าชายเลน",
        "ฟื้นฟูป่า",

        # Vietnamese
        "đa dạng sinh học",
        "động vật hoang dã",
        "bảo tồn",
        "hệ sinh thái",
        "môi trường sống",
        "tuyệt chủng",
        "rừng ngập mặn",
        "phục hồi rừng",

        # Filipino
        "pangangalaga",
        "konserbasyon",
    ],

    "renewable_energy": [
        # English
        "renewable energy",
        "solar energy",
        "solar power",
        "solar panel",
        "clean energy",
        "green energy",
        "wind energy",
        "hydropower",

        # Malay / Indonesian
        "tenaga boleh baharu",
        "tenaga suria",
        "tenaga bersih",
        "energi terbarukan",
        "tenaga surya",
        "energi bersih",

        # Thai
        "พลังงานหมุนเวียน",
        "พลังงานแสงอาทิตย์",
        "พลังงานสะอาด",
        "พลังงานลม",

        # Vietnamese
        "năng lượng tái tạo",
        "năng lượng mặt trời",
        "năng lượng sạch",
        "năng lượng gió",
    ],

    "energy_policy_transition": [
        # English
        "energy transition",
        "power sector",
        "electricity generation",
        "power generation",
        "power plant",
        "gas plant",
        "coal plant",
        "nuclear energy",
        "nuclear power",
        "energy policy",
        "power development plan",
        "pdp2026",
        "electricity plan",
        "energy security",
        "fossil fuel",
        "fossil fuels",
        "data center",
        "data centre",

        # Malay / Indonesian
        "transisi energi",
        "kebijakan energi",
        "pembangkit listrik",
        "bahan bakar fosil",
        "peralihan tenaga",
        "dasar tenaga",
        "loji janakuasa",
        "bahan api fosil",

        # Thai
        "เปลี่ยนผ่านพลังงาน",
        "พลังงานไทย",
        "โรงไฟฟ้า",
        "ไฟฟ้า",
        "แผนพัฒนากำลังผลิตไฟฟ้า",
        "ก๊าซฟอสซิล",
        "เชื้อเพลิงฟอสซิล",
        "นิวเคลียร์",
        "ดาต้าเซ็นเตอร์",

        # Vietnamese
        "chuyển dịch năng lượng",
        "chính sách năng lượng",
        "nhà máy điện",
        "nhiên liệu hóa thạch",
    ],

    "carbon_emissions": [
        # English
        "carbon emissions",
        "carbon emission",
        "carbon footprint",
        "greenhouse gas",
        "greenhouse gases",
        "net zero",
        "decarbonisation",
        "decarbonization",
        "carbon neutral",
        "carbon dioxide",
        "co2 emissions",
        "carbon storage",
        "blue carbon",

        # Malay / Indonesian
        "pelepasan karbon",
        "gas rumah hijau",
        "neutral karbon",
        "jejak karbon",
        "emisi karbon",
        "gas rumah kaca",

        # Thai
        "การปล่อยคาร์บอน",
        "ก๊าซเรือนกระจก",
        "คาร์บอนสุทธิเป็นศูนย์",
        "คาร์บอนฟุตพรินต์",

        # Vietnamese
        "phát thải carbon",
        "khí nhà kính",
        "dấu chân carbon",
        "trung hòa carbon",
        "carbon xanh",
    ],

    "water_flooding": [
        # English
        "water pollution",
        "water conservation",
        "water scarcity",
        "flooding",
        "flash flood",
        "flood",
        "drought",
        "water security",
        "water level",
        "dam level",
        "dry spell",
        "river drying",
        "watershed",
        "waterway",
        "waterways",

        # Malay / Indonesian
        "pencemaran air",
        "pemuliharaan air",
        "kekurangan air",
        "banjir",
        "kemarau",
        "paras air",
        "empangan",
        "sungai",
        "polusi air",
        "kekeringan",
        "tinggi muka air",
        "bendungan",
        "daerah aliran sungai",

        # Thai
        "มลพิษทางน้ำ",
        "น้ำท่วม",
        "ภัยแล้ง",
        "ระดับน้ำ",
        "เขื่อน",
        "ลุ่มน้ำ",

        # Vietnamese
        "ô nhiễm nước",
        "lũ lụt",
        "ngập lụt",
        "hạn hán",
        "mực nước",
        "lưu vực",
    ],

    "deforestation_land_use": [
        # English
        "deforestation",
        "forest clearing",
        "land clearing",
        "land use",
        "forest fire",
        "forest fires",
        "peat fire",
        "peatland",
        "wildfire",
        "wildfires",
        "forest loss",
        "illegal logging",
        "forest crime",
        "land conversion",

        # Malay
        "penebangan hutan",
        "pembukaan tanah",
        "kebakaran hutan",
        "tanah gambut",
        "pembalakan haram",
        "guna tanah",

        # Indonesian
        "deforestasi",
        "pembukaan lahan",
        "kebakaran hutan",
        "karhutla",
        "gambut",
        "pembalakan liar",
        "alih fungsi lahan",

        # Thai
        "ตัดไม้ทำลายป่า",
        "ไฟป่า",
        "บุกรุกป่า",
        "การใช้ที่ดิน",
        "ป่าพรุ",

        # Vietnamese
        "phá rừng",
        "cháy rừng",
        "chuyển đổi đất",
        "khai thác gỗ trái phép",
        "đất than bùn",
    ],

    "sustainable_consumption": [
        # English
        "sustainability",
        "sustainable living",
        "sustainable consumption",
        "green living",
        "eco-friendly",
        "eco friendly",
        "reuse",
        "reusable",
        "sustainable lifestyle",
        "responsible consumption",
        "sustainable choice",
        "sustainable choices",

        # Malay / Indonesian
        "kelestarian",
        "kehidupan lestari",
        "penggunaan mampan",
        "mesra alam",
        "guna semula",
        "mampan",
        "keberlanjutan",
        "gaya hidup berkelanjutan",
        "konsumsi berkelanjutan",
        "ramah lingkungan",
        "guna ulang",

        # Thai
        "ความยั่งยืน",
        "การบริโภคอย่างยั่งยืน",
        "เป็นมิตรต่อสิ่งแวดล้อม",
        "ใช้ซ้ำ",

        # Vietnamese
        "bền vững",
        "tiêu dùng bền vững",
        "sống xanh",
        "thân thiện với môi trường",
        "tái sử dụng",
    ],

    "marine_ocean": [
        # English
        "ocean",
        "oceans",
        "marine conservation",
        "marine ecosystem",
        "coral reef",
        "coral reefs",
        "seagrass",
        "blue carbon",
        "high seas",
        "ocean pollution",
        "coastal ecosystem",

        # Malay / Indonesian
        "ekosistem laut",
        "terumbu karang",
        "padang lamun",
        "laut lepas",
        "pencemaran laut",

        # Thai
        "มหาสมุทร",
        "ทะเล",
        "แนวปะการัง",
        "หญ้าทะเล",
        "ระบบนิเวศทางทะเล",

        # Vietnamese
        "đại dương",
        "rạn san hô",
        "cỏ biển",
        "hệ sinh thái biển",
    ],

    "environmental_governance_justice": [
        # English
        "environmental justice",
        "environmental governance",
        "environmental law",
        "environmental policy",
        "public participation",
        "environmental impact assessment",
        "environmental rights",
        "right to a healthy environment",
        "environmental interests",
        "ecological disaster",
        "indigenous land",
        "indigenous community",
        "indigenous communities",
        "land rights",

        # Malay
        "tadbir urus alam sekitar",
        "undang-undang alam sekitar",
        "keadilan alam sekitar",
        "hak tanah",
        "orang asli",

        # Indonesian
        "keadilan lingkungan",
        "tata kelola lingkungan",
        "hukum lingkungan",
        "hak atas tanah",
        "masyarakat adat",
        "bencana ekologis",

        # Thai
        "ธรรมาภิบาลด้านสิ่งแวดล้อม",
        "กฎหมายสิ่งแวดล้อม",
        "ความยุติธรรมด้านสิ่งแวดล้อม",
        "สิทธิชุมชน",

        # Vietnamese
        "quản trị môi trường",
        "luật môi trường",
        "công lý môi trường",
        "quyền đất đai",
        "cộng đồng bản địa",
    ],

    "agriculture_food_systems": [
        # English
        "sustainable agriculture",
        "food system",
        "food systems",
        "food security",
        "agriculture",
        "farming",
        "farmer",
        "farmers",
        "pesticide",
        "pesticides",
        "genetically modified",
        "genetically engineered",
        "gmo",
        "agroecology",

        # Malay / Indonesian
        "pertanian mampan",
        "keselamatan makanan",
        "petani",
        "racun perosak",
        "diubah suai secara genetik",
        "pertanian berkelanjutan",
        "ketahanan pangan",
        "pestisida",
        "rekayasa genetika",

        # Thai
        "เกษตรยั่งยืน",
        "ความมั่นคงทางอาหาร",
        "เกษตรกร",
        "สารกำจัดศัตรูพืช",
        "ดัดแปลงพันธุกรรม",

        # Vietnamese
        "nông nghiệp bền vững",
        "an ninh lương thực",
        "nông dân",
        "thuốc trừ sâu",
        "biến đổi gen",
    ],
}


# =========================================================
# HELPER FUNCTIONS
# =========================================================

def canonicalise_url(url):
    """Standardise URLs so they are easier to compare."""

    if not url:
        return ""

    return str(url).rstrip("/").lower()


def safe_int(value):
    """Convert engagement fields safely to integers."""

    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def is_in_previous_calendar_month(value):
    """Return True when a timestamp falls inside the reporting month."""

    timestamp = pd.to_datetime(value, utc=True, errors="coerce")
    if pd.isna(timestamp):
        return False

    return MONTH_START <= timestamp < CURRENT_MONTH_START


def get_page_name(post):
    """Apify may return pageName as either a string or object."""

    page_name = post.get("pageName")

    if isinstance(page_name, dict):
        return (
            page_name.get("name")
            or page_name.get("title")
            or "Unknown"
        )

    return page_name or "Unknown"


def normalise_text(value):
    """Normalise Unicode consistently before keyword matching."""

    return unicodedata.normalize(
        "NFKC",
        str(value or "")
    ).lower()


def keyword_present(text, keyword):
    """
    Check whether a keyword appears in text.

    Latin-script terms use regex boundaries to reduce accidental
    partial matches. For non-ASCII terms (for example Thai and
    Vietnamese), substring matching is more reliable because some
    scripts do not separate words in the same way as English.
    """

    text = normalise_text(text)
    keyword = normalise_text(keyword)

    if not keyword:
        return False

    if any(ord(character) > 127 for character in keyword):
        return keyword in text

    pattern = (
        r"(?<!\w)"
        + re.escape(keyword)
        + r"(?!\w)"
    )

    return re.search(pattern, text) is not None


def collect_ocr_text(value):
    """
    Recursively collect Apify/Facebook OCR text from media objects.

    This helps classify image-heavy posts whose caption contains
    little or no useful text.
    """

    collected = []

    if isinstance(value, dict):
        ocr_text = value.get("ocrText")

        if isinstance(ocr_text, str) and ocr_text.strip():
            collected.append(ocr_text)

        for child in value.values():
            if isinstance(child, (dict, list)):
                collected.extend(
                    collect_ocr_text(child)
                )

    elif isinstance(value, list):
        for child in value:
            collected.extend(
                collect_ocr_text(child)
            )

    return collected


def build_classification_text(post):
    """
    Build a richer text representation of a Facebook post.

    In addition to the main caption, this includes preview text,
    shared-post text, and media OCR text. These fields were important
    in the cached ASEAN data, especially for Thai image-based posts.
    """

    text_parts = []

    for field in (
        "text",
        "previewTitle",
        "previewDescription",
        "title",
    ):
        value = post.get(field)

        if isinstance(value, str) and value.strip():
            text_parts.append(value)

    shared_post = post.get("sharedPost")

    if isinstance(shared_post, dict):
        for field in (
            "text",
            "previewTitle",
            "previewDescription",
            "title",
        ):
            value = shared_post.get(field)

            if isinstance(value, str) and value.strip():
                text_parts.append(value)

        text_parts.extend(
            collect_ocr_text(
                shared_post.get("media")
            )
        )

    text_parts.extend(
        collect_ocr_text(
            post.get("media")
        )
    )

    return " ".join(text_parts)


def save_json(data, filepath):
    """Save local cache/output without repeated Apify calls."""

    filepath.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    with open(
        filepath,
        "w",
        encoding="utf-8"
    ) as file:
        json.dump(
            data,
            file,
            indent=2,
            ensure_ascii=False
        )

    print(f"Saved: {filepath}")


def load_json(filepath):
    """Load previously saved JSON data."""

    with open(
        filepath,
        "r",
        encoding="utf-8"
    ) as file:
        return json.load(file)


def require_apify_client():
    """Only require an Apify token when a paid scrape is requested."""

    if client is None:
        raise RuntimeError(
            "APIFY_TOKEN was not found. Add it to the repo-root "
            ".env file before running a fresh Apify scrape."
        )

    return client


# =========================================================
# POST SCRAPING
# =========================================================

def fetch_facebook_posts(
    sources,
    limit=POST_LIMIT_PER_PAGE
):

    apify_client = require_apify_client()

    page_urls = [
        {"url": source["url"]}
        for source in sources
    ]

    run_input = {
        "startUrls": page_urls,
        "resultsLimit": limit,
        "onlyPostsNewerThan": POST_DATE_RANGE,
        "onlyPostsOlderThan": CURRENT_MONTH_START.date().isoformat(),
        "captionText": False,
    }

    print(
        f"\nStarting Facebook post scraper "
        f"for {len(page_urls)} page(s)..."
    )

    run = apify_client.actor(
        POSTS_ACTOR
    ).call(
        run_input=run_input,
        max_total_charge_usd=(
            POST_RUN_MAX_COST_USD
        ),
    )

    if run is None:
        print(
            "Facebook post scraper failed "
            "to start."
        )
        return []

    dataset_id = run.default_dataset_id

    items = (
        apify_client
        .dataset(dataset_id)
        .list_items()
        .items
    )

    source_lookup = {
        canonicalise_url(source["url"]): source
        for source in sources
    }

    enriched_posts = []
    seen_post_ids = set()

    for item in items:
        post = dict(item)

        post_id = str(
            post.get("postId") or ""
        )

        if post_id:
            if post_id in seen_post_ids:
                continue

            seen_post_ids.add(post_id)

        # inputUrl is particularly useful for error records.
        source_url_candidates = [
            post.get("facebookUrl"),
            post.get("inputUrl"),
            post.get("url"),
        ]

        source_info = None

        for source_url in source_url_candidates:
            source_info = source_lookup.get(
                canonicalise_url(source_url)
            )

            if source_info:
                break

        if source_info:
            post["country"] = source_info["country"]
            post["source_name"] = source_info["source_name"]
        else:
            post["country"] = post.get("country") or "Unknown"
            post["source_name"] = (
                post.get("source_name")
                or get_page_name(post)
            )

        enriched_posts.append(post)

    # The actor accepts a lower boundary only. Enforce both boundaries
    # locally so the output contains exactly the previous calendar month.
    return [
        post
        for post in enriched_posts
        if not post.get("postId")
        or is_in_previous_calendar_month(post.get("time"))
    ]


# =========================================================
# ENVIRONMENTAL CLASSIFICATION
# =========================================================

def classify_environmental_post(post):
    """Identify environmental topics appearing in one Facebook post."""

    # Error/no-item records are useful diagnostics but are not posts.
    if not post.get("postId"):
        return None

    combined_text = build_classification_text(post)

    matched_topics = {}

    for topic, keywords in ENVIRONMENT_TOPICS.items():
        matches = [
            keyword
            for keyword in keywords
            if keyword_present(
                combined_text,
                keyword
            )
        ]

        if matches:
            matched_topics[topic] = matches

    if not matched_topics:
        return None

    # Choose the topic with the most evidence. If tied, favour the
    # topic whose matched terms are more specific/longer overall.
    primary_topic = max(
        matched_topics,
        key=lambda topic: (
            len(matched_topics[topic]),
            sum(
                len(keyword)
                for keyword in matched_topics[topic]
            ),
        ),
    )

    classified_post = dict(post)
    classified_post["primary_topic"] = primary_topic
    classified_post["matched_topics"] = matched_topics

    return classified_post


def split_environmental_posts(posts):
    """Return (environmental_posts, rejected_posts)."""

    environmental_posts = []
    rejected_posts = []

    for post in posts:
        # Keep source errors separate from rejected real posts.
        if not post.get("postId"):
            continue

        classified_post = (
            classify_environmental_post(post)
        )

        if classified_post:
            environmental_posts.append(
                classified_post
            )
        else:
            rejected_posts.append(post)

    return environmental_posts, rejected_posts


def filter_environmental_posts(posts):
    """Backwards-compatible helper returning only accepted posts."""

    environmental_posts, _ = (
        split_environmental_posts(posts)
    )

    return environmental_posts


# =========================================================
# ANALYSIS / DIAGNOSTICS
# =========================================================

def print_topic_distribution(posts):
    if not posts:
        print("\nNo environmental posts available.")
        return

    counts = Counter(
        post["primary_topic"]
        for post in posts
    )

    total = len(posts)

    print("\n==============================")
    print("ENVIRONMENTAL TOPIC DISTRIBUTION")
    print("==============================")

    for topic, count in counts.most_common():
        percentage = (count / total) * 100

        print(
            f"{topic}: "
            f"{count} "
            f"({percentage:.1f}%)"
        )


def print_country_distribution(posts, heading):
    counts = Counter(
        post.get("country") or "Unknown"
        for post in posts
    )

    print("\n==============================")
    print(heading)
    print("==============================")

    for country, count in counts.most_common():
        print(f"{country}: {count}")


def print_source_coverage(posts):
    counts = Counter(
        post.get("source_name") or "Unknown"
        for post in posts
        if post.get("postId")
    )

    print("\n==============================")
    print("SOURCE COVERAGE")
    print("==============================")

    for source in FACEBOOK_SOURCES:
        source_name = source["source_name"]
        print(
            f"{source_name}: "
            f"{counts.get(source_name, 0)} usable post(s)"
        )


def print_source_errors(posts):
    errors = [
        post
        for post in posts
        if not post.get("postId")
        and post.get("error")
    ]

    if not errors:
        return

    print("\n==============================")
    print("SOURCE ERRORS")
    print("==============================")

    for post in errors:
        print(
            f"{post.get('source_name', 'Unknown')}: "
            f"{post.get('error')} - "
            f"{post.get('errorDescription', '')}"
        )


# =========================================================
# SELECT DIVERSE POSTS FOR COMMENTS
# =========================================================

def select_diverse_posts_for_comments(
    posts,
    max_per_topic=(
        MAX_POSTS_PER_TOPIC_FOR_COMMENTS
    ),
    max_total=(
        MAX_TOTAL_POSTS_FOR_COMMENTS
    ),
):
    """
    Select a country- and topic-diverse set of posts for comments.

    The raw topic distribution is never altered. This function only
    determines where the paid comment-scraping budget is spent.

    Selection goals:
      1. Exclude posts with zero reported comments.
      2. Rotate across countries so Malaysia/Thailand are not crowded
         out by countries with more high-engagement posts.
      3. Limit the number of selected posts from one topic.
      4. Within those constraints, prefer engagement.
    """

    candidates = [
        post
        for post in posts
        if safe_int(post.get("comments")) > 0
        and post.get("country")
        and post.get("country") != "Unknown"
    ]

    if not candidates:
        return []

    grouped_by_country = defaultdict(list)

    for post in candidates:
        grouped_by_country[
            post["country"]
        ].append(post)

    # Highest engagement first within each country.
    for country in grouped_by_country:
        grouped_by_country[country].sort(
            key=lambda post: (
                safe_int(post.get("comments")),
                safe_int(post.get("likes")),
                safe_int(post.get("shares")),
            ),
            reverse=True
        )

    candidate_topic_counts = Counter(
        post["primary_topic"]
        for post in candidates
    )

    # Countries with fewer available candidates go first so they
    # are less likely to be excluded by the overall max_total cap.
    country_order = sorted(
        grouped_by_country,
        key=lambda country: (
            len(grouped_by_country[country]),
            country,
        )
    )

    selected = []
    selected_post_ids = set()
    selected_topic_counts = Counter()

    while len(selected) < max_total:
        progress_made = False

        for country in country_order:
            if len(selected) >= max_total:
                break

            available = [
                post
                for post in grouped_by_country[country]
                if str(post.get("postId"))
                not in selected_post_ids
                and selected_topic_counts[
                    post["primary_topic"]
                ] < max_per_topic
            ]

            if not available:
                continue

            # Prefer topics not yet represented. If still tied,
            # favour rarer topics, then higher engagement.
            available.sort(
                key=lambda post: (
                    selected_topic_counts[
                        post["primary_topic"]
                    ],
                    candidate_topic_counts[
                        post["primary_topic"]
                    ],
                    -safe_int(post.get("comments")),
                    -safe_int(post.get("likes")),
                    -safe_int(post.get("shares")),
                )
            )

            chosen = available[0]
            chosen_id = str(
                chosen.get("postId")
            )

            selected.append(chosen)
            selected_post_ids.add(chosen_id)
            selected_topic_counts[
                chosen["primary_topic"]
            ] += 1

            progress_made = True

        if not progress_made:
            break

    return selected


# =========================================================
# COMMENT SCRAPING + ENRICHMENT
# =========================================================

def refresh_comment_metadata(comments, posts):
    """
    Reattach current parent-post metadata to comments.

    This is useful after reclassifying cached posts because the cached
    comments may still contain the old primary_topic value.
    """

    post_lookup = {
        canonicalise_url(post["url"]): post
        for post in posts
        if post.get("url")
    }

    enriched_comments = []

    for item in comments:
        comment = dict(item)

        parent_url = canonicalise_url(
            comment.get("facebookUrl")
        )

        parent_post = post_lookup.get(
            parent_url
        )

        if parent_post:
            comment["parent_post_id"] = (
                parent_post.get("postId")
            )
            comment["country"] = (
                parent_post.get("country")
            )
            comment["source_name"] = (
                parent_post.get("source_name")
            )
            comment["primary_topic"] = (
                parent_post.get("primary_topic")
            )

        enriched_comments.append(comment)

    return enriched_comments


def fetch_facebook_comments(
    posts,
    limit=COMMENT_LIMIT_PER_POST
):

    post_urls = [
        {"url": post["url"]}
        for post in posts
        if post.get("url")
    ]

    if not post_urls:
        print(
            "\nNo post URLs available "
            "for comment scraping."
        )
        return []

    apify_client = require_apify_client()

    run_input = {
        "startUrls": post_urls,
        "resultsLimit": limit,
        "includeNestedComments": False,
    }

    print(
        f"\nStarting comment scraper "
        f"for {len(post_urls)} post(s)..."
    )

    run = apify_client.actor(
        COMMENTS_ACTOR
    ).call(
        run_input=run_input,
        max_total_charge_usd=(
            COMMENT_RUN_MAX_COST_USD
        ),
    )

    if run is None:
        print(
            "Comment scraper failed "
            "to start."
        )
        return []

    dataset_id = run.default_dataset_id

    items = (
        apify_client
        .dataset(dataset_id)
        .list_items()
        .items
    )

    unique_comments = []
    seen_comment_ids = set()

    for item in items:
        comment = dict(item)

        comment_id = str(
            comment.get("commentId") or ""
        )

        if comment_id:
            if comment_id in seen_comment_ids:
                continue

            seen_comment_ids.add(comment_id)

        unique_comments.append(comment)

    return refresh_comment_metadata(
        unique_comments,
        posts
    )


def print_cached_comment_coverage(
    comments,
    selected_posts
):
    """Explain whether the old cached comments match the new selection."""

    cached_urls = {
        canonicalise_url(
            comment.get("facebookUrl")
        )
        for comment in comments
        if comment.get("facebookUrl")
    }

    selected_urls = {
        canonicalise_url(post.get("url"))
        for post in selected_posts
        if post.get("url")
    }

    overlap = len(
        cached_urls.intersection(selected_urls)
    )

    print(
        f"Cached comments currently cover "
        f"{overlap}/{len(selected_urls)} "
        f"of the newly selected post URLs."
    )

    if overlap < len(selected_urls):
        print(
            "This is expected after changing the classifier/selection. "
            "No new Apify comment scrape was run because "
            "USE_CACHED_COMMENTS=True."
        )
        print(
            "When you are ready to collect comments for the new balanced "
            "selection, set USE_CACHED_COMMENTS=False."
        )


# =========================================================
# NORMALISATION
# =========================================================

def normalise_facebook_post(post):
    return {
        "platform": "facebook",
        "post_id": post.get("postId"),
        "country": post.get("country"),
        "source_name": post.get("source_name"),
        "page_name": get_page_name(post),
        "published_at": post.get("time"),
        "url": post.get("url"),
        "text": post.get("text"),
        "likes": safe_int(post.get("likes")),
        "comments_count": safe_int(
            post.get("comments")
        ),
        "shares": safe_int(post.get("shares")),
        "primary_topic": post.get("primary_topic"),
        "matched_topics": post.get(
            "matched_topics",
            {}
        ),
    }


def normalise_facebook_comment(comment):
    return {
        "platform": "facebook",
        "comment_id": comment.get("commentId"),
        "parent_post_id": comment.get(
            "parent_post_id"
        ),
        "post_url": comment.get("facebookUrl"),
        "country": comment.get("country"),
        "source_name": comment.get("source_name"),
        "primary_topic": comment.get(
            "primary_topic"
        ),
        "published_at": comment.get("date"),
        "text": comment.get("text"),
        "likes": safe_int(
            comment.get("likesCount")
        ),
    }


def save_csv(rows, filepath, json_columns=None):
    """Save normalised rows using the same UTF-8 CSV format as other sources."""

    dataframe = pd.DataFrame(rows)

    for column in json_columns or []:
        if column in dataframe.columns:
            dataframe[column] = dataframe[column].apply(
                lambda value: json.dumps(value, ensure_ascii=False)
                if isinstance(value, (dict, list))
                else value
            )

    dataframe.to_csv(filepath, index=False, encoding="utf-8-sig")
    print(f"Saved {len(dataframe)} rows to {filepath}")


def sync_to_supabase(posts, comments):
    """Sync cleaned Facebook records through the existing pipeline."""

    url = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
    key = (
        os.environ.get("SUPABASE_SECRET_KEY")
        or os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
        or os.environ.get("SUPABASE_KEY")
        or ""
    ).strip()

    if not url or not key:
        print("✗ Missing SUPABASE_URL or Supabase server key in .env")
        return None

    if key.startswith("sb_publishable_") or key.startswith("sb_anon_"):
        print("✗ Supabase key must be a server-only secret/service-role key")
        return None

    try:
        from scripts.supabase.facebook_pipeline import sync_facebook_rows

        print("Syncing to Supabase...")
        counts = sync_facebook_rows(posts, comments)
        print("✓ Supabase sync successful")
        print(f"Upserted: {counts}")
        return counts
    except ImportError as error:
        print(f"✗ Import error: {error}")
    except Exception as error:
        print(f"✗ Supabase sync failed: {error}")
        import traceback

        traceback.print_exc()

    return None


# =========================================================
# MAIN PROGRAM
# =========================================================

if __name__ == "__main__":

    print("\n==============================")
    print("FACEBOOK ENVIRONMENT PIPELINE")
    print("==============================")

    if OFFLINE_TEST_MODE:
        print(
            "Offline test mode enabled: "
            "using local caches only; "
            "Apify and Supabase are disabled."
        )

    # =====================================================
    # STEP 1: COLLECT / LOAD POSTS
    # =====================================================

    if OFFLINE_TEST_MODE and not POSTS_CACHE_FILE.exists():
        raise SystemExit(
            "Offline test requires the cached posts file: "
            f"{POSTS_CACHE_FILE}"
        )

    if (
        (USE_CACHED_POSTS or OFFLINE_TEST_MODE)
        and POSTS_CACHE_FILE.exists()
    ):
        print("\nUsing cached Facebook posts...")
        posts = load_json(POSTS_CACHE_FILE)
    else:
        posts = fetch_facebook_posts(
            FACEBOOK_SOURCES
        )
        save_json(posts, POSTS_CACHE_FILE)

    # Apply the exact month boundary to both fresh and cached records.
    posts = [
        post
        for post in posts
        if not post.get("postId")
        or is_in_previous_calendar_month(post.get("time"))
    ]

    usable_posts = [
        post
        for post in posts
        if post.get("postId")
    ]

    source_error_records = [
        post
        for post in posts
        if not post.get("postId")
    ]

    print(
        f"\nRaw scraper records: "
        f"{len(posts)}"
    )
    print(
        f"Usable Facebook posts: "
        f"{len(usable_posts)}"
    )
    print(
        f"Non-post/error records: "
        f"{len(source_error_records)}"
    )

    print_source_coverage(posts)
    print_source_errors(posts)

    # =====================================================
    # STEP 2: CLASSIFY ENVIRONMENTAL POSTS
    # =====================================================

    (
        environmental_posts,
        rejected_posts,
    ) = split_environmental_posts(posts)

    print(
        f"\nEnvironmental posts found: "
        f"{len(environmental_posts)}"
    )

    if usable_posts:
        classification_rate = (
            len(environmental_posts)
            / len(usable_posts)
            * 100
        )

        print(
            f"Environmental classification rate: "
            f"{classification_rate:.1f}% "
            f"of usable posts"
        )

    print(
        f"Rejected usable posts: "
        f"{len(rejected_posts)}"
    )

    save_json(
        environmental_posts,
        ENVIRONMENTAL_POSTS_FILE
    )

    save_json(
        rejected_posts,
        REJECTED_POSTS_FILE
    )

    # =====================================================
    # STEP 3: DISTRIBUTIONS
    # =====================================================

    print_topic_distribution(
        environmental_posts
    )

    print_country_distribution(
        environmental_posts,
        "ENVIRONMENTAL POSTS BY COUNTRY"
    )

    # =====================================================
    # STEP 4: SELECT BALANCED POSTS FOR COMMENTS
    # =====================================================

    selected_posts = (
        select_diverse_posts_for_comments(
            environmental_posts
        )
    )

    print("\n==============================")
    print("POSTS SELECTED FOR COMMENTS")
    print("==============================")

    print(
        f"Selected {len(selected_posts)} "
        f"post(s)."
    )

    # for post in selected_posts:
    #     print(
    #         f"\nCountry: "
    #         f"{post.get('country')}"
    #     )
    #     print(
    #         f"Topic: "
    #         f"{post.get('primary_topic')}"
    #     )
    #     print(
    #         f"Source: "
    #         f"{post.get('source_name')}"
    #     )
    #     print(
    #         f"Facebook comment count: "
    #         f"{post.get('comments')}"
    #     )
    #     print(
    #         f"URL: "
    #         f"{post.get('url')}"
    #     )

    print_country_distribution(
        selected_posts,
        "SELECTED COMMENT POSTS BY COUNTRY"
    )

    # =====================================================
    # STEP 5: SCRAPE / LOAD COMMENTS
    # =====================================================

    if selected_posts:
        if OFFLINE_TEST_MODE and not COMMENTS_CACHE_FILE.exists():
            raise SystemExit(
                "Offline test requires the cached comments file: "
                f"{COMMENTS_CACHE_FILE}"
            )

        if (
            (USE_CACHED_COMMENTS or OFFLINE_TEST_MODE)
            and COMMENTS_CACHE_FILE.exists()
        ):
            print(
                "\nUsing cached Facebook comments..."
            )

            comments = load_json(
                COMMENTS_CACHE_FILE
            )

            # Refresh topic/country metadata using the newly
            # classified parent posts without calling Apify.
            comments = refresh_comment_metadata(
                comments,
                environmental_posts
            )

            print_cached_comment_coverage(
                comments,
                selected_posts
            )
        else:
            comments = fetch_facebook_comments(
                selected_posts
            )

            save_json(
                comments,
                COMMENTS_CACHE_FILE
            )
    else:
        comments = []

    # Remove duplicates and keep comments attached to accepted posts only.
    unique_comments = []
    seen_comment_ids = set()
    valid_post_ids = {
        str(post.get("postId"))
        for post in environmental_posts
        if post.get("postId")
    }

    for comment in comments:
        comment_id = str(comment.get("commentId") or "")
        parent_post_id = str(comment.get("parent_post_id") or "")

        if comment_id and comment_id in seen_comment_ids:
            continue
        if parent_post_id not in valid_post_ids:
            continue
        if comment_id:
            seen_comment_ids.add(comment_id)
        unique_comments.append(comment)

    comments = unique_comments

    print(
        f"\nComments available: "
        f"{len(comments)}"
    )

    comment_country_counts = Counter(
        comment.get("country") or "Unknown"
        for comment in comments
    )

    # if comments:
    #     print("\n==============================")
    #     print("COMMENTS BY COUNTRY")
    #     print("==============================")

    #     for country, count in (
    #         comment_country_counts.most_common()
    #     ):
    #         print(f"{country}: {count}")

    # =====================================================
    # STEP 6: NORMALISE + SAVE
    # =====================================================

    normalised_posts = [
        normalise_facebook_post(post)
        for post in environmental_posts
    ]

    normalised_comments = [
        normalise_facebook_comment(comment)
        for comment in comments
    ]

    save_json(
        normalised_posts,
        NORMALISED_POSTS_FILE
    )

    save_json(
        normalised_comments,
        NORMALISED_COMMENTS_FILE
    )

    save_csv(
        normalised_posts,
        POSTS_CSV,
        json_columns=["matched_topics"],
    )

    save_csv(
        normalised_comments,
        COMMENTS_CSV,
    )

    # =====================================================
    # STEP 7: SUPABASE SYNC
    # =====================================================

    if UPLOAD_TO_SUPABASE and not OFFLINE_TEST_MODE:
        print("\n==============================")
        print("SYNCING TO SUPABASE")
        print("==============================")

        sync_counts = sync_to_supabase(
            normalised_posts,
            normalised_comments
        )

        if sync_counts is not None:
            print(
                "\nSupabase sync completed:",
                sync_counts
            )
    else:
        print("\nSupabase upload disabled.")

    # =====================================================
    # SUMMARY
    # =====================================================

    print("\n==============================")
    print("PIPELINE SUMMARY")
    print("==============================")

    print(
        "Raw scraper records:",
        len(posts)
    )
    print(
        "Usable posts:",
        len(usable_posts)
    )
    print(
        "Environmental posts:",
        len(environmental_posts)
    )
    print(
        "Rejected usable posts:",
        len(rejected_posts)
    )
    print(
        "Posts selected for comments:",
        len(selected_posts)
    )
    print(
        "Comments available:",
        len(comments)
    )

    print("Saved:", POSTS_CSV)
    print("Saved:", COMMENTS_CSV)

    print("\nDone.")
