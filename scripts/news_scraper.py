import os
import requests
import pandas as pd
from transformers import pipeline
from datetime import datetime, timedelta

API_KEY = "0ed9a1b08e964c64beae21a4958619ae"
CSV_PATH = "environmental_articles.csv"

url = "https://newsapi.org/v2/everything"

all_articles = []

today = datetime.now()

if not os.path.exists(CSV_PATH):

    # First run: collect the past 30 days
    print("\n======================================")
    print("FIRST RUN")
    print("Collecting articles from the past 30 days")
    print("======================================")

    start_date = today - timedelta(days=30) #Note: This will take quite a while for first initial setup

else:

    # Subsequent runs: collect today's articles only
    print("\n======================================")
    print("DAILY RUN")
    print("Collecting today's articles")
    print("======================================")

    start_date = today - timedelta(days=1)

current_start = start_date


while current_start <= today:

    current_end = today

    from_date = current_start.strftime("%Y-%m-%d")
    to_date = current_end.strftime("%Y-%m-%d")

    print(
        f"\nSearching: {from_date} → {to_date}"
    )

    params = {
        "q": (
            'environment OR environmental OR climate OR ecology OR '
            'ecosystem OR pollution OR biodiversity OR conservation OR '
            'deforestation OR "renewable energy" OR "carbon emissions" OR '
            '"climate change" OR "clean energy" OR wildlife OR '
            'sustainability OR recycling OR "fossil fuel" OR '
            '"global warming" OR "greenhouse gas" OR "plastic pollution" OR '
            '"water pollution" OR "air pollution" OR "sea level" OR '
            '"water scarcity" OR drought OR "waste management" OR '
            '"rising sea levels"'
        ),
        "language": "en",
        "from": from_date,
        "to": to_date,
        "sortBy": "publishedAt",
        "pageSize": 100,
        "apiKey": API_KEY
    }

    response = requests.get(
        url,
        params=params
    )

    if response.status_code != 200:

        print(
            "Error:",
            response.status_code
        )

        print(response.text)

        break

    data = response.json()

    articles = data.get(
        "articles",
        []
    )

    print(
        f"Found {len(articles)} articles "
        f"out of {data.get('totalResults', 0)} available"
    )

    all_articles.extend(articles)

    break

print(
    f"\nTotal articles collected before "
    f"duplicate removal: {len(all_articles)}"
)

unique_articles = {}

for article in all_articles:

    article_url = article.get("url")

    if article_url:
        unique_articles[article_url] = article


articles = list(
    unique_articles.values()
)

print(
    f"Total unique articles after "
    f"duplicate removal: {len(articles)}"
)

topics_list = []

for article in articles:

    topics_list.append({
        "title": article.get("title"),
        "source": article.get("source", {}).get("name"),
        "description": article.get("description"),
        "url": article.get("url"),
        "published_at": article.get("publishedAt")
    })


df = pd.DataFrame(topics_list)

print("\nInitial articles:")
print(df.head())

if df.empty:

    print(
        "\nNo articles were found. "
        "Skipping filtering and classification."
    )

    # Don't crash the program
    exit()

df["text"] = (
    df["title"].fillna("") +
    " " +
    df["description"].fillna("")
)

# Drop rows where there is no text
df = df[df["text"].str.strip() != ""]

print("\nLoading classification model...")

