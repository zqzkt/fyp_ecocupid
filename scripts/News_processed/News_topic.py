# =========================================================
# news_topic.py
#
# SUPABASE MONTHLY ENVIRONMENTAL TOPIC PIPELINE
#
# INPUT:
#   news_cleaned
#
# OUTPUT:
#   topic_registry
#   news_topics
#   monthly_topic_stats
#
# IMPORTANT:
#   - One PRIMARY topic per article
#   - Topics are broader than previous version
#   - Monthly statistics are country-specific
#   - Exactly one sequential rank per topic
#   - No CSV files
# =========================================================


# =========================================================
# IMPORTS
# =========================================================

import os
import re
import warnings

from collections import defaultdict
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from dotenv import load_dotenv
from supabase import create_client

from sentence_transformers import SentenceTransformer

from sklearn.cluster import AgglomerativeClustering

from sklearn.feature_extraction.text import (
    TfidfVectorizer,
    ENGLISH_STOP_WORDS
)

from sklearn.metrics.pairwise import cosine_similarity

from transformers import pipeline


warnings.filterwarnings("ignore")


# =========================================================
# ENVIRONMENT VARIABLES
# =========================================================

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")


if not SUPABASE_URL:
    raise ValueError(
        "SUPABASE_URL is missing from .env"
    )


if not SUPABASE_KEY:
    raise ValueError(
        "SUPABASE_KEY is missing from .env"
    )


# =========================================================
# SUPABASE
# =========================================================

supabase = create_client(
    SUPABASE_URL,
    SUPABASE_KEY
)


CLEANED_TABLE = "news_cleaned"

TOPIC_REGISTRY_TABLE = "topic_registry"

NEWS_TOPICS_TABLE = "news_topics"

MONTHLY_STATS_TABLE = "monthly_topic_stats"


# =========================================================
# ASEAN COUNTRIES
# =========================================================

TARGET_COUNTRIES = [
    "Singapore",
    "Malaysia",
    "Indonesia",
    "Thailand",
    "Philippines",
    "Brunei"
]


# =========================================================
# TOPIC MODELLING SETTINGS
# =========================================================
#
# PREVIOUS:
#   PRIMARY_CLUSTER_DISTANCE = 0.34
#   TOPIC_MERGE_SIMILARITY = 0.82
#
# NEW:
#   Broader initial clustering
#   More aggressive semantic merging
#
# =========================================================

PRIMARY_CLUSTER_DISTANCE = 0.42

TOPIC_MERGE_SIMILARITY = 0.72

REGISTRY_MATCH_THRESHOLD = 0.75


# =========================================================
# ARTICLE-TOPIC SIMILARITY
# =========================================================

WHOLE_ARTICLE_WEIGHT = 0.45

STRONGEST_CHUNK_WEIGHT = 0.55


# =========================================================
# CHUNK SETTINGS
# =========================================================

CHUNK_SIZE = 100

CHUNK_STRIDE = 60


# =========================================================
# KEYWORD SETTINGS
# =========================================================

TOP_KEYWORDS = 3

MAX_KEYWORD_CANDIDATES = 30


# =========================================================
# SUPABASE SETTINGS
# =========================================================

PAGE_SIZE = 1000

WRITE_BATCH_SIZE = 100


# =========================================================
# STOPWORDS
# =========================================================

CUSTOM_STOPWORDS = set(
    ENGLISH_STOP_WORDS
)


CUSTOM_STOPWORDS.update({

    # Journalism
    "said",
    "say",
    "says",
    "according",
    "reported",
    "report",
    "reports",
    "told",
    "added",
    "published",
    "updated",
    "article",
    "news",

    # Generic
    "people",
    "public",
    "year",
    "years",
    "new",
    "government",
    "ministry",
    "agency",
    "official",
    "officials",

    # Countries
    "singapore",
    "singaporean",
    "singaporeans",

    "malaysia",
    "malaysian",
    "malaysians",

    "indonesia",
    "indonesian",
    "indonesians",

    "thailand",
    "thai",

    "philippines",
    "philippine",
    "filipino",
    "filipinos",

    "brunei",
    "bruneian",

    "asean"
})


# =========================================================
# LOAD MODELS
# =========================================================

print()
print("=" * 70)
print("LOADING NLP MODELS")
print("=" * 70)


print(
    "Loading MiniLM embedding model..."
)

embedding_model = SentenceTransformer(
    "all-MiniLM-L6-v2"
)

print(
    "MiniLM loaded."
)


print(
    "Loading FLAN-T5..."
)

text_generator = pipeline(
    "text2text-generation",
    model="google/flan-t5-base",
    tokenizer="google/flan-t5-base",
    device=-1
)

print(
    "FLAN-T5 loaded."
)


# =========================================================
# NORMALISE TEXT
# =========================================================

def normalise_text(text):

    if pd.isna(text):
        return ""

    text = str(text)

    text = re.sub(
        r"\s+",
        " ",
        text
    )

    return text.strip()


# =========================================================
# GENERATE TEXT
# =========================================================

def generate_text(
    prompt,
    max_new_tokens=60
):

    try:

        result = text_generator(
            prompt,
            max_new_tokens=max_new_tokens,
            do_sample=False
        )

        return normalise_text(
            result[0]["generated_text"]
        )

    except Exception as e:

        print(
            f"FLAN-T5 generation failed: {e}"
        )

        return ""


# =========================================================
# CLEAN GENERATED SENTENCE
# =========================================================

def clean_generated_sentence(text):

    text = normalise_text(text)

    text = re.sub(
        (
            r"^(summary|article summary|"
            r"explanation|relevance|answer)"
            r"\s*:\s*"
        ),
        "",
        text,
        flags=re.IGNORECASE
    ).strip()


    match = re.match(
        r"^(.+?[.!?])(?:\s|$)",
        text
    )


    if match:
        text = match.group(1).strip()


    if (
        text
        and
        text[-1] not in ".!?"
    ):
        text += "."


    return text


# =========================================================
# SUPABASE PAGINATION
# =========================================================

def fetch_all_rows(
    table_name,
    columns="*"
):

    rows = []

    start = 0


    while True:

        response = (
            supabase
            .table(table_name)
            .select(columns)
            .range(
                start,
                start + PAGE_SIZE - 1
            )
            .execute()
        )


        batch = response.data or []

        rows.extend(batch)


        if len(batch) < PAGE_SIZE:
            break


        start += PAGE_SIZE


    return rows


# =========================================================
# MONTH HELPER
# =========================================================

