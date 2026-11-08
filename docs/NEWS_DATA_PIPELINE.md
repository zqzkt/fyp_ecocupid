# News Data Collection, Processing and Topic Modelling

## Purpose

This document explains how EcoCupid's news pipeline collects environmental news from six ASEAN countries, prepares multilingual articles for analysis, identifies environmental themes, and stores the results in Supabase for the dashboard and downstream social-media analysis.

The geographic scope covers **Singapore, Malaysia, Indonesia, Philippines, Thailand and Brunei**. The pipeline is designed to process the **previous complete calendar month** each time it is run. It writes results directly to Supabase rather than relying on a permanent local news-data folder.

## Main Components

| Component | Responsibility |
| --- | --- |
| `news_datapipeline.py` | Main entry point: calculates the monthly window, runs six scrapers sequentially, then cleaning and topic modelling, and prints a status summary. |
| `News_raw/SG_news.py` | Collects Singapore articles from The Straits Times environment listing API. |
| `News_raw/MY_news.py` | Collects Malaysia articles from Astro Awani topic pages. |
| `News_raw/ID_news.py` | Collects Indonesia articles from Mongabay Indonesia using GraphQL. |
| `News_raw/PH_news.py` | Collects Philippines articles from Mongabay news archive pages. |
| `News_raw/TH_news.py` | Collects Thailand articles from Thai PBS environment category/archive pages. |
| `News_raw/BN_news.py` | Collects Brunei articles from Pelita Brunei category pages. |
| `News_processed/News_cleaned.py` | Detects languages, translates where needed, cleans text, classifies environmental categories, extracts keywords and computes semantic scores. |
| `News_processed/News_topic.py` | Groups semantically related articles, assigns reusable topic IDs, and updates monthly country-specific topic statistics. |
| Supabase | Stores raw articles, cleaned article-country records, topic assignments, the topic registry and monthly aggregates. |

Paths above are relative to the directory containing `news_datapipeline.py`.

## Data Flow

```text
Run news_datapipeline.py
         |
         v
Calculate previous complete calendar month
         |
         v
Run six country-specific news scrapers, one at a time
         |
         v
Discover articles -> filter dates -> skip existing URLs
         |
         v
Scrape article pages -> extract text and metadata
         |
         v
                    news_raw
         |
         v
News_cleaned.py
  -> detect language / translate to English
  -> clean text / check quality
  -> classify environmental category / extract keywords
  -> calculate semantic similarity scores
         |
         v
                  news_cleaned
         |
         v
News_topic.py
  -> create article embeddings / cluster related stories
  -> match or register reusable topics
  -> assign a primary topic to each article
  -> aggregate topics by country and month
         |
         +--> news_topics
         +--> topic_registry
         +--> monthly_topic_stats
         |
         v
       Streamlit dashboard / downstream analysis
```

## 1. Credentials and Configuration

The scripts use `python-dotenv` and Supabase credentials. The cleaning stage also requires a Google Cloud project and credentials for Cloud Translation.

```env
SUPABASE_URL=...
SUPABASE_KEY=...
GOOGLE_CLOUD_PROJECT=...
```

Google Cloud Translation also requires valid Google application credentials in the execution environment (for example, Application Default Credentials). Never commit `.env`, service-account keys or other secrets to Git.

The orchestrator passes these two environment variables to each country scraper:

```env
NEWS_START_DATE=2026-10-01
NEWS_END_DATE=2026-10-31
```

They are calculated automatically during a normal pipeline run; the example dates above illustrate a run during November 2026.

## 2. Monthly Collection Window

`news_datapipeline.py` computes:

1. The first day of the current month.
2. The last day of the previous month (`END_DATE`).
3. The first day of that previous month (`START_DATE`).

For example, running the pipeline on **8 November 2026** collects articles dated **1–31 October 2026**. The scrapers receive the same date range to keep country-level collection consistent. Dates are handled according to each scraper's parsing and filtering logic; this is not a single shared UTC timestamp query.

The entry point is **not an automatic scheduler**: it performs the previous-month run when invoked. A separate external scheduler would be required for unattended monthly execution.

## 3. Raw News Collection

The six scrapers share a common objective but have separate implementations because news sites expose articles in different ways.

| Country | Source | Discovery approach |
| --- | --- | --- |
| Singapore | The Straits Times | Paginated article-listing API for the Singapore Environment section. |
| Malaysia | Astro Awani | Environmental topic pages and article links. |
| Indonesia | Mongabay Indonesia | GraphQL queries and paginated article results. |
| Philippines | Mongabay | Archive-page discovery and article URL processing. |
| Thailand | Thai PBS | Environment category and archive pages; Thai date handling. |
| Brunei | Pelita Brunei | Category-page discovery and article extraction. |

### Article discovery and filtering

Depending on the source, each scraper:

1. Retrieves article listings from a website, archive or API.
2. Identifies candidate article URLs and publication dates.
3. Keeps articles within the requested monthly date window.
4. Compares candidate URLs with those already stored in `news_raw` for the source country.
5. Fetches new article pages and extracts usable titles, body text and publication metadata.
6. Identifies environmental keywords and mentioned ASEAN countries as metadata.
7. Inserts accepted records into `news_raw` in batches.

The Singapore scraper additionally excludes articles marked as premium, since full article content may be inaccessible. Other scrapers have source-specific extraction, date parsing and validation rules. For example, the Thailand scraper converts Thai Buddhist-calendar years when necessary and can use structured JSON-LD article data.

### Why use six scrapers?

Different sites have different URL structures, pagination methods, languages and article layouts. Separate scripts make those differences easier to handle and allow failures to be reported by country without stopping all other collection attempts.

## 4. Raw Supabase Storage

The raw collection destination is **`news_raw`**. Fields written by the scrapers include:

| Field | Meaning |
| --- | --- |
| `source_country` | Country associated with the news source/scraper. |
| `title` | Article headline. |
| `source` | Publisher name. |
| `published_at` | Article publication date. |
| `url` | Original article URL. |
| `article_text` | Extracted article body. |
| `countries` | ASEAN countries detected in the article text. |
| `environment_keywords` | Environmental terms matched during scraping. |

**Source country is not necessarily the same as the countries discussed in the article.** For example, a Singapore publication can report on an environmental issue in Malaysia.

The cleaning process also uses `news_raw.cleaning_status` to track whether a raw record has been accepted, rejected or needs later processing.

## 5. Duplicate Prevention

The scrapers retrieve existing URLs from Supabase before fetching full article pages. They also remove duplicate URLs discovered during the same run. This reduces redundant requests and repeated storage.

The cleaning stage checks existing **article-country** records, and topic modelling checks already processed **article-country** pairs. These checks support incremental runs and reduce repeated processing.

Unlike an unconditional database upsert, raw scraper inserts can still fail if a duplicate slips through and conflicts with database constraints. The pre-insert URL checks are therefore important.

## 6. News Cleaning and Translation

`News_cleaned.py` reads pending records from `news_raw` and prepares a common English-language representation for analysis.

### Language detection

- Uses `langdetect` to identify the article language.
- English articles bypass translation.
- Non-English articles use **Google Cloud Translation API** to translate the title and body into English.
- Long text is split into chunks, translated in small batches and joined again.
- Temporary API failures are retried with backoff; a failed translation is left pending rather than silently treated as a successful result.

### Text cleaning and quality checks

The cleaner removes HTML markup, URLs, email-like text, punctuation and selected low-information words, and normalizes whitespace/case. It checks that sufficient usable text remains; the configured minimum is **20 words**.

The cleaner also checks country metadata. An article may produce multiple `news_cleaned` records when multiple target ASEAN countries are identified. Records are tracked by the combination of `article_id` and `country`.

## 7. Environmental Classification and Keywords

The cleaner uses **DeBERTa-v3-xsmall zero-shot classification** (`MoritzLaurer/deberta-v3-xsmall-zeroshot-v1.1-all-33`) to assign one broad environmental category. Examples include climate change, pollution, biodiversity and conservation, renewable energy, waste management, sustainable transport and marine conservation.

The model evaluates the beginning of the prepared article text (up to **1,800 characters**) against the predefined categories. It returns a selected category and a classification confidence score.

- Minimum category confidence: **0.30**.
- Articles below this threshold are rejected from the cleaned dataset.
- Classification failures are left pending for later processing.
- **KeyBERT**, backed by the **all-MiniLM-L6-v2** sentence embedding model, extracts up to **five** keyphrases from accepted articles.

The 0.30 threshold is a configurable heuristic and should not be interpreted as a validated probability that an article is environmental.

## 8. Semantic Similarity Scores

`News_cleaned.py` also calculates semantic scores using **SentenceTransformer embeddings** and cosine similarity. These scores compare article representations with category-related article representations and are updated in Supabase after processing.

This is different from `confidence_score`:

| Score | What it represents |
| --- | --- |
| `confidence_score` | DeBERTa's score for the selected environmental category. |
| `semantic_score` | Embedding-based similarity used to describe semantic alignment. |

Neither should be presented as a manually verified measure of article correctness.

## 9. Cleaned Supabase Storage

Accepted articles are written to **`news_cleaned`**, with fields including:

| Field | Meaning |
| --- | --- |
| `article_id` | Identifier of the source record in `news_raw`. |
| `country` | ASEAN country associated with this cleaned record. |
| `source_country` | Country of the originating news source. |
| `title`, `source`, `published_at`, `url` | Traceable article metadata. |
| `cleaned_text` | Normalized English text used for analysis. |
| `environment_category` | Selected broad environmental category. |
| `environment_keywords` | Extracted keyphrases. |
| `confidence_score` | Classification score. |
| `semantic_score` | Embedding-based similarity score. |
| `language_code` | Detected source language. |
| `translated_text`, `translation_provider` | Translation output and provider information where applicable. |

The **`article_id` + `country`** pair distinguishes country-specific rows. One source article may therefore contribute to more than one country's analysis when appropriate.

## 10. Monthly Topic Modelling

`News_topic.py` groups related cleaned articles into reusable environmental topics, instead of relying only on the broad categories assigned during cleaning.

### Semantic clustering

1. Load cleaned article-country rows from Supabase.
2. Create article embeddings using **all-MiniLM-L6-v2**; the script also uses overlapping text chunks to capture article-level meaning.
3. Cluster related articles with **agglomerative clustering** using cosine distance.
4. Merge sufficiently similar clusters.
5. Extract meaningful topic keywords with TF-IDF and semantic similarity.
6. Produce environmental issue-oriented topic names rather than names based only on generic locations or entities.

The clustering is **similarity-driven**: it does not force a fixed number of topics. A distinctive article may remain a one-article topic.

### Reusing topics across months

The script compares newly discovered clusters with the existing `topic_registry`. If a topic is sufficiently similar, it reuses the established topic ID; otherwise, it creates a new registry entry. This makes it possible to compare topics across different months.

Each unique article is assigned **one primary topic**, while the same article can have country-specific assignment records.

### Incremental and rebuild modes

- **`REBUILD_MODE = False` (normal):** processes previously unprocessed article-country pairs and updates the affected monthly statistics.
- **`REBUILD_MODE = True` (special historical baseline):** rebuilds topic history, subject to the script's requirement that the derived topic tables are empty. This should not be used casually during normal monthly collection.

## 11. Topic Supabase Tables

| Table | Purpose |
| --- | --- |
| `news_topics` | Stores article-country topic assignments, including topic ID, name, keywords and assignment score. |
| `topic_registry` | Stores canonical reusable topics and their first/last observed month. |
| `monthly_topic_stats` | Aggregates article counts and topic keywords by month, country and topic; includes country-specific topic rank. |

`monthly_topic_stats` includes:

- `month`
- `country`
- `topic_id`
- `topic_name`
- `article_count`
- `monthly_keywords`
- `topic_rank`

Within each country and month, topics are ranked by their article coverage. The sequential ranking allows `topic_rank <= 3` to select **at most three topics per country** for dashboard reporting or downstream social-media searches.

