import os
import re
import html
import time
import random
import numpy as np
import torch

from pathlib import Path
from datetime import datetime, timezone

from bs4 import BeautifulSoup
from dotenv import load_dotenv
from supabase import create_client, Client
from transformers import pipeline
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity
from keybert import KeyBERT
from langdetect import detect, DetectorFactory

from google.cloud import translate_v3
from google.api_core.exceptions import (
    DeadlineExceeded,
    InternalServerError,
    ResourceExhausted,
    ServiceUnavailable,
    TooManyRequests,
)


# ==========================================================
# SETTINGS AND SUPABASE
# ==========================================================

# Find .env in the script directory or a parent directory.
SCRIPT_DIR = Path(__file__).resolve().parent

for folder in [SCRIPT_DIR, *SCRIPT_DIR.parents]:
    env_path = folder / ".env"

    if env_path.is_file():
        load_dotenv(env_path)
        break


SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
GOOGLE_CLOUD_PROJECT = os.getenv("GOOGLE_CLOUD_PROJECT")


if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError(
        "SUPABASE_URL or SUPABASE_KEY is missing. "
        "Check your .env file."
    )


if not GOOGLE_CLOUD_PROJECT:
    raise ValueError(
        "GOOGLE_CLOUD_PROJECT is missing. "
        "Check your .env file."
    )


supabase: Client = create_client(
    SUPABASE_URL,
    SUPABASE_KEY
)


RAW_TABLE = "news_raw"
CLEANED_TABLE = "news_cleaned"

MIN_WORD_COUNT = 20

# Starting threshold for DeBERTa.
# This should be evaluated against manually reviewed articles later.
MIN_CATEGORY_CONFIDENCE = 0.30

KEYWORD_TOP_N = 5
SUPABASE_BATCH_SIZE = 1000


# ==========================================================
# GOOGLE TRANSLATION SETTINGS
# ==========================================================

TRANSLATION_CHUNK_SIZE = 4500
TRANSLATION_BATCH_SIZE = 5
TRANSLATION_MAX_RETRIES = 4

TRANSLATION_PARENT = (
    f"projects/{GOOGLE_CLOUD_PROJECT}/locations/global"
)

# Prevent repeated translation requests within one run.
translation_cache = {}


# ==========================================================
# DEBERTA CLASSIFICATION SETTINGS
# ==========================================================

# DeBERTa-v3-xsmall has a smaller context window than BART.
# For news articles, the title and opening paragraphs usually
# contain the main subject of the article.
CLASSIFICATION_MAX_CHARACTERS = 1800


# ==========================================================
# COUNTRIES AND ENVIRONMENT CATEGORIES
# ==========================================================

TARGET_COUNTRIES = [
    "Singapore",
    "Malaysia",
    "Indonesia",
    "Thailand",
    "Philippines",
    "Brunei",
]

TARGET_COUNTRY_SET = set(TARGET_COUNTRIES)


ENVIRONMENT_CATEGORIES = [
    "Climate Change",
    "Renewable Energy",
    "Pollution",
    "Waste Management",
    "Biodiversity and Conservation",
    "Deforestation and Forest Conservation",
    "Extreme Weather and Natural Hazards",
    "Sustainable Transport",
    "Green Buildings and Urban Sustainability",
    "Green Finance and Environmental Policy",
    "Water Resources and Water Security",
    "Oceans and Marine Conservation",
    "Agriculture and Food Sustainability",
    "Energy and Fossil Fuels",
    "Environmental Health",
]


LOW_INFORMATION_WORDS = {
    "said",
    "says",
    "say",
    "according",
    "reported",
    "report",
    "reports",
    "reporting",
    "added",
    "told",
    "also",
    "would",
    "could",
    "may",
    "might",
}


DetectorFactory.seed = 0


# ==========================================================
# PROCESSING DEVICE
# ==========================================================

if torch.cuda.is_available():
    DEVICE = torch.device("cuda")
    PIPELINE_DEVICE = 0

    print("CUDA GPU detected.")

else:
    DEVICE = torch.device("cpu")
    PIPELINE_DEVICE = -1

    print(
        "CUDA GPU not detected. "
        "Models will run on CPU."
    )