def month_start_string(value):

    dt = pd.to_datetime(
        value,
        utc=True,
        errors="coerce"
    )


    if pd.isna(dt):
        return None


    return (
        f"{dt.year:04d}-"
        f"{dt.month:02d}-01"
    )


# =========================================================
# SPLIT ARTICLE INTO CHUNKS
# =========================================================

def split_into_chunks(text):

    words = normalise_text(
        text
    ).split()


    if not words:
        return []


    if len(words) <= CHUNK_SIZE:
        return [
            " ".join(words)
        ]


    chunks = []

    start = 0


    while start < len(words):

        chunk = words[
            start:
            start + CHUNK_SIZE
        ]


        if len(chunk) >= 25:

            chunks.append(
                " ".join(chunk)
            )


        start += CHUNK_STRIDE


    return chunks


# =========================================================
# CALCULATE CENTROID
# =========================================================

def calculate_centroid(embeddings):

    centroid = np.mean(
        embeddings,
        axis=0
    )


    norm = np.linalg.norm(
        centroid
    )


    if norm > 0:
        centroid = centroid / norm


    return centroid


# =========================================================
# INITIAL ARTICLE CLUSTERING
# =========================================================

def cluster_articles(embeddings):

    if len(embeddings) == 1:
        return np.array([0])


    clustering_model = AgglomerativeClustering(
        n_clusters=None,
        metric="cosine",
        linkage="average",
        distance_threshold=(
            PRIMARY_CLUSTER_DISTANCE
        )
    )


    return clustering_model.fit_predict(
        embeddings
    )


# =========================================================
# MERGE SIMILAR CLUSTERS
# =========================================================

def merge_similar_clusters(
    embeddings,
    labels
):

    unique_labels = sorted(
        set(labels)
    )


    if len(unique_labels) <= 1:

        return np.zeros(
            len(labels),
            dtype=int
        )


    centroids = []


    for label in unique_labels:

        positions = np.where(
            labels == label
        )[0]


        centroid = calculate_centroid(
            embeddings[positions]
        )


        centroids.append(
            centroid
        )


    centroids = np.vstack(
        centroids
    )


    # -----------------------------------------------------
    # Convert cosine similarity threshold to
    # cosine distance:
    #
    # similarity 0.72
    # distance   0.28
    # -----------------------------------------------------

    merge_model = AgglomerativeClustering(
        n_clusters=None,
        metric="cosine",
        linkage="average",
        distance_threshold=(
            1 - TOPIC_MERGE_SIMILARITY
        )
    )


    merged_labels = merge_model.fit_predict(
        centroids
    )


    mapping = {

        original_label:
            merged_label

        for (
            original_label,
            merged_label
        )
        in zip(
            unique_labels,
            merged_labels
        )
    }


    return np.array([

        mapping[label]

        for label in labels

    ])


# =========================================================
# CLEAN KEYWORD
# =========================================================

def clean_keyword(phrase):

    phrase = (
        normalise_text(phrase)
        .lower()
    )


    words = []


    for word in phrase.split():

        word = re.sub(
            r"[^a-zA-Z\-]",
            "",
            word
        )


        if not word:
            continue


        if word in CUSTOM_STOPWORDS:
            continue


        if len(word) <= 2:
            continue


        if re.fullmatch(
            r"(19|20)\d{2}",
            word
        ):
            continue


        words.append(word)


    if not words:
        return None


    return " ".join(words)


# =========================================================
# REMOVE REDUNDANT KEYWORDS
# =========================================================

def remove_redundant_keywords(
    keywords
):

    selected = []


    for candidate in keywords:

        candidate_words = set(
            candidate.split()
        )


        redundant = False


        for existing in selected:

            existing_words = set(
                existing.split()
            )


            intersection = len(
                candidate_words
                &
                existing_words
            )


            smaller = min(
                len(candidate_words),
                len(existing_words)
            )


            if (
                smaller > 0
                and
                intersection / smaller >= 0.80
            ):

                redundant = True

                break


        if not redundant:

            selected.append(
                candidate
            )


        if len(selected) >= TOP_KEYWORDS:
            break


    return selected


# =========================================================
# EXTRACT TOPIC KEYWORDS
# =========================================================

def extract_topic_keywords(
    documents,
    topic_centroid
):

    documents = [

        normalise_text(document)

        for document in documents

        if normalise_text(document)

    ]


    if not documents:
        return []


    vectorizer = TfidfVectorizer(
        stop_words=list(
            CUSTOM_STOPWORDS
        ),
        ngram_range=(1, 3),
        min_df=1,
        max_df=1.0,
        max_features=5000
    )


    try:

        matrix = vectorizer.fit_transform(
            documents
        )

    except ValueError:

        return []


    features = (
        vectorizer
        .get_feature_names_out()
    )


    tfidf_scores = np.asarray(
        matrix.mean(axis=0)
    ).flatten()


    ranked_positions = np.argsort(
        tfidf_scores
    )[::-1]


    candidates = []


    for position in ranked_positions:

        phrase = clean_keyword(
            features[position]
        )


        if not phrase:
            continue


        if phrase not in candidates:
            candidates.append(
                phrase
            )


        if (
            len(candidates)
            >=
            MAX_KEYWORD_CANDIDATES
        ):
            break


    if not candidates:
        return []


    candidate_embeddings = (
        embedding_model.encode(
            candidates,
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False
        )
    )


    semantic_scores = (
        cosine_similarity(
            candidate_embeddings,
            topic_centroid.reshape(
                1,
                -1
            )
        )
        .flatten()
    )


    semantic_order = np.argsort(
        semantic_scores
    )[::-1]


    ranked_keywords = [

        candidates[position]

        for position
        in semantic_order

    ]


    return remove_redundant_keywords(
        ranked_keywords
    )[:TOP_KEYWORDS]


# =========================================================
# FALLBACK TOPIC NAME
# =========================================================

def keyword_topic_name(keywords):

    if not keywords:
        return "Unlabelled Topic"


    name = normalise_text(
        keywords[0]
    )


    if not name:
        return "Unlabelled Topic"


    return name.title()


# =========================================================
# GENERATE TOPIC NAME
# =========================================================

