# Database

All EcoCupid data is stored in one Supabase (Postgres) project. The full schema
is in [`scripts/supabase/migrations/initial_schema.sql`](../scripts/supabase/migrations/initial_schema.sql).
It creates 20 tables and uses `IF NOT EXISTS` throughout, so it is safe to re-run.

## Creating the tables

1. Open the Supabase dashboard for the project.
2. Go to **SQL Editor** and create a new query.
3. Paste the contents of `initial_schema.sql` and click **Run**.

The Supabase CLI (`supabase db push`) only reads `supabase/migrations/` at the
repository root, using a timestamped file name. To use it, copy the file to
`supabase/migrations/<timestamp>_initial_schema.sql` first.

Notes on the schema:

- Tables are created parents first, so foreign keys resolve.
- Array columns are `text[]`.
- A unique index on `clean_comments.source_id` is included because
  `clean_social.py` upserts with `on_conflict=source_id`.
- Two older tables, `sentiment_analysis_1` and `sentiment_analysis_2`, are not
  used by any script and are not created.
- Row Level Security is **off**. An optional block at the end of the file turns
  it on for every public table. Use it only after confirming every `.env` uses
  a server-side key, because RLS blocks the publishable (anon) key.

## Tables by group

### News

| Table | Primary key | Written by | Purpose |
| --- | --- | --- | --- |
| `news_raw` | `news_id` (unique `url`) | `News_raw/*_news.py` | Scraped articles, with `cleaning_status` |
| `news_cleaned` | `article_id`, `country` | `News_cleaned.py` | Translated, cleaned and classified articles, with similarity scores |
| `topic_registry` | `topic_id` | `News_topic.py` | Reusable topics (name, keywords, centroid vector) |
| `news_topics` | `article_id`, `topic_id`, `country` | `News_topic.py` | The topic assigned to each article |
| `monthly_topic_stats` | `month`, `country`, `topic_id` | `News_topic.py` | Mentions per topic, country and month, with `topic_rank` and `monthly_keywords` |

`monthly_topic_stats` is the most important table. Every social collector reads
the previous month's top-ranked topics and keywords from it, and the dashboard
shows nothing until it has rows.

### Raw social data

One pair of tables per platform, written by the collectors through
`scripts/supabase/*_pipeline.py`.

| Platform | Posts | Comments or replies |
| --- | --- | --- |
| Facebook | `facebook_posts` | `facebook_comments` |
| Instagram | `instagram_posts` | `instagram_comments` (foreign key to posts) |
| Reddit | `reddit_posts` | `reddit_comments` (foreign key to posts) |
| X | `x_posts` | `x_replies` |
| YouTube | `youtube_videos` | `youtube_comments` (foreign key to videos) |

Each platform keeps its own columns, because the platforms expose different
fields. See the platform documents for details.

### Shared clean data

| Table | Primary key | Written by | Purpose |
| --- | --- | --- | --- |
| `clean_posts` | `id` (unique `source_id`) | `clean_social.py`, `filter_environmental.py` | All platforms in one shape, with `is_environmental` |
| `clean_comments` | `id` (unique `source_id`) | `clean_social.py` | All comments in one shape |

`source_id` has the form `platform:type:original_id`, for example
`facebook:post:12345`. `clean_comments` has no `is_environmental` column. A
comment is treated as environmental when its parent post is. See
[SOCIAL_CLEANING_AND_FILTERING.md](SOCIAL_CLEANING_AND_FILTERING.md).

### Results

| Table | Primary key | Written by | Purpose |
| --- | --- | --- | --- |
| `sentiment_analysis` | `country`, `topic`, `month`, `year` | `sentiment_analysis.py` | Emotion counts per country, topic and month (27 emotions plus neutral) |
| `summary` | `topic_name`, `country`, `month` | `posts_comments_summary.py` | AI-written discussion summaries |
| `topic_based_analysis` | `topic_name`, `country` | `topic_based_analysis.py` | AI-written messaging guidance |

**`topic_based_analysis` keeps one row per topic and country.** Its key has no
month, so when the same topic recurs in a later month, the new analysis
replaces the old one and the row's `month` is updated. Earlier months' guidance
is not kept.

## Relationships

```text
news_raw ──< news_cleaned
news_raw ──< news_topics >── topic_registry ──< monthly_topic_stats
instagram_posts ──< instagram_comments
reddit_posts    ──< reddit_comments
youtube_videos  ──< youtube_comments
```

Facebook, X and the clean tables link posts and comments by ID columns
(`parent_post_id`, `parent_source_id`, `conversation_id`) without foreign keys.

## Which parts read which tables

| Component | Reads |
| --- | --- |
| Social collectors | `monthly_topic_stats` (and their own raw tables, to avoid duplicates) |
| `clean_social.py` | All raw social tables, existing clean tables |
| `filter_environmental.py` | `clean_posts` |
| `sentiment_analysis.py` | `clean_posts`, `clean_comments`, `monthly_topic_stats` |
| `posts_comments_summary.py` | Clean tables, `monthly_topic_stats` |
| `topic_based_analysis.py` | `clean_posts`, `monthly_topic_stats` |
| Dashboard | `monthly_topic_stats`, `news_cleaned`, `clean_posts`, `clean_comments`, `topic_registry`, `sentiment_analysis`, `summary`, `topic_based_analysis`, and the raw tables (Data page) |

## Keys and access

Scripts that write data need a server-side key (secret or service-role). The
environmental filter refuses to run with a publishable or anon key. See the
Configuration section of the main README for the variable names.
