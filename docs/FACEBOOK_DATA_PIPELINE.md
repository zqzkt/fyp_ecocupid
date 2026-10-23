# Facebook Data Collection and Supabase Storage

## Purpose

This document explains how the project collects Facebook page posts and
sampled comments with Apify and stores the results in Supabase.

The collector scrapes a fixed list of environmental Facebook pages across
Singapore, Malaysia, Indonesia, the Philippines, Thailand, and Brunei for the
previous calendar month. Posts are kept only when they match that month's
top-ranked topic keywords for their country. Non-English posts are translated
to English before matching, so they are kept rather than discarded. Comments
are then collected for the matched posts.

## Main Components

| Component | Responsibility |
| --- | --- |
| `scripts/sources/facebook.py` | Defines the source pages, runs the Apify post and comment scrapers, assigns regional posts to countries, translates and classifies posts, writes local outputs, and starts the Supabase sync. |
| `scripts/supabase/facebook_pipeline.py` | Projects posts and comments onto the table columns, upserts them in batches, and runs the shared cleaner. |
| `scripts/supabase/instagram_pipeline.py` | Provides `monthly_keyword_specs()`, which reads the monthly topic keywords from Supabase. |
| `scripts/cleaning/clean_social.py` | Provides the Cloud Translation batching used for posts, and refreshes `clean_posts` / `clean_comments` after the upload. |
| Supabase `monthly_topic_stats` | Provides the monthly topics, ranks, countries, and keywords. |
| Supabase Facebook tables | `facebook_posts` stores posts and `facebook_comments` stores comments. |

## Data Flow

```text
Run `scripts/sources/facebook.py`
    |
    v
Read previous-month keywords from `monthly_topic_stats` (topic_rank <= 3)
    |
    v
Scrape up to 100 posts per page with `apify/facebook-posts-scraper`
    |
    v
Assign regional-page posts to a country by place-name keywords
    |
    v
Keep posts from the exact previous calendar month
    |
    v
Translate non-English post text to English (Cloud Translation)
    |
    v
Keep posts that match their country's monthly topic keywords
    |
    v
Scrape up to 20 comments per matched post with `apify/facebook-comments-scraper`
    |
    v
Apply one cumulative `$20` Apify budget across posts and comments
    |
    v
Deduplicate, normalise, and save JSON/CSV outputs
    |
    v
Upsert into `facebook_posts` and `facebook_comments`
    |
    v
Run `clean_social.py` to refresh the shared clean tables
```

## 1. Credentials

The script loads the repository-root `.env` file with `python-dotenv`.

Required variables include:

```env
APIFY_TOKEN=...
SUPABASE_URL=...
SUPABASE_SECRET_KEY=...
GOOGLE_TRANSLATE_API_KEY=...
```

`SUPABASE_SERVICE_ROLE_KEY` or `SUPABASE_KEY` are accepted in place of
`SUPABASE_SECRET_KEY`. The key must be a server-side secret or service-role
key; publishable and anon keys are rejected.

Google Cloud Translation is needed for post translation in `facebook.py` and
comment translation in `clean_social.py`. Set either
`GOOGLE_TRANSLATE_API_KEY` (a Cloud Translation API key) or
`GOOGLE_APPLICATION_CREDENTIALS` (a service-account JSON file). The API key
is used when both are set.

The `.env` file must remain private and must not be committed to Git.

## 2. Source Pages

Pages are configured in `FACEBOOK_SOURCES` in `facebook.py`. Each entry has a
`source_name`, a page `url`, and either a fixed `country` or
`country_keywords`.

Most pages belong to one country and every post they publish is assigned to
it. Pages that post mainly in a local language, such as Mongabay Indonesia,
are included because their posts are translated before classification.

### Regional pages

Mongabay, Greenpeace Southeast Asia, and Eco-Business report across the
region. Each is listed once, so it is scraped once, with a `country_keywords`
map:

| Page | Countries matched | Unmatched posts |
| --- | --- | --- |
| Mongabay | Indonesia, Thailand, Philippines | Dropped |
| Greenpeace Southeast Asia | Indonesia, Thailand, Philippines | Dropped |
| Eco-Business | Thailand | Kept as Singapore |

`split_posts_by_source_keywords()` checks the post caption, the shared link's
title, and the shared link URL against `INDONESIA_KEYWORDS`,
`THAILAND_KEYWORDS`, and `PHILIPPINES_KEYWORDS`. Matching is case-insensitive and whole-word. A post is
assigned to the first country in the map whose keywords it mentions. Place
names shared with other countries, such as `borneo`, `mekong`, or `sulu`,
are deliberately excluded from the lists.

The script stops at startup if a page URL appears more than once in
`FACEBOOK_SOURCES`, because posts are matched back to their source by URL
and a duplicate entry would silently override the other.

## 3. Apify Collection and Budget

Posts are collected with `apify/facebook-posts-scraper` using:

```python
POST_LIMIT_PER_PAGE = 100
"onlyPostsNewerThan": <first day of previous month>
"onlyPostsOlderThan": <first day of current month>
```

A source can override the post limit with its own `post_limit`. Sources with
different limits are scraped in separate actor runs.

Comments are collected with `apify/facebook-comments-scraper` using:

```python
COMMENT_LIMIT_PER_POST = 20
"includeNestedComments": False
```

Comments are scraped for every topic-matched post that has at least one
reported comment and a known country, ordered by engagement.

Both scrapers share one budget:

```python
TOTAL_MAX_COST_USD = 20.00
```

Each post run is capped at the budget the earlier runs left, and the comment
run is capped at whatever remains after post scraping. Each run's cost is
read from Apify's `usage_total_usd` after it finishes. If Apify does not
report a cost, the run's full cap is counted against the budget. If nothing
is left, comment scraping is skipped.

## 4. Date Filtering

The script calculates:

* `MONTH_START`: the first day of the previous calendar month
* `CURRENT_MONTH_START`: the first day of the current month

For example, when run on 23 October, only posts from:

```text
1 September 00:00 UTC through 30 September 23:59:59 UTC
```

are passed to later processing. The actor date filters are followed by an
explicit local check in `keep_reporting_month()`.

## 5. Translation

`translate_non_english_posts()` runs after the date filter and before topic
classification, so the English monthly keywords can match translated posts.

* `lingua` detects English posts locally; these are not sent to Google.
* Other posts are translated with `translate_comments_batch()` from
  `clean_social.py`: batches of 50, up to 3 retries, and the original text is
  kept if translation fails.
* Translated text is HTML-unescaped before keyword matching.
* The post's `text` becomes the English version. The source text is kept in
  `original_text` and the detected language in `lang`.

Translations are cached by `postId` in
`data/raw/facebook_post_translations.json`. A post is translated again only
if its text changes or its previous translation failed.

Only the main post text is translated. Link preview titles, shared-post
text, and image OCR text stay in their original language.

Comments are not translated here. `clean_social.py` translates them when it
refreshes `clean_comments`.

## 6. Topic Classification

`monthly_keyword_specs()` reads `monthly_topic_stats` for the previous month
with `topic_rank <= 3`. These are the same top-three topics used by the
Instagram and YouTube collectors, produced by
`scripts/News_processed/News_topic.py`.

`classify_environmental_post()` matches each post against its own country's
keywords. The text checked combines the caption, link preview text,
shared-post text, and media OCR text. Latin-script keywords use word
boundaries; non-ASCII keywords use substring matching because scripts such
as Thai do not separate words with spaces.

When several topics match, the topic with the most matched keywords becomes
`primary_topic`, with ties broken by longer, more specific matches. Posts
that match no topic are rejected and saved to
`data/raw/facebook_posts_rejected.json`.

If a country has no monthly keywords, a warning is printed at startup and all
of its posts will be rejected.

## 7. Data Transformation

### Posts

Facebook post records include:

* `post_id`
* `platform`
* `country`
* `source_name`
* `page_name`
* `published_at`
* `url`
* `text` (English)
* `original_text` and `lang` (local outputs only)
* `likes`, `comments_count`, `shares`
* `primary_topic`
* `matched_topics`
* `matched_keywords`

### Comments

Facebook comment records include:

* `comment_id`
* `parent_post_id`
* `platform`
* `post_url`
* `country`
* `source_name`
* `primary_topic`
* `matched_keywords`
* `published_at`
* `text`
* `likes`

Comments take their country, source, and topic from their parent post.

## 8. Local Outputs

Raw and intermediate files are written under `data/raw/`:

| File | Contents |
| --- | --- |
| `facebook_posts_raw.json` | Raw post scrape, before any filtering |
| `facebook_comments_raw.json` | Raw comment scrape |
| `facebook_topic_keywords.json` | Monthly keywords used for the run |
| `facebook_post_translations.json` | Translation cache |
| `facebook_posts_environmental.json` | Topic-matched posts |
| `facebook_posts_rejected.json` | Posts that matched no topic |
| `facebook_posts_normalised.json` | Final post records |
| `facebook_comments_normalised.json` | Final comment records |

The final records are also written to `scripts/sources/facebook_posts.csv`
and `scripts/sources/facebook_comments.csv`.

Each normal run scrapes fresh data and overwrites the raw files.

## 9. Deduplication and Supabase Storage

Before synchronisation:

* Posts are deduplicated by `postId` when the scrape is collected.
* Comments are deduplicated by `commentId`, and comments whose parent post
  was not kept are dropped.

`facebook_pipeline.py` keeps only the table columns and upserts in batches
of 100:

```text
facebook_posts      on_conflict=post_id
facebook_comments   on_conflict=comment_id
```

Existing rows are updated rather than inserted as duplicates. Only the
English `text` is uploaded; `original_text` and `lang` are not columns in
`facebook_posts`.

After the upload, `run_cleaner()` runs `clean_social.py` to refresh
`clean_posts` and `clean_comments` for all platforms.

## 10. Running the Pipeline

Normal run:

```bash
python scripts/sources/facebook.py
```

Offline test against existing local caches, with no Apify, Google
Translation for uncached posts, or Supabase calls:

```bash
FACEBOOK_OFFLINE_TEST=1 python scripts/sources/facebook.py
```

Small paid test run: set `TEST_MODE = True` in `facebook.py`. It scrapes only
the pages in `TEST_SOURCE_POST_LIMITS` (Mongabay: 40, Greenpeace Southeast
Asia: 15), keeps posts from every date, prints sample kept and dropped posts
for the regional filter, skips comments and Supabase, and writes outputs
under `data/raw/test/`.

`UPLOAD_TO_SUPABASE = False` in `facebook.py` disables the upload for normal
runs.

## 11. Failure Behaviour

* A missing month in `monthly_topic_stats` stops the run before any Apify
  charges are incurred.
* A missing `APIFY_TOKEN` stops the run when a scrape is requested.
* An actor run that fails to start is skipped with a message.
* A failed translation batch keeps the original text for those posts.
* A Supabase sync failure is printed with its traceback; local JSON and CSV
  outputs have already been written by then.

## 12. Stopping a Run

Press `Ctrl+C` in the terminal to stop the local Python process. If an Apify
actor is already running remotely, abort that run in the Apify Console as
well to prevent it from continuing to consume credit.

Supabase synchronisation occurs after scraping and transformation complete.
A local interruption before that point prevents the current run's results
from being uploaded.
