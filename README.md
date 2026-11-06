# Project EcoCupid

Project EcoCupid is an environmental media-monitoring system for Southeast
Asia (Singapore, Malaysia, Indonesia, the Philippines, Thailand and Brunei).
Each month it collects environmental news and social-media content, ranks the
most prominent environmental topics per country, filters and analyses social
content for those topics, stores everything in Supabase, and presents the
results in a Streamlit dashboard.

Built by Team Ninja Turtles, Singapore Management University (IS483 Final Year
Project), for the sponsor EcoCupid.

## How it works

```text
1. News collection     6 country collectors      -> news_raw
2. News cleaning       translate, filter, clean   -> news_cleaned
3. Topic ranking       cluster into topics        -> monthly_topic_stats
        |
        |  top 3 topic keywords per country, previous month
        v
4. Social collection   Facebook, Instagram, Reddit, X, YouTube -> raw platform tables
5. Shared cleaning     translate, normalise       -> clean_posts, clean_comments
6. Environmental filter  Gemini labels each post  -> clean_posts.is_environmental
7. Sentiment analysis  emotion model, per country and topic -> sentiment_analysis
8. Dashboard           Streamlit reads the tables above
```

Steps 4 to 7 depend on step 3. **Always run the news collection before the
social media collection.**

## What this repository contains

- `scripts/News_raw/` — country-specific news collectors (SG, MY, ID, PH, TH, BN).
- `scripts/News_processed/` — news cleaning (`News_cleaned.py`) and monthly
  topic processing (`News_topic.py`).
- `scripts/sources/` — Facebook, Instagram, Reddit, X and YouTube collectors,
  and `locations.json` (search coordinates for each country; required by
  YouTube collection and the summary scripts).
- `scripts/supabase/` — platform-specific Supabase integrations.
- `scripts/cleaning/clean_social.py` — normalises collected posts and comments
  into shared clean tables, translating non-English text.
- `scripts/cleaning/filter_environmental.py` — classifies unlabelled clean
  posts with Gemini and writes `is_environmental` as a boolean.
- `scripts/sentiment/` — emotion model, training script, validation workbook,
  GoEmotions dataset and sentiment aggregation.
- `scripts/communication_framework/` — engagement comparison and topic-based
  analysis used by the dashboard.
- `scripts/news_datapipeline.py` — runs the whole news pipeline.
- `scripts/social_media_pipeline.py` — runs the whole social-media pipeline.
- `dashboard/` — Streamlit dashboard and its pages.
- `docs/` — detailed collection and storage notes for each social platform.

## Requirements

