# Topic-Based Analysis

## Purpose

This document explains `scripts/communication_framework/topic_based_analysis.py`,
which compares high- and low-engagement posts for each country and topic and
asks Gemini what drives engagement. The result is short-form video guidance
written to the `topic_based_analysis` table and shown on the dashboard's
**Communication Framework** page.

`social_media_pipeline.py` runs it after sentiment analysis, as long as
environmental filtering succeeded, and regenerates the previous month's rows
(passing `--force`). The Data page's **Rerun topic-based analysis** button runs it alone for the previous month,
regenerating existing rows without collecting new data. Run it from the
command line to cover other months.

## Main Components

| Component | Responsibility |
| --- | --- |
| `topic_based_analysis.py` | Fetches environmental posts per country and topic, splits them by engagement, asks Gemini what drives engagement, and upserts the result to `topic_based_analysis` |
| Supabase tables | Reads `monthly_topic_stats` (top 3 topics per country) and `clean_posts`; writes `topic_based_analysis` |
| Dashboard | **Communication Framework** page reads `topic_based_analysis` |

## Data Flow

```text
monthly_topic_stats (top 3 topics per country, chosen month)
    |
    v
clean_posts (is_environmental, matched_keywords, posted_at in month)
    |
    v
top 25% vs bottom 25% by total_engagement
    |
    v
Gemini (JSON mode)
    |
    v
topic_based_analysis
```

## How it works

1. Reads the top three topics and their keywords for each country from
   `monthly_topic_stats` for the month.
2. Fetches `clean_posts` for the month where `is_environmental` is true,
   `matched_keywords` overlaps the topic keywords, and `inferred_country` is the
   country name or region code (for example `Singapore` or `SG`).
3. **Regional fallback.** If fewer than 20 posts (`MIN_POSTS`) are found, it
   fetches matching posts from all countries instead and tells Gemini to treat
   them as a regional proxy.
4. Sorts posts by `total_engagement` and takes the top 25% and bottom 25%. Each
   post is tagged with its platform.
5. Sends both groups to Gemini (`gemini-3.1-flash-lite`, JSON mode). The prompt
   asks for advice aimed at short-form vertical video (TikTok and Instagram
   Reels), written as concise, imperative points.
6. Gemini also lists which posts are genuinely about the environment. Only those
   posts are kept as example links: up to 5 top and 5 bottom
   (`TOP_POST_LINKS`, `BOTTOM_POST_LINKS`).
7. Upserts one row per topic and country.

## Output fields

| Column | Content |
| --- | --- |
| `month`, `country`, `topic_name`, `keywords` | What the row covers |
| `tone_and_emotion` | Tone, delivery and pacing on camera |
| `recommendations` | 2 to 3 specific tips for reach on TikTok and Reels |
| `key_message` | The one core message, short enough for a text overlay |
| `narrative_method` | On-camera storytelling approach |
| `content_type` | Short-form video format to produce |
| `story_structure` | Second-by-second beat outline |
| `hooks` | Opening 1 to 3 second hooks |
| `call_to_action` | CTAs suited to TikTok and Reels |
| `captions` | Caption and on-screen text guidance |
| `what_not_to_do` | Mistakes drawn from low-engagement posts |
| `top_post_links`, `bottom_post_links` | Example post URLs |
| `updated_at` | When the row was last written |

## Running

From the repository root:

```bash
# Previous month, skipping topics already analysed for that month
python scripts/communication_framework/topic_based_analysis.py

# A specific month (YYYY-MM-01 format)
python scripts/communication_framework/topic_based_analysis.py 2026-09-01

# Only some countries or topics (always re-run)
python scripts/communication_framework/topic_based_analysis.py 2026-09-01 --country Singapore Malaysia
python scripts/communication_framework/topic_based_analysis.py --topic "Climate Change"

# Re-run every topic for the month
python scripts/communication_framework/topic_based_analysis.py 2026-09-01 --force
```

## Rerun behaviour

- Rows are upserted on `(topic_name, country)`, **not** on month. A topic keeps
  one row, which is replaced by the most recent analysis. The dashboard shows
  that latest guidance when an earlier month is selected.
- A default run skips topics that already have an analysis for that month.
- Passing `--country`, `--topic` or `--force` re-runs the matching topics even
  if they already exist.
- A topic is skipped if it has no keywords, no matching posts, or too few posts
  to form both a top and bottom group.

## Error handling

- **Retries.** Gemini is retried up to 5 times (`GEMINI_RETRIES`) with
  exponential backoff on 503, 429, `UNAVAILABLE` and `RESOURCE_EXHAUSTED`
  errors. The response is also regenerated when Gemini returns malformed JSON.
- **Silent RLS blocks.** If Supabase row-level security blocks a write, the
  script prints `No rows written ... check RLS insert/update policies`. Use a
  server-side `SUPABASE_KEY`.
- **Credentials.** Needs `SUPABASE_URL`, `SUPABASE_KEY` and `GEMINI_API_KEY`
  (or `GOOGLE_API_KEY`) in the repository-root `.env`.

## Limitations

- Output is written by a language model and can be generic or wrong. Review it
  before acting on it.
- Uses posts only, not comments, and engagement is compared across platforms
  with different engagement norms.
- When the regional fallback is used, the guidance for a country is based
  mostly on other countries' posts.
- Gemini model availability and free-tier quota are not guaranteed, so a run
  may fail depending on when it is made.
