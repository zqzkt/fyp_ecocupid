# Dashboard

The dashboard is a Streamlit app that lets EcoCupid explore the news topics,
engagement, emotions and communication recommendations, and run the monthly
data collection.

```bash
streamlit run dashboard/app.py     # from the repository root
```

It reads `.env` from the repository root and needs `SUPABASE_URL` and a
server-side Supabase key. If `monthly_topic_stats` has no rows, it shows a
message and stops. Run the news collection first.

## 1. Pages

`app.py` defines the navigation, in three groups.

| Group | Page | File | Purpose |
| --- | --- | --- | --- |
| News | Coverage Overview | `views/overview.py` | ASEAN-level topic coverage, topic mix and trends. Sidebar filters, and a slider for the number of top topics |
| News | Country-Specific Explorer | `views/country_opportunity.py` | Topic trends for one country, classifying topics as New, Emerging or Recurring |
| Social Media | Engagement Metrics Overview | `views/engagement_comparison.py` | Engagement by country, across platforms, and platform by country |
| Social Media | Sentiment Analysis | `views/sentiment_analysis.py` | Emotions behind the top topics for a month and chosen countries |
| Social Media | Communication Framework | `views/communication_framework.py` | Recommended channels and AI messaging guidance |
| Raw Data | Data | `views/data.py` | Browse and export last month's collected data, and run the collectors |

`views/trends.py` is in the repository but is not linked from the navigation.

### Country-Specific Explorer: topic classes

A topic is classified for the latest selected month in this order of priority.

| Class | Rule |
| --- | --- |
| **New** | First-ever appearance of the topic in that country is in the latest selected month |
| **Emerging** | Already seen before, at least 3 mentions in the latest month, and month-on-month growth of at least 50% |
| **Recurring** | Appears in at least 2 months of the selected period (and is not New or Emerging) |

These thresholds are constants at the top of `country_opportunity.py`
(`EMERGING_GROWTH_PCT`, `EMERGING_MIN_MENTIONS`, `RECURRING_MIN_MONTHS`).
Mentions are article counts from `monthly_topic_stats`, so they reflect how much
news each outlet published, not how concerned people are.

### Sentiment Analysis page

Shows up to the top nine topics for the chosen month and countries as bubbles.
Bubble size is the number of items, and bubble colour is the topic's most
dominant non-neutral emotion. Selecting a topic shows more detail, including the
AI discussion summary if `posts_comments_summary.py` has been run. See
[SENTIMENT_ANALYSIS.md](SENTIMENT_ANALYSIS.md).

### Communication Framework page

Has its own country and month filters. Section 1 recommends channels and
section 2 shows messaging guidance for the period's top topics. Guidance appears
only after `topic_based_analysis.py` has been run. See
[COMMUNICATION_FRAMEWORK.md](COMMUNICATION_FRAMEWORK.md).

## 2. The Data page

The Data page shows the previous calendar month's data and exports it as CSV.
It has two groups of buttons.

| Button | Runs |
| --- | --- |
| Run news collection | `scripts/news_datapipeline.py` |
| Run all social media collections | `scripts/social_media_pipeline.py` |
| Run Facebook, Instagram, Reddit, X, YouTube | `scripts/social_media_pipeline.py --platform <name>` |

How they behave:

- Each button runs the script as a subprocess from the repository root. The page
  waits for it to finish, then shows a log and whether it completed or failed.
  Caches are cleared afterwards, so new data appears straight away.
- A button is **disabled** when the data for that step is already in Supabase for
  the previous month. The all-platforms button is disabled once any platform has
  data. A button is also disabled if the page cannot check Supabase.
- The page does **not** stop you running social collection before news. Always
  run news first.
- The buttons use paid API credits. There is no login, so anyone who can open
  the dashboard can start a run.
- The buttons do **not** run `posts_comments_summary.py` or
  `topic_based_analysis.py`. Run those from the command line afterwards.

## 3. How the dashboard loads data

- Data is fetched from the Supabase REST API in pages of 1,000 rows, using the
  server-side key.
- Results are cached for 10 minutes, so new data can take up to 10 minutes to
  appear unless a Data page run clears the cache. The Data page's own checks are
  cached for 60 seconds.
- Whole tables are loaded and filtered in the app, so the dashboard may slow
  down as the amount of data grows.

## 4. Files

| File | Role |
| --- | --- |
| `app.py` | Page setup, navigation and page-specific filters |
| `load_data.py` | Loads topic statistics and cleaned news |
| `filters.py` | Sidebar filters for the news pages |
| `metrics.py` | Topic totals and other calculations for the news pages |
| `sentiment_analysis_data.py` | Loads and prepares sentiment data and summaries |
| `communication_channels_data.py` | Loads data for the communication pages |
| `previous_month_data.py` | Checks and loads last month's data for the Data page |
| `style.py` | Shared styling and colours |
| `.streamlit/config.toml` | EcoCupid theme (light and dark) |

The theme colours come from the EcoCupid website. The background and text
colours in `.streamlit/config.toml` must match `SURFACE_COLOR` and `TEXT_COLOR`
in `style.py`, and the light `primaryColor` must match `SERIES_COLOR["light"]`.

## 5. Limitations

- **Local only, no login.** The dashboard runs on one computer and has no user
  access control. Add authentication before anyone outside the team can reach it.
- **Only as fresh as the last run.** It does not update by itself.
- **Runs block the page.** Closing the page or letting the computer sleep during
  a collection run may interrupt it.
- **Depends on Supabase.** Nothing is shown if the database is unreachable or
  `monthly_topic_stats` is empty.
- **May slow down as data grows**, because tables are loaded in full.
- **Large files.** Some page files are very long (for example
  `country_opportunity.py` is about 2,900 lines), which makes changes slower and
  riskier.
- **No automated tests.**
