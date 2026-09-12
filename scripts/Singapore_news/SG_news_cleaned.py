import os
import re
import html
import pandas as pd
import numpy as np

from bs4 import BeautifulSoup

from transformers import pipeline
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity
from keybert import KeyBERT


# =========================================================
# SETTINGS
# =========================================================

SCRIPT_DIR = os.path.dirname(
    os.path.abspath(__file__)
)

INPUT_FILE = os.path.join(
    SCRIPT_DIR,
    "straits_times_environment.csv"
)

OUTPUT_FILE = os.path.join(
    SCRIPT_DIR,
    "SGnews_cleaned_classified.csv"
)


# =========================================================
# FIXED ENVIRONMENTAL CATEGORIES
# =========================================================

ENVIRONMENT_CATEGORIES = [
    "Climate Change",
    "Renewable Energy",
    "Pollution",
    "Waste Management",
    "Biodiversity and Conservation",
    "Extreme Weather and Natural Hazards",
    "Sustainable Transport",
    "Green Buildings",
    "Green Finance"
]


# =========================================================
# LOW-INFORMATION NEWS WORDS
# =========================================================

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
    "might"
}


# =========================================================
# LOAD NLP MODELS
# =========================================================

print("Loading NLP models...")

category_classifier = pipeline(
    "zero-shot-classification",
    model="facebook/bart-large-mnli"
)

embedding_model = SentenceTransformer(
    "all-MiniLM-L6-v2"
)

keyword_model = KeyBERT(
    model=embedding_model
)

print("Models loaded.")


# =========================================================
# CLEAN TEXT
# =========================================================

def clean_text(text):

    if pd.isna(text):
        return ""

    text = str(text)

    # Convert HTML entities
    text = html.unescape(text)

    # Remove HTML tags
    text = BeautifulSoup(
        text,
        "html.parser"
    ).get_text(" ")

    # Remove URLs
    text = re.sub(
        r"https?://\S+|www\.\S+",
        " ",
        text
    )

    # Remove email addresses
    text = re.sub(
        r"\S+@\S+",
        " ",
        text
    )

    # Lowercase
    text = text.lower()

    # Keep letters, numbers, spaces and hyphens
    text = re.sub(
        r"[^a-z0-9\s\-]",
        " ",
        text
    )

    # Normalise whitespace
    text = re.sub(
        r"\s+",
        " ",
        text
    ).strip()

    # Remove selected low-information words
    words = text.split()

    words = [
        word
        for word in words
        if word not in LOW_INFORMATION_WORDS
    ]

    return " ".join(words)


# =========================================================
# ASSIGN ENVIRONMENT CATEGORY
# =========================================================

def assign_environment_category(text):

    if not text.strip():
        return None, None

    # Limit length for BART
    text_for_classification = text[:4000]

    result = category_classifier(
        text_for_classification,
        candidate_labels=ENVIRONMENT_CATEGORIES,
        hypothesis_template=(
            "This news article is mainly about {}."
        )
    )

    category = result["labels"][0]
    confidence = result["scores"][0]

    return category, round(
        float(confidence),
        4
    )


# =========================================================
# EXTRACT MODEL-BASED KEYWORDS
# =========================================================

def extract_keywords(
    text,
    top_n=5
):

    if not text.strip():
        return ""

    try:

        keywords = keyword_model.extract_keywords(
            text,
            keyphrase_ngram_range=(1, 2),
            stop_words="english",
            top_n=top_n,
            use_mmr=True,
            diversity=0.5
        )

        keyword_names = [
            keyword
            for keyword, score in keywords
        ]

        return ", ".join(
            keyword_names
        )

    except Exception as e:

        print(
            "Keyword extraction error:",
            e
        )

        return ""


# =========================================================
# CREATE ARTICLE IDs
# =========================================================

def create_article_ids(
    df,
    existing_df
):

    # Find highest current article number
    if (
        not existing_df.empty
        and "article_id"
        in existing_df.columns
    ):

        existing_numbers = (
            existing_df["article_id"]
            .astype(str)
            .str.extract(r"(\d+)")[0]
        )

        existing_numbers = (
            pd.to_numeric(
                existing_numbers,
                errors="coerce"
            )
            .dropna()
        )

        if len(existing_numbers) > 0:

            start_number = (
                int(
                    existing_numbers.max()
                )
                + 1
            )

        else:

            start_number = 1

    else:

        start_number = 1

    df = df.reset_index(
        drop=True
    )

    df["article_id"] = [
        f"A{number:05d}"
        for number in range(
            start_number,
            start_number + len(df)
        )
    ]

    return df