def generate_topic_name(
    environment_category,
    keywords,
    titles
):

    keyword_text = ", ".join(
        keywords[:5]
    )


    title_text = " | ".join(

        normalise_text(title)

        for title in titles[:5]

        if normalise_text(title)

    )


    prompt = (
        "Create one broad but meaningful topic name "
        "for this group of environmental news articles.\n\n"

        f"Environmental category: "
        f"{environment_category}\n"

        f"Keywords: "
        f"{keyword_text}\n"

        f"Article titles: "
        f"{title_text}\n\n"

        "The topic should combine closely related "
        "environmental issues rather than creating an "
        "overly specific topic.\n\n"

        "For example:\n"

        "- haze, PM2.5 and poor air quality can be "
        "called 'Air Pollution and Haze'\n"

        "- forest loss, deforestation and forest "
        "protection can be called "
        "'Forest Conservation and Deforestation'\n\n"

        "Rules:\n"

        "- Use 2 to 6 words.\n"

        "- Use a broad environmental concept.\n"

        "- Do not use country names or city names.\n"

        "- Do not use dates or years.\n"

        "- Do not simply repeat the environmental category.\n"

        "- Do not say 'environmental issue'.\n"

        "- Return only the topic name."
    )


    topic_name = generate_text(
        prompt,
        max_new_tokens=20
    )


    topic_name = re.sub(
        r"[\n\r]+",
        " ",
        topic_name
    )


    topic_name = re.sub(
        r"\s+",
        " ",
        topic_name
    ).strip(
        " .,:;-/\"'"
    )


    prefixes = [
        "topic:",
        "topic name:",
        "subtopic:",
        "subtopic name:"
    ]


    for prefix in prefixes:

        if (
            topic_name.lower()
            .startswith(prefix)
        ):

            topic_name = (
                topic_name[
                    len(prefix):
                ]
                .strip()
            )


    topic_name = re.sub(
        r"\b(?:19|20)\d{2}\b",
        "",
        topic_name
    )


    topic_name = re.sub(
        r"\s+",
        " ",
        topic_name
    ).strip()


    invalid_names = {
        "",
        "environment",
        "environmental issue",
        "environmental issues",
        "environmental problem",
        "environmental problems",
        "environmental topic",
        "environmental topics",
        environment_category.lower()
    }


    if (
        topic_name.lower()
        in invalid_names
        or
        len(topic_name.split()) > 8
    ):

        topic_name = keyword_topic_name(
            keywords
        )


    return topic_name


# =========================================================
# ARTICLE-TOPIC SIMILARITY
# =========================================================

def calculate_article_topic_score(
    article_text,
    article_embedding,
    topic_centroid
):

    whole_similarity = float(

        cosine_similarity(
            article_embedding.reshape(
                1,
                -1
            ),
            topic_centroid.reshape(
                1,
                -1
            )
        )[0][0]

    )


    chunks = split_into_chunks(
        article_text
    )


    if not chunks:
        return whole_similarity


    chunk_embeddings = (
        embedding_model.encode(
            chunks,
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False
        )
    )


    chunk_scores = (
        cosine_similarity(
            chunk_embeddings,
            topic_centroid.reshape(
                1,
                -1
            )
        )
        .flatten()
    )


    strongest_chunk = float(
        np.max(chunk_scores)
    )


    final_score = (
        WHOLE_ARTICLE_WEIGHT
        *
        whole_similarity
        +
        STRONGEST_CHUNK_WEIGHT
        *
        strongest_chunk
    )


    return float(final_score)


# =========================================================
# ARTICLE SUMMARY
# =========================================================

def generate_article_summary(
    title,
    article_text
):

    title = normalise_text(title)

    article_text = normalise_text(
        article_text
    )


    article_for_prompt = (
        article_text[:3500]
    )


    prompt = (
        "Summarize this environmental news article "
        "in exactly one concise factual sentence. "

        "State the main issue or development. "
        "Do not add information that is not stated "
        "in the article. "
        "Return only one sentence.\n\n"

        f"Title: {title}\n\n"

        f"Article: {article_for_prompt}"
    )


    summary = generate_text(
        prompt,
        max_new_tokens=70
    )


    summary = clean_generated_sentence(
        summary
    )


    if not summary:

        summary = clean_generated_sentence(
            title
        )


    if not summary:

        summary = (
            "The article discusses an "
            "environmental development."
        )


    return summary


# =========================================================
# TOPIC RELEVANCE EXPLANATION
# =========================================================

def generate_topic_relevance_explanation(
    article_summary,
    topic_name,
    topic_keywords
):

    keyword_text = ", ".join(
        topic_keywords
    )


    prompt = (
        "Explain in exactly one concise factual "
        "sentence why this article belongs to the "
        "assigned environmental topic. "

        "Use only the information provided. "
        "Do not introduce new facts. "
        "Return only one sentence.\n\n"

        f"Article summary: "
        f"{article_summary}\n\n"

        f"Assigned topic: "
        f"{topic_name}\n\n"

        f"Topic keywords: "
        f"{keyword_text}"
    )


    explanation = generate_text(
        prompt,
        max_new_tokens=70
    )


    explanation = clean_generated_sentence(
        explanation
    )


    if not explanation:

        explanation = (
            f"The article relates to {topic_name} "
            "through the environmental issue "
            "described in its content."
        )


    return explanation


# =========================================================
# LOAD NEWS_CLEANED
# =========================================================

def load_cleaned_rows():

    print()
    print("=" * 70)
    print("LOADING NEWS_CLEANED")
    print("=" * 70)


    rows = fetch_all_rows(
        CLEANED_TABLE,
        (
            "article_id,"
            "title,"
            "published_at,"
            "country,"
            "cleaned_text,"
            "environment_category"
        )
    )


    df = pd.DataFrame(rows)


    if df.empty:

        print(
            "No news_cleaned rows found."
        )

        return df


    df["article_id"] = pd.to_numeric(
        df["article_id"],
        errors="coerce"
    )


    df = df[
        df["article_id"].notna()
    ].copy()


    df["article_id"] = (
        df["article_id"]
        .astype(int)
    )


    for column in [
        "title",
        "country",
        "cleaned_text",
        "environment_category"
    ]:

        df[column] = (
            df[column]
            .fillna("")
            .astype(str)
        )


    df = df[
        df["country"].isin(
            TARGET_COUNTRIES
        )
        &
        (
            df["cleaned_text"]
            .str.strip()
            !=
            ""
        )
        &
        (
            df["environment_category"]
            .str.strip()
            !=
            ""
        )
    ].copy()


    print(
        f"Valid cleaned rows loaded: "
        f"{len(df)}"
    )


    print(
        "Unique articles: "
        f"{df['article_id'].nunique()}"
    )


    return df


# =========================================================
# LOAD PROCESSED ARTICLE-COUNTRY PAIRS
# =========================================================