# ==========================================================
# LOAD NLP MODELS
# ==========================================================

print()
print("==========================================")
print("LOADING NLP MODELS")
print("==========================================")

print("Loading DeBERTa-v3-xsmall zero-shot classifier...")

category_classifier = pipeline(
    "zero-shot-classification",
    model="MoritzLaurer/deberta-v3-xsmall-zeroshot-v1.1-all-33",
    device=PIPELINE_DEVICE,
)

print("DeBERTa-v3-xsmall classifier loaded.")


print("Loading MiniLM embedding model...")

embedding_model = SentenceTransformer(
    "all-MiniLM-L6-v2",
    device=str(DEVICE),
)


print("Loading KeyBERT...")

keyword_model = KeyBERT(
    model=embedding_model
)


print("Initializing Google Cloud Translation API...")

translation_client = (
    translate_v3.TranslationServiceClient()
)


print("Models and Google Translate client loaded.")


# ==========================================================
# COUNTRY HANDLING
# ==========================================================

def normalize_country(country):

    if not country:
        return None

    country = str(country).strip()

    lookup = {
        "singapore": "Singapore",
        "malaysia": "Malaysia",
        "indonesia": "Indonesia",
        "thailand": "Thailand",
        "philippines": "Philippines",
        "philippine": "Philippines",
        "brunei": "Brunei",
        "brunei darussalam": "Brunei",
    }

    return lookup.get(
        country.lower()
    )


def parse_countries(countries_value):

    if countries_value is None:
        return []

    text = str(
        countries_value
    ).strip()

    if not text:
        return []

    parts = re.split(
        r"[,;|]",
        text
    )

    countries = []

    for part in parts:

        country = normalize_country(
            part
        )

        if (
            country
            and country in TARGET_COUNTRY_SET
            and country not in countries
        ):
            countries.append(
                country
            )

    return countries


# ==========================================================
# LANGUAGE DETECTION
# ==========================================================

def detect_language(text):

    if not text:
        return "unknown"

    sample = re.sub(
        r"\s+",
        " ",
        str(text)
    ).strip()

    if len(sample) < 20:
        return "unknown"

    try:
        return detect(
            sample[:5000]
        )

    except Exception as e:

        print(
            "  Language detection error:",
            e
        )

        return "unknown"


def resolve_language(
    detected_language,
    source_country,
    text
):

    """
    Skip translation when langdetect identifies English.

    For non-English articles, Google Translate automatically
    detects the source language.
    """

    detected_language = (
        detected_language or "unknown"
    ).lower()

    if detected_language == "en":
        return "en"

    return "auto"


# ==========================================================
# SPLIT LONG TEXT FOR GOOGLE TRANSLATE
# ==========================================================

def split_text_for_translation(
    text,
    max_chars=TRANSLATION_CHUNK_SIZE
):

    text = str(
        text or ""
    ).strip()

    if not text:
        return []

    if len(text) <= max_chars:
        return [text]

    sentences = re.split(
        r"(?<=[.!?。！？])\s+|\n+",
        text
    )

    chunks = []
    current_chunk = ""

    for sentence in sentences:

        sentence = sentence.strip()

        if not sentence:
            continue

        if len(sentence) > max_chars:

            if current_chunk:

                chunks.append(
                    current_chunk.strip()
                )

                current_chunk = ""

            remaining = sentence

            while len(remaining) > max_chars:

                split_at = remaining.rfind(
                    " ",
                    0,
                    max_chars + 1
                )

                if split_at < max_chars // 2:

                    candidates = [
                        remaining.rfind(
                            punctuation,
                            0,
                            max_chars + 1
                        )
                        for punctuation in [
                            "。",
                            "！",
                            "？",
                            "ฯ",
                            ".",
                            "!",
                            "?",
                            ";",
                            "；",
                        ]
                    ]

                    split_at = max(
                        candidates
                    )

                if split_at < max_chars // 2:
                    split_at = max_chars
                else:
                    split_at += 1

                piece = remaining[
                    :split_at
                ].strip()

                if piece:
                    chunks.append(
                        piece
                    )

                remaining = remaining[
                    split_at:
                ].strip()

            if remaining:
                current_chunk = remaining

            continue

        proposed = (
            current_chunk
            + " "
            + sentence
        ).strip()

        if len(proposed) <= max_chars:

            current_chunk = proposed

        else:

            if current_chunk:

                chunks.append(
                    current_chunk.strip()
                )

            current_chunk = sentence

    if current_chunk:

        chunks.append(
            current_chunk.strip()
        )

    return chunks