# =========================================================
# CALCULATE SEMANTIC SCORES
# =========================================================

def calculate_semantic_scores(df):

    print()
    print(
        "Recalculating semantic scores "
        "for full dataset..."
    )

    # Generate embeddings for all cleaned articles
    embeddings = embedding_model.encode(
        df["cleaned_text"].fillna("").tolist(),
        show_progress_bar=True,
        convert_to_numpy=True
    )

    df["semantic_score"] = 0.0

    # Process each category separately
    for category in (
        df["environment_category"]
        .dropna()
        .unique()
    ):

        category_indices = df[
            df["environment_category"]
            == category
        ].index.tolist()

        if len(category_indices) == 0:
            continue

        # If category only contains one article
        if len(category_indices) == 1:

            df.loc[
                category_indices[0],
                "semantic_score"
            ] = 1.0

            continue

        category_embeddings = embeddings[
            category_indices
        ]

        # Calculate category centroid
        category_centroid = np.mean(
            category_embeddings,
            axis=0
        ).reshape(
            1,
            -1
        )

        # Compare each article against centroid
        similarities = cosine_similarity(
            category_embeddings,
            category_centroid
        ).flatten()

        for index, similarity in zip(
            category_indices,
            similarities
        ):

            df.loc[
                index,
                "semantic_score"
            ] = round(
                float(similarity),
                4
            )

    return df


# =========================================================
# MAIN
# =========================================================

