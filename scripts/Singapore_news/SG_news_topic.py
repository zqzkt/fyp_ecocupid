import os
import re
import warnings

import numpy as np
import pandas as pd
import pycountry

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
# FILE SETTINGS
# =========================================================

SCRIPT_DIR = os.path.dirname(
    os.path.abspath(__file__)
)

INPUT_FILE = os.path.join(
    SCRIPT_DIR,
    "SGnews_cleaned_classified.csv"
)

OUTPUT_FILE = os.path.join(
    SCRIPT_DIR,
    "SGnews_topics.csv"
)


# =========================================================
# TARGET COUNTRIES
# =========================================================

TARGET_COUNTRIES = [
    "Singapore",
    "Malaysia",
    "Indonesia",
    "Thailand",
    "Philippines",
    "Brunei"
]


TARGET_COUNTRY_ALIASES = {

    "Singapore": [
        "singapore",
        "singaporean",
        "singaporeans"
    ],

    "Malaysia": [
        "malaysia",
        "malaysian",
        "malaysians"
    ],

    "Indonesia": [
        "indonesia",
        "indonesian",
        "indonesians"
    ],

    "Thailand": [
        "thailand",
        "thai"
    ],

    "Philippines": [
        "philippines",
        "philippine",
        "filipino",
        "filipinos"
    ],

    "Brunei": [
        "brunei",
        "brunei darussalam",
        "bruneian"
    ]
}


# =========================================================
# TOPIC MODELLING SETTINGS
# =========================================================

PRIMARY_CLUSTER_DISTANCE = 0.34

TOPIC_MERGE_SIMILARITY = 0.82

SECONDARY_TOPIC_THRESHOLD = 0.66

SECONDARY_RELATIVE_THRESHOLD = 0.78

MAX_TOPICS_PER_ARTICLE = 3


# =========================================================
# ARTICLE CHUNK SETTINGS
# =========================================================

CHUNK_SIZE = 100

CHUNK_STRIDE = 60


# =========================================================
# KEYWORD SETTINGS
# =========================================================

TOP_KEYWORDS = 3

MAX_KEYWORD_CANDIDATES = 30


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

    # News source
    "straits",
    "times",
    "news",

    # Generic words
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

    # Country terms
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
# LOAD NLP MODELS
# =========================================================

print("Loading embedding model...")

embedding_model = SentenceTransformer(
    "all-MiniLM-L6-v2"
)

print("Embedding model loaded.")


print("Loading topic naming model...")

topic_namer = pipeline(
    "text2text-generation",
    model="google/flan-t5-base",
    tokenizer="google/flan-t5-base",
    device=-1
)

print("Topic naming model loaded.")


# =========================================================
# NORMALISE TEXT
# =========================================================

def normalise_text(text):

    if pd.isna(text):
        return ""

    text = str(text).lower()

    text = re.sub(
        r"\s+",
        " ",
        text
    )

    return text.strip()


# =========================================================
# BUILD COUNTRY LOOKUP
# =========================================================

def build_country_lookup():

    lookup = {}

    for country in pycountry.countries:

        names = set()

        names.add(
            country.name.lower()
        )


        if hasattr(
            country,
            "official_name"
        ):

            names.add(
                country.official_name.lower()
            )


        if hasattr(
            country,
            "common_name"
        ):

            names.add(
                country.common_name.lower()
            )


        if country.alpha_2 == "US":

            names.update({
                "united states",
                "united states of america",
                "u.s.",
                "u.s.a."
            })


        if country.alpha_2 == "GB":

            names.update({
                "united kingdom",
                "britain",
                "great britain",
                "u.k."
            })


        lookup[
            country.name
        ] = list(
            names
        )


    return lookup


ALL_COUNTRY_NAMES = build_country_lookup()


# =========================================================
# COUNT PHRASE
# =========================================================

def count_phrase(
    text,
    phrase
):

    phrase = re.escape(
        phrase.lower()
    )


    pattern = (
        r"(?<!\w)"
        +
        phrase
        +
        r"(?!\w)"
    )


    return len(
        re.findall(
            pattern,
            text
        )
    )


