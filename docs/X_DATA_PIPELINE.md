# X Data Collection and Supabase Storage

## Purpose

This document explains how the project collects public X data and stores it in Supabase for analysis.

The collector uses monthly topic keywords from `monthly_topic_stats`. Replies
are collected in all languages; non-English comments are translated during
cleaning before they reach sentiment analysis.

The geographic scope is limited to six primary ASEAN countries:

1. Singapore
2. Malaysia
3. Indonesia
4. Philippines
5. Brunei
6. Thailand

Every collection run searches the previous calendar month with X full-archive
search and does not keep a local `data/` folder.

## Main Components

| Component | Responsibility |
| --- | --- |
| `scripts/sources/twitter.py` | Calls the X API, transforms posts/users/replies, estimates cost, and starts the Supabase upload. |
| `scripts/supabase/twitter_pipeline.py` | Reads Supabase credentials, provides monthly scheduling, normalizes rows, and upserts batches. |
| `scripts/supabase/__init__.py` | Makes the local Supabase integration importable as a Python package. |
| Supabase tables | Permanently store posts and replies. |

## Data Flow

```text
Call the X endpoint
    |
    v
Fetch posts and replies
    |
    v
Upsert raw posts in x_posts and raw replies in x_replies
    |
    v
Clean posts and comments into clean_posts and clean_comments
    |
    v
Translate non-English comments during cleaning
    |
    v
Classify unlabelled clean_posts as environmental
    |
    v
Derive sentiment_analysis
```

No permanent JSON or JSONL files are created by the current collection path.

## 1. Credentials

The script loads credentials from the repository `.env` file using `python-dotenv`:

```env
SUPABASE_URL=...
SUPABASE_KEY=...
TWITTER_BEARER_TOKEN=...
```

The token file must remain private and must not be committed to Git. The collector stops before making an API call if the X token is missing. The Supabase client similarly stops if the Supabase URL or key is missing.

## 2. Search Query

The collector reads `country`, `topic_name`, `topic_rank`, and `monthly_keywords`
from Supabase `monthly_topic_stats`. It keeps rows where `topic_rank <= 3`,
extracts the comma-separated `monthly_keywords`, and deduplicates them by
country. It then sends one country-specific query per country with data:

```text
(<country keyword 1> OR <country keyword 2> OR ...)
lang:en -is:retweet ("<country>")
```

Important query behavior:

- `lang:en` keeps the sample focused on English posts.
- `-is:retweet` excludes retweets.
- Each country query contains only that country's top-three topic rows, preventing the X 512-character query limit from truncating the vocabulary.
- The post cap is divided across countries so the first country cannot consume the entire sample.
- The query is no longer hardcoded to a fixed environmental keyword list.
- Country labels are inferred from author location, post text, or supported place-country values. A post can remain `unspecified` when there is not enough evidence.

## 3. Collection Date Window

Every collector run uses X full-archive search for the previous calendar
month. The start is inclusive and the end is exclusive, both in UTC. For
example, a run on 5 November searches from 1 October 00:00 UTC up to (but not
including) 1 November 00:00 UTC, covering all of October. The matching
`monthly_topic_stats` month defaults to that same previous month.

The collector does not use a Supabase `since_id` checkpoint, because a
checkpoint from the current month could exclude posts from the prior month.
Existing post and reply IDs still prevent duplicate rows in Supabase.

## 4. Default Collection Size

The defaults collect a broader sample while keeping the estimated maximum below the spend cap:

| Setting | Default |
| --- | ---: |
| New seed posts | 150 |
| Reply conversations | 15 |
| Replies per conversation | 20 |
| Maximum seed posts hard cap | 250 |
| User expansions | Disabled; `x_users` is not written |
| Reply collection | Enabled |
| Default estimated spend limit | `$5.00` |

The reply conversations are selected from seed posts with the highest reply counts, using engagement as a tie-breaker. This prioritizes active discussions.

## 5. Cost Control

The script estimates cost before calling the X API.

Approximate configured rates:

- Post read: `$0.005`
- User read: not used by the default collector
- Media reads: not requested by the current collector

The estimate is conservative:

```text
post reads = seed posts + reply budget
detail reads = one individual lookup per post for missing impressions
estimated cost = post reads * $0.005 + detail reads * $0.005
```

With the defaults:

```text
150 seed posts + (15 conversations * 20 replies) = 450 post reads
450 post reads + 450 detail reads
(450 * $0.005) + (450 * $0.005) = $4.50
```

The script refuses to call the API if the estimate exceeds `--max-spend`.

Example dry run:

```bash
python scripts/sources/twitter.py --dry-run
```

The dry run prints the estimated maximum cost and makes no API request.

