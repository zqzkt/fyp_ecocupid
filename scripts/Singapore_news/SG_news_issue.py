import os
import re
import warnings

import numpy as np
import pandas as pd

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


CLEANED_FILE = os.path.join(
    SCRIPT_DIR,
    "SGnews_cleaned_classified.csv"
)


TOPICS_FILE = os.path.join(
    SCRIPT_DIR,
    "SGnews_topics.csv"
)


OUTPUT_FILE = os.path.join(
    SCRIPT_DIR,
    "SGnews_issues.csv"
)


# =========================================================
# ISSUE MODELLING SETTINGS
# =========================================================

# Smaller threshold = stricter clustering
# Larger threshold = more articles grouped together
ISSUE_CLUSTER_DISTANCE = 0.30


# Merge issue clusters that are extremely similar
ISSUE_MERGE_SIMILARITY = 0.84


TOP_ISSUE_KEYWORDS = 3

MAX_KEYWORD_CANDIDATES = 30


# =========================================================
# SUMMARY SETTINGS
# =========================================================

MIN_SUMMARY_WORDS = 20

MAX_SUMMARY_WORDS = 30


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

print("Loading embedding model...")


embedding_model = SentenceTransformer(
    "all-MiniLM-L6-v2"
)


print("Embedding model loaded.")


print("Loading issue naming / summarisation model...")


text_model = pipeline(
    "text2text-generation",
    model="google/flan-t5-base",
    tokenizer="google/flan-t5-base",
    device=-1
)


print("Language model loaded.")


# =========================================================
# NORMALISE TEXT
# =========================================================

def normalise_text(text):

    if pd.isna(text):
        return ""

    text = str(
        text
    ).lower()


    text = re.sub(
        r"\s+",
        " ",
        text
    )


    return text.strip()


# =========================================================
# CALCULATE CENTROID
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
# INITIAL ISSUE CLUSTERING
# =========================================================

def cluster_issues(
    embeddings
):

    """
    Cluster articles within one topic.

    Each resulting cluster represents a possible
    recurring issue / sub-theme.
    """


    if len(embeddings) == 1:

        return np.array(
            [0]
        )


    model = AgglomerativeClustering(

        n_clusters=None,

        metric="cosine",

        linkage="average",

        distance_threshold=
            ISSUE_CLUSTER_DISTANCE

    )


    return model.fit_predict(
        embeddings
    )


# =========================================================
# MERGE SIMILAR ISSUE CLUSTERS
# =========================================================

