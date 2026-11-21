# Communication Framework

The Communication Framework turns the collected data into decisions for
EcoCupid: **where** to communicate (which platform) and **how** (what to say).
It has three parts.

| Part | Dashboard page | Code | Run by |
| --- | --- | --- | --- |
| Engagement comparison | Engagement Metrics Overview | `engagement_metric_comparison.py` | Calculated live by the page |
| Channel recommendation ("Where to communicate") | Communication Framework, section 1 | `channel_recommendations.py` | Calculated live by the page |
| Messaging guidance ("How to communicate") | Communication Framework, section 2 | `topic_based_analysis.py` | Run at the end of the social pipeline, or from the Data page's rerun button; stored in `topic_based_analysis` |

All three work from `clean_posts` and `clean_comments` (see
[SOCIAL_CLEANING_AND_FILTERING.md](SOCIAL_CLEANING_AND_FILTERING.md)) and the
monthly topics in `monthly_topic_stats`.

## 1. Engagement comparison

`engagement_metric_comparison.py` loads posts and comments and calculates
engagement for the **Engagement Metrics Overview** page. The page has three
views:

1. a chosen platform's engagement **by country**,
2. engagement **across platforms**, and
3. **platform by country**.

### Definitions

- **Post engagement** = likes + replies + reposts + quotes on posts. A post's
  reply count counts as engagement, because replying is an audience action.
- **Comment engagement** = likes + replies + reposts + quotes received by
  comments. It is added to totals only when the page's comment-engagement switch
  is on.
- **Reach** (impressions or views) is a post-level measure and is never
  increased by comments. It is available only for **YouTube and X**. Facebook,
  Instagram and Reddit have no usable impression data in the collected data, so
  engagement rate and reach figures are not shown for them.
- The page shows both **average per post** and **median per post**. The median
  is less affected by a few very popular posts.

### Page filters

Topic, platform, countries, a switch to include comment engagement, and a
month-range slider.

## 2. Channel recommendation (section 1 of the page)

`channel_recommendations.py` recommends a **Primary** channel and, where the
evidence supports it, a **Secondary** channel for a chosen country and period.
It runs when the page is opened, using data that is cached for 10 minutes. No
AI is involved. It is a statistical comparison.

### Which posts are used

- All **environmental original posts** (posts, not comments) from the chosen
  country and months, whatever their topic. The recommendation is not limited to
  the top three news topics.
- Each post's engagement is its own total engagement **plus the reactions
  received by its linked comments** (likes, reposts and quotes). Comments are
  never counted as posts.
- Posts with missing engagement are left out. A genuine zero is kept.

### Rules

1. **A platform needs at least 30 posts** to be compared. Platforms with fewer
   are shown as "not eligible" and are never recommended.
2. **Summary statistics** are calculated per platform: median, lower quartile
   (Q1), upper quartile (Q3), average and totals.
3. **Statistical test.** If two or more platforms are eligible, a
   Kruskal-Wallis test (significance level 0.05) checks whether their
   engagement differs. If it does, Dunn's pairwise tests with Holm correction
   compare each pair.