classifier = pipeline(
    "zero-shot-classification",
    model="facebook/bart-large-mnli"
)
ENV_ANCHOR_WORDS = [

    # General environmental terms
    "environment",
    "environmental",
    "ecology",
    "ecosystem",
    "sustainability",
    "sustainable",

    # Climate change
    "climate",
    "climate change",
    "global warming",
    "greenhouse gas",
    "greenhouse gases",
    "carbon emissions",
    "carbon emission",
    "carbon footprint",
    "net zero",

    # Air pollution
    "air pollution",
    "air quality",
    "particulate matter",
    "smog",

    # Water / oceans
    "water pollution",
    "water scarcity",
    "water shortage",
    "drought",
    "sea level",
    "sea levels",
    "rising sea levels",
    "ocean pollution",
    "marine pollution",
    "ocean acidification",

    # Biodiversity / wildlife
    "biodiversity",
    "biodiversity loss",
    "wildlife",
    "endangered species",
    "species loss",
    "habitat loss",
    "ecosystem loss",
    "conservation",

    # Deforestation
    "deforestation",
    "forest loss",
    "forest destruction",
    "logging",
    "rainforest",

    # Plastic / waste
    "plastic pollution",
    "plastic waste",
    "microplastics",
    "recycling",
    "waste management",
    "waste disposal",
    "landfill",
    "single-use plastic",

    # Energy
    "renewable energy",
    "renewable",
    "clean energy",
    "solar energy",
    "solar power",
    "wind energy",
    "wind power",
    "hydropower",
    "clean electricity",

    # Fossil fuels
    "fossil fuel",
    "fossil fuels",
    "coal",
    "oil",
    "natural gas",

    # Other environmental terms
    "emissions",
    "carbon",
    "pollution",
    "conservation"
]

def is_environment_related(
    text,
    keywords=ENV_ANCHOR_WORDS
):

    if not text:
        return False

    text_lower = text.lower()

    return any(
        keyword in text_lower
        for keyword in keywords
    )

# Apply environmental relevance filter
before_count = len(df)

df = df[
    df["text"].apply(is_environment_related)
]

print(
    f"\nEnvironmental filter: "
    f"kept {len(df)} out of {before_count} articles"
)

candidate_labels = [
    "Air Pollution",
    "Deforestation",
    "Rising Sea Levels",
    "Biodiversity Loss",
    "Water Scarcity",
    "Plastic Pollution",
    "Renewable Energy",
    "Waste Management",
    "Climate Change"
]


def classify_category(
    text,
    labels=candidate_labels,
    threshold=0.5
):

    result = classifier(text, labels)

    top_label = result["labels"][0]
    top_score = result["scores"][0]

    if top_score < threshold:
        return "Uncategorized"

    return top_label

print("\nClassifying articles...")

df["category"] = df["text"].apply(classify_category)

print("\nArticle classifications:")

print(
    df[
        [
            "title",
            "category"
        ]
    ]
)

final_topics = sorted(
    c
    for c in df["category"].unique()
    if c != "Uncategorized"
)

print("\nFinal topics for scraper:")
print(final_topics)

def save_articles_to_csv(df, csv_path=CSV_PATH):

    # Columns to save
    columns_to_save = [
        "title",
        "source",
        "description",
        "url",
        "published_at",
        "category"
    ]

    new_df = df[columns_to_save].copy()

    # Do not save Uncategorized articles
    new_df = new_df[
        new_df["category"] != "Uncategorized"
    ]

    if not os.path.exists(csv_path):

        new_df.to_csv(
            csv_path,
            index=False
        )

        print(
            f"\nCreated {csv_path} "
            f"with {len(new_df)} articles."
        )

        return

    existing_df = pd.read_csv(csv_path)

    # Make sure URL column exists
    if "url" not in existing_df.columns:

        print(
            f"Error: {csv_path} "
            "does not contain a 'url' column."
        )
        return


    # Get URLs of existing articles
    existing_urls = set(
        existing_df["url"]
        .dropna()
        .astype(str)
        .str.strip()
    )

    new_articles = new_df[
        ~new_df["url"]
        .astype(str)
        .str.strip()
        .isin(existing_urls)
    ]

    if len(new_articles) > 0:

        new_articles.to_csv(
            csv_path,
            mode="a",
            header=False,
            index=False
        )

        print(
            f"\nAdded {len(new_articles)} "
            f"new articles to {csv_path}."
        )

    else:

        print(
            "\nNo new articles to add. "
            "CSV is already up to date."
        )


save_articles_to_csv(df)