# =========================================================
# COUNTRY PROMINENCE SCORE
# =========================================================

def country_score(
    text,
    aliases
):

    score = 0.0

    words = text.split()


    early_text = " ".join(
        words[:250]
    )


    for alias in aliases:

        total_mentions = count_phrase(
            text,
            alias
        )

        early_mentions = count_phrase(
            early_text,
            alias
        )


        score += total_mentions

        score += (
            early_mentions
            * 0.75
        )


    return score


# =========================================================
# COUNTRY DETECTION
# =========================================================

def detect_country_from_text(
    cleaned_text,
    fallback_country=None
):

    text = normalise_text(
        cleaned_text
    )


    detected_scores = {}


    # -----------------------------------------------------
    # FORMAL COUNTRY NAMES
    # -----------------------------------------------------

    for country, aliases in (
        ALL_COUNTRY_NAMES.items()
    ):

        score = country_score(
            text,
            aliases
        )


        if score > 0:

            detected_scores[
                country
            ] = score


    # -----------------------------------------------------
    # TARGET COUNTRY ALIASES
    # -----------------------------------------------------

    for country, aliases in (
        TARGET_COUNTRY_ALIASES.items()
    ):

        score = country_score(
            text,
            aliases
        )


        if score > 0:

            current_score = detected_scores.get(
                country,
                0
            )


            detected_scores[
                country
            ] = max(
                current_score,
                score
            )


    # -----------------------------------------------------
    # FALLBACK TO CSV2 COUNTRIES
    # -----------------------------------------------------

    if not detected_scores:

        if pd.notna(
            fallback_country
        ):

            fallback_text = normalise_text(
                fallback_country
            )


            fallback_targets = []


            for country, aliases in (
                TARGET_COUNTRY_ALIASES.items()
            ):

                for alias in aliases:

                    if count_phrase(
                        fallback_text,
                        alias
                    ) > 0:

                        fallback_targets.append(
                            country
                        )

                        break


            if fallback_targets:

                return ", ".join(
                    fallback_targets
                )


        return None


    # -----------------------------------------------------
    # DETERMINE PROMINENT COUNTRIES
    # -----------------------------------------------------

    highest_score = max(
        detected_scores.values()
    )


    prominent_countries = [

        country

        for country, score
        in detected_scores.items()

        if (
            score
            >=
            highest_score * 0.65
        )

    ]


    target_prominent = [

        country

        for country
        in prominent_countries

        if country
        in TARGET_COUNTRIES

    ]


    if not target_prominent:

        return None


    return ", ".join(
        target_prominent
    )


# =========================================================
# SPLIT ARTICLE INTO CHUNKS
# =========================================================

def split_into_chunks(
    text
):

    words = str(
        text
    ).split()


    if not words:
        return []


    if len(words) <= CHUNK_SIZE:

        return [
            " ".join(
                words
            )
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
                " ".join(
                    chunk
                )
            )


        start += CHUNK_STRIDE


    return chunks


# =========================================================
# INITIAL ARTICLE CLUSTERING
# =========================================================

def cluster_articles(
    embeddings
):

    if len(embeddings) == 1:

        return np.array(
            [0]
        )


    model = AgglomerativeClustering(

        n_clusters=None,

        metric="cosine",

        linkage="average",

        distance_threshold=
            PRIMARY_CLUSTER_DISTANCE

    )


    return model.fit_predict(
        embeddings
    )


# =========================================================
# CALCULATE TOPIC CENTROID
# =========================================================

def calculate_centroid(
    embeddings
):

    centroid = np.mean(
        embeddings,
        axis=0
    )


    norm = np.linalg.norm(
        centroid
    )


    if norm > 0:

        centroid = (
            centroid
            /
            norm
        )


    return centroid


# =========================================================
# MERGE SIMILAR TOPIC CLUSTERS
# =========================================================

