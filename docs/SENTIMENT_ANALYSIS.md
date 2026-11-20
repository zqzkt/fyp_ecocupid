# Sentiment (Emotion) Analysis

EcoCupid measures the **emotions** people express about each environmental
topic, not simply "positive" or "negative". The results feed the Sentiment
Analysis page of the dashboard.

```text
clean_posts + clean_comments  (environmental only)
        |
        |  match each item to the month's top-3 topics by keyword
        v
emotion model (27 emotions + neutral)  -- scripts/sentiment/emotion_model.joblib
        |
        v
sentiment_analysis   one row per country, topic, month and year

(separately)  posts_comments_summary.py --> summary   AI-written discussion points
```

## 1. Files

| File | Role |
| --- | --- |
| `sentiment_analysis.py` | Scores items and writes the monthly aggregates |
| `emotion_model.joblib` | The trained model (labels, vectoriser, classifier and thresholds) |
| `train_emotion_model.py` | Trains the model from the GoEmotions files in `dataset/goemotions/` |
| `emotion_labels.py` | The 28 labels in a fixed order, shared by training and scoring |
| `emotion_inference.py` | Turns model probabilities into emotion labels |
| `text_preprocessing.py` | Text preparation shared by training and scoring |
| `sentiment_keywords.py` | Interpretable keyword cues recorded alongside predictions |
| `sentiment_validation_score.py` and `Sentiment Validation.xlsx` | Accuracy check against human labels |
| `posts_comments_summary.py` | AI-written discussion summaries per topic |

## 2. The emotion model

### Labels

The model predicts the 27 emotions of the GoEmotions dataset plus `neutral`:
admiration, amusement, anger, annoyance, approval, caring, confusion, curiosity,
desire, disappointment, disapproval, disgust, embarrassment, excitement, fear,
gratitude, grief, joy, love, nervousness, optimism, pride, realization, relief,
remorse, sadness and surprise.

An item can have **more than one emotion** (multi-label).

### Training

`train_emotion_model.py` trains on the GoEmotions train, dev and test files
included in the repository. GoEmotions is a public dataset of English Reddit
comments labelled by people.

| Part | Setting |
| --- | --- |
| Text features | TF-IDF on words and word pairs (1 to 2 grams), words must appear in at least 2 texts, up to 250,000 features |
| Classifier | One logistic regression per emotion (one-vs-rest), regularisation `C=4`, balanced class weights, `liblinear` solver |
| Decision thresholds | One threshold per emotion, chosen to maximise F1 on the validation split (searched from 0.05 to 0.95) |
| Evaluation | Micro, macro and samples F1 on the validation and test splits, printed when training |

Retrain with:

```bash
python scripts/sentiment/train_emotion_model.py
```

This overwrites `emotion_model.joblib`. `sentiment_analysis.py` refuses to run if
the file is missing, is in the old single-label format, or its labels do not
match `emotion_labels.py`.

### Turning probabilities into labels

For each item the model gives a probability for every emotion. Emotions whose
probability passes their own threshold are selected. `neutral` is reported only
when no other emotion passes. If nothing passes at all, the single most likely
emotion is used, so every item gets at least one label.

### Text preparation

Emoji names such as `[red_heart]` (produced by cleaning) are expanded to plain
words (`red heart`) so the model can use them. The same preparation is used in
training and scoring.

## 3. Aggregation: `sentiment_analysis.py`

### What is scored

- **Environmental posts only** (`is_environmental = true`), and
- **Comments on those posts.** A comment follows its parent post, because
  `clean_comments` has no environmental label of its own. Comments whose parent
  never reached `clean_posts` are dropped.

### Matching to topics

For each country and month, the script takes the **top three topics** from
`monthly_topic_stats` (`topic_rank` 3 or lower). Each item is matched to a topic
through its `matched_keywords` (and, for Instagram, the topic name), ignoring
case. An item can match more than one topic. **Items that match none of that
month's top three topics are skipped**, and the script reports how many.

A comment is placed in the month of its parent post, not the month it was
written.

### Output

One row per country, topic, month and year in `sentiment_analysis`, with:

- `total_items`,
- a count for each of the 27 emotions and `neutral_count`,
- `dominant_emotions` (the most frequent emotions), and
- `matched_sentiment_keywords`, the keyword cues found in the text (from
  `sentiment_keywords.py`), kept as supporting evidence.

Rows are upserted on (country, topic, month, year).

### Running it

The social pipeline runs it automatically, with `--run-now` so it works on any
day of the month. To run it yourself, from the repository root:

```bash
python scripts/sentiment/sentiment_analysis.py                 # previous month
python scripts/sentiment/sentiment_analysis.py --month 2026-09-01
python scripts/sentiment/sentiment_analysis.py --all           # every cleaned item
```

| Option | Effect |
| --- | --- |
| `--month YYYY-MM-01` | Score that month (default: previous calendar month) |
| `--run-now` | Run outside the monthly job's first-of-month guard |
| `--all` | Recompute aggregates across all cleaned posts and comments |
| `--platform` | Restrict input to one platform |
| `--source-type post\|comment` | Restrict input to posts or comments |
| `--dry-run` | Classify and summarise without changing `sentiment_analysis` |

## 4. Validation

The team labelled a sample by hand in `Sentiment Validation.xlsx` and compared
the model with `sentiment_validation_score.py`:

```bash
cd scripts/sentiment
python sentiment_validation_score.py
```

| Measure | Result |
| --- | --- |
| Items validated | 359 |
| Agreement | 58.8% |
| Cohen's kappa | 0.555 (moderate agreement) |

**The check is lenient.** An item counts as a match when the human's emotion
appears anywhere in the model's list of predicted emotions (92 of the 359 items
matched only this way). True one-to-one accuracy is lower than the figures
suggest.

## 5. Discussion summaries: `posts_comments_summary.py`

This script writes short AI summaries shown on the Sentiment Analysis page.

- It collects the same posts and comments, with the same environmental filter
  and topic matching as `sentiment_analysis.py`, so each summary describes the
  discussion counted on the dashboard.
- For each country and topic it sends the texts to Gemini
  (`gemini-3.1-flash-lite`) and asks for up to three bullet points covering the
  main consensus, overall sentiment and primary concerns.
- Results are stored in `summary`, keyed by topic, country and month.

**It is not part of the pipelines or the Data page buttons.** Run it separately:

```bash
python scripts/sentiment/posts_comments_summary.py                    # previous month
python scripts/sentiment/posts_comments_summary.py --months 2026-09 2026-10
python scripts/sentiment/posts_comments_summary.py --countries Malaysia
```

By default it processes the previous month and skips summaries that already
exist. Months named with `--months` are always regenerated.

## 6. Limitations

- **Moderate accuracy.** See the validation figures above. Use results to
  compare countries and topics and to spot trends, not to judge single posts.
- **A simple model.** It is a classical text classifier, not a modern language
  model. It can struggle with sarcasm, slang, Singlish and Manglish, mixed
  languages and translated text.
- **Trained on English Reddit comments.** Social posts on other platforms and
  translated comments differ from its training data.
- **Emotion is not opinion.** It estimates emotions in text, such as anger or
  hope. It does not measure whether someone supports a policy or topic.
- **Small counts are unreliable.** With 28 labels, emotions with few examples
  for a country, topic and month should not be over-interpreted, especially for
  countries with less data.
- **Only the top three topics** are analysed each month, and matching is by
  keyword, so a post can match a keyword without being about the topic.
- **Summaries are AI-written** and are not human-reviewed.