4. **A "meaningful" difference** needs both statistical evidence and a practical
   effect size of at least "moderate" (Cliff's delta of 0.33 or more). A platform
   with a meaningful loss to another cannot be Primary.
5. **Primary** is the eligible platform with the broadest advantage across the
   distribution: it beats another platform when at least two of Q1, median and
   Q3 are higher. Ties are broken by the number of statistical wins. If the
   leaders are still tied, the result is "inconclusive". Posting volume is never
   used for this.
6. **Evidence strength** is "Strong" when the test was significant and the
   Primary has statistical wins, and "Indicative" otherwise. Significance is
   supporting evidence, not a requirement.
7. **Secondary** must not have a meaningful loss to the Primary, and must be
   competitive (at least one quartile at or above the Primary's, or a supported
   win over a third platform). It is assigned only if exactly one platform is
   the best option.
8. **Activity fallback.** If no Primary can be identified, the platform with the
   most environmental posts may be shown as a provisional Primary, labelled
   "activity fallback". This reflects posting volume, not stronger engagement,
   and no Secondary is assigned.

The page shows the outcome, the reasons for each channel, and a table of every
platform's post count and whether it qualified ("How this was decided").

### Example

For Malaysia in Sep to Oct 2026 the page analysed 753 environmental posts.
Facebook had 20 posts and did not qualify. YouTube had by far the most posts
(564) but was not chosen, because the decision compares engagement, not
volume. Instagram was Primary and Reddit Secondary.

## 3. Messaging guidance (section 2 of the page)

`topic_based_analysis.py` uses Gemini to turn the contrast between high- and
low-performing posts into practical messaging advice for each topic and country.
The page only **reads the saved results**. It does not call Gemini.

### How it works

For each country and each of its top-ranked topics for the month:

1. It fetches environmental posts from `clean_posts` that match the topic's
   keywords, posted in that month, from that country.
2. If there are fewer than **20** posts, it widens to posts from **all
   countries** and tells Gemini the posts are a regional stand-in.
3. It sorts posts by engagement and takes the **top 25%** and **bottom 25%**.
4. Gemini (`gemini-3.1-flash-lite`) is asked to find what separates them and to
   write advice for **short-form vertical video** (TikTok and Instagram Reels),
   as a JSON object. It also picks which of the posts are genuinely
   environmental, and only those are kept as source links.
5. The result is saved to `topic_based_analysis`, with up to 5 top-post and 5
   bottom-post links.

### What each report contains

| Field | Shown on the page as |
| --- | --- |
| `key_message` | Key message |
| `tone_and_emotion` | Tone |
| `content_type`, `narrative_method`, `story_structure` | Content and story tab |
| `hooks`, `call_to_action`, `captions` | Hooks and captions tab |
| `recommendations`, `what_not_to_do` | Do's and don'ts tab |
| `top_post_links`, `bottom_post_links` | Source posts tab |

### Running it

`social_media_pipeline.py` runs it with `--force` after sentiment analysis, so
every Data page social button also produces guidance. To regenerate the
previous month's guidance without collecting data, use **Rerun topic-based
analysis** on the Data page.

To run it by hand, from the repository root:

```bash
python scripts/communication_framework/topic_based_analysis.py             # previous month
python scripts/communication_framework/topic_based_analysis.py 2026-09-01  # a given month
python scripts/communication_framework/topic_based_analysis.py --country Malaysia
python scripts/communication_framework/topic_based_analysis.py --topic "Climate Change"
python scripts/communication_framework/topic_based_analysis.py --force
```

| Option | Effect |
| --- | --- |
| month (`YYYY-MM-01`) | Month to analyse (default: previous month) |
| `--country` | Only these countries. Matching topics are re-run |
| `--topic` | Only these topics. Matching topics are re-run |
| `--force` | Re-run every topic, even those with an analysis already |

By default, topics that already have an analysis are skipped. The script needs
`GEMINI_API_KEY` and `SUPABASE_KEY` in `.env`, and retries when Gemini is busy.

### One report per topic and country

The table's key is topic and country, with no month. If the same topic comes
back in a later month, the new report replaces the old one and the stored month
changes. The page shows which month a report comes from in the topic selector.

## 4. Limitations

- **Platforms measure different things.** Only YouTube and X give reach figures,
  so cross-platform comparisons are not like for like.
- **Collection design shapes the result.** Facebook comes from selected pages,
  Instagram from hashtags, and X from a small capped sample, so differences
  between platforms partly reflect how data was collected.
- **Larger accounts dominate raw engagement.** Likes and replies favour pages
  and accounts with bigger followings.
- **Small samples.** A platform with fewer than 30 posts cannot be recommended,
  and for some countries few platforms qualify.
- **Country is inferred** and posts may be attributed to the wrong country.
- **Regional fallback.** When a country has fewer than 20 matching posts for a
  topic, the advice partly reflects other countries.
- **AI-written advice** can be inaccurate or generic and is not human-reviewed.
  It always targets short-form vertical video, even when the recommended channel
  is different. Treat it as a starting point.
- **Only the latest report is kept** for each topic and country.
- **Availability.** Section 2 depends on Gemini having been available when the
  script was run.