# ==========================================================
# GOOGLE CLOUD TRANSLATION
# ==========================================================

RETRYABLE_TRANSLATION_ERRORS = (
    DeadlineExceeded,
    InternalServerError,
    ResourceExhausted,
    ServiceUnavailable,
    TooManyRequests,
)


def translate_google_batch(
    chunks,
    source_language="auto"
):

    """
    Translate multiple chunks using Google's standard
    Neural Machine Translation model.

    When source_language is "auto", source_language_code
    is omitted and Google detects the language.
    """

    if not chunks:
        return []

    request = {
        "parent": TRANSLATION_PARENT,
        "contents": chunks,
        "mime_type": "text/plain",
        "target_language_code": "en",
        "model": (
            f"{TRANSLATION_PARENT}/models/general/nmt"
        ),
    }

    if source_language not in {
        "auto",
        "unknown",
        None,
        ""
    }:

        request[
            "source_language_code"
        ] = source_language

    for attempt in range(
        1,
        TRANSLATION_MAX_RETRIES + 1
    ):

        try:

            response = (
                translation_client.translate_text(
                    request=request,
                    timeout=90,
                )
            )

            translations = [
                html.unescape(
                    translation.translated_text
                ).strip()
                for translation
                in response.translations
            ]

            if len(translations) != len(chunks):

                raise ValueError(
                    "Google Translate returned "
                    "an unexpected number of translations."
                )

            if any(
                not translated
                for translated in translations
            ):

                raise ValueError(
                    "Google Translate returned "
                    "an empty translation."
                )

            return translations

        except RETRYABLE_TRANSLATION_ERRORS as e:

            print(
                f"    Translation request failed "
                f"(attempt {attempt}/"
                f"{TRANSLATION_MAX_RETRIES}): "
                f"{e}"
            )

            if attempt == TRANSLATION_MAX_RETRIES:
                raise

            delay = min(
                2 ** attempt
                + random.uniform(0, 1),
                30
            )

            print(
                f"    Retrying in "
                f"{delay:.1f} seconds..."
            )

            time.sleep(
                delay
            )

    return []


def translate_to_english(
    text,
    language="auto"
):

    if not text:
        return ""

    text = str(
        text
    ).strip()

    if not text:
        return ""

    if language == "en":

        print(
            "  Translation not required."
        )

        return text

    cache_key = (
        language,
        text
    )

    if cache_key in translation_cache:

        print(
            "  Using cached translation."
        )

        return translation_cache[
            cache_key
        ]

    print(
        "  Translating with Google Cloud "
        "Translation API..."
    )

    chunks = split_text_for_translation(
        text
    )

    if not chunks:
        return ""

    print(
        f"  Translation chunks: "
        f"{len(chunks)}"
    )

    translated_chunks = []

    for start in range(
        0,
        len(chunks),
        TRANSLATION_BATCH_SIZE
    ):

        batch = chunks[
            start:
            start + TRANSLATION_BATCH_SIZE
        ]

        batch_number = (
            start
            // TRANSLATION_BATCH_SIZE
        ) + 1

        total_batches = (
            len(chunks)
            + TRANSLATION_BATCH_SIZE
            - 1
        ) // TRANSLATION_BATCH_SIZE

        print(
            f"    Translating batch "
            f"{batch_number}/"
            f"{total_batches}..."
        )

        try:

            translations = (
                translate_google_batch(
                    batch,
                    source_language=language,
                )
            )

            translated_chunks.extend(
                translations
            )

            print(
                f"    Batch "
                f"{batch_number} completed."
            )

        except Exception as e:

            print(
                f"    Google translation failed "
                f"on batch {batch_number}: "
                f"{e}"
            )

            return None

    translated_text = " ".join(
        translated_chunks
    ).strip()

    translation_cache[
        cache_key
    ] = translated_text

    return translated_text


