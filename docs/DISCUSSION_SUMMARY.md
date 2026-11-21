# Discussion Summaries

## Purpose

This document explains `scripts/sentiment/posts_comments_summary.py`, which
summarises what people are saying about each country and topic each month. The
result is written to the `summary` table and shown on the dashboard's
**Sentiment Analysis** page.

`social_media_pipeline.py` runs it after sentiment analysis, as long as
environmental filtering succeeded, and regenerates the previous month's rows
(passing `--months <previous month>`). The Data page's **Rerun discussion summaries** button runs it alone for the previous month,
regenerating existing rows without collecting new data. Run it from the
command line to cover other months.

## Main Components

| Component | Responsibility |
| --- | --- |
| `posts_comments_summary.py` | Fetches environmental posts and comments per country and topic, asks Gemini for up to three summary points, and upserts the result to `summary` |
| `sentiment_analysis.py` | Supplies the fetching, environmental filter and topic matching, so summaries cover the same content as the sentiment figures |
| `locations.json` | Lists the countries the script loops over |
| Supabase tables | Reads `monthly_topic_stats` (top 3 topics per country), `clean_posts` and `clean_comments`; writes `summary` |
| Dashboard | **Sentiment Analysis** page reads `summary` |

## Data Flow

```text
clean_posts + clean_comments (environmental, in month)
    |
    v
grouped by (country, topic) using monthly_topic_stats
    |
    v
Gemini
    |
    v
summary
```

## How it works

1. Loads all `clean_posts` and `clean_comments` for the month and applies the
   same environmental filter and topic matching as `sentiment_analysis.py`
   (comments are dated by their parent post; keyword matching is
   case-insensitive).
2. Groups the cleaned text by country and topic.
3. For each of the top three topics per country in `monthly_topic_stats`, sends
   all of that topic's text to Gemini (`gemini-3.1-flash-lite`) and asks for up
   to three bullet points on the consensus, overall sentiment and main concerns.
4. Stores the result as JSON in `summary.summary`, in the form
   `{"Topic1": "...", "Topic2": "...", "Topic3": "..."}`. If Gemini returns text
   that is not valid JSON, it is stored as `{"Raw_Summary": "..."}`. An empty
   `{}` means the content had nothing meaningful to summarise.

## Output fields

| Column | Content |
| --- | --- |
| `month`, `country`, `topic_name` | What the row covers |
| `keywords` | The topic's keywords as a comma-separated string |
| `summary` | JSON object with up to three summary points |

## Running

From the repository root:

```bash
# Previous month, skipping summaries that already exist
python scripts/sentiment/posts_comments_summary.py

# Specific months (YYYY-MM format; always regenerated)
python scripts/sentiment/posts_comments_summary.py --months 2026-08 2026-09

# Only some countries
python scripts/sentiment/posts_comments_summary.py --months 2026-09 --countries Malaysia
```

Valid countries are the names in `locations.json`: `Singapore`, `Malaysia`,
`Indonesia`, `Philippines`, `Brunei` and `Thailand`.

## Rerun behaviour

- Rows are upserted on `(topic_name, country, month)`, so each month keeps its
  own summary.
- A default run covers the previous month and skips summaries that already
  exist.
- Months passed with `--months` are always regenerated.
- A topic is skipped if it has no keywords or no matching posts or comments.

## Error handling

- **Retries.** Gemini is retried up to 5 times (`GEMINI_RETRIES`) with
  exponential backoff on 503, 429, `UNAVAILABLE` and `RESOURCE_EXHAUSTED`
  errors. If it still fails, nothing is stored, so the next run retries that
  topic.
- **Silent RLS blocks.** If Supabase row-level security blocks a write, the
  script prints `No rows written ... check RLS insert/update policies`. Use a
  server-side `SUPABASE_KEY`.
- **Credentials.** Needs `SUPABASE_URL`, `SUPABASE_KEY` and `GEMINI_API_KEY`
  (or `GOOGLE_API_KEY`). The script searches upward from its own folder for
  `.env`, so the repository-root `.env` is found.

## Limitations

- Output is written by a language model and can be generic or wrong. Review it
  before acting on it.
- All of a topic's text is sent in one request, so a very large month could
  exceed Gemini's context window.
- Gemini model availability and free-tier quota are not guaranteed, so a run
  may fail depending on when it is made.