def main():

    print()
    print(
        "=========================================="
    )
    print(
        "NEWS ARTICLE PREPROCESSING"
    )
    print(
        "=========================================="
    )

    # -----------------------------------------------------
    # STEP 1: Load raw scraper CSV
    # -----------------------------------------------------

    print()
    print(
        "Loading raw data..."
    )

    raw_df = pd.read_csv(
        INPUT_FILE
    )

    print(
        f"{len(raw_df)} raw articles found."
    )

    # Remove duplicates inside raw file
    raw_df = raw_df.drop_duplicates(
        subset=["url"]
    ).copy()


    # -----------------------------------------------------
    # STEP 2: Check existing processed dataset
    # -----------------------------------------------------

    if os.path.exists(
        OUTPUT_FILE
    ):

        print()
        print(
            "Existing processed CSV found."
        )

        existing_df = pd.read_csv(
            OUTPUT_FILE
        )

        print(
            f"{len(existing_df)} articles "
            f"already processed."
        )

        # URLs already processed
        processed_urls = set(
            existing_df["url"]
            .dropna()
            .astype(str)
        )

        # Only keep NEW raw articles
        new_df = raw_df[
            ~raw_df["url"]
            .astype(str)
            .isin(processed_urls)
        ].copy()

    else:

        print()
        print(
            "No existing processed CSV found."
        )

        existing_df = pd.DataFrame()

        new_df = raw_df.copy()


    print()
    print(
        f"{len(new_df)} new articles "
        f"need processing."
    )


    # -----------------------------------------------------
    # STEP 3: If there are new articles, process them
    # -----------------------------------------------------

    if len(new_df) > 0:

        # ---------------------------------------------
        # Create article IDs
        # ---------------------------------------------

        new_df = create_article_ids(
            new_df,
            existing_df
        )


        # ---------------------------------------------
        # Handle missing text
        # ---------------------------------------------

        new_df["title"] = (
            new_df["title"]
            .fillna("")
        )

        new_df["article_text"] = (
            new_df["article_text"]
            .fillna("")
        )


        # ---------------------------------------------
        # Combine title + article text
        # ---------------------------------------------

        new_df["modelling_text"] = (
            new_df["title"]
            .str.strip()
            + ". "
            + new_df["article_text"]
            .str.strip()
        )


        # ---------------------------------------------
        # Clean text
        # ---------------------------------------------

        print()
        print(
            "Cleaning new article text..."
        )

        new_df["cleaned_text"] = (
            new_df["modelling_text"]
            .apply(clean_text)
        )


        # ---------------------------------------------
        # Remove articles with too little usable text
        # ---------------------------------------------

        before_filter = len(
            new_df
        )

        new_df = new_df[
            new_df["cleaned_text"]
            .str.split()
            .str.len()
            >= 20
        ].copy()

        new_df.reset_index(
            drop=True,
            inplace=True
        )

        removed_count = (
            before_filter
            - len(new_df)
        )

        if removed_count > 0:

            print(
                f"{removed_count} article(s) "
                f"removed due to insufficient text."
            )


        # ---------------------------------------------
        # Assign environmental categories
        # ---------------------------------------------

        print()
        print(
            "Assigning environmental categories..."
        )

        categories = []
        category_confidences = []

        for number, text in enumerate(
            new_df["cleaned_text"],
            start=1
        ):

            print(
                f"Classifying article "
                f"{number}/{len(new_df)}"
            )

            category, confidence = (
                assign_environment_category(
                    text
                )
            )

            categories.append(
                category
            )

            category_confidences.append(
                confidence
            )

        new_df[
            "environment_category"
        ] = categories

        new_df[
            "category_confidence"
        ] = category_confidences


        # ---------------------------------------------
        # Extract NLP keywords
        # ---------------------------------------------

        print()
        print(
            "Extracting keywords..."
        )

        extracted_keywords = []

        for number, text in enumerate(
            new_df["cleaned_text"],
            start=1
        ):

            print(
                f"Keywords "
                f"{number}/{len(new_df)}"
            )

            keywords = extract_keywords(
                text,
                top_n=5
            )

            extracted_keywords.append(
                keywords
            )

        new_df[
            "environment_keywords"
        ] = extracted_keywords


        # ---------------------------------------------
        # Select fields for CSV 2
        # ---------------------------------------------

        new_output_df = new_df[
            [
                "article_id",
                "title",
                "source",
                "published_at",
                "countries",
                "cleaned_text",
                "environment_category",
                "environment_keywords",
                "category_confidence",
                "url"
            ]
        ].copy()


        # ---------------------------------------------
        # Combine existing + new
        # ---------------------------------------------

        if not existing_df.empty:

            combined_df = pd.concat(
                [
                    existing_df,
                    new_output_df
                ],
                ignore_index=True
            )

        else:

            combined_df = (
                new_output_df.copy()
            )


    # -----------------------------------------------------
    # STEP 4: No new articles
    # -----------------------------------------------------

    else:

        print()
        print(
            "No new articles need NLP processing."
        )

        # If output already exists,
        # keep using existing data
        if not existing_df.empty:

            combined_df = (
                existing_df.copy()
            )

        else:

            print(
                "No processed dataset exists."
            )
            return


    # -----------------------------------------------------
    # STEP 5: Safety duplicate check
    # -----------------------------------------------------

    combined_df.drop_duplicates(
        subset=["url"],
        keep="first",
        inplace=True
    )

    combined_df.reset_index(
        drop=True,
        inplace=True
    )


    # -----------------------------------------------------
    # STEP 6: Recalculate semantic scores
    #
    # Semantic score depends on all articles currently
    # belonging to the category, so this must be updated
    # whenever the dataset changes.
    # -----------------------------------------------------

    combined_df = (
        calculate_semantic_scores(
            combined_df
        )
    )


    # -----------------------------------------------------
    # STEP 7: Final column order
    # -----------------------------------------------------

    combined_df = combined_df[
        [
            "article_id",
            "title",
            "source",
            "published_at",
            "countries",
            "cleaned_text",
            "environment_category",
            "environment_keywords",
            "category_confidence",
            "semantic_score",
            "url"
        ]
    ]


    # -----------------------------------------------------
    # STEP 8: Save CSV 2
    # -----------------------------------------------------

    combined_df.to_csv(
        OUTPUT_FILE,
        index=False,
        encoding="utf-8-sig"
    )


    # -----------------------------------------------------
    # FINISHED
    # -----------------------------------------------------

    print()
    print(
        "=========================================="
    )
    print(
        "PREPROCESSING FINISHED"
    )
    print(
        "=========================================="
    )

    print(
        f"New articles processed: "
        f"{len(new_df)}"
    )

    print(
        f"Total processed articles: "
        f"{len(combined_df)}"
    )

    print(
        "File:",
        OUTPUT_FILE
    )

    print()

    print(
        combined_df[
            [
                "article_id",
                "environment_category",
                "environment_keywords",
                "category_confidence",
                "semantic_score"
            ]
        ].tail(20)
    )


# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":
    main()