# ==========================================================
# TEXT CLEANING
# ==========================================================

def clean_text(text):

    if text is None:
        return ""

    text = str(text)

    text = html.unescape(
        text
    )

    text = BeautifulSoup(
        text,
        "html.parser"
    ).get_text(" ")

    text = re.sub(
        r"https?://\S+|www\.\S+",
        " ",
        text
    )

    text = re.sub(
        r"\S+@\S+",
        " ",
        text
    )

    text = text.lower()

    text = re.sub(
        r"[^a-z0-9\s\-]",
        " ",
        text
    )

    text = re.sub(
        r"\s+",
        " ",
        text
    ).strip()

    words = text.split()

    words = [
        word
        for word in words
        if word
        not in LOW_INFORMATION_WORDS
    ]

    return " ".join(
        words
    )


# ==========================================================
# DEBERTA ENVIRONMENT CATEGORY CLASSIFICATION
# ==========================================================

def assign_environment_category(text):

    """
    Classify the article into one broad environmental
    category using DeBERTa-v3-xsmall zero-shot classification.

    The title is already included at the beginning of
    cleaned_text, followed by the article content.

    Only the first CLASSIFICATION_MAX_CHARACTERS characters
    are used to keep classification fast and within the
    smaller DeBERTa model's context window.
    """

    if not text or not text.strip():
        return None, None

    text_for_classification = (
        text[:CLASSIFICATION_MAX_CHARACTERS]
    )

    try:

        print(
            "  DeBERTa input characters:",
            len(text_for_classification)
        )

        result = category_classifier(
            text_for_classification,
            candidate_labels=ENVIRONMENT_CATEGORIES,
            hypothesis_template=(
                "This news article is mainly about {}."
            ),
            multi_label=False,
        )

        category = result[
            "labels"
        ][0]

        confidence = result[
            "scores"
        ][0]

        print(
            "  Top DeBERTa categories:"
        )

        for label, score in zip(
            result["labels"][:5],
            result["scores"][:5]
        ):

            print(
                f"    {label}: "
                f"{float(score):.4f}"
            )

        return (
            category,
            round(
                float(confidence),
                4
            )
        )

    except Exception as e:

        print(
            "  Classification error:",
            e
        )

        return None, None


# ==========================================================
# KEYWORD EXTRACTION
# ==========================================================

def extract_keywords(
    text,
    top_n=KEYWORD_TOP_N
):

    if not text.strip():
        return ""

    try:

        keywords = (
            keyword_model.extract_keywords(
                text,
                keyphrase_ngram_range=(
                    1,
                    2
                ),
                stop_words="english",
                top_n=top_n,
                use_mmr=True,
                diversity=0.5,
            )
        )

        keyword_names = [
            keyword
            for keyword, score
            in keywords
        ]

        return ", ".join(
            keyword_names
        )

    except Exception as e:

        print(
            "  Keyword extraction error:",
            e
        )

        return ""


# ==========================================================
# SUPABASE DATA ACCESS
# ==========================================================

def get_pending_raw_articles():

    print()
    print("==========================================")
    print("LOADING PENDING RAW ARTICLES")
    print("==========================================")

    all_rows = []
    start = 0

    while True:

        response = (
            supabase
            .table(RAW_TABLE)
            .select(
                "news_id,source_country,title,source,"
                "published_at,countries,article_text,"
                "url,cleaning_status"
            )
            .eq(
                "cleaning_status",
                "pending"
            )
            .order(
                "news_id"
            )
            .range(
                start,
                start
                + SUPABASE_BATCH_SIZE
                - 1
            )
            .execute()
        )

        rows = (
            response.data
            or []
        )

        all_rows.extend(
            rows
        )

        if len(rows) < SUPABASE_BATCH_SIZE:
            break

        start += SUPABASE_BATCH_SIZE

    print(
        f"{len(all_rows)} pending raw "
        f"article(s) found."
    )

    return all_rows