def load_processed_pairs():

    rows = fetch_all_rows(
        NEWS_TOPICS_TABLE,
        "article_id,country"
    )


    processed_pairs = set()


    for row in rows:

        article_id = row.get(
            "article_id"
        )

        country = row.get(
            "country"
        )


        if (
            article_id is None
            or
            country is None
        ):
            continue


        processed_pairs.add(
            (
                int(article_id),
                str(country)
            )
        )


    print(
        "Previously processed "
        "article-country pairs: "
        f"{len(processed_pairs)}"
    )


    return processed_pairs


# =========================================================
# LOAD TOPIC REGISTRY
# =========================================================

def load_topic_registry():

    rows = fetch_all_rows(
        TOPIC_REGISTRY_TABLE,
        (
            "topic_id,"
            "environment_category,"
            "topic_name,"
            "topic_keywords,"
            "topic_centroid,"
            "first_detected_at,"
            "last_detected_at"
        )
    )


    registry = []


    for row in rows:

        centroid = row.get(
            "topic_centroid"
        )


        if not isinstance(
            centroid,
            list
        ):
            continue


        try:

            centroid_array = np.asarray(
                centroid,
                dtype=float
            )

        except Exception:
            continue


        if centroid_array.ndim != 1:
            continue


        if centroid_array.size == 0:
            continue


        norm = np.linalg.norm(
            centroid_array
        )


        if norm > 0:

            centroid_array = (
                centroid_array
                /
                norm
            )


        row[
            "centroid_array"
        ] = centroid_array


        registry.append(row)


    print(
        f"Registry topics loaded: "
        f"{len(registry)}"
    )


    return registry


# =========================================================
# NEXT TOPIC NUMBER
# =========================================================

def get_next_topic_number(registry):

    highest = 0


    for topic in registry:

        topic_id = str(
            topic.get(
                "topic_id",
                ""
            )
        ).strip()


        match = re.fullmatch(
            r"T(\d+)",
            topic_id
        )


        if match:

            highest = max(
                highest,
                int(
                    match.group(1)
                )
            )


    return highest + 1


# =========================================================
# FIND REGISTRY MATCH
# =========================================================

def find_registry_match(
    environment_category,
    new_centroid,
    registry
):

    candidates = [

        topic

        for topic in registry

        if (
            topic.get(
                "environment_category"
            )
            ==
            environment_category
        )

    ]


    if not candidates:

        return None, None


    best_topic = None

    best_similarity = -1.0


    for topic in candidates:

        existing_centroid = (
            topic[
                "centroid_array"
            ]
        )


        if (
            existing_centroid.shape
            !=
            new_centroid.shape
        ):
            continue


        similarity = float(

            cosine_similarity(
                new_centroid.reshape(
                    1,
                    -1
                ),
                existing_centroid.reshape(
                    1,
                    -1
                )
            )[0][0]

        )


        if similarity > best_similarity:

            best_similarity = similarity

            best_topic = topic


    if (
        best_topic is not None
        and
        best_similarity
        >=
        REGISTRY_MATCH_THRESHOLD
    ):

        return (
            best_topic,
            best_similarity
        )


    return (
        None,
        best_similarity
    )


# =========================================================
# INSERT REGISTRY TOPIC
# =========================================================

def insert_registry_topic(
    topic_id,
    environment_category,
    topic_name,
    topic_keywords,
    centroid,
    first_detected_at,
    last_detected_at
):

    payload = {

        "topic_id":
            topic_id,

        "environment_category":
            environment_category,

        "topic_name":
            topic_name,

        "topic_keywords":
            ", ".join(
                topic_keywords
            ),

        "topic_centroid":
            centroid
            .astype(float)
            .tolist(),

        "first_detected_at":
            first_detected_at,

        "last_detected_at":
            last_detected_at

    }


    (
        supabase
        .table(
            TOPIC_REGISTRY_TABLE
        )
        .insert(payload)
        .execute()
    )


    return {

        **payload,

        "centroid_array":
            centroid.copy()

    }


# =========================================================
# UPDATE REGISTRY LAST DETECTED
# =========================================================

def update_registry_last_detected(
    topic_id,
    detected_at
):

    (
        supabase
        .table(
            TOPIC_REGISTRY_TABLE
        )
        .update({
            "last_detected_at":
                detected_at,

            "updated_at":
                datetime.now(
                    timezone.utc
                ).isoformat()
        })
        .eq(
            "topic_id",
            topic_id
        )
        .execute()
    )


# =========================================================
# DISCOVER TOPICS FOR MONTH
# =========================================================