def merge_similar_issue_clusters(
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


    issue_clusterer = AgglomerativeClustering(

        n_clusters=None,

        metric="cosine",

        linkage="average",

        distance_threshold=(
            1
            -
            ISSUE_MERGE_SIMILARITY
        )

    )


    merged_labels = issue_clusterer.fit_predict(
        centroids
    )


    mapping = {

        old_label:
            new_label

        for old_label, new_label
        in zip(
            unique_labels,
            merged_labels
        )

    }


    return np.array([

        mapping[
            label
        ]

        for label
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


            overlap = len(
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
                overlap / smaller >= 0.80
            ):

                redundant = True
                break


        if not redundant:

            selected.append(
                candidate
            )


        if (
            len(selected)
            >=
            TOP_ISSUE_KEYWORDS
        ):

            break


    return selected


# =========================================================
# EXTRACT ISSUE KEYWORDS
# =========================================================

def extract_issue_keywords(
    documents,
    issue_centroid
):

    """
    Dynamically extract keywords representing
    the issue cluster.
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


    ranked_positions = np.argsort(
        tfidf_scores
    )[::-1]


    candidates = []


    for position in ranked_positions:

        keyword = clean_keyword(
            features[
                position
            ]
        )


        if not keyword:
            continue


        if keyword not in candidates:

            candidates.append(
                keyword
            )


        if (
            len(candidates)
            >=
            MAX_KEYWORD_CANDIDATES
        ):

            break


    if not candidates:

        return []


    # =====================================================
    # SEMANTIC KEYWORD RANKING
    # =====================================================

    candidate_embeddings = embedding_model.encode(

        candidates,

        convert_to_numpy=True,

        normalize_embeddings=True,

        show_progress_bar=False

    )


    similarities = cosine_similarity(

        candidate_embeddings,

        issue_centroid.reshape(
            1,
            -1
        )

    ).flatten()


    ranked = np.argsort(
        similarities
    )[::-1]


    semantic_candidates = [

        candidates[
            position
        ]

        for position
        in ranked

    ]


    selected = remove_redundant_keywords(
        semantic_candidates
    )


    return selected[
        :TOP_ISSUE_KEYWORDS
    ]


# =========================================================
# CHECK WHETHER ISSUE NAME IS GENERIC
# =========================================================

def is_generic_issue_name(
    issue_name
):

    if not issue_name:
        return True


    cleaned_name = (
        str(
            issue_name
        )
        .lower()
        .strip()
    )


    # Remove punctuation and quotes before checking.
    cleaned_name = re.sub(
        r"[^a-z\s\-]",
        "",
        cleaned_name
    )


    cleaned_name = re.sub(
        r"\s+",
        " ",
        cleaned_name
    ).strip()


    generic_exact_names = {

        "",
        "issue",
        "issues",
        "topic",
        "topics",
        "subtheme",
        "subthemes",
        "sub-theme",
        "sub-themes",

        "environmental issue",
        "environmental issues",

        "environment issue",
        "environment issues",

        "environmental concern",
        "environmental concerns",

        "environment concern",
        "environment concerns",

        "environmental problem",
        "environmental problems",

        "environment problem",
        "environment problems"

    }


    generic_phrases = [

        "environmental issue",
        "environmental issues",

        "environment issue",
        "environment issues",

        "environmental concern",
        "environmental concerns",

        "environmental problem",
        "environmental problems"

    ]


    if cleaned_name in generic_exact_names:

        return True


    if any(
        phrase in cleaned_name
        for phrase in generic_phrases
    ):

        return True


    if len(
        cleaned_name.split()
    ) > 8:

        return True


    return False


# =========================================================
# GENERATE ISSUE NAME
# =========================================================

def generate_issue_name(
    topic_name,
    keywords,
    titles,
    article_count
):

    """
    Single article:
        Use the first extracted keyword.

    Multi-article issue:
        Use FLAN-T5.

    Generic model outputs such as
    'environmental issue' are rejected.
    """


    # =====================================================
    # SINGLE-ARTICLE ISSUE
    # =====================================================

    if article_count == 1:

        if keywords:

            return (
                str(
                    keywords[0]
                )
                .strip()
                .title()
            )


        return "Unlabelled Issue"


    # =====================================================
    # MULTI-ARTICLE ISSUE
    # =====================================================

    keyword_text = ", ".join(
        keywords[:5]
    )


    title_text = " | ".join(
        [
            str(title)
            for title
            in titles[:4]
        ]
    )


    prompt = (
        f"Main topic: {topic_name}\n"
        f"Issue keywords: {keyword_text}\n"
        f"Article titles: {title_text}\n\n"
        "Identify the specific recurring issue or sub-theme "
        "shared by these news articles. "
        "Return only a concise noun phrase of 2 to 6 words. "
        "The name must describe the actual subject discussed. "
        "Do not use generic labels such as environmental issue, "
        "environmental concern, environmental problem, issue, "
        "sub-theme, or topic. "
        "Do not use country names. "
        "Return only the issue name."
    )


    issue_name = ""


    try:

        result = text_model(

            prompt,

            max_new_tokens=18,

            do_sample=False

        )


        issue_name = (

            result[0][
                "generated_text"
            ]
            .strip()

        )


    except Exception as e:

        print(
            f"Issue naming failed: {e}"
        )


    # =====================================================
    # CLEAN MODEL OUTPUT
    # =====================================================

    issue_name = re.sub(
        r"[\n\r]+",
        " ",
        issue_name
    )


    issue_name = re.sub(
        r"\s+",
        " ",
        issue_name
    )


    issue_name = issue_name.strip(
        " \t\n\r.,:;-/\\'\"`"
    )


    # =====================================================
    # FALLBACK IF GENERIC
    # =====================================================

    if is_generic_issue_name(
        issue_name
    ):

        if keywords:

            issue_name = (
                str(
                    keywords[0]
                )
                .strip()
                .title()
            )


        else:

            issue_name = (
                "Unlabelled Issue"
            )


    return issue_name


# =========================================================
# LIMIT WORDS
# =========================================================

def limit_words(
    text,
    max_words=30
):

    """
    Ensure text never exceeds max_words.
    """


    text = re.sub(
        r"\s+",
        " ",
        str(text)
    ).strip()


    words = text.split()


    if len(words) <= max_words:

        return text


    shortened = " ".join(
        words[:max_words]
    )


    shortened = shortened.rstrip(
        " ,;:"
    )


    if not shortened.endswith(
        (
            ".",
            "!",
            "?"
        )
    ):

        shortened += "."


    return shortened


# =========================================================
# CHECK SUMMARY QUALITY
# =========================================================

def is_poor_summary(
    summary
):

    if not summary:
        return True


    cleaned_summary = (
        str(
            summary
        )
        .lower()
        .strip()
    )


    word_count = len(
        cleaned_summary.split()
    )


    bad_phrases = [

        "environmental issue",
        "environmental issues",

        "environmental concern",
        "environmental concerns",

        "environmental problem",
        "environmental problems",

        "global issue",

        "the articles discuss",
        "articles discuss",

        "this issue is",
        "the issue is"

    ]


    if word_count < 15:

        return True


    if any(
        phrase in cleaned_summary
        for phrase in bad_phrases
    ):

        return True


    return False


# =========================================================
# CLEAN SUMMARY OUTPUT
# =========================================================

def clean_summary(
    summary
):

    summary = re.sub(
        r"[\n\r]+",
        " ",
        str(summary)
    )


    summary = re.sub(
        r"\s+",
        " ",
        summary
    ).strip()


    summary = summary.strip(
        " \"'`"
    )


    return summary


# =========================================================
# GENERATE ISSUE SUMMARY
# =========================================================

def generate_issue_summary(
    topic_name,
    issue_name,
    keywords,
    titles,
    article_texts
):

    """
    Generate a specific issue summary.

    Desired length:
        20-30 words

    Absolute maximum:
        30 words
    """


    keyword_text = ", ".join(
        keywords[:5]
    )


    title_text = " | ".join(
        [
            str(title)
            for title
            in titles[:5]
        ]
    )


    # =====================================================
    # ARTICLE EVIDENCE
    # =====================================================

    excerpts = []


    for text in article_texts[:5]:

        words = str(
            text
        ).split()


        # Use more context than before.
        excerpt = " ".join(
            words[:220]
        )


        excerpts.append(
            excerpt
        )


    article_context = "\n\n".join(
        excerpts
    )


    # =====================================================
    # FIRST SUMMARY ATTEMPT
    # =====================================================

    prompt = (
        f"Main topic: {topic_name}\n"
        f"Specific issue: {issue_name}\n"
        f"Keywords: {keyword_text}\n"
        f"Article titles: {title_text}\n\n"
        f"Article evidence:\n{article_context}\n\n"
        "Write ONE informative sentence between 20 and 30 words "
        "summarising the specific issue discussed in the evidence. "
        "Explain the concrete development, problem, impact, action, "
        "response, risk, or concern being discussed. "
        "Use specific information from the evidence. "
        "Do not merely repeat the issue name. "
        "Do not say 'environmental issue', "
        "'environmental concern', 'environmental problem', "
        "'global issue', or 'the articles discuss'. "
        "Do not invent information. "
        "Return only the summary sentence."
    )


    summary = ""


    try:

        result = text_model(

            prompt,

            max_new_tokens=55,

            do_sample=False

        )


        summary = (

            result[0][
                "generated_text"
            ]
            .strip()

        )


    except Exception as e:

        print(
            f"Issue summarisation failed: {e}"
        )


    summary = clean_summary(
        summary
    )


    # =====================================================
    # RETRY IF SUMMARY IS TOO SHORT OR GENERIC
    # =====================================================

    if is_poor_summary(
        summary
    ):

        retry_prompt = (
            f"Main topic: {topic_name}\n"
            f"Specific issue: {issue_name}\n"
            f"Keywords: {keyword_text}\n\n"
            f"Evidence:\n{article_context}\n\n"
            "Write exactly one detailed sentence of about "
            "20 to 30 words. "
            "Summarise what is specifically happening in the evidence. "
            "Include the main development or problem and, where supported, "
            "its impact, cause, response, or significance. "
            "Avoid generic statements. "
            "Do not simply define the issue. "
            "Do not repeat the issue name as the whole summary. "
            "Do not use the phrases environmental issue, "
            "environmental concern, environmental problem, "
            "global issue, or the articles discuss. "
            "Use only information supported by the evidence."
        )


        try:

            retry_result = text_model(

                retry_prompt,

                max_new_tokens=55,

                do_sample=False

            )


            retry_summary = (

                retry_result[0][
                    "generated_text"
                ]
                .strip()

            )


            retry_summary = clean_summary(
                retry_summary
            )


            # Prefer the retry when:
            # - first summary is poor
            # - retry is longer
            # - retry is not itself obviously poor
            if (
                retry_summary
                and
                (
                    not is_poor_summary(
                        retry_summary
                    )
                    or
                    len(
                        retry_summary.split()
                    )
                    >
                    len(
                        summary.split()
                    )
                )
            ):

                summary = retry_summary


        except Exception as e:

            print(
                f"Summary retry failed: {e}"
            )


    # =====================================================
    # SECOND RETRY IF STILL VERY SHORT
    # =====================================================

    if (
        summary
        and
        len(
            summary.split()
        )
        <
        MIN_SUMMARY_WORDS
    ):

        expansion_prompt = (
            f"Issue: {issue_name}\n"
            f"Current summary: {summary}\n\n"
            f"Evidence:\n{article_context}\n\n"
            "Rewrite the summary as one complete sentence "
            "between 20 and 30 words. "
            "Add only relevant details supported by the evidence, "
            "such as the cause, effect, response, development, "
            "or significance. "
            "Do not add unsupported facts."
        )


        try:

            expansion_result = text_model(

                expansion_prompt,

                max_new_tokens=55,

                do_sample=False

            )


            expanded_summary = (

                expansion_result[0][
                    "generated_text"
                ]
                .strip()

            )


            expanded_summary = clean_summary(
                expanded_summary
            )


            if (
                len(
                    expanded_summary.split()
                )
                >
                len(
                    summary.split()
                )
            ):

                summary = expanded_summary


        except Exception as e:

            print(
                f"Summary expansion failed: {e}"
            )


    # =====================================================
    # FINAL FALLBACK
    # =====================================================

    if not summary:

        if keywords:

            if len(keywords) >= 2:

                summary = (
                    f"The issue centres on {keywords[0]}, "
                    f"with related concerns involving "
                    f"{', '.join(keywords[1:])} "
                    f"within the broader topic of "
                    f"{topic_name.lower()}."
                )


            else:

                summary = (
                    f"The issue centres on {keywords[0]} "
                    f"and its implications within the broader "
                    f"topic of {topic_name.lower()}."
                )


        else:

            summary = (
                f"The issue concerns developments related to "
                f"{issue_name.lower()} within the broader "
                f"topic of {topic_name.lower()}."
            )


    # =====================================================
    # ABSOLUTE 30-WORD LIMIT
    # =====================================================

    return limit_words(
        summary,
        MAX_SUMMARY_WORDS
    )


# =========================================================
# COMBINE COUNTRY VALUES
# =========================================================

def combine_countries(
    country_values
):

    countries = set()


    for value in country_values:

        if pd.isna(value):
            continue


        for country in str(
            value
        ).split(","):

            country = (
                country
                .strip()
            )


            if country:

                countries.add(
                    country
                )


    return ", ".join(
        sorted(
            countries
        )
    )


# =========================================================
# MAIN
# =========================================================

def main():

    print()

    print("=" * 70)
    print("ASEAN ENVIRONMENTAL ISSUE / SUB-THEME MODELLING")
    print("=" * 70)


    # =====================================================
    # LOAD CSV2
    # =====================================================

    cleaned_df = pd.read_csv(
        CLEANED_FILE
    )


    print(
        f"\nLoaded CSV2: "
        f"{len(cleaned_df)} articles"
    )


    # =====================================================
    # LOAD CSV3
    # =====================================================

    topics_df = pd.read_csv(
        TOPICS_FILE
    )


    print(
        f"Loaded CSV3: "
        f"{len(topics_df)} article-topic relationships"
    )


    # =====================================================
    # VALIDATE REQUIRED COLUMNS
    # =====================================================

    required_cleaned = {

        "article_id",
        "title",
        "cleaned_text"

    }


    required_topics = {

        "article_id",
        "environment_category",
        "topic_id",
        "topic_name",
        "topic_keywords",
        "article_topic_similarity",
        "country"

    }


    missing_cleaned = (

        required_cleaned
        -
        set(
            cleaned_df.columns
        )

    )


    missing_topics = (

        required_topics
        -
        set(
            topics_df.columns
        )

    )


    if missing_cleaned:

        raise ValueError(

            "CSV2 is missing columns: "
            +
            str(
                missing_cleaned
            )

        )


    if missing_topics:

        raise ValueError(

            "CSV3 is missing columns: "
            +
            str(
                missing_topics
            )

        )


    # =====================================================
    # JOIN CSV2 + CSV3
    # =====================================================

    article_columns = [

        "article_id",
        "title",
        "cleaned_text"

    ]


    if (
        "published_at"
        in cleaned_df.columns
    ):

        article_columns.append(
            "published_at"
        )


    combined_df = topics_df.merge(

        cleaned_df[
            article_columns
        ],

        on="article_id",

        how="left",

        validate="many_to_one"

    )


    combined_df[
        "cleaned_text"
    ] = (

        combined_df[
            "cleaned_text"
        ]
        .fillna("")

    )


    combined_df[
        "title"
    ] = (

        combined_df[
            "title"
        ]
        .fillna("")

    )


    print(
        f"Joined dataset: "
        f"{len(combined_df)} rows"
    )


    # =====================================================
    # DISCOVER ISSUES WITHIN EACH TOPIC
    # =====================================================

    issue_records = []


    for (
        topic_id,
        topic_df
    ) in combined_df.groupby(

        "topic_id",
        sort=True

    ):


        topic_df = (
            topic_df
            .reset_index(
                drop=True
            )
        )


        topic_name = str(
            topic_df.iloc[0][
                "topic_name"
            ]
        )


        environment_category = str(
            topic_df.iloc[0][
                "environment_category"
            ]
        )


        print()

        print("-" * 70)

        print(
            f"TOPIC: "
            f"{topic_id} | {topic_name}"
        )

        print(
            f"Articles: "
            f"{len(topic_df)}"
        )


        documents = (
            topic_df[
                "cleaned_text"
            ]
            .tolist()
        )


        # =================================================
        # EMBEDDINGS
        # =================================================

        embeddings = embedding_model.encode(

            documents,

            convert_to_numpy=True,

            normalize_embeddings=True,

            show_progress_bar=False

        )


        # =================================================
        # ISSUE CLUSTERING
        # =================================================

        initial_labels = cluster_issues(
            embeddings
        )


        final_labels = (
            merge_similar_issue_clusters(

                embeddings,
                initial_labels

            )
        )


        unique_issue_labels = sorted(
            set(
                final_labels
            )
        )


        print(
            f"Issues discovered: "
            f"{len(unique_issue_labels)}"
        )


        # =================================================
        # PROCESS EACH ISSUE
        # =================================================

        for issue_label in (
            unique_issue_labels
        ):


            positions = np.where(

                final_labels
                ==
                issue_label

            )[0]


            issue_df = (

                topic_df
                .iloc[
                    positions
                ]
                .copy()

            )


            issue_embeddings = (
                embeddings[
                    positions
                ]
            )


            issue_centroid = (
                calculate_centroid(
                    issue_embeddings
                )
            )


            issue_documents = (

                issue_df[
                    "cleaned_text"
                ]
                .tolist()

            )


            issue_titles = (

                issue_df[
                    "title"
                ]
                .tolist()

            )


            # =================================================
            # ISSUE KEYWORDS
            # =================================================

            issue_keywords = (
                extract_issue_keywords(

                    issue_documents,
                    issue_centroid

                )
            )


            # =================================================
            # ISSUE NAME
            # =================================================

            article_count = len(
                issue_df
            )


            issue_name = generate_issue_name(

                topic_name,
                issue_keywords,
                issue_titles,
                article_count

            )


            # =================================================
            # FINAL SAFEGUARD AGAINST GENERIC ISSUE NAMES
            # =================================================

            if is_generic_issue_name(
                issue_name
            ):

                if issue_keywords:

                    issue_name = (
                        str(
                            issue_keywords[0]
                        )
                        .strip()
                        .title()
                    )


                else:

                    issue_name = (
                        "Unlabelled Issue"
                    )


            # =================================================
            # ISSUE SUMMARY
            # =================================================

            issue_summary = (
                generate_issue_summary(

                    topic_name,
                    issue_name,
                    issue_keywords,
                    issue_titles,
                    issue_documents

                )
            )


            # =================================================
            # ARTICLE IDS
            # =================================================

            article_ids = ", ".join(

                issue_df[
                    "article_id"
                ]
                .astype(str)
                .tolist()

            )


            # =================================================
            # COUNTRIES
            # =================================================

            countries = combine_countries(

                issue_df[
                    "country"
                ]
                .tolist()

            )


            # =================================================
            # AVERAGE ARTICLE-TOPIC SIMILARITY
            # =================================================

            average_similarity = (

                issue_df[
                    "article_topic_similarity"
                ]
                .astype(float)
                .mean()

            )


            issue_records.append({

                "environment_category":
                    environment_category,

                "topic_id":
                    topic_id,

                "topic_name":
                    topic_name,

                "issue_label":
                    issue_label,

                "issue_name":
                    issue_name,

                "issue_keywords":
                    ", ".join(
                        issue_keywords
                    ),

                "issue_summary":
                    issue_summary,

                "article_count":
                    article_count,

                "article_ids":
                    article_ids,

                "countries":
                    countries,

                "average_article_topic_similarity":
                    round(
                        float(
                            average_similarity
                        ),
                        4
                    )

            })


            print()

            print(
                f"  Issue: "
                f"{issue_name}"
            )


            print(
                f"     Articles: "
                f"{article_count}"
            )


            print(

                "     Keywords:",

                ", ".join(
                    issue_keywords
                )

                if issue_keywords

                else "None"

            )


            print(
                f"     Summary: "
                f"{issue_summary}"
            )


            print(
                f"     Summary words: "
                f"{len(issue_summary.split())}"
            )


    # =====================================================
    # CREATE ISSUE DATAFRAME
    # =====================================================

    output_df = pd.DataFrame(
        issue_records
    )


    if output_df.empty:

        print(
            "\nNo issues were produced."
        )

        return


    # =====================================================
    # SORT
    # =====================================================

    output_df = (

        output_df

        .sort_values(

            by=[
                "topic_id",
                "issue_name"
            ]

        )

        .reset_index(
            drop=True
        )

    )


    # =====================================================
    # ASSIGN SEQUENTIAL ISSUE IDS
    # =====================================================

    output_df[
        "issue_id"
    ] = [

        f"I{i:04d}"

        for i in range(

            1,
            len(output_df) + 1

        )

    ]


    # =====================================================
    # VALIDATE ISSUE NAMES
    # =====================================================

    invalid_issue_rows = output_df[

        output_df[
            "issue_name"
        ]
        .apply(
            is_generic_issue_name
        )

    ]


    if not invalid_issue_rows.empty:

        print()

        print(
            "WARNING: Generic issue names detected:"
        )


        print(

            invalid_issue_rows[

                [
                    "issue_id",
                    "topic_id",
                    "issue_name"
                ]

            ].to_string(
                index=False
            )

        )


    # =====================================================
    # SUMMARY WORD COUNT
    # =====================================================

    output_df[
        "summary_word_count"
    ] = (

        output_df[
            "issue_summary"
        ]

        .apply(

            lambda text:

                len(
                    str(
                        text
                    ).split()
                )

        )

    )


    # =====================================================
    # ABSOLUTE MAXIMUM VALIDATION
    # =====================================================

    too_long = output_df[

        output_df[
            "summary_word_count"
        ]
        >
        MAX_SUMMARY_WORDS

    ]


    if not too_long.empty:

        raise ValueError(

            "ERROR: Some summaries exceed "
            f"{MAX_SUMMARY_WORDS} words."

        )


    # =====================================================
    # REPORT SHORT SUMMARIES
    # =====================================================

    short_summaries = output_df[

        output_df[
            "summary_word_count"
        ]
        <
        MIN_SUMMARY_WORDS

    ]


    if not short_summaries.empty:

        print()

        print(
            f"Note: {len(short_summaries)} summaries "
            f"are shorter than "
            f"{MIN_SUMMARY_WORDS} words."
        )


        print(

            short_summaries[

                [
                    "issue_id",
                    "issue_name",
                    "summary_word_count"
                ]

            ].to_string(
                index=False
            )

        )


    # =====================================================
    # FINAL CSV4 COLUMN ORDER
    # =====================================================

    output_df = output_df[

        [
            "issue_id",
            "environment_category",
            "topic_id",
            "topic_name",
            "issue_name",
            "issue_keywords",
            "issue_summary",
            "article_count",
            "article_ids",
            "countries",
            "average_article_topic_similarity"
        ]

    ]


    # =====================================================
    # SAVE CSV4
    # =====================================================

    output_df.to_csv(

        OUTPUT_FILE,

        index=False,

        encoding="utf-8-sig"

    )


    # =====================================================
    # FINAL SUMMARY
    # =====================================================

    print()

    print("=" * 70)
    print("ISSUE MODELLING FINISHED")
    print("=" * 70)


    print(

        f"Topics analysed: "
        f"{output_df['topic_id'].nunique()}"

    )


    print(

        f"Issues / sub-themes discovered: "
        f"{len(output_df)}"

    )


    recurring = (

        output_df[
            "article_count"
        ]
        >= 2

    ).sum()


    single_article = (

        output_df[
            "article_count"
        ]
        ==
        1

    ).sum()


    print(

        f"Recurring issues "
        f"(2+ articles): "
        f"{recurring}"

    )


    print(

        f"Single-article sub-themes: "
        f"{single_article}"

    )


    print(

        f"Target summary length: "
        f"{MIN_SUMMARY_WORDS}-"
        f"{MAX_SUMMARY_WORDS} words"

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