def get_existing_cleaned_rows():

    print()
    print("==========================================")
    print("LOADING EXISTING CLEANED DATA")
    print("==========================================")

    all_rows = []
    start = 0

    while True:

        response = (
            supabase
            .table(CLEANED_TABLE)
            .select(
                "article_id,title,source,source_country,"
                "published_at,country,cleaned_text,"
                "environment_category,environment_keywords,"
                "semantic_score,confidence_score,url"
            )
            .order(
                "article_id"
            )
            .range(
                start,
                start
                + SUPABASE_BATCH_SIZE
                - 1
            )
            .execute()
        )

        rows = (
            response.data
            or []
        )

        all_rows.extend(
            rows
        )

        if len(rows) < SUPABASE_BATCH_SIZE:
            break

        start += SUPABASE_BATCH_SIZE

    print(
        f"{len(all_rows)} existing cleaned "
        f"row(s) found."
    )

    return all_rows


def set_raw_status(
    news_id,
    status
):

    timestamp = (
        datetime.now(
            timezone.utc
        ).isoformat()
    )

    return (
        supabase
        .table(RAW_TABLE)
        .update({
            "cleaning_status": status,
            "cleaned_at": timestamp,
        })
        .eq(
            "news_id",
            news_id
        )
        .execute()
    )


def insert_cleaned_rows(rows):

    if not rows:
        return 0

    response = (
        supabase
        .table(CLEANED_TABLE)
        .insert(
            rows
        )
        .execute()
    )

    if response.data:
        return len(
            response.data
        )

    return len(rows)


# ==========================================================
# SEMANTIC SCORE CALCULATION
# ==========================================================

def calculate_semantic_scores(
    cleaned_rows
):

    print()
    print("==========================================")
    print("CALCULATING SEMANTIC SCORES")
    print("==========================================")

    if not cleaned_rows:

        print(
            "No cleaned rows available."
        )

        return {}

    unique_articles = {}

    for row in cleaned_rows:

        article_id = row.get(
            "article_id"
        )

        if article_id is None:
            continue

        if article_id not in unique_articles:

            unique_articles[
                article_id
            ] = {
                "article_id": article_id,
                "cleaned_text": (
                    row.get(
                        "cleaned_text",
                        ""
                    )
                    or ""
                ),
                "environment_category": (
                    row.get(
                        "environment_category"
                    )
                ),
            }

    article_list = list(
        unique_articles.values()
    )

    if not article_list:
        return {}

    print(
        "Unique articles used for semantic "
        f"calculation: {len(article_list)}"
    )

    texts = [
        article[
            "cleaned_text"
        ]
        for article
        in article_list
    ]

    print(
        "Generating article embeddings..."
    )

    embeddings = embedding_model.encode(
        texts,
        show_progress_bar=True,
        convert_to_numpy=True,
    )

    semantic_scores = {}

    for category in ENVIRONMENT_CATEGORIES:

        category_indices = [
            index
            for index, article
            in enumerate(article_list)
            if article[
                "environment_category"
            ] == category
        ]

        if not category_indices:
            continue

        print(
            f"{category}: "
            f"{len(category_indices)} "
            f"article(s)"
        )

        if len(category_indices) == 1:

            article_id = article_list[
                category_indices[0]
            ]["article_id"]

            semantic_scores[
                article_id
            ] = 1.0

            continue

        category_embeddings = (
            embeddings[
                category_indices
            ]
        )

        category_centroid = np.mean(
            category_embeddings,
            axis=0
        ).reshape(
            1,
            -1
        )

        similarities = cosine_similarity(
            category_embeddings,
            category_centroid
        ).flatten()

        for index, similarity in zip(
            category_indices,
            similarities
        ):

            article_id = article_list[
                index
            ]["article_id"]

            semantic_scores[
                article_id
            ] = round(
                float(similarity),
                4
            )

    return semantic_scores