def merge_similar_clusters(
    embeddings,
    labels
):

    unique_labels = sorted(
        set(
            labels
        )
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
            embeddings[
                positions
            ]
        )


        centroids.append(
            centroid
        )


    centroids = np.vstack(
        centroids
    )


    distance_threshold = (
        1
        -
        TOPIC_MERGE_SIMILARITY
    )


    topic_clusterer = AgglomerativeClustering(

        n_clusters=None,

        metric="cosine",

        linkage="average",

        distance_threshold=
            distance_threshold

    )


    merged_labels = topic_clusterer.fit_predict(
        centroids
    )


    mapping = {

        original_label:
            merged_label

        for original_label, merged_label
        in zip(
            unique_labels,
            merged_labels
        )

    }


    return np.array([

        mapping[
            original_label
        ]

        for original_label
        in labels

    ])


# =========================================================
# CLEAN KEYWORD
# =========================================================

def clean_keyword(
    phrase
):

    phrase = normalise_text(
        phrase
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


        words.append(
            word
        )


    if not words:

        return None


    return " ".join(
        words
    )


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
# EXTRACT DYNAMIC TOPIC KEYWORDS
# =========================================================

def extract_topic_keywords(
    documents,
    topic_centroid
):

    """
    Extract keywords dynamically from the articles
    belonging to the discovered topic.

    No fixed subtopic taxonomy is used.
    """


    vectorizer = TfidfVectorizer(

        stop_words=list(
            CUSTOM_STOPWORDS
        ),

        ngram_range=(
            1,
            3
        ),

        min_df=1,

        max_df=1.0,

        max_features=5000

    )


    try:

        matrix = (
            vectorizer
            .fit_transform(
                documents
            )
        )


    except ValueError:

        return []


    features = (
        vectorizer
        .get_feature_names_out()
    )


    tfidf_scores = np.asarray(

        matrix.mean(
            axis=0
        )

    ).flatten()


    ranked = np.argsort(
        tfidf_scores
    )[::-1]


    candidate_phrases = []


    for position in ranked:

        cleaned = clean_keyword(
            features[
                position
            ]
        )


        if not cleaned:

            continue


        if (
            cleaned
            not in candidate_phrases
        ):

            candidate_phrases.append(
                cleaned
            )


        if (
            len(candidate_phrases)
            >=
            MAX_KEYWORD_CANDIDATES
        ):

            break


    if not candidate_phrases:

        return []


    # -----------------------------------------------------
    # EMBED CANDIDATE PHRASES
    # -----------------------------------------------------

    phrase_embeddings = embedding_model.encode(

        candidate_phrases,

        convert_to_numpy=True,

        normalize_embeddings=True,

        show_progress_bar=False

    )


    # -----------------------------------------------------
    # RANK CANDIDATES BY SEMANTIC REPRESENTATIVENESS
    # -----------------------------------------------------

    semantic_scores = cosine_similarity(

        phrase_embeddings,

        topic_centroid.reshape(
            1,
            -1
        )

    ).flatten()


    ranked_phrase_positions = np.argsort(
        semantic_scores
    )[::-1]


    semantic_ranked = [

        candidate_phrases[
            position
        ]

        for position
        in ranked_phrase_positions

    ]


    selected = remove_redundant_keywords(
        semantic_ranked
    )


    if not selected:

        return []


    return selected[
        :TOP_KEYWORDS
    ]


# =========================================================
# KEYWORD-BASED FALLBACK TOPIC NAME
# =========================================================

def create_keyword_based_topic_name(
    keywords
):

    """
    Used when the language model does not return
    a useful topic name.

    This is also similar to the singleton-cluster rule,
    where the first keyword is used directly.
    """


    if not keywords:

        return "Unlabelled Topic"


    first_keyword = str(
        keywords[0]
    ).strip()


    if not first_keyword:

        return "Unlabelled Topic"


    return first_keyword.title()


# =========================================================
# GENERATE MODEL-BASED TOPIC NAME
# =========================================================

def generate_topic_name(
    environment_category,
    keywords,
    representative_titles
):

    """
    Generate a human-readable topic name using FLAN-T5.

    This function should only normally be used for
    genuine multi-article clusters.
    """


    clean_keywords = [

        keyword.strip()

        for keyword in keywords

        if (
            keyword
            and keyword.strip()
        )

    ]


    clean_titles = [

        str(title).strip()

        for title
        in representative_titles

        if (
            pd.notna(title)
            and str(title).strip()
        )

    ]


    keyword_text = ", ".join(
        clean_keywords[:5]
    )


    title_text = " | ".join(
        clean_titles[:3]
    )


    prompt = (
        f"Broad category: {environment_category}\n"
        f"Keywords: {keyword_text}\n"
        f"Article titles: {title_text}\n\n"
        "Name the specific environmental topic shared "
        "by these articles. "
        "Use a short noun phrase of 2 to 5 words. "
        "Describe the environmental issue, event, trend, "
        "policy, technology, or impact being discussed. "
        "Do not use country names. "
        "Do not repeat the broad category. "
        "Do not say 'environmental issue'. "
        "Do not say 'environmental issues'. "
        "Do not use dates or years. "
        "Do not use slash symbols. "
        "Return only the topic name."
    )


    topic_name = ""


    try:

        result = topic_namer(

            prompt,

            max_new_tokens=20,

            do_sample=False

        )


        topic_name = (

            result[0][
                "generated_text"
            ]
            .strip()

        )


    except Exception as e:

        print(
            f"Topic naming model failed: {e}"
        )

        topic_name = ""


    # -----------------------------------------------------
    # CLEAN GENERATED NAME
    # -----------------------------------------------------

    topic_name = re.sub(
        r"[\n\r]+",
        " ",
        topic_name
    )


    topic_name = re.sub(
        r"\s+",
        " ",
        topic_name
    )


    topic_name = topic_name.strip(
        " .,:;-/"
    )


    unwanted_prefixes = [

        "topic:",
        "topic name:",
        "subtopic:",
        "subtopic name:"

    ]


    for prefix in unwanted_prefixes:

        if topic_name.lower().startswith(
            prefix
        ):

            topic_name = (
                topic_name[
                    len(prefix):
                ]
                .strip()
            )


    # Remove years.
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


    # -----------------------------------------------------
    # REJECT GENERIC TOPIC NAMES
    # -----------------------------------------------------

    topic_name_lower = (
        topic_name
        .lower()
        .strip()
    )


    generic_topic_names = {

        "",
        "environmental issue",
        "environmental issues",
        "environment issue",
        "environment issues",
        "environmental problem",
        "environmental problems",
        "environmental concern",
        "environmental concerns",
        "general environmental issue",
        "general environmental issues",
        "environment",
        "environmental topic",
        "environmental topics",
        "topic",
        "general topic",
        environment_category.lower()

    }


    is_invalid = (
        topic_name_lower
        in generic_topic_names
    )


    if (
        "environmental issue"
        in topic_name_lower
    ):

        is_invalid = True


    if (
        "environmental problem"
        in topic_name_lower
    ):

        is_invalid = True


    if (
        "environmental concern"
        in topic_name_lower
    ):

        is_invalid = True


    if len(
        topic_name.split()
    ) > 7:

        is_invalid = True


    # -----------------------------------------------------
    # FALLBACK TO FIRST KEYWORD
    # -----------------------------------------------------

    if is_invalid:

        topic_name = (
            create_keyword_based_topic_name(
                clean_keywords
            )
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

    """
    Article-topic similarity uses:

    45% whole article similarity
    55% strongest chunk similarity
    """


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


    chunk_embeddings = embedding_model.encode(

        chunks,

        convert_to_numpy=True,

        normalize_embeddings=True,

        show_progress_bar=False

    )


    chunk_similarities = cosine_similarity(

        chunk_embeddings,

        topic_centroid.reshape(
            1,
            -1
        )

    ).flatten()


    strongest_chunk = float(
        np.max(
            chunk_similarities
        )
    )


    final_score = (

        0.45
        *
        whole_similarity

        +

        0.55
        *
        strongest_chunk

    )


    return final_score


# =========================================================
# MAIN
# =========================================================

def main():

    print()
    print("=" * 70)
    print("DYNAMIC ASEAN ENVIRONMENTAL TOPIC MODELLING")
    print("=" * 70)


    # =====================================================
    # LOAD CSV2
    # =====================================================

    df = pd.read_csv(
        INPUT_FILE
    )


    print(
        f"\nLoaded {len(df)} articles."
    )


    required_columns = {

        "article_id",
        "environment_category",
        "cleaned_text"

    }


    missing = (

        required_columns
        -
        set(
            df.columns
        )

    )


    if missing:

        raise ValueError(

            f"Missing required columns: "
            f"{missing}"

        )


    if "countries" not in df.columns:

        df[
            "countries"
        ] = None


    if "title" not in df.columns:

        df[
            "title"
        ] = ""


    df[
        "cleaned_text"
    ] = (

        df[
            "cleaned_text"
        ]
        .fillna("")

    )


    # =====================================================
    # COUNTRY DETECTION
    # =====================================================

    print(
        "\nDetecting primary country from article text..."
    )


    df[
        "country"
    ] = df.apply(

        lambda row:

            detect_country_from_text(

                row[
                    "cleaned_text"
                ],

                row[
                    "countries"
                ]

            ),

        axis=1

    )


    total_before = len(
        df
    )


    df = df[

        df[
            "country"
        ]
        .notna()

    ].copy()


    print(

        f"ASEAN-relevant articles kept: "
        f"{len(df)}"

    )


    print(

        f"Non-target/unclear articles excluded: "
        f"{total_before - len(df)}"

    )


    # =====================================================
    # STORAGE
    # =====================================================

    discovered_topics = []

    article_category_data = {}


    # =====================================================
    # DISCOVER TOPICS WITHIN EACH ENVIRONMENT CATEGORY
    # =====================================================

    for (
        category,
        category_df
    ) in df.groupby(

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
        print("-" * 70)

        print(
            f"CATEGORY: {category}"
        )

        print(
            f"Articles: {len(category_df)}"
        )


        documents = (

            category_df[
                "cleaned_text"
            ]
            .tolist()

        )


        # =================================================
        # ARTICLE EMBEDDINGS
        # =================================================

        embeddings = embedding_model.encode(

            documents,

            convert_to_numpy=True,

            normalize_embeddings=True,

            show_progress_bar=True

        )


        # =================================================
        # INITIAL CLUSTERING
        # =================================================

        initial_labels = cluster_articles(
            embeddings
        )


        # =================================================
        # MERGE SIMILAR CLUSTERS
        # =================================================

        final_labels = merge_similar_clusters(

            embeddings,
            initial_labels

        )


        unique_labels = sorted(
            set(
                final_labels
            )
        )


        print(

            f"Discovered topics: "
            f"{len(unique_labels)}"

        )


        category_topics = []


        # =================================================
        # BUILD EACH DISCOVERED TOPIC
        # =================================================

        for cluster_label in unique_labels:

            positions = np.where(

                final_labels
                ==
                cluster_label

            )[0]


            cluster_embeddings = (

                embeddings[
                    positions
                ]

            )


            centroid = calculate_centroid(
                cluster_embeddings
            )


            cluster_documents = [

                documents[
                    position
                ]

                for position
                in positions

            ]


            cluster_titles = [

                str(

                    category_df.iloc[
                        position
                    ][
                        "title"
                    ]

                )

                for position
                in positions

            ]


            # -------------------------------------------------
            # GENERATE KEYWORDS ONCE FOR THE TOPIC
            # -------------------------------------------------

            keywords = extract_topic_keywords(

                cluster_documents,
                centroid

            )


            # -------------------------------------------------
            # TOPIC NAMING RULE
            #
            # ONE ARTICLE:
            #     No genuine recurring cluster exists.
            #     Use the first extracted keyword.
            #
            # MULTIPLE ARTICLES:
            #     Use FLAN-T5 to generate the shared topic.
            # -------------------------------------------------

            if len(positions) == 1:

                if keywords:

                    topic_name = (
                        str(
                            keywords[0]
                        )
                        .strip()
                        .title()
                    )

                else:

                    topic_name = (
                        "Unlabelled Topic"
                    )


                naming_method = (
                    "First keyword "
                    "(single-article topic)"
                )


            else:

                topic_name = generate_topic_name(

                    category,
                    keywords,
                    cluster_titles

                )


                naming_method = (
                    "Language model "
                    "(multi-article cluster)"
                )


            category_topics.append({

                "environment_category":
                    category,

                "cluster_label":
                    cluster_label,

                "topic_name":
                    topic_name,

                "topic_keywords":
                    keywords,

                "centroid":
                    centroid,

                "article_positions":
                    positions

            })


            print()

            print(
                f"  Topic: {topic_name}"
            )


            print(

                "     Naming method:",
                naming_method

            )


            print(

                "     Keywords:",
                ", ".join(
                    keywords
                )
                if keywords
                else "No keywords extracted"

            )


            print(

                "     Articles:",

                [

                    category_df.iloc[
                        position
                    ][
                        "article_id"
                    ]

                    for position
                    in positions

                ]

            )


        discovered_topics.extend(
            category_topics
        )


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


    # =====================================================
    # ASSIGN SEQUENTIAL TOPIC IDs
    # =====================================================

    discovered_topics = sorted(

        discovered_topics,

        key=lambda topic: (

            topic[
                "environment_category"
            ],

            topic[
                "topic_name"
            ].lower(),

            topic[
                "cluster_label"
            ]

        )

    )


    # =====================================================
    # OFFICIAL TOPIC LOOKUP
    #
    # One topic_id = one name + one keyword set
    # =====================================================

    topic_lookup_by_id = {}


    for index, topic in enumerate(

        discovered_topics,
        start=1

    ):

        topic_id = (
            f"T{index:04d}"
        )


        topic[
            "topic_id"
        ] = topic_id


        topic_lookup_by_id[
            topic_id
        ] = {

            "topic_name":
                topic[
                    "topic_name"
                ],

            "topic_keywords":
                ", ".join(
                    topic[
                        "topic_keywords"
                    ]
                ),

            "environment_category":
                topic[
                    "environment_category"
                ]

        }


    # =====================================================
    # MAP TOPIC IDs BACK TO CATEGORY TOPICS
    # =====================================================

    for category, category_data in (
        article_category_data.items()
    ):

        for topic in category_data[
            "topics"
        ]:

            matching_topic = next(

                final_topic

                for final_topic
                in discovered_topics

                if (

                    final_topic[
                        "environment_category"
                    ]
                    ==
                    topic[
                        "environment_category"
                    ]

                    and

                    final_topic[
                        "cluster_label"
                    ]
                    ==
                    topic[
                        "cluster_label"
                    ]

                )

            )


            topic[
                "topic_id"
            ] = matching_topic[
                "topic_id"
            ]


    # =====================================================
    # ARTICLE-TOPIC ASSIGNMENT
    # =====================================================

    results = []


    for (
        category,
        category_data
    ) in article_category_data.items():


        category_df = category_data[
            "df"
        ]


        embeddings = category_data[
            "embeddings"
        ]


        labels = category_data[
            "labels"
        ]


        topics = category_data[
            "topics"
        ]


        for article_position in range(
            len(category_df)
        ):


            row = category_df.iloc[
                article_position
            ]


            article_id = row[
                "article_id"
            ]


            article_text = row[
                "cleaned_text"
            ]


            article_embedding = embeddings[
                article_position
            ]


            # =================================================
            # SCORE ARTICLE AGAINST EACH TOPIC
            # =================================================

            topic_scores = []


            for topic in topics:

                score = calculate_article_topic_score(

                    article_text,
                    article_embedding,
                    topic[
                        "centroid"
                    ]

                )


                topic_scores.append(
                    (
                        topic,
                        score
                    )
                )


            topic_scores.sort(

                key=lambda x:
                    x[1],

                reverse=True

            )


            # =================================================
            # PRIMARY TOPIC
            # =================================================

            primary_label = labels[
                article_position
            ]


            primary_topic = next(

                topic

                for topic
                in topics

                if (
                    topic[
                        "cluster_label"
                    ]
                    ==
                    primary_label
                )

            )


            primary_score = next(

                score

                for topic, score
                in topic_scores

                if (
                    topic[
                        "cluster_label"
                    ]
                    ==
                    primary_label
                )

            )


            primary_id = (
                primary_topic[
                    "topic_id"
                ]
            )


            results.append({

                "article_id":
                    article_id,

                "environment_category":
                    category,

                "topic_id":
                    primary_id,

                "topic_name":
                    topic_lookup_by_id[
                        primary_id
                    ][
                        "topic_name"
                    ],

                "topic_keywords":
                    topic_lookup_by_id[
                        primary_id
                    ][
                        "topic_keywords"
                    ],

                "article_topic_similarity":
                    round(
                        float(
                            primary_score
                        ),
                        4
                    ),

                "country":
                    row[
                        "country"
                    ]

            })


            # =================================================
            # SECONDARY TOPICS
            # =================================================

            topic_count = 1


            for (
                candidate_topic,
                candidate_score
            ) in topic_scores:


                if (
                    candidate_topic[
                        "cluster_label"
                    ]
                    ==
                    primary_label
                ):

                    continue


                if (
                    candidate_score
                    <
                    SECONDARY_TOPIC_THRESHOLD
                ):

                    continue


                if (

                    candidate_score

                    <

                    primary_score
                    *
                    SECONDARY_RELATIVE_THRESHOLD

                ):

                    continue


                candidate_id = (
                    candidate_topic[
                        "topic_id"
                    ]
                )


                results.append({

                    "article_id":
                        article_id,

                    "environment_category":
                        category,

                    "topic_id":
                        candidate_id,

                    "topic_name":
                        topic_lookup_by_id[
                            candidate_id
                        ][
                            "topic_name"
                        ],

                    "topic_keywords":
                        topic_lookup_by_id[
                            candidate_id
                        ][
                            "topic_keywords"
                        ],

                    "article_topic_similarity":
                        round(
                            float(
                                candidate_score
                            ),
                            4
                        ),

                    "country":
                        row[
                            "country"
                        ]

                })


                topic_count += 1


                if (
                    topic_count
                    >=
                    MAX_TOPICS_PER_ARTICLE
                ):

                    break


    # =====================================================
    # CREATE OUTPUT DATAFRAME
    # =====================================================

    output_df = pd.DataFrame(
        results
    )


    if output_df.empty:

        print(
            "\nNo ASEAN-relevant article-topic "
            "relationships were produced."
        )

        return


    # =====================================================
    # FINAL TOPIC CONSISTENCY SAFEGUARD
    # =====================================================

    output_df[
        "topic_name"
    ] = (

        output_df[
            "topic_id"
        ]

        .map(

            lambda topic_id:

                topic_lookup_by_id[
                    topic_id
                ][
                    "topic_name"
                ]

        )

    )


    output_df[
        "topic_keywords"
    ] = (

        output_df[
            "topic_id"
        ]

        .map(

            lambda topic_id:

                topic_lookup_by_id[
                    topic_id
                ][
                    "topic_keywords"
                ]

        )

    )


    # =====================================================
    # REMOVE DUPLICATE ARTICLE-TOPIC RELATIONSHIPS
    # =====================================================

    output_df = (

        output_df

        .drop_duplicates(

            subset=[
                "article_id",
                "topic_id"
            ]

        )

        .sort_values(

            by=[
                "article_id",
                "article_topic_similarity"
            ],

            ascending=[
                True,
                False
            ]

        )

        .reset_index(
            drop=True
        )

    )


    # =====================================================
    # FINAL CSV3 COLUMN ORDER
    # =====================================================

    output_df = output_df[

        [
            "article_id",
            "environment_category",
            "topic_id",
            "topic_name",
            "topic_keywords",
            "article_topic_similarity",
            "country"
        ]

    ]


    # =====================================================
    # VALIDATION 1:
    # SAME TOPIC ID = SAME TOPIC NAME
    # =====================================================

    name_validation = (

        output_df

        .groupby(
            "topic_id"
        )[
            "topic_name"
        ]

        .nunique()

    )


    invalid_names = (
        name_validation[
            name_validation > 1
        ]
    )


    if not invalid_names.empty:

        raise ValueError(

            "ERROR: Some topic IDs have "
            "multiple topic names:\n"
            +
            invalid_names.to_string()

        )


    # =====================================================
    # VALIDATION 2:
    # SAME TOPIC ID = SAME KEYWORDS
    # =====================================================

    keyword_validation = (

        output_df

        .groupby(
            "topic_id"
        )[
            "topic_keywords"
        ]

        .nunique()

    )


    invalid_keywords = (
        keyword_validation[
            keyword_validation > 1
        ]
    )


    if not invalid_keywords.empty:

        raise ValueError(

            "ERROR: Some topic IDs have "
            "multiple keyword sets:\n"
            +
            invalid_keywords.to_string()

        )


    # =====================================================
    # VALIDATION 3:
    # SAME TOPIC ID = SAME ENVIRONMENT CATEGORY
    # =====================================================

    category_validation = (

        output_df

        .groupby(
            "topic_id"
        )[
            "environment_category"
        ]

        .nunique()

    )


    invalid_categories = (
        category_validation[
            category_validation > 1
        ]
    )


    if not invalid_categories.empty:

        raise ValueError(

            "ERROR: Some topic IDs belong to "
            "multiple environment categories:\n"
            +
            invalid_categories.to_string()

        )


    # =====================================================
    # SAVE CSV3
    # =====================================================

    output_df.to_csv(

        OUTPUT_FILE,

        index=False,

        encoding="utf-8-sig"

    )


    # =====================================================
    # SUMMARY
    # =====================================================

    article_topic_counts = (

        output_df

        .groupby(
            "article_id"
        )

        .size()

    )


    print()
    print("=" * 70)
    print("TOPIC MODELLING FINISHED")
    print("=" * 70)


    print(

        f"ASEAN articles: "
        f"{output_df['article_id'].nunique()}"

    )


    print(

        f"Discovered topics: "
        f"{output_df['topic_id'].nunique()}"

    )


    print(

        f"Article-topic relationships: "
        f"{len(output_df)}"

    )


    print(

        f"Articles with 1 topic: "
        f"{(article_topic_counts == 1).sum()}"

    )


    print(

        f"Articles with multiple topics: "
        f"{(article_topic_counts > 1).sum()}"

    )


    # =====================================================
    # DISPLAY DISCOVERED TOPICS
    # =====================================================

    print()
    print("=" * 70)
    print("DISCOVERED TOPICS")
    print("=" * 70)


    topic_summary = (

        output_df[

            [
                "topic_id",
                "environment_category",
                "topic_name",
                "topic_keywords"
            ]

        ]

        .drop_duplicates(
            subset=[
                "topic_id"
            ]
        )

        .sort_values(
            "topic_id"
        )

    )


    print(

        topic_summary.to_string(
            index=False
        )

    )


    # =====================================================
    # FINAL VALIDATION
    # =====================================================

    print()
    print("=" * 70)
    print("VALIDATION")
    print("=" * 70)


    print(
        "Topic consistency check: PASSED"
    )


    print(
        "Each topic_id has exactly one topic_name."
    )


    print(
        "Each topic_id has exactly one topic_keywords value."
    )


    print(
        "Each topic_id belongs to exactly one "
        "environment_category."
    )


    print()
    print(
        "Output saved to:"
    )

    print(
        OUTPUT_FILE
    )


# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":

    main()