## 6. User Collection

User expansions are disabled. The collector does not request author profiles and
does not write to `x_users`. Country inference uses post text and country data
directly available in the post response. The existing `--with-users` option is
kept only for compatibility and should not be used because user rows are still
ignored by the Supabase sync.

## 7. Reply Collection

Reply collection is a separate search for selected conversations. For each selected seed post, the collector builds a query like:

```text
conversation_id:<conversation ID> is:reply
```

The collector then:

1. Selects posts with a non-zero reply count.
2. Sorts them by reply count and total engagement.
3. Selects the top configured number of conversations.
4. Fetches up to the configured reply limit for each conversation.
5. Links each reply to its source post and parent tweet when available.
6. Stores reply authors only as `author_id` values on reply rows.

The current reply sample is deliberately limited because each reply search consumes additional reads.

## 8. Data Transformation

The collector converts X API responses into analysis-friendly records.

### Posts

Posts include fields such as:

- `post_id`
- `author_id`
- `conversation_id`
- `text`
- `lang`
- `created_at`
- Like, reply, repost, and quote counts
- `impression_count`: impressions reported by Twitter/X in `public_metrics`
- `matched_keywords`: environmental query phrases found in the post text
- Hashtags, mentions, and URLs
- Media keys
- Referenced tweets
- Parent tweet ID
- Inferred country
- Whether the row is a reply
- Total engagement
- Discussion ratio
- Amplification ratio
- Original query
- Collection timestamp

`total_engagement` is calculated as:

```text
likes + replies + reposts + quotes
```

`discussion_ratio` is calculated as:

```text
replies / likes
```

It is `null` when the post has zero likes.

`amplification_ratio` is calculated as:

```text
(reposts + quotes) / total engagement
```

It is `null` when total engagement is zero.

### Replies

Replies include:

- `reply_id`
- Source `post_id`
- `parent_tweet_id`
- `conversation_id`
- `author_id`
- Text and language
- Created time
- Engagement counts
- Hashtags, mentions, and URLs
- Inferred country
- Collection timestamp

Replies are stored in `x_replies`, not mixed into the normal `x_posts` table.
The reply search does not filter by language so the cleaner can translate
non-English comments before writing `clean_comments`.

### Analysis columns

The `x_posts` table includes these analysis-oriented columns:

| Column | Type | Meaning |
| --- | --- | --- |
| `impression_count` | `bigint` | Twitter/X's public impression count for the post, when returned by the API. |
| `matched_keywords` | `text[]` | The environmental query phrases matched in the post text. |

Country terms are not placed in `matched_keywords`; country classification is stored separately in `inferred_country`.

Before collecting new data, run [supabase/migrations/003_add_x_post_analysis_columns.sql](../supabase/migrations/003_add_x_post_analysis_columns.sql) once in the Supabase SQL Editor. The migration is idempotent and will not recreate columns that already exist.

## 9. Supabase Storage

The direct collection path uploads three types of rows:

| Supabase table | Primary identifier | Contents |
| --- | --- | --- |
| `x_posts` | `post_id` | Seed posts returned by the topic/country query |
| `x_replies` | `reply_id` | Replies sampled from selected conversations |

Rows are normalized to the table column lists before upload. Missing optional fields are sent as `null`; missing `media_types` values are sent as an empty array where required by the schema.

Uploads are sent in batches of 100 rows. This avoids sending one large request and gives progress output during collection.

## 10. Repeated Data and Deduplication

Repeated data can occur when:

- The same month's collection is rerun.
- The X API returns overlapping results.
- A reply appears in more than one fetched conversation result.
- A scheduled job is retried after a partial failure.

The system handles this at two levels:

### In-memory deduplication

During a run:

- Seed posts are deduplicated by `post_id`.
- Reply IDs already seen in the seed set or earlier reply results are skipped.
- User profiles are not collected or stored by the current pipeline.

### Supabase upserts

The Supabase REST requests use conflict resolution:

```text
resolution=merge-duplicates
```

The conflict identifiers are:

- `x_posts.post_id`
- `x_replies.reply_id`

Therefore, rerunning the same collection updates the existing row instead of creating a second copy.

Deduplication prevents duplicate storage, but it does not make repeated X API reads free.

## 11. Normal Collection Command

Run the collector:

```bash
python scripts/sources/twitter.py
```

This collects data from the previous calendar month and performs the following
sequence:

1. Estimate the maximum cost.
2. Search the previous month using X full-archive search and that month's
   topic keywords.
3. Fetch the configured reply sample.
4. Upsert posts and replies into Supabase.
5. Exit without creating local data files.

To force a fresh endpoint call from the pipeline entry point and then run the
full raw → clean → environmental classification → sentiment flow, run:

```bash
python scripts/supabase/twitter_pipeline.py
```

The pipeline entry point runs the collector for the previous month, upserts raw
records to `x_posts` and `x_replies`, runs the cleaner, and then derives
environmental labels and `sentiment_analysis`. The collector's configured
spend cap still applies.

## 12. Scheduled Monthly Job

The scheduler-oriented monthly command is available on the first day of each
month:

```bash
python scripts/supabase/twitter_pipeline.py --monthly
```

It uses the same previous-month collection window as a normal collector run,
and additionally:

1. Checks that today is the first day of the month.
2. Collects up to 200 seed posts.
3. Samples up to 10 replies from each of the top 5 conversations.
4. Fetches missing impression counts through individual tweet lookups.
5. Uploads users, posts, and replies directly to Supabase.
6. After collection, the pipeline wrapper runs
   `scripts/cleaning/clean_social.py` to add only
   source rows not already present in `clean_posts` or `clean_comments`,
   translating new non-English comments, then runs
   `scripts/cleaning/filter_environmental.py` to classify clean posts.
7. It runs `scripts/sentiment/sentiment_analysis.py --all` to derive
    `sentiment_analysis` from the refreshed clean tables.

For a full multi-platform collection, use `python scripts/social_media_pipeline.py`.
It waits until all five platform collectors finish successfully before running
the shared cleaner, environmental classifier, and sentiment step. Platform
collector scripts by themselves only collect and upload raw platform rows.

The monthly run has a `$5.00` maximum estimate. With user expansions disabled, its configured maximum is 250 post/detail reads, costing `$2.50` at the current rates. This is a large bounded monthly sample, not an unlimited export: obtaining every post from a busy month would require a larger budget and may require X full-archive access.

## Emotion model

The multilabel classifier is trained on the official GoEmotions train split and
uses its dev split to tune per-label thresholds. It predicts the 27 GoEmotions
emotions plus `neutral`; each post or comment may receive multiple non-neutral
emotions, while `neutral` is exclusive. `sentiment_analysis.dominant_emotions`
stores up to three emotion labels ranked by count (ties are alphabetical). Run
training and apply the count-column migrations before deriving aggregates:

```bash
python scripts/sentiment/train_emotion_model.py
```

Apply `scripts/supabase/migrations/005_goemotions_multilabel_counts.sql` and
`scripts/supabase/migrations/006_top_three_dominant_emotions.sql` in the Supabase
SQL Editor. Emotion count columns can sum to more than `total_items` because a
text can receive multiple emotion labels. The official data source and paper
are documented in `scripts/sentiment/dataset/goemotions/README.md`.

On any day other than the first, the job exits without calling X:

```text
Monthly job skipped: it only runs on the first day of the month.
```

For a deliberate one-off run outside the first day, use the explicit override:

```bash
python scripts/supabase/twitter_pipeline.py --monthly --run-now
```

X full-archive access is required for collection. If the account does not have
that access, X may return `403`.

The monthly command is run manually; no automatic scheduler is included.

## 13. Useful Commands

Preview cost without calling the API:

```bash
python scripts/sources/twitter.py --dry-run
```

Run collection for the previous month (the default behavior):

```bash
python scripts/sources/twitter.py
```

The default run requests up to 150 posts and samples up to 20 replies
from each of the 15 highest-reply conversations. Its estimated maximum is
`$4.50`, under the default `$5.00` spend cap.

Override these limits for a one-off run, subject to the spend limit:

```bash
python scripts/sources/twitter.py --max-posts 150 --max-reply-conversations 15 --max-replies-per-post 20 --max-spend 5.00
```

Collect without replies or users for troubleshooting:

```bash
python scripts/sources/twitter.py --no-replies --no-users
```

## 14. Failure Behavior

The collector stops without retrying when X returns:

- `429`: rate limited
- `401`: invalid or unauthorized bearer token
- `402`: credits depleted
- `403`: forbidden request

This avoids automatic retries that could create unexpected billed reads.

Supabase upload failures also stop the job. The data remains in Supabase for batches that completed before the failure, and rerunning the normal command is safe because IDs are upsert keys.

## 15. Analysis Considerations

The stored sample has the following limitations for downstream analysis:

- The monthly sample is capped and is not a complete census of all public discussion.
- Replies are sampled, not exhaustive; non-English replies are translated
  during cleaning.
- Country inference is heuristic and can be `unspecified`.
- Reply sampling favors conversations with higher reply counts, which may introduce selection bias.
- User expansion data describes public profile fields at collection time and may change later.
- Engagement counts are snapshots and can change after collection.

Report the collection window, sample sizes, country coverage, number of unspecified records, and reply-selection method alongside analysis results.

## 16. Current Architecture Summary

The permanent source of truth is Supabase. The collection job does not need the
removed `data/` folder, JSON files, or JSONL files.

The key design choices are:

- Supabase stores all collected records.
- Every run is bounded to the previous calendar month.
- Full-archive search retrieves the requested historical month.
- Primary-key upserts make retries safe.
- Cost checks happen before API calls.
- Replies and users are collected in intentionally small, configurable samples.

## 17. Cross-Platform Cleaning

Raw data remains in the platform-specific tables, while cross-platform analysis
uses two shared tables:

- `clean_posts`: original posts/videos from X, Reddit, YouTube, or Instagram.
- `clean_comments`: replies/comments from X, Reddit, YouTube, or Instagram.

The cleaning script is [scripts/cleaning/clean_social.py](../scripts/cleaning/clean_social.py).
It reads `x_posts`, `x_replies`, `reddit_posts`, `reddit_comments`,
`youtube_videos`, `youtube_comments`, `instagram_posts`, and
`instagram_comments`, then upserts normalized rows into the shared clean tables.
Sources are safely ignored when their raw tables are empty.

### Fields kept

The shared schema keeps fields needed for analysis and reproducibility:

| Field | Purpose |
| `source_id`, `platform`, `source_type`, `source_table` | Trace each clean record back to its source without mixing platforms. |
| `original_text`, `cleaned_text` | Preserve auditability while giving NLP a normalized input. |
| `lang` | Source language and translation audit. |
| `inferred_country` | ASEAN comparison. |
| `author_id` | Anonymous author-level grouping without storing profiles. |
| `conversation_id`, `parent_source_id` | Reconstruct discussion structure. |
| `posted_at` | Source timestamp for the post or comment. |
| `parent_posted_at` | For comments, the linked post's source timestamp; use this when assigning comments to a topic's sentiment month. |
| `matched_keywords` | Topic-level analysis. |
| Engagement counts and `impression_count` | Engagement and reach analysis. |
| `cleaned_at` | Track the cleaning version/time. |

The clean tables store timestamps rather than separate `year` and `month`
columns. Run `scripts/supabase/migrations/007_clean_social_year_month.sql`
before refreshing the clean tables. For sentiment aggregation, retain
`month` and `year` on the aggregate table, and group each linked comment using
its parent's `parent_posted_at` and inherited topic keywords. This attributes
the comment to the month its post was published while preserving the comment's
own timestamp in `posted_at`.

### Text cleaning rules

For every post and comment:

1. Remove `@mentions`.
Emoji conversion uses the attached `emoji` package's `demojize` function with
square-bracket delimiters, so compound emoji, skin-tone variants, flags, and
newer emoji are handled consistently. The dependency is declared in
`requirements.txt`.
2. Replace emoji with square-bracket labels such as `[happy]`, `[sad]`, or `[seedling]`.
3. Normalize repeated whitespace.
4. Keep the original text separately; never overwrite raw data.

Apply the schema once in the Supabase SQL Editor:

```sql
-- Run scripts/supabase/migrations/004_create_clean_social_tables.sql
```

Then run the cleaner from the repository root:

```bash
python scripts/cleaning/clean_social.py
```

For comments with a known non-English language, the cleaner uses Google Cloud
Translation to translate the text to English. When a comment has no language
metadata, Cloud Translation detects its language during translation. Configure
Google Application Default Credentials (ADC) for a project with the Cloud
Translation API enabled before running the cleaner. You do not need to set
`GOOGLE_APPLICATION_CREDENTIALS` or `GOOGLE_TRANSLATE_API_KEY`. For local
development, authenticate with:

```bash
gcloud auth application-default login
```

In deployed environments, use the platform's standard Google Cloud identity.
That identity must be authorized to use Cloud Translation. If translation
fails after the client is initialized, the cleaner preserves the original
comment text.

The cleaner is incremental by default: it checks candidate `source_id` values
against the clean tables and processes only missing rows. Existing clean rows
are not reprocessed on each collection. Use `--full-refresh` only when an
intentional complete rebuild is required:

```bash
python scripts/cleaning/clean_social.py --full-refresh
```

The clean-table migration must be applied before running the cleaner.

The end-to-end social-media pipeline runs the cleaner once after all five raw
platform collectors succeed. It inserts only raw rows whose normalized IDs
are not already present in the clean tables.

Emoji conversion uses the attached `emoji` package's `demojize` function with
square-bracket delimiters, so compound emoji, skin-tone variants, flags, and
newer emoji are handled consistently. The dependency is declared in
`requirements.txt`.