def update_semantic_scores(
    semantic_scores
):

    print()
    print("==========================================")
    print("UPDATING SEMANTIC SCORES IN SUPABASE")
    print("==========================================")

    if not semantic_scores:

        print(
            "No semantic scores to update."
        )

        return

    total = len(
        semantic_scores
    )

    total_rows_updated = 0

    for number, (
        article_id,
        score
    ) in enumerate(
        semantic_scores.items(),
        start=1
    ):

        try:

            response = (
                supabase
                .table(CLEANED_TABLE)
                .update({
                    "semantic_score": score
                })
                .eq(
                    "article_id",
                    article_id
                )
                .execute()
            )

            rows_updated = len(
                response.data
                or []
            )

            total_rows_updated += (
                rows_updated
            )

            print(
                f"Semantic update "
                f"{number}/{total}: "
                f"article_id={article_id}, "
                f"score={score}, "
                f"rows={rows_updated}"
            )

        except Exception as e:

            print(
                "ERROR updating semantic "
                "score for article "
                f"{article_id}:"
            )

            print(e)

    print()
    print(
        "Semantic score update finished."
    )

    print(
        f"Rows updated: "
        f"{total_rows_updated}"
    )


# ==========================================================
# PROCESS ONE ARTICLE
# ==========================================================

def process_article(
    article,
    existing_pairs
):

    news_id = article.get(
        "news_id"
    )

    title = (
        article.get("title")
        or ""
    )

    article_text = (
        article.get("article_text")
        or ""
    )

    source_country = (
        article.get("source_country")
        or ""
    )

    print()
    print("------------------------------------------")
    print(
        f"ARTICLE {news_id}"
    )

    print(
        title[:150]
    )

    print(
        "  Source country:",
        source_country
    )

    countries = parse_countries(
        article.get(
            "countries"
        )
    )

    print(
        "  Raw countries:",
        article.get(
            "countries"
        )
    )

    print(
        "  Parsed countries:",
        ", ".join(countries)
        if countries
        else "None"
    )

    if not countries:

        print(
            "  REJECTED: No target "
            "ASEAN country detected."
        )

        return {
            "status": "rejected",
            "reason": "no_country",
            "rows": [],
        }

    modelling_text = (
        title.strip()
        + ". "
        + article_text.strip()
    ).strip()

    if not modelling_text:

        print(
            "  REJECTED: "
            "Empty article text."
        )

        return {
            "status": "rejected",
            "reason": "empty_text",
            "rows": [],
        }


    # ------------------------------------------------------
    # LANGUAGE DETECTION
    # ------------------------------------------------------

    detected_language = (
        detect_language(
            modelling_text
        )
    )

    print(
        "  langdetect result:",
        detected_language
    )

    language = resolve_language(
        detected_language,
        source_country,
        modelling_text,
    )

    print(
        "  Google translation source:",
        language
    )


    # ------------------------------------------------------
    # TRANSLATE TITLE
    # ------------------------------------------------------

    print(
        "  Processing title translation..."
    )

    translated_title = (
        translate_to_english(
            title,
            language
        )
    )

    if translated_title is None:

        print(
            "  PROCESSING FAILED: "
            "Title translation failed."
        )

        return {
            "status": "pending",
            "reason": "translation_failed",
            "rows": [],
        }

    translated_title = (
        translated_title.strip()
    )

    print(
        "  English title:",
        translated_title
    )


    # ------------------------------------------------------
    # TRANSLATE ARTICLE TEXT
    # ------------------------------------------------------

    print(
        "  Processing article text "
        "translation..."
    )

    translated_article_text = (
        translate_to_english(
            article_text,
            language
        )
    )

    if translated_article_text is None:

        print(
            "  PROCESSING FAILED: "
            "Article translation failed."
        )

        return {
            "status": "pending",
            "reason": "translation_failed",
            "rows": [],
        }

    translated_text = (
        translated_title.strip()
        + ". "
        + translated_article_text.strip()
    ).strip()


    # ------------------------------------------------------
    # CLEAN TEXT
    # ------------------------------------------------------

    cleaned_text = clean_text(
        translated_text
    )

    word_count = len(
        cleaned_text.split()
    )

    print(
        "  Cleaned word count:",
        word_count
    )

    if word_count < MIN_WORD_COUNT:

        print(
            "  REJECTED: "
            "Insufficient usable text."
        )

        return {
            "status": "rejected",
            "reason": "insufficient_text",
            "rows": [],
        }


    # ------------------------------------------------------
    # DEBERTA CLASSIFICATION
    # ------------------------------------------------------

    print(
        "  Classifying environmental "
        "category using DeBERTa-v3-xsmall "
        "and the first "
        f"{CLASSIFICATION_MAX_CHARACTERS} characters..."
    )

    category, confidence = (
        assign_environment_category(
            cleaned_text
        )
    )

    if (
        category is None
        or confidence is None
    ):

        print(
            "  PROCESSING FAILED: "
            "Classification failed."
        )

        return {
            "status": "pending",
            "reason": "classification_failed",
            "rows": [],
        }

    print(
        "  Category:",
        category
    )

    print(
        "  Confidence:",
        confidence
    )

    if (
        confidence
        < MIN_CATEGORY_CONFIDENCE
    ):

        print(
            "  REJECTED: Category "
            f"confidence {confidence} "
            f"is below "
            f"{MIN_CATEGORY_CONFIDENCE}."
        )

        return {
            "status": "rejected",
            "reason": "low_confidence",
            "rows": [],
        }


    # ------------------------------------------------------
    # EXTRACT KEYWORDS
    # ------------------------------------------------------

    print(
        "  Extracting environmental "
        "keywords..."
    )

    keywords = extract_keywords(
        cleaned_text
    )

    print(
        "  Keywords:",
        keywords
        if keywords
        else "None"
    )


    # ------------------------------------------------------
    # CREATE ONE ROW PER COUNTRY
    # ------------------------------------------------------

    cleaned_rows = []

    for country in countries:

        pair = (
            news_id,
            country
        )

        if pair in existing_pairs:

            print(
                f"  Already exists: "
                f"{news_id} / "
                f"{country}"
            )

            continue

        row = {
            "article_id": news_id,
            "title": translated_title,
            "source": (
                article.get("source")
                or ""
            ),
            "source_country": source_country,
            "published_at": (
                article.get(
                    "published_at"
                )
            ),
            "country": country,
            "cleaned_text": cleaned_text,
            "environment_category": category,
            "environment_keywords": keywords,
            "semantic_score": None,
            "confidence_score": confidence,
            "url": (
                article.get("url")
                or ""
            ),
        }

        cleaned_rows.append(
            row
        )

    if not cleaned_rows:

        print(
            "  All required cleaned rows "
            "already exist."
        )

        return {
            "status": "accepted",
            "reason": "already_exists",
            "rows": [],
        }

    return {
        "status": "accepted",
        "reason": "accepted",
        "rows": cleaned_rows,
    }


# ==========================================================
# MAIN PIPELINE
# ==========================================================

def main():

    print()
    print("==========================================")
    print("ASEAN NEWS CLEANING PIPELINE")
    print("==========================================")

    print(
        "Raw table:",
        RAW_TABLE
    )

    print(
        "Cleaned table:",
        CLEANED_TABLE
    )

    print(
        "Minimum word count:",
        MIN_WORD_COUNT
    )

    print(
        "Minimum category confidence:",
        MIN_CATEGORY_CONFIDENCE
    )

    print(
        "Translation model:",
        "Google Cloud Translation - Standard NMT"
    )

    print(
        "Classification model:",
        "DeBERTa-v3-xsmall zero-shot"
    )

    print(
        "Classification input:",
        f"First {CLASSIFICATION_MAX_CHARACTERS} characters"
    )

    print(
        "Environment categories:",
        len(ENVIRONMENT_CATEGORIES)
    )

    print(
        "Google Cloud project:",
        GOOGLE_CLOUD_PROJECT
    )

    print(
        "Processing device:",
        DEVICE
    )


    # ------------------------------------------------------
    # LOAD EXISTING CLEANED DATA
    # ------------------------------------------------------

    existing_cleaned_rows = (
        get_existing_cleaned_rows()
    )

    existing_pairs = set()

    for row in existing_cleaned_rows:

        article_id = row.get(
            "article_id"
        )

        country = row.get(
            "country"
        )

        if (
            article_id is not None
            and country
        ):

            existing_pairs.add(
                (
                    article_id,
                    country
                )
            )


    # ------------------------------------------------------
    # LOAD PENDING RAW ARTICLES
    # ------------------------------------------------------

    pending_articles = (
        get_pending_raw_articles()
    )

    if not pending_articles:

        print()

        print(
            "No pending raw articles."
        )

        print(
            "No article cleaning "
            "is required."
        )

        print(
            "Semantic scores will still "
            "be recalculated."
        )


    stats = {
        "pending": len(
            pending_articles
        ),
        "accepted": 0,
        "rejected": 0,
        "failed": 0,
        "inserted_rows": 0,
        "translation_failed": 0,
        "classification_failed": 0,
        "no_country": 0,
        "empty_text": 0,
        "insufficient_text": 0,
        "low_confidence": 0,
    }


    # ------------------------------------------------------
    # PROCESS ARTICLES
    # ------------------------------------------------------

    for number, article in enumerate(
        pending_articles,
        start=1
    ):

        news_id = article.get(
            "news_id"
        )

        print()
        print("==========================================")

        print(
            f"PROCESSING "
            f"{number}/"
            f"{len(pending_articles)}"
        )

        print("==========================================")

        try:

            result = process_article(
                article,
                existing_pairs
            )

            status = result[
                "status"
            ]

            reason = result[
                "reason"
            ]

            rows = result[
                "rows"
            ]


            if status == "accepted":

                if rows:

                    inserted = (
                        insert_cleaned_rows(
                            rows
                        )
                    )

                    stats[
                        "inserted_rows"
                    ] += inserted

                    for row in rows:

                        existing_pairs.add(
                            (
                                row[
                                    "article_id"
                                ],
                                row[
                                    "country"
                                ],
                            )
                        )

                set_raw_status(
                    news_id,
                    "accepted"
                )

                stats[
                    "accepted"
                ] += 1

                print(
                    "  RAW STATUS -> "
                    "accepted"
                )


            elif status == "rejected":

                set_raw_status(
                    news_id,
                    "rejected"
                )

                stats[
                    "rejected"
                ] += 1

                if reason in stats:

                    stats[
                        reason
                    ] += 1

                print(
                    "  RAW STATUS -> "
                    "rejected"
                )


            else:

                stats[
                    "failed"
                ] += 1

                if reason in stats:

                    stats[
                        reason
                    ] += 1

                print(
                    "  RAW STATUS remains "
                    "pending."
                )

                print(
                    "  This article can be "
                    "retried on the next run."
                )


        except Exception as e:

            stats[
                "failed"
            ] += 1

            print(
                "  UNEXPECTED "
                "PROCESSING ERROR:"
            )

            print(e)

            print(
                "  RAW STATUS remains "
                "pending."
            )


    # ------------------------------------------------------
    # RECALCULATE SEMANTIC SCORES
    # ------------------------------------------------------

    all_cleaned_rows = (
        get_existing_cleaned_rows()
    )

    semantic_scores = (
        calculate_semantic_scores(
            all_cleaned_rows
        )
    )

    update_semantic_scores(
        semantic_scores
    )


    # ------------------------------------------------------
    # FINAL SUMMARY
    # ------------------------------------------------------

    print()
    print("==========================================")
    print("CLEANING FINISHED")
    print("==========================================")

    print(
        "Pending raw articles found:",
        stats["pending"]
    )

    print(
        "Accepted articles this run:",
        stats["accepted"]
    )

    print(
        "Rejected articles this run:",
        stats["rejected"]
    )

    print(
        "Processing failures / retry later:",
        stats["failed"]
    )

    print(
        "Cleaned country rows inserted:",
        stats["inserted_rows"]
    )

    print()
    print("REJECTION BREAKDOWN")

    print(
        "No target country:",
        stats["no_country"]
    )

    print(
        "Empty text:",
        stats["empty_text"]
    )

    print(
        "Insufficient text:",
        stats["insufficient_text"]
    )

    print(
        "Low category confidence:",
        stats["low_confidence"]
    )

    print()
    print("RETRY BREAKDOWN")

    print(
        "Translation failures:",
        stats["translation_failed"]
    )

    print(
        "Classification failures:",
        stats["classification_failed"]
    )

    print()
    print(
        "Supabase raw table:",
        RAW_TABLE
    )

    print(
        "Supabase cleaned table:",
        CLEANED_TABLE
    )

    print()


# ==========================================================
# RUN
# ==========================================================

if __name__ == "__main__":
    main()

