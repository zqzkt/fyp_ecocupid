# Instagram Data Collection and Supabase Storage

## Purpose

This document explains how the project collects Instagram posts and sampled
comments with Apify and stores the cleaned results in Supabase.

The collector uses the previous calendar month's top-ranked monthly topic
keywords, converts each keyword and country into a hashtag, and requests posts
from the previous month. Only posts with English captions are retained.
Comments belonging to retained posts are kept regardless of comment language.

## Main Components

| Component | Responsibility |
| --- | --- |
| `scripts/sources/instagram_apify.py` | Loads monthly keyword specifications, starts the Instagram Apify actor, filters and transforms posts/comments, and starts the Supabase sync. |
| `scripts/supabase/instagram_pipeline.py` | Reads monthly keywords and credentials, projects records, and updates the existing Instagram Supabase tables. |
| Supabase `monthly_topic_stats` | Provides the monthly topics, ranks, countries, and keywords. |
| Supabase Instagram tables | `instagram_posts` stores posts and `instagram_comments` stores comments. |

No CSV files are read or written by the current Instagram collection path.

## Data Flow

```text
Run `scripts/sources/instagram_apify.py`
    |
    v
Read previous-month rows from `monthly_topic_stats`
    |
    v
Keep topics where `topic_rank <= 3`
    |
    v
Convert monthly keywords and countries into unique hashtags
    |
    v
Start one `khadinakbar/instagram-hashtag-scraper` Apify run
    |
    v
Apply one cumulative `$12` run budget
    |
    v
Collect posts and comments in memory
    |
    v
Keep posts from the exact previous calendar month
    |
    v
Keep English-caption posts and their comments
    |
    v
Deduplicate by post/comment IDs
    |
    v
Upsert directly into existing `instagram_posts` and `instagram_comments`
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

## 2. Monthly Keywords and Hashtags

`instagram_apify.py` calls `monthly_keyword_specs()` from
`instagram_pipeline.py`. The function queries Supabase
`monthly_topic_stats` using:

```text
topic_rank <= 3
month = previous calendar month
```

Each keyword is combined with its country and normalized into a hashtag. For
Singapore, the country suffix is normalized to `sg`; other countries use their
country name. Duplicate hashtags are removed before the Apify run starts.

The topic and country associated with each hashtag are attached to returned
dataset items using the actor's returned `hashtag` field.

## 3. Apify Collection and Budget

All generated hashtags are sent in one actor run. The script does not start a
separate actor run for each hashtag.

The run uses:

```python
APIFY_BUDGET_USD = Decimal("12")
max_total_charge_usd=APIFY_BUDGET_USD
```

The actor input enables:

* `datePosted: "last-month"`
* Comment collection with `includeComments: True`
* Full output mode
* No `minimumLikes` filter, so posts are collected regardless of like count

After the run finishes, the script refreshes the run from Apify and reports its
final `usage_total_usd`. The single run-level charge cap is the authoritative
budget for the complete Instagram scrape.

The Apify account may still show other charges from previous runs, other
scripts, storage, or usage outside this run. The printed amount is for the
current actor run.

## 4. Date Filtering

The script calculates:

* `MONTH_START`: the first day of the previous calendar month
* `CURRENT_MONTH_START`: the first day of the current month

For example, when run on 22 October, the exact local filter keeps posts from:

```text
1 September 00:00 UTC through 30 September 23:59:59 UTC
```

The actor's `datePosted: "last-month"` filter is followed by an explicit local
`posted_at` filter, so only posts from the exact previous calendar month are
passed to later processing.

Comments are collected from those retained posts. Their own language is not
filtered, and their own timestamps are not used to exclude them.

## 5. Language Filtering

Posts are retained only when their captions are detected as English.

The script first attempts to use `lingua`. If Windows blocks its native DLL, it
falls back to the installed pure-Python `langdetect` package and requires at
least `75%` English probability.

Comments are not independently filtered by language. A non-English comment is
kept when it belongs to a retained English-caption post.

## 6. Data Transformation

### Posts

Instagram post records include:

* `topic`
* `country`
* `hashtag`
* `post_id`
* `post_url`
* `caption`
* `posted_at`
* Author information
* Like, comment, engagement, and play counts
* `media_type`
* `is_reel`

### Comments

Instagram comment records include:

* `topic`
* `country`
* `hashtag`
* `post_id`
* `post_url`
* `post_author_username`
* `comment_id`
* `comment_text`
* `comment_username`
* `comment_created_at`
* `comment_like_count`

## 7. Deduplication and Supabase Storage

Before synchronization:

* Posts are deduplicated by `post_id`.
* Comments are deduplicated by `comment_id`.
* The shared batch upsert helper removes duplicate conflict keys from each
  payload before sending it to Supabase.

The existing tables are updated directly:

```text
instagram_posts      on_conflict=post_id
instagram_comments   on_conflict=comment_id
```

Existing rows are updated rather than inserted as duplicates when
`post_id` and `comment_id` are unique or primary-key constrained in Supabase.
No new Instagram tables are created by the scraper.

## 8. Stopping a Run

Press `Ctrl+C` in the terminal to stop the local Python process. If the Apify
actor is already running remotely, terminate that actor run in the Apify
Console as well to prevent it from continuing to consume resources.

Supabase synchronization occurs after scraping and transformation complete. A
local interruption before that point may prevent the current run's results from
being uploaded.