def discover_topics_for_month(
    month_df,
    registry,
    next_topic_number
):

    # -----------------------------------------------------
    # Deduplicate article-country rows before modelling.
    #
    # Same article appearing in three countries must not
    # affect clustering three times.
    # -----------------------------------------------------

    modelling_df = (
        month_df
        .sort_values(
            [
                "article_id",
                "country"
            ]
        )
        .drop_duplicates(
            subset=[
                "article_id"
            ]
        )
        .reset_index(
            drop=True
        )
    )


    article_category_data = {}


    for (
        category,
        category_df
    ) in modelling_df.groupby(
        "environment_category",
        sort=True
    ):

        category_df = (
            category_df
            .reset_index(
                drop=True
            )
        )


        print()
        print("=" * 70)

        print(
            f"CATEGORY: {category}"
        )

        print(
            "Unique articles: "
            f"{len(category_df)}"
        )

        print("=" * 70)


        documents = (
            category_df[
                "cleaned_text"
            ]
            .tolist()
        )


        print(
            "Generating article embeddings..."
        )


        embeddings = (
            embedding_model.encode(
                documents,
                convert_to_numpy=True,
                normalize_embeddings=True,
                show_progress_bar=True
            )
        )


        # =================================================
        # INITIAL CLUSTERING
        # =================================================

        initial_labels = cluster_articles(
            embeddings
        )


        print(
            "Initial clusters: "
            f"{len(set(initial_labels))}"
        )


        # =================================================
        # BROADER CLUSTER MERGING
        # =================================================

        final_labels = merge_similar_clusters(
            embeddings,
            initial_labels
        )


        unique_labels = sorted(
            set(final_labels)
        )


        print(
            "Clusters after semantic merging: "
            f"{len(unique_labels)}"
        )


        category_topics = []


        # =================================================
        # BUILD TOPICS
        # =================================================

        for (
            cluster_number,
            cluster_label
        ) in enumerate(
            unique_labels,
            start=1
        ):

            print()
            print(
                f"Processing cluster "
                f"{cluster_number}/"
                f"{len(unique_labels)}..."
            )


            positions = np.where(
                final_labels
                ==
                cluster_label
            )[0]


            print(
                "  Articles in cluster: "
                f"{len(positions)}"
            )


            cluster_embeddings = (
                embeddings[
                    positions
                ]
            )


            centroid = calculate_centroid(
                cluster_embeddings
            )


            cluster_documents = [

                documents[position]

                for position
                in positions

            ]


            cluster_titles = [

                str(
                    category_df.iloc[
                        position
                    ]["title"]
                )

                for position
                in positions

            ]


            # =============================================
            # KEYWORDS
            # =============================================

            print(
                "  Extracting keywords..."
            )


            monthly_keywords = (
                extract_topic_keywords(
                    cluster_documents,
                    centroid
                )
            )


            print(
                "  Keywords: "
                +
                (
                    ", ".join(
                        monthly_keywords
                    )
                    if monthly_keywords
                    else
                    "None"
                )
            )


            # =============================================
            # REGISTRY MATCHING
            # =============================================

            print(
                "  Comparing with "
                "topic_registry..."
            )


            (
                registry_match,
                registry_similarity
            ) = find_registry_match(
                category,
                centroid,
                registry
            )


            # =============================================
            # EXISTING TOPIC
            # =============================================

            if registry_match is not None:

                topic_id = (
                    registry_match[
                        "topic_id"
                    ]
                )


                topic_name = (
                    registry_match[
                        "topic_name"
                    ]
                )


                stored_keywords = (
                    normalise_text(
                        registry_match.get(
                            "topic_keywords",
                            ""
                        )
                    )
                )


                topic_keywords = [

                    keyword.strip()

                    for keyword
                    in stored_keywords.split(",")

                    if keyword.strip()

                ]


                print(
                    f"  Existing topic: "
                    f"{topic_id} - "
                    f"{topic_name}"
                )


                print(
                    "  Registry similarity: "
                    f"{registry_similarity:.4f}"
                )


            # =============================================
            # NEW TOPIC
            # =============================================

            else:

                topic_id = (
                    f"T"
                    f"{next_topic_number:04d}"
                )


                next_topic_number += 1


                # -----------------------------------------
                # Even single-article clusters are named
                # with FLAN-T5 now.
                #
                # This helps produce broader labels rather
                # than simply taking an overly-specific
                # first keyword.
                # -----------------------------------------

                print(
                    "  Generating broad topic name "
                    "with FLAN-T5..."
                )


                topic_name = (
                    generate_topic_name(
                        category,
                        monthly_keywords,
                        cluster_titles
                    )
                )


                published_dates = (
                    pd.to_datetime(
                        category_df.iloc[
                            positions
                        ][
                            "published_at"
                        ],
                        utc=True,
                        errors="coerce"
                    )
                    .dropna()
                )


                if len(
                    published_dates
                ) > 0:

                    first_detected_at = (
                        published_dates
                        .min()
                        .isoformat()
                    )


                    last_detected_at = (
                        published_dates
                        .max()
                        .isoformat()
                    )


                else:

                    now = (
                        datetime.now(
                            timezone.utc
                        )
                        .isoformat()
                    )


                    first_detected_at = now

                    last_detected_at = now


                new_registry_topic = (
                    insert_registry_topic(
                        topic_id=topic_id,
                        environment_category=(
                            category
                        ),
                        topic_name=topic_name,
                        topic_keywords=(
                            monthly_keywords
                        ),
                        centroid=centroid,
                        first_detected_at=(
                            first_detected_at
                        ),
                        last_detected_at=(
                            last_detected_at
                        )
                    )
                )


                registry.append(
                    new_registry_topic
                )


                topic_keywords = (
                    monthly_keywords
                )


                print(
                    f"  New registry topic: "
                    f"{topic_id} - "
                    f"{topic_name}"
                )


                if (
                    registry_similarity
                    is not None
                ):

                    print(
                        "  Best previous registry "
                        "similarity: "
                        f"{registry_similarity:.4f}"
                    )


            category_topics.append({

                "environment_category":
                    category,

                "cluster_label":
                    cluster_label,

                "topic_id":
                    topic_id,

                "topic_name":
                    topic_name,

                "topic_keywords":
                    topic_keywords,

                "monthly_keywords":
                    monthly_keywords,

                "centroid":
                    centroid,

                "article_positions":
                    positions
            })


        article_category_data[
            category
        ] = {

            "df":
                category_df,

            "embeddings":
                embeddings,

            "labels":
                final_labels,

            "topics":
                category_topics
        }


    return (
        article_category_data,
        next_topic_number
    )


# =========================================================
# ASSIGN ONE PRIMARY TOPIC PER ARTICLE
# =========================================================

def assign_primary_topics(
    article_category_data
):

    assignments = []


    for (
        category,
        category_data
    ) in article_category_data.items():

        category_df = (
            category_data[
                "df"
            ]
        )


        embeddings = (
            category_data[
                "embeddings"
            ]
        )


        labels = (
            category_data[
                "labels"
            ]
        )


        topics = (
            category_data[
                "topics"
            ]
        )


        topic_by_label = {

            topic[
                "cluster_label"
            ]:
                topic

            for topic in topics

        }


        for article_position in range(
            len(category_df)
        ):

            row = category_df.iloc[
                article_position
            ]


            article_id = int(
                row[
                    "article_id"
                ]
            )


            article_text = (
                row[
                    "cleaned_text"
                ]
            )


            article_embedding = (
                embeddings[
                    article_position
                ]
            )


            primary_label = (
                labels[
                    article_position
                ]
            )


            primary_topic = (
                topic_by_label[
                    primary_label
                ]
            )


            score = (
                calculate_article_topic_score(
                    article_text,
                    article_embedding,
                    primary_topic[
                        "centroid"
                    ]
                )
            )


            assignments.append({

                "article_id":
                    article_id,

                "environment_category":
                    category,

                "topic":
                    primary_topic,

                "score":
                    score
            })


    return assignments


# =========================================================
# BUILD NEWS_TOPICS ROWS
# =========================================================

