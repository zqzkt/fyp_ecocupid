# X Data Collection and Supabase Storage

## Purpose

This document explains how the project collects public X data for later sentiment analysis and stores it in Supabase.

The collector focuses on English-language public discussion related to (TEMPORARY):

- Climate change
- Sustainability
- Renewable energy
- Plastic pollution

The geographic scope is limited to six primary ASEAN countries:

1. Singapore
2. Malaysia
3. Indonesia
4. Philippines
5. Brunei
6. Thailand

The collection is designed to run once per day without keeping a local `data/` folder.

## Main Components

| Component | Responsibility |
| --- | --- |
| `scripts/sources/twitter.py` | Calls the X API, transforms posts/users/replies, estimates cost, and starts the Supabase upload. |
| `supabase/twitter_pipeline.py` | Reads Supabase credentials, finds the latest stored post, normalizes rows, and upserts batches. |
| `supabase/__init__.py` | Makes the local Supabase integration importable as a Python package. |
| Supabase tables | Permanently store users, posts, and replies. |

## Daily Data Flow

```text
Scheduled job
    |
    v
Read latest post ID from Supabase
    |
    v
Call X Recent Search with since_id
    |
    v
Collect up to the configured number of new posts
    |
    v
Select high-discussion conversations
    |
    v
Fetch a small sample of replies
    |
    v
Collect author expansions for posts and replies
    |
    v
Normalize rows in memory
    |
    v
Upsert users, posts, and replies into Supabase
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

The collector sends one keyword search query to the X Recent Search endpoint:

```text
("climate change" OR sustainability OR "renewable energy" OR "plastic pollution")
lang:en -is:retweet
(Singapore OR Malaysia OR Indonesia OR Philippines OR Thailand OR Brunei OR "Brunei Darussalam")
```

Important query behavior:

- `lang:en` keeps the sample focused on English posts.
- `-is:retweet` excludes retweets.
- The country terms are combined into one query, so the country scope does not require six separate searches.
- Country labels are inferred from author location, post text, or supported place-country values. A post can remain `unspecified` when there is not enough evidence.

## 3. Supabase Checkpointing

Before a normal collection, the script calls the Supabase REST API for the newest stored post:

```text
GET /rest/v1/x_posts
    ?select=post_id,created_at
    &order=created_at.desc
    &limit=1