- Python 3.10 or later.
- A Supabase project, with the database tables created (see
  [Database](#database)).
- Accounts and keys for the services listed under
  [Configuration](#configuration).
- A computer with enough disk space, memory and time to run transformer
  models locally. The first run downloads several models from the internet
  (a DeBERTa zero-shot classifier, `flan-t5-base` and `all-MiniLM-L6-v2`).
- A stable internet connection and a computer that stays on during runs.

## Setup

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

Create a `.env` file in the repository root. If a `.env.example` file is
present, copy it to `.env`. Fill in the values for the pipelines you intend to
run:

```env
# Supabase (required by every script and the dashboard)
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your-server-side-supabase-key

# Data sources
APIFY_TOKEN=your-apify-token                  # Facebook, Instagram, Reddit
TWITTER_BEARER_TOKEN=your-x-bearer-token      # X
YOUTUBE_KEY=your-youtube-data-api-key         # YouTube

# Gemini (environmental filter and AI-written summaries)
GEMINI_API_KEY=your-gemini-api-key            # GOOGLE_API_KEY also works

# Google Cloud (translation in the news cleaner)
GOOGLE_CLOUD_PROJECT=your-google-cloud-project-id
```

| Variable | Used for |
| --- | --- |
| `SUPABASE_URL` | Database address |
| `SUPABASE_KEY` | Server-side key. Scripts that write data need a secret or service-role key, not a publishable or anon key. `SUPABASE_SECRET_KEY` and `SUPABASE_SERVICE_ROLE_KEY` are accepted by several scripts |
| `APIFY_TOKEN` | Facebook, Instagram and Reddit collection |
| `TWITTER_BEARER_TOKEN` | X collection |
| `YOUTUBE_KEY` | YouTube Data API |
| `GEMINI_API_KEY` or `GOOGLE_API_KEY` | `filter_environmental.py` stops without one. Also used by the summary and topic analysis scripts |
| `GOOGLE_CLOUD_PROJECT` | Required by `scripts/News_processed/News_cleaned.py` |

Do not commit `.env` or any credentials.

### Google Cloud Translation

The news cleaner and social cleaner use Google Cloud Translation. You do not
need `GOOGLE_TRANSLATE_API_KEY` or `GOOGLE_APPLICATION_CREDENTIALS`; they use
Google Application Default Credentials (ADC). For local runs, authenticate
with:

```bash
gcloud auth application-default login
```

Enable the Cloud Translation API for the Google Cloud project and make sure
your ADC identity is allowed to use it. Deployed environments should use their
standard Google Cloud identity.

## Database

All data lives in Supabase. The scripts expect these tables:

| Group | Tables |
| --- | --- |
| News | `news_raw`, `news_cleaned`, `topic_registry`, `news_topics`, `monthly_topic_stats` |
| Raw social data | `facebook_posts`, `facebook_comments`, `instagram_posts`, `instagram_comments`, `reddit_posts`, `reddit_comments`, `x_posts`, `x_replies`, `youtube_videos`, `youtube_comments` |
| Shared clean data | `clean_posts`, `clean_comments` |
| Results | `sentiment_analysis`, `summary`, `topic_based_analysis` |

The platform documents in `docs/` refer to SQL migration files (numbered 001
to 007) in a `supabase/migrations/` folder that create and update these tables.
Apply them in the Supabase SQL Editor before the first run, and keep that
folder in the repository.

`monthly_topic_stats` is central: every social collector reads the previous
month's top three topic keywords per country from it, and the dashboard shows
nothing until it has rows.

## Running the monthly update

Each run covers the **previous complete calendar month**.

### Option 1: from the dashboard (recommended)

1. Start the dashboard (see [Run the dashboard](#run-the-dashboard)) and open
   the **Data** page.
2. Click **Run news collection** and wait until it shows as completed.
3. Click **Run all social media collections**.

Notes:

- **Order matters and is not enforced.** The page lets you click the social
  button before the news button. Always run news first.
- **Protection against double runs.** A button is disabled when that month's
  data is already in Supabase. Once any social platform has data for the
  month, the all-platforms button is disabled.
- **Rerunning one platform.** If a platform fails, fix the cause and use its
  own button (Run Facebook, Run Instagram, and so on). Each single-platform run
  also performs shared cleaning, environmental classification and sentiment
  analysis.
- **Keep the page open and the computer awake** until the run finishes. The
  page shows a collection log afterwards.
- Runs can take hours (the Reddit step alone takes around 2 hours) and use
  paid credits.
- The dashboard can start paid runs and has no login. Do not expose it to
  people who should not be able to do this.

### Option 2: from the command line

From the repository root, in this order:

```bash
python scripts/news_datapipeline.py
python scripts/social_media_pipeline.py
```

To run one platform followed by shared cleaning, filtering and sentiment:

```bash
python scripts/social_media_pipeline.py --platform facebook
```

Valid platforms are `facebook`, `instagram`, `reddit`, `x` and `youtube`. To
run an individual collector without the shared stages:

```bash
python scripts/sources/twitter.py
```

### News pipeline

`scripts/news_datapipeline.py` runs the six country news collectors
sequentially, then `News_cleaned.py` and `News_topic.py`. Topic processing
depends on successful news cleaning. `News_topic.py` has a `REBUILD_MODE`
setting that must stay `False` except for a one-time historical rebuild.

### Social-media pipeline

`scripts/social_media_pipeline.py` runs these steps in order:

1. Facebook
2. Instagram
3. Reddit
4. X
5. YouTube
6. Shared social cleaning
7. Environmental filtering
8. Sentiment analysis

If one collector fails, the pipeline continues with the next one and reports
the failure in its summary. Shared cleaning runs once after all collectors,
even if some failed. Environmental classification runs only if cleaning
succeeded, and sentiment runs only after classification succeeded. The
pipeline passes `--run-now` so sentiment can be computed on any day of the
month. It exits with a nonzero status if a step fails.

### Typical cost and time per run

| Item | Typical figure |
| --- | --- |
| Google Cloud Translation | About US$90 per run |
| X API | About US$2 to 3 per run |
| Reddit collection time | Around 2 hours |
| Supabase | Free plan |

Spending caps in the code: Facebook US$20, Instagram US$12, Reddit US$12 (all
Apify), and X with an estimated US$5 limit. Check the Apify, Gemini and Google
Cloud consoles for current spend.

## Run the dashboard

After configuring Supabase access and installing the dependencies, start the
dashboard from the repository root:

```bash
streamlit run dashboard/app.py
```

The dashboard reads its configuration from the repository-root `.env`. It
stops with a message if `monthly_topic_stats` has no rows. Pages:

- **Overview**
- **Country Opportunity Explorer**
- **Engagement Comparison**
- **Data** — browse and export collected records, and run the collectors
- **Communication Channels**
- **Communication Insights**
- **Sentiment Analysis**

## Emotion model

Sentiment analysis uses a multi-label classifier trained on the GoEmotions
dataset (27 emotions plus neutral) and saved as
`scripts/sentiment/emotion_model.joblib`.

```bash
# Retrain the model
python scripts/sentiment/train_emotion_model.py

# Recompute sentiment across all cleaned data
python scripts/sentiment/sentiment_analysis.py --all

# Check agreement against the manually validated sample
cd scripts/sentiment && python sentiment_validation_score.py
```

On the 359 manually validated items, agreement was 58.8% and Cohen's kappa
was 0.555. The check counted a match when the human label appeared anywhere in
the model's predicted emotions, so treat results as indicative.

## Troubleshooting

| Symptom | Likely cause and fix |
| --- | --- |
| Dashboard shows "monthly_topic_stats has no rows yet" | The news pipeline has not run. Run news collection first |
| Social collector stops at startup | `monthly_topic_stats` has no rows for the previous month. Run news first |
| `filter_environmental.py` exits asking for a key | Set `GEMINI_API_KEY` or `GOOGLE_API_KEY` |
| Environmental filter rejects the Supabase key | `SUPABASE_KEY` is a publishable or anon key. Use a server-side key |
| Translation errors | Run `gcloud auth application-default login`, enable the Cloud Translation API and check `GOOGLE_CLOUD_PROJECT` |
| YouTube or summary scripts cannot find locations | Make sure `scripts/sources/locations.json` exists |
| Missing table errors | Apply the Supabase migration files (see [Database](#database)) |
| A button on the Data page is greyed out | That month's data is already in Supabase |
| A run was interrupted | Abort any running Apify actor in the Apify Console to stop charges, then rerun the failed platform |

## Known limitations

The results are a sample of public discussion, not a complete record. In
particular: collection is capped by budget, only the top three news topics per
country are searched, news comes from one outlet per country, Facebook is
collected from a fixed list of pages, Instagram and Reddit keep English posts
only, country is inferred, and the emotion model has moderate accuracy. See
the handover document (Section 11) for the full list by component.

## Platform documentation

- [Facebook pipeline](docs/FACEBOOK_DATA_PIPELINE.md)
- [Instagram pipeline](docs/INSTAGRAM_DATA_PIPELINE.md)
- [Reddit pipeline](docs/REDDIT_DATA_PIPELINE.md)
- [X pipeline](docs/X_DATA_PIPELINE.md)
- [YouTube pipeline](docs/YOUTUBE_DATA_PIPELINE.md)