def build_news_topic_rows(
    month_df,
    assignments,
    pending_pairs
):

    article_lookup = (
        month_df
        .sort_values(
            [
                "article_id",
                "country"
            ]
        )
        .drop_duplicates(
            subset=[
                "article_id"
            ]
        )
        .set_index(
            "article_id"
        )
        .to_dict(
            "index"
        )
    )


    countries_by_article = (
        month_df
        .groupby(
            "article_id"
        )[
            "country"
        ]
        .apply(
            lambda values:
                sorted(
                    set(values)
                )
        )
        .to_dict()
    )


    summary_cache = {}

    explanation_cache = {}

    output_rows = []


    total_assignments = len(
        assignments
    )


    for (
        assignment_number,
        assignment
    ) in enumerate(
        assignments,
        start=1
    ):

        article_id = (
            assignment[
                "article_id"
            ]
        )


        topic = (
            assignment[
                "topic"
            ]
        )


        target_countries = [

            country

            for country
            in countries_by_article.get(
                article_id,
                []
            )

            if (
                (
                    article_id,
                    country
                )
                in
                pending_pairs
            )

        ]


        if not target_countries:
            continue


        article = (
            article_lookup[
                article_id
            ]
        )


        print()
        print(
            f"Preparing article "
            f"{assignment_number}/"
            f"{total_assignments}: "
            f"{article_id}"
        )


        # =============================================
        # SUMMARY
        # =============================================

        if (
            article_id
            not in
            summary_cache
        ):

            print(
                "  Generating article summary..."
            )


            summary_cache[
                article_id
            ] = (
                generate_article_summary(
                    article.get(
                        "title",
                        ""
                    ),
                    article.get(
                        "cleaned_text",
                        ""
                    )
                )
            )


        # =============================================
        # RELEVANCE EXPLANATION
        # =============================================

        explanation_key = (
            article_id,
            topic[
                "topic_id"
            ]
        )


        if (
            explanation_key
            not in
            explanation_cache
        ):

            print(
                "  Generating topic "
                "relevance explanation..."
            )


            explanation_cache[
                explanation_key
            ] = (
                generate_topic_relevance_explanation(
                    article_summary=(
                        summary_cache[
                            article_id
                        ]
                    ),
                    topic_name=(
                        topic[
                            "topic_name"
                        ]
                    ),
                    topic_keywords=(
                        topic[
                            "topic_keywords"
                        ]
                    )
                )
            )


        # =============================================
        # ONE ROW PER ARTICLE-COUNTRY
        # =============================================

        for country in target_countries:

            output_rows.append({

                "article_id":
                    article_id,

                "topic_id":
                    topic[
                        "topic_id"
                    ],

                "country":
                    country,

                "article_topic_similarity":
                    round(
                        float(
                            assignment[
                                "score"
                            ]
                        ),
                        4
                    ),

                "article_summary":
                    summary_cache[
                        article_id
                    ],

                "topic_relevance_explanation":
                    explanation_cache[
                        explanation_key
                    ]
            })


    return output_rows


# =========================================================
# UPSERT NEWS_TOPICS
# =========================================================

def upsert_news_topics(rows):

    if not rows:

        print(
            "No news_topics rows "
            "to insert."
        )

        return


    unique_rows = {}


    for row in rows:

        key = (
            row["article_id"],
            row["topic_id"],
            row["country"]
        )


        unique_rows[key] = row


    rows = list(
        unique_rows.values()
    )


    print()
    print("=" * 70)
    print("WRITING NEWS_TOPICS")
    print("=" * 70)


    print(
        f"Rows to write: "
        f"{len(rows)}"
    )


    for start in range(
        0,
        len(rows),
        WRITE_BATCH_SIZE
    ):

        batch = rows[
            start:
            start + WRITE_BATCH_SIZE
        ]


        (
            supabase
            .table(
                NEWS_TOPICS_TABLE
            )
            .upsert(
                batch,
                on_conflict=(
                    "article_id,"
                    "topic_id,"
                    "country"
                )
            )
            .execute()
        )


        print(
            "Written: "
            f"{min(start + WRITE_BATCH_SIZE, len(rows))}"
            f"/{len(rows)}"
        )


# =========================================================
# UPDATE REGISTRY LAST DETECTED
# =========================================================

def update_registry_dates(
    month_df,
    assignments
):

    published_lookup = (
        month_df
        .sort_values(
            "published_at"
        )
        .drop_duplicates(
            subset=[
                "article_id"
            ],
            keep="last"
        )
        .set_index(
            "article_id"
        )[
            "published_at"
        ]
        .to_dict()
    )


    latest_by_topic = {}


    for assignment in assignments:

        topic_id = (
            assignment[
                "topic"
            ][
                "topic_id"
            ]
        )


        article_id = (
            assignment[
                "article_id"
            ]
        )


        dt = pd.to_datetime(
            published_lookup.get(
                article_id
            ),
            utc=True,
            errors="coerce"
        )


        if pd.isna(dt):
            continue


        previous = (
            latest_by_topic.get(
                topic_id
            )
        )


        if (
            previous is None
            or
            dt > previous
        ):

            latest_by_topic[
                topic_id
            ] = dt


    for (
        topic_id,
        dt
    ) in latest_by_topic.items():

        update_registry_last_detected(
            topic_id,
            dt.isoformat()
        )


# =========================================================
# REBUILD MONTHLY TOPIC STATS
# =========================================================