```

The returned `post_id` becomes the X API `since_id` value.

This means a normal daily run asks for posts newer than the latest post already stored in Supabase. It avoids repeatedly requesting the same recent posts and reduces unnecessary billed reads.

### First run

If `x_posts` is empty, there is no checkpoint. The script searches the available recent-post window and stores the results.

### Later runs

If Supabase already contains posts, the script uses the newest stored post as the checkpoint:

```text
X API query + since_id=<latest Supabase post ID>
```

If no new posts match, the script uploads zero new rows and exits normally.

### Forced run

Passing `--force` ignores the checkpoint and searches recent posts again:

```bash
python scripts/sources/twitter.py --force
```

This is useful for recovery or backfilling, but it can cause repeated API reads. Supabase IDs prevent duplicate rows, but the repeated API request may still cost money.

## 4. Default Collection Size

The default settings are intentionally moderate:

| Setting | Default |
| --- | ---: |
| New seed posts | 20 |
| Reply conversations | 2 |
| Replies per conversation | 5 |
| Maximum seed posts hard cap | 50 |
| User expansions | Enabled |
| Reply collection | Enabled |
| Default estimated spend limit | `$0.50` |

The reply conversations are selected from seed posts with the highest reply counts, using engagement as a tie-breaker. This prioritizes conversations likely to provide more sentiment-rich discussion.

## 5. Cost Control

The script estimates cost before calling the X API.

Approximate configured rates:

- Post read: `$0.005`
- User read: `$0.010`
- Media reads: not requested by the current collector

The estimate is conservative:

```text
post reads = seed posts + reply budget
user reads = post reads, when user expansions are enabled
estimated cost = post reads * $0.005 + user reads * $0.010
```

With the defaults:

```text
20 seed posts + (2 conversations * 5 replies) = 30 post reads
30 post reads + 30 user reads
(30 * $0.005) + (30 * $0.010) = $0.45
```

The script refuses to call the API if the estimate exceeds `--max-spend`.

Example dry run:

```bash
python scripts/sources/twitter.py --dry-run
```

The dry run prints the estimated maximum cost and makes no API request.

## 6. User Collection

User expansions are enabled by default through:

```text
expansions=author_id
user.fields=id,username,name,description,location,created_at,public_metrics
```

For each included user, the collector stores:

- X author ID
- Username
- Display name
- Description
- Location
- Account creation time
- Followers
- Following count
- Tweet count
- List count
- Inferred country
- Collection timestamp

Users from both seed posts and replies are included. The in-memory user dictionary is keyed by `author_id`, so the same author is only prepared once per run.

## 7. Reply Collection

Reply collection is a separate search for selected conversations. For each selected seed post, the collector builds a query like:

```text
conversation_id:<conversation ID> is:reply lang:en
```

The collector then:

1. Selects posts with a non-zero reply count.
2. Sorts them by reply count and total engagement.
3. Selects the top configured number of conversations.
4. Fetches up to the configured reply limit for each conversation.
5. Links each reply to its source post and parent tweet when available.
6. Collects author expansions for reply authors.

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

## 9. Supabase Storage

The direct collection path uploads three types of rows:

| Supabase table | Primary identifier | Contents |
| --- | --- | --- |
| `x_users` | `author_id` | Author profiles and public metrics |
| `x_posts` | `post_id` | Seed posts returned by the topic/country query |
| `x_replies` | `reply_id` | Replies sampled from selected conversations |

Rows are normalized to the table column lists before upload. Missing optional fields are sent as `null`; missing `media_types` values are sent as an empty array where required by the schema.

Uploads are sent in batches of 100 rows. This avoids sending one large request and gives progress output during collection.

## 10. Repeated Data and Deduplication

Repeated data can occur when:

- A forced run ignores the checkpoint.
- The X API returns overlapping results.
- A reply appears in more than one fetched conversation result.
- A scheduled job is retried after a partial failure.

The system handles this at two levels:

### In-memory deduplication

During a run:

- Seed posts are deduplicated by `post_id`.
- Reply IDs already seen in the seed set or earlier reply results are skipped.
- Included users are stored in dictionaries keyed by `author_id`.

### Supabase upserts

The Supabase REST requests use conflict resolution:

```text
resolution=merge-duplicates
```

The conflict identifiers are:

- `x_users.author_id`
- `x_posts.post_id`
- `x_replies.reply_id`

Therefore, rerunning the same collection updates the existing row instead of creating a second copy.

Deduplication prevents duplicate storage, but it does not make repeated X API reads free. Avoid `--force` unless it is necessary.

## 11. Normal Daily Command

Run the collector without `--force`:

```bash
python scripts/sources/twitter.py
```

This performs the following sequence:

1. Estimate the maximum cost.
2. Read the latest post checkpoint from Supabase.
3. Search only for newer posts.
4. Fetch the configured reply sample.
5. Collect user expansions.
6. Upsert users, posts, and replies into Supabase.
7. Exit without creating local data files.

This command is suitable for a daily scheduler such as `cron`, GitHub Actions, or another job runner.

## 12. Useful Commands

Preview cost without calling the API:

```bash
python scripts/sources/twitter.py --dry-run
```

Run a fresh search while ignoring the checkpoint:

```bash
python scripts/sources/twitter.py --force
```

Collect more posts for a one-off run, subject to the spend limit:

```bash
python scripts/sources/twitter.py --max-posts 40 --max-spend 1.00
```

Collect without replies or users for troubleshooting:

```bash
python scripts/sources/twitter.py --no-replies --no-users
```

## 13. Failure Behavior

The collector stops without retrying when X returns:

- `429`: rate limited
- `401`: invalid or unauthorized bearer token
- `402`: credits depleted
- `403`: forbidden request

This avoids automatic retries that could create unexpected billed reads.

Supabase upload failures also stop the job. The data remains in Supabase for batches that completed before the failure, and rerunning the normal command is safe because IDs are upsert keys.

## 14. Analysis Considerations

The stored sample is suitable for later sentiment analysis, but the following limitations should be considered:

- X Recent Search only covers the API's available recent-search window.
- The daily sample is capped and is not a complete census of all public discussion.
- English filtering excludes discussion in other languages.
- Country inference is heuristic and can be `unspecified`.
- Reply sampling favors conversations with higher reply counts, which may introduce selection bias.
- User expansion data describes public profile fields at collection time and may change later.
- Engagement counts are snapshots and can change after collection.

For more accurate findings, report the collection window, sample sizes, country coverage, number of unspecified records, and reply-selection method alongside sentiment results.

## 15. Current Architecture Summary

The permanent source of truth is Supabase. The daily job does not need the removed `data/` folder, JSON files, or JSONL files.

The key design choices are:

- Supabase stores all collected records.
- Supabase `x_posts` provides the daily checkpoint.
- X `since_id` reduces overlap between daily searches.
- Primary-key upserts make retries safe.
- Cost checks happen before API calls.
- Replies and users are collected in intentionally small, configurable samples.
