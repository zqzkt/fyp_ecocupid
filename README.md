# Project EcoCupid

Project EcoCupid is an environmental media-monitoring project for Southeast Asia. It
collects news and social-media content, classifies it against monthly
environmental topics, stores results in Supabase, and presents the data in a
Streamlit dashboard.

## What this repository contains

- `scripts/News_raw/` — country-specific news collectors.
- `scripts/News_processed/` — news cleaning and monthly topic processing.
- `scripts/sources/` — Facebook, Instagram, Reddit, X, and YouTube collectors.
- `scripts/cleaning/clean_social.py` — normalizes collected social posts and
  comments in Supabase into shared clean tables.
- `scripts/sentiment/` — emotion model and sentiment aggregation.
- `scripts/supabase/` — platform-specific Supabase integrations.
- `dashboard/` — Streamlit dashboard and its pages.
- `docs/` — detailed collection and storage notes for each social platform.

## Requirements

- Python 3.10 or later.
- Access to the project's Supabase instance and required platform APIs.
- The repository's Python dependencies.

From the repository root, create and activate a virtual environment, then
install dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

On Windows, activate the environment with `.venv\Scripts\activate` instead.

## Configuration

Copy `.env.example` to `.env` in the repository root, then fill in the
credentials required for the pipelines you intend to run:

```env
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your-server-side-supabase-key

# Data sources
APIFY_TOKEN=your-apify-token
TWITTER_BEARER_TOKEN=your-x-bearer-token
YOUTUBE_KEY=your-youtube-data-api-key

# Required by scripts/News_processed/News_cleaned.py
GOOGLE_CLOUD_PROJECT=your-google-cloud-project-id
```

Do not commit `.env` or credentials. Use a server-side Supabase key for
scripts that write data. Some social scripts also accept
`SUPABASE_SECRET_KEY` or `SUPABASE_SERVICE_ROLE_KEY`.

The news cleaner and social cleaner use Google Cloud Translation. You do not
need to set `GOOGLE_TRANSLATE_API_KEY` or
`GOOGLE_APPLICATION_CREDENTIALS`; they use Google Application Default
Credentials (ADC). For local runs, authenticate with:

```bash
gcloud auth application-default login
```

Enable the Cloud Translation API for the Google Cloud project and ensure your
ADC identity is authorized to use it. Deployed environments should use their
standard Google Cloud identity.

The news collectors, social collectors, and dashboard depend on Supabase
tables being available. In particular, social collectors use
`monthly_topic_stats` to determine the previous month's top-ranked topic
keywords. Run the news pipeline first to refresh those monthly topics.

The YouTube collector additionally expects
`scripts/sources/locations.json` with country location settings. That file is
not included in this repository; obtain the project's configured copy before
running YouTube collection.

## Collect data

Run both pipelines from the repository root, in this order:

```bash
python scripts/news_datapipeline.py
python scripts/social_media_pipeline.py
```

### News pipeline

`scripts/news_datapipeline.py` runs the six country news collectors
sequentially, then runs `News_cleaned.py` and `News_topic.py`. The collection
period is the previous complete calendar month. Topic processing depends on
successful news cleaning.

### Social-media pipeline

`scripts/social_media_pipeline.py` runs the collectors sequentially in this
order:

1. Facebook
2. Instagram
3. Reddit
4. X
5. YouTube
6. Shared social cleaning
7. Sentiment analysis

The pipeline continues to the other collectors if a collector fails, then
attempts to clean data that was successfully collected. Sentiment runs only
after cleaning succeeds. It passes `--run-now` so sentiment can be computed
when the pipeline is run on a day other than the first of the month. The
pipeline prints a step-by-step summary and exits with a nonzero status if a
step fails.

To run an individual social collector, invoke its script from the repository
root, for example:

```bash
python scripts/sources/twitter.py
```

## Run the dashboard

After configuring Supabase access and installing the dependencies, start the
dashboard from the repository root:

```bash
streamlit run dashboard/app.py
```

The dashboard loads topic statistics and supporting news data from Supabase.
Its pages include overview, country opportunity, engagement comparison,
communication channels and insights, sentiment analysis, and data views.

## Platform documentation

- [Facebook pipeline](docs/FACEBOOK_DATA_PIPELINE.md)
- [Instagram pipeline](docs/INSTAGRAM_DATA_PIPELINE.md)
- [Reddit pipeline](docs/REDDIT_DATA_PIPELINE.md)
- [X pipeline](docs/X_DATA_PIPELINE.md)
- [YouTube pipeline](docs/YOUTUBE_DATA_PIPELINE.md)