def rebuild_monthly_stats(
    month_string,
    month_df
):

    print()
    print("=" * 70)
    print("REBUILDING MONTHLY TOPIC STATS")
    print("=" * 70)


    # =====================================================
    # ARTICLE IDS BELONGING TO THIS MONTH
    # =====================================================

    month_article_ids = set(
        month_df[
            "article_id"
        ]
        .astype(int)
        .tolist()
    )


    # =====================================================
    # LOAD NEWS_TOPICS
    # =====================================================

    topic_rows = fetch_all_rows(
        NEWS_TOPICS_TABLE,
        (
            "article_id,"
            "topic_id,"
            "country,"
            "article_topic_similarity"
        )
    )


    # -----------------------------------------------------
    # IMPORTANT:
    #
    # Only retain:
    #   1. Articles published in this month
    #   2. The exact article-country pair that exists
    #      in month_df
    #
    # This prevents a topic's global article count from
    # being copied into every country.
    # -----------------------------------------------------

    valid_month_pairs = set(

        zip(
            month_df[
                "article_id"
            ].astype(int),

            month_df[
                "country"
            ].astype(str)
        )

    )


    topic_rows = [

        row

        for row in topic_rows

        if (
            int(
                row[
                    "article_id"
                ]
            )
            in
            month_article_ids

            and

            (
                int(
                    row[
                        "article_id"
                    ]
                ),
                str(
                    row[
                        "country"
                    ]
                )
            )
            in
            valid_month_pairs
        )

    ]


    if not topic_rows:

        print(
            "No topic rows found "
            "for this month."
        )

        return


    # =====================================================
    # REGISTRY TOPIC NAMES
    # =====================================================

    registry_rows = fetch_all_rows(
        TOPIC_REGISTRY_TABLE,
        "topic_id,topic_name"
    )


    topic_name_lookup = {

        row[
            "topic_id"
        ]:
            row[
                "topic_name"
            ]

        for row in registry_rows

    }


    # =====================================================
    # CLEANED TEXT LOOKUP
    # =====================================================

    cleaned_lookup = {

        (
            int(row.article_id),
            row.country
        ):
            row.cleaned_text

        for row in month_df.itertuples(
            index=False
        )

    }


    # =====================================================
    # GROUP BY COUNTRY + TOPIC
    # =====================================================
    #
    # IMPORTANT:
    #
    # Each country's article IDs are stored independently.
    #
    # Example:
    #
    # Singapore + T0001 -> {2, 4}
    # Malaysia  + T0001 -> {8, 9, 10}
    #
    # therefore:
    #
    # Singapore article_count = 2
    # Malaysia  article_count = 3
    #
    # =====================================================

    grouped_articles = defaultdict(
        set
    )


    grouped_similarities = defaultdict(
        list
    )


    for row in topic_rows:

        country = str(
            row[
                "country"
            ]
        )


        topic_id = str(
            row[
                "topic_id"
            ]
        )


        article_id = int(
            row[
                "article_id"
            ]
        )


        key = (
            country,
            topic_id
        )


        grouped_articles[
            key
        ].add(
            article_id
        )


        similarity = row.get(
            "article_topic_similarity"
        )


        if similarity is not None:

            grouped_similarities[
                key
            ].append(
                float(
                    similarity
                )
            )


    # =====================================================
    # CREATE COUNTRY-SPECIFIC STAT ROWS
    # =====================================================

    stat_rows = []


    for (
        country,
        topic_id
    ), article_ids in grouped_articles.items():

        # ---------------------------------------------
        # Get only this country's versions of the
        # articles for monthly keyword extraction.
        # ---------------------------------------------

        documents = [

            cleaned_lookup[
                (
                    article_id,
                    country
                )
            ]

            for article_id
            in article_ids

            if (
                (
                    article_id,
                    country
                )
                in
                cleaned_lookup
            )

        ]


        # =============================================
        # COUNTRY + MONTH SPECIFIC KEYWORDS
        # =============================================

        if documents:

            document_embeddings = (
                embedding_model.encode(
                    documents,
                    convert_to_numpy=True,
                    normalize_embeddings=True,
                    show_progress_bar=False
                )
            )


            monthly_centroid = (
                calculate_centroid(
                    document_embeddings
                )
            )


            monthly_keywords = (
                extract_topic_keywords(
                    documents,
                    monthly_centroid
                )
            )


        else:

            monthly_keywords = []


        similarities = (
            grouped_similarities[
                (
                    country,
                    topic_id
                )
            ]
        )


        if similarities:

            average_similarity = float(
                np.mean(
                    similarities
                )
            )

        else:

            average_similarity = 0.0


        stat_rows.append({

            "month":
                month_string,

            "country":
                country,

            "topic_id":
                topic_id,

            "topic_name":
                topic_name_lookup.get(
                    topic_id,
                    "Unlabelled Topic"
                ),

            # -----------------------------------------
            # DISTINCT ARTICLE COUNT FOR THIS COUNTRY
            # -----------------------------------------

            "article_count":
                len(
                    article_ids
                ),

            "monthly_keywords":
                ", ".join(
                    monthly_keywords
                ),

            # Used only internally for tie-breaking.
            "_average_similarity":
                average_similarity
        })


    stats_df = pd.DataFrame(
        stat_rows
    )


    if stats_df.empty:

        print(
            "No monthly statistics "
            "were produced."
        )

        return


    # =====================================================
    # EXACT SEQUENTIAL RANKING PER COUNTRY
    # =====================================================
    #
    # Previous:
    #
    #   dense rank:
    #       8 -> 1
    #       8 -> 1
    #       7 -> 2
    #       7 -> 2
    #
    # New:
    #
    #   sort by:
    #       1. article_count DESC
    #       2. average similarity DESC
    #       3. topic_id ASC
    #
    # Then assign:
    #
    #       1
    #       2
    #       3
    #       4
    #
    # This means topic_rank <= 3 ALWAYS returns
    # exactly three topics when >= 3 topics exist.
    # =====================================================

    stats_df = (
        stats_df
        .sort_values(
            by=[
                "country",
                "article_count",
                "_average_similarity",
                "topic_id"
            ],
            ascending=[
                True,
                False,
                False,
                True
            ]
        )
        .reset_index(
            drop=True
        )
    )


    stats_df[
        "topic_rank"
    ] = (
        stats_df
        .groupby(
            "country"
        )
        .cumcount()
        +
        1
    )


    # =====================================================
    # SHOW COUNTRY COUNTS BEFORE WRITE
    # =====================================================

    print()
    print(
        "COUNTRY-SPECIFIC TOPIC COUNTS"
    )

    print("-" * 70)


    for country in TARGET_COUNTRIES:

        country_df = stats_df[
            stats_df[
                "country"
            ]
            ==
            country
        ]


        if country_df.empty:
            continue


        print()
        print(country)


        for row in (
            country_df
            .head(5)
            .itertuples(
                index=False
            )
        ):

            print(
                f"  #{row.topic_rank} "
                f"{row.topic_id} - "
                f"{row.topic_name}: "
                f"{row.article_count} article(s)"
            )


    # =====================================================
    # DELETE OLD MONTH
    # =====================================================
    #
    # Your Supabase RLS must allow DELETE on
    # monthly_topic_stats for this operation.
    # =====================================================

    (
        supabase
        .table(
            MONTHLY_STATS_TABLE
        )
        .delete()
        .eq(
            "month",
            month_string
        )
        .execute()
    )


    # =====================================================
    # REMOVE INTERNAL TIE-BREAK COLUMN
    # =====================================================

    payload_df = stats_df.drop(
        columns=[
            "_average_similarity"
        ]
    )


    payload = payload_df[
        [
            "month",
            "country",
            "topic_id",
            "topic_name",
            "article_count",
            "monthly_keywords",
            "topic_rank"
        ]
    ].to_dict(
        "records"
    )


    # =====================================================
    # WRITE MONTHLY STATS
    # =====================================================

    for start in range(
        0,
        len(payload),
        WRITE_BATCH_SIZE
    ):

        batch = payload[
            start:
            start + WRITE_BATCH_SIZE
        ]


        (
            supabase
            .table(
                MONTHLY_STATS_TABLE
            )
            .upsert(
                batch,
                on_conflict=(
                    "month,"
                    "country,"
                    "topic_id"
                )
            )
            .execute()
        )


    print()
    print(
        f"Monthly stats written: "
        f"{len(payload)}"
    )


    # =====================================================
    # TOP 3
    # =====================================================

    print()
    print("=" * 70)
    print("TOP 3 TOPICS BY COUNTRY")
    print("=" * 70)


    top_three = stats_df[
        stats_df[
            "topic_rank"
        ]
        <=
        3
    ]


    for country in TARGET_COUNTRIES:

        country_df = (
            top_three[
                top_three[
                    "country"
                ]
                ==
                country
            ]
            .sort_values(
                "topic_rank"
            )
        )


        if country_df.empty:
            continue


        print()
        print(country)


        for row in country_df.itertuples(
            index=False
        ):

            print(
                f"  #{row.topic_rank} "
                f"{row.topic_id} - "
                f"{row.topic_name}"
            )


            print(
                f"     Articles: "
                f"{row.article_count}"
            )


            print(
                f"     Keywords: "
                f"{row.monthly_keywords}"
            )


