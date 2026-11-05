# Reddit Data Collection and Supabase Storage

## Purpose

This document explains how the project collects Reddit posts and comments with
Apify and stores the cleaned results in Supabase.

The collector searches the previous calendar month's top-ranked monthly topic
keywords across the project's target countries. It runs one Apify actor run
per country to reduce timeout risk while retaining the complete month and
comment crawling. It keeps English posts and their comments, while comments
may remain in any language.

## Main Components

| Component | Responsibility |
| --- | --- |
| `scripts/sources/reddit_apify.py` | Loads monthly keywords, starts the Reddit Apify actor, transforms posts and comments, filters posts by language, and starts the Supabase sync. |
| `scripts/supabase/reddit_pipeline.py` | Reads credentials and monthly keywords, projects records, deduplicates upsert payloads, and updates Supabase in batches. |
| Supabase `monthly_topic_stats` | Provides the monthly topics, ranks, countries, and keywords used to build Reddit searches. |
| Supabase Reddit tables | `reddit_posts` stores posts and `reddit_comments` stores comments. |

No CSV files are read or written by the current Reddit collection path.

## Data Flow

```text
Run `scripts/sources/reddit_apify.py`
    |
    v
Read previous-month rows from `monthly_topic_stats`
    |
    v
Keep topics where `topic_rank <= 3`
    |
    v
Build one Reddit search URL per monthly keyword and country
    |
    v
Start one `harshmaur/reddit-scraper` Apify run per country
    |
    v
Apply the cumulative `$12` budget across country runs
    |
    v
Collect posts and comments in memory
    |
    v
Deduplicate posts and comments by their IDs
    |
    v
Keep English posts and comments belonging to those posts
    |
    v
Upsert directly into the existing Supabase Reddit tables
```

## 1. Credentials

The script loads the repository-root `.env` file with `python-dotenv`.

Required variables include:

```env
APIFY_TOKEN=...
SUPABASE_URL=...
SUPABASE_KEY=...
```

The token file must remain private and must not be committed to Git.

## 2. Monthly Keywords and Search Scope

`reddit_apify.py` calls `topic_keyword_groups()` from
`reddit_pipeline.py`. The function queries Supabase
`monthly_topic_stats` using:

```text
topic_rank <= 3
month = previous calendar month
```

The configured countries are Singapore, Malaysia, Indonesia, Philippines,
Thailand, and Brunei. Each returned keyword is combined with its country to
build a Reddit search URL.

For example, a keyword may produce a search query similar to:

```text
<monthly keyword> Singapore
```

Duplicate keywords are removed per country before the search URLs are created.

## 3. Apify Collection and Budget

The collector groups generated search URLs by country and starts one actor run
per country. It does not start a separate actor run for each keyword. The
configured `$12` budget is divided evenly across countries with keywords, so
the total budget remains capped at `$12`.

The run uses:

```python
APIFY_BUDGET_USD = Decimal("12")
max_total_charge_usd=APIFY_BUDGET_USD
```

The actor input enables:

* Previous-month post dates using `postedAfter` and `postedBefore`
* Comment crawling with `crawlCommentsPerPost`
* One community per search request

The script also validates each returned post and comment timestamp locally
before synchronization, so records outside the previous calendar month are
discarded even if the actor returns them. Existing rows in Supabase are not
deleted by an upsert.

Proxy configuration is intentionally omitted because the Reddit Scraper actor
handles its own connections and pricing. After each country run finishes, the
script refreshes the run from Apify and reports its final `usage_total_usd`.
Failed countries are reported while successful country results continue through
processing and synchronization.

The Apify account may still show other charges from previous runs, other
scripts, storage, or usage outside this run. The printed amounts are for the
current country runs and their cumulative total.

## 4. Post and Comment Transformation

The script converts actor records into the project's Reddit fields.

### Posts

Post records include:

* `post_id`
* `post_url`
* `created_at`
* `author_name`
* `title`
* `body`
* `community_name`
* `subreddit`
* `score`
* `upvote_ratio`
* `topic`
* `country`

### Comments

Comment records include:

* `comment_id`
* `comment_url`
* `comment_created_at`
* `author_name`
* `post_id`
* `post_title`
* `body`
* `subreddit_name`
* `parent_id`
* `score`
* `depth`
* `topic`
* `country`

The script supports both top-level comment records and nested comments returned
inside a post.

## 5. Language Filtering

Posts are filtered to English after extraction. Comments are not independently
filtered by language. Comments belonging to retained English posts are kept
regardless of the comment language.

The script first attempts to use `lingua`. If Windows blocks its native DLL, it
falls back to the installed pure-Python `langdetect` package and requires at
least `75%` English probability.

## 6. Deduplication and Supabase Storage

Deduplication happens before synchronization:

* Posts are deduplicated by `post_id`.
* Comments are deduplicated by `comment_id`.
* The shared batch upsert helper removes duplicate conflict keys from each
  payload before sending it to Supabase.

The data is sent directly to the existing Reddit Supabase tables using their
existing conflict keys. Re-running the collector does not create duplicate
rows when those IDs are constrained uniquely in Supabase.

## 7. Stopping a Run

Press `Ctrl+C` in the terminal to stop the local Python process. If the Apify
actor is already running remotely, terminate that actor run in the Apify
Console as well to prevent it from continuing to consume resources.

Supabase synchronization occurs after scraping and transformation complete. A
local interruption before that point may prevent the current run's results from
being uploaded.
