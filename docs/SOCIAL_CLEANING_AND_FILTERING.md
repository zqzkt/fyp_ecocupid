# Social Cleaning and Environmental Filtering

After the five platform collectors have stored raw data, two shared scripts turn
it into one consistent dataset that sentiment analysis and the Communication
Framework use.

```text
raw platform tables
  facebook_*, instagram_*, reddit_*, x_*, youtube_*
        |
        v
scripts/cleaning/clean_social.py          normalise, translate comments
        |
        v
clean_posts, clean_comments
        |
        v
scripts/cleaning/filter_environmental.py  Gemini labels each post
        |
        v
clean_posts.is_environmental (true or false)
```

Both scripts run automatically at the end of `social_media_pipeline.py` (and so
after each Data page button). They can also be run alone, from the repository
root:

```bash
python scripts/cleaning/clean_social.py
python scripts/cleaning/filter_environmental.py
```

## 1. Shared cleaning: `clean_social.py`

### What it reads and writes

It reads the raw tables for X, Reddit, YouTube, Instagram and Facebook (in that
order), in pages of 1,000 rows, and writes to `clean_posts` and
`clean_comments` in batches of 100. Writes are upserts on `source_id`.

### Only new data is processed

Before cleaning, the script checks which `source_id` values already exist in the
clean tables and skips them. This means:

- Re-running the script is cheap and does not duplicate rows or repeat
  translation.
- It never updates a row that has already been cleaned. If a raw row changes
  later, the clean row is not refreshed.
- `--full-refresh` deletes every row in `clean_posts` and `clean_comments` and
  rebuilds them. This re-translates all comments, which is costly, and also
  removes the `is_environmental` labels, so the filter has to run again.

### The common row format

Every raw row becomes one row in the clean tables. Platform-specific column
names are mapped to shared ones.

| Clean column | Meaning |
| --- | --- |
| `source_id` | `platform:type:original_id`, for example `reddit:comment:abc123` |
| `platform`, `source_type`, `source_table` | Where the row came from (`post` or `comment`) |
| `original_text` | The source text exactly as collected |
| `cleaned_text` | The text after cleaning and, for comments, translation |
| `lang` | Language code |
| `inferred_country` | Country, normalised to full names (`SG` becomes `Singapore`) |
| `author_id`, `conversation_id`, `parent_source_id` | Links between posts, comments and authors |
| `matched_keywords` | The topic keywords that led to this item being collected |
| `like_count`, `reply_count`, `repost_count`, `quote_count` | Engagement counts, mapped from each platform's own fields |
| `impression_count` | Views or impressions where the platform provides them |
| `total_engagement` | Provided by the platform, or the sum of the four counts |
| `posted_at`, `post_url`, `parent_posted_at` | Timing and link (posts carry the URL; comments carry the parent's date) |
| `is_environmental` | Set later by the filter (posts only) |

### Text cleaning

`cleaned_text` is produced by three steps:

1. Emoji are replaced by their names in square brackets, for example a smiling
   face becomes `[grinning_face]`, so the emotion model can use them.
2. `@mentions` are removed.
3. Extra whitespace is collapsed.

For YouTube posts the text is the title and description joined together.

### Translation

- **Comments** are translated to English with Google Cloud Translation, in
  batches of 50 (and under 100,000 bytes per request), with up to three retries.
  Comments already in English are left alone, as is text with no language
  content (such as emoji-only comments). X's code for Indonesian (`in`) is
  mapped to `id`, and if Google rejects a language code the script retries with
  automatic detection.
- **Posts** are not translated by this script. Facebook posts are translated in
  the Facebook collector, and Instagram and Reddit posts are kept only if they
  are English, so they need no translation.
- **YouTube posts** are kept only if they are English, judged from the stored
  language or, if missing, from language detection on the title and description.
  Others are excluded from the clean tables.

Translation is the largest running cost of the system (about US$90 per run), so
the "only new rows" behaviour matters.

### How comments inherit from their posts

A comment takes its country, matched keywords and `parent_posted_at` from its
parent post. This keeps comments grouped under the same topic and month as the
post they belong to. YouTube comments, which have no publish time of their own,
use the video's date.

## 2. Environmental filter: `filter_environmental.py`

Social collection searches by topic keyword, so some collected posts only
mention an environmental word in passing. The filter removes those.

### How it works

- It reads posts from `clean_posts` where `is_environmental` is empty, in pages
  of 1,000.
- It sends them to Gemini (`gemini-3.1-flash-lite`) in batches of 50, using the
  first 1,000 characters of each post and the platform name.
- Gemini is asked which posts are genuinely about the environment (for example
  climate, extreme weather, pollution, haze, waste, conservation, wildlife,
  forests and oceans) and told to exclude posts that only mention an
  environmental word incidentally, such as unrelated news, politics,
  entertainment, sports, product sales, promotions, spam, or posts with too
  little text.
- It writes `true` or `false` to `is_environmental`. Posts with no text are set
  to `false` without calling Gemini.
- If a batch fails (for example Gemini is busy), it is left empty and retried on
  the next run. Calls retry up to five times with increasing waits.

### Options and requirements

| Option | Effect |
| --- | --- |
| (none) | Classify only posts with no label yet |
| `--reclassify` | Classify every post again |

It needs `GEMINI_API_KEY` (or `GOOGLE_API_KEY`) and a server-side Supabase key.
It exits with an error if the Supabase key is a publishable or anon key.

### Comments

Only posts are labelled. `clean_comments` has no `is_environmental` column, and
later steps treat a comment as environmental when its parent post is.

## 3. Limitations

- **Only new rows are cleaned.** Corrections to raw data do not flow through
  unless a full refresh is run.
- **Translation is machine translation** and can lose slang, tone and local
  expressions. If translation fails, the original text is kept.
- **Posts are only partly translated.** Facebook posts are translated at
  collection time. Instagram, Reddit and YouTube posts are English only.
- **The filter is an AI judgement.** It can make mistakes, may not give
  identical answers on every run, and only sees the first 1,000 characters.
- **Labels are set once.** A wrong label stays until a full reclassification.
- **Availability.** The filter depends on Gemini being available and within
  quota when it runs.
- **Emoji handling** turns emoji into text names, which are useful to the
  emotion model but make `cleaned_text` less natural to read.