# =========================================================
# MAIN
# =========================================================

def main():

    print()
    print("=" * 70)

    print(
        "ASEAN ENVIRONMENTAL TOPIC MODELLING"
    )

    print("=" * 70)


    # =====================================================
    # LOAD CLEANED DATA
    # =====================================================

    cleaned_df = load_cleaned_rows()


    if cleaned_df.empty:

        print(
            "Nothing to process."
        )

        return


    # =====================================================
    # PROCESSED PAIRS
    # =====================================================

    processed_pairs = (
        load_processed_pairs()
    )


    # =====================================================
    # FIND PENDING ARTICLE-COUNTRY PAIRS
    # =====================================================

    cleaned_df[
        "is_processed"
    ] = cleaned_df.apply(

        lambda row:

            (
                int(
                    row[
                        "article_id"
                    ]
                ),
                row[
                    "country"
                ]
            )
            in
            processed_pairs,

        axis=1
    )


    pending_df = cleaned_df[
        ~cleaned_df[
            "is_processed"
        ]
    ].copy()


    print()
    print("=" * 70)
    print("PROCESSING STATUS")
    print("=" * 70)


    print(
        f"news_cleaned rows: "
        f"{len(cleaned_df)}"
    )


    print(
        f"Unique articles: "
        f"{cleaned_df['article_id'].nunique()}"
    )


    print(
        "Already processed "
        "article-country rows: "
        f"{int(cleaned_df['is_processed'].sum())}"
    )


    print(
        "Unprocessed "
        "article-country rows: "
        f"{len(pending_df)}"
    )


    if pending_df.empty:

        print()
        print(
            "No new article-country pairs "
            "need topic modelling."
        )

        return


    # =====================================================
    # MONTH
    # =====================================================

    pending_df[
        "month"
    ] = (
        pending_df[
            "published_at"
        ]
        .apply(
            month_start_string
        )
    )


    invalid_dates = int(
        pending_df[
            "month"
        ]
        .isna()
        .sum()
    )


    if invalid_dates > 0:

        print(
            f"Warning: {invalid_dates} rows "
            "have invalid published_at."
        )


    pending_df = pending_df[
        pending_df[
            "month"
        ]
        .notna()
    ].copy()


    if pending_df.empty:

        print(
            "No pending rows have "
            "valid dates."
        )

        return


    # =====================================================
    # REGISTRY
    # =====================================================

    registry = (
        load_topic_registry()
    )


    next_topic_number = (
        get_next_topic_number(
            registry
        )
    )


    print(
        "Next topic ID: "
        f"T{next_topic_number:04d}"
    )


    # =====================================================
    # AFFECTED MONTHS
    # =====================================================

    affected_months = sorted(
        pending_df[
            "month"
        ]
        .unique()
    )


    print()
    print(
        "Months requiring processing:"
    )


    for month_string in affected_months:

        print(
            f"  {month_string}"
        )


    # =====================================================
    # PROCESS MONTHS
    # =====================================================

    cleaned_months = (
        cleaned_df[
            "published_at"
        ]
        .apply(
            month_start_string
        )
    )


    for month_string in affected_months:

        print()
        print("=" * 70)

        print(
            f"PROCESSING MONTH: "
            f"{month_string}"
        )

        print("=" * 70)


        # -------------------------------------------------
        # Use all articles from the month for clustering.
        # -------------------------------------------------

        month_df = cleaned_df[
            cleaned_months
            ==
            month_string
        ].copy()


        pending_month_df = pending_df[
            pending_df[
                "month"
            ]
            ==
            month_string
        ].copy()


        pending_pairs = {

            (
                int(row.article_id),
                row.country
            )

            for row
            in pending_month_df.itertuples(
                index=False
            )

        }


        print(
            "Cleaned article-country rows "
            f"in month: {len(month_df)}"
        )


        print(
            "Unique articles in month: "
            f"{month_df['article_id'].nunique()}"
        )


        print(
            "Pending article-country pairs: "
            f"{len(pending_pairs)}"
        )


        # =================================================
        # DISCOVER + CONSOLIDATE TOPICS
        # =================================================

        (
            article_category_data,
            next_topic_number
        ) = discover_topics_for_month(
            month_df,
            registry,
            next_topic_number
        )


        # =================================================
        # PRIMARY TOPIC ONLY
        # =================================================

        print()
        print("=" * 70)
        print("ASSIGNING PRIMARY TOPICS")
        print("=" * 70)


        assignments = (
            assign_primary_topics(
                article_category_data
            )
        )


        print(
            "Unique article-topic "
            f"assignments: {len(assignments)}"
        )


        # =================================================
        # BUILD NEWS_TOPICS
        # =================================================

        news_topic_rows = (
            build_news_topic_rows(
                month_df,
                assignments,
                pending_pairs
            )
        )


        # =================================================
        # WRITE NEWS_TOPICS
        # =================================================

        upsert_news_topics(
            news_topic_rows
        )


        # =================================================
        # UPDATE REGISTRY DATES
        # =================================================

        update_registry_dates(
            month_df,
            assignments
        )


        # =================================================
        # MONTHLY COUNTRY STATS
        # =================================================

        rebuild_monthly_stats(
            month_string,
            month_df
        )


        processed_pairs.update(
            pending_pairs
        )


    # =====================================================
    # FINISHED
    # =====================================================

    print()
    print("=" * 70)
    print("TOPIC PIPELINE FINISHED")
    print("=" * 70)


    print(
        "Updated topic_registry"
    )

    print(
        "Updated news_topics"
    )

    print(
        "Updated monthly_topic_stats"
    )


    print()
    print(
        "One primary topic was assigned "
        "to each unique article."
    )


    print(
        "monthly_topic_stats counts are "
        "country-specific."
    )


    print(
        "topic_rank is sequential, so "
        "rank <= 3 gives at most 3 topics "
        "per country."
    )


# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":
    main()