**Interpretation:** `article_count` measures coverage within the collected news dataset, not the total number of articles published in the country or public interest in the topic.

## 12. Pipeline Execution Order and Failure Handling

The orchestrator uses `subprocess.run()` and waits for each script to finish before launching the next one.

```text
1. SG_news.py
2. MY_news.py
3. ID_news.py
4. PH_news.py
5. TH_news.py
6. BN_news.py
7. News_cleaned.py
8. News_topic.py
```

Its failure behavior is deliberate:

- **One or more scrapers fail:** it records the failures but continues to `News_cleaned.py`, using data successfully collected by the other scrapers.
- **Cleaning fails:** it stops before topic modelling, because topics depend on cleaned data.
- **Topic modelling fails:** the failure appears in the final summary; earlier successful stages are not automatically rolled back.
- **A script file is missing:** the orchestrator reports `FILE NOT FOUND` for that stage.

At the end, the console displays each script's status, the successful-stage count and the collection date range.

## 13. How to Run

From the directory containing `news_datapipeline.py`:

```bash
python news_datapipeline.py
```

Or, from the repository root, if the pipeline is stored in a subdirectory:

```bash
python path/to/news_datapipeline.py
```

Replace `path/to/` with the actual directory in your project. The orchestrator resolves its scraper and processing paths relative to its own file location, so it does not depend on being launched from a particular working directory.

A normal run:

1. Prints the date range and pipeline order.
2. Runs all six country scrapers sequentially.
3. Cleans, translates and classifies pending raw articles.
4. Updates semantic scores.
5. Performs incremental topic modelling and refreshes monthly topic statistics.
6. Prints the final execution summary.

The first run may take longer because NLP models need to be downloaded or loaded, translation calls take time, and historical articles may require processing.

## 14. Repeated Runs and Recovery

Running the pipeline again in the same month targets the same previous-month date range. Existing raw URLs are checked before scraping, existing cleaned article-country records are checked during cleaning, and processed topic assignments are skipped in incremental topic modelling.

This design helps recover from partial runs without starting from an empty database. However, some stages may already have written data before an error, and rerunning may still incur website requests, translation costs or model processing.

If a source site changes its HTML or API response, update that country's scraper rather than changing the shared cleaning or topic-modelling logic unless necessary.

## 15. Data Quality and Analysis Limitations

- **Source coverage:** each country uses a selected news publisher or set of pages, not all news outlets in that country.
- **Date coverage:** archive/API pagination and source availability may limit retrieval of older articles.
- **Language and translation:** automatic language detection and translation can introduce errors or lose nuance.
- **Country assignment:** keyword-based country detection may miss implicit references or assign an article to multiple countries.
- **Environmental classification:** zero-shot model predictions and the 0.30 cutoff are heuristics; ambiguous stories may be misclassified.
- **Topic clustering:** semantic similarity can group distinct stories or separate closely related ones, and topic labels may require review.
- **Relative rankings:** the top-three topics reflect the articles collected, not a representative measure of all public concern.
- **Partial failures:** a pipeline can complete cleaning and topic modelling even when one country scraper failed; check the final summary before interpreting country comparisons.

For reproducible reporting, record the collection month, source coverage, number of raw and cleaned articles, failed stages, classification threshold and topic-modelling configuration.

## 16. Current Architecture Summary

The pipeline follows a **raw -> clean -> topic -> monthly aggregate** architecture, with Supabase as its persistent data store.

Key design choices:

- Country-specific scrapers handle different website structures and languages.
- The main pipeline targets the previous complete calendar month.
- Existing URLs and article-country pairs reduce repeated work.
- Google Cloud Translation standardizes non-English news into English for analysis.
- DeBERTa classifies broad environmental categories; KeyBERT and MiniLM support keyword extraction and semantic analysis.
- Similarity-based clustering identifies more specific topics and reuses topic IDs over time.
- `monthly_topic_stats` provides country-level ranked topics for EcoCupid's dashboard and communication analysis.
- Pipeline stage statuses are printed so failures can be diagnosed without confusing partial success with complete collection.
