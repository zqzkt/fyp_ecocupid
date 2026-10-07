"""Aggregate emotions per environmental issue and ASEAN country.

Classifies clean_posts and clean_comments rows into the 27 GoEmotions emotions
plus neutral, allowing multiple non-neutral labels per item, and upserts per
(country, topic) emotion counts into Supabase. The default mode scores the previous month;
--all recomputes aggregates across all cleaned social data.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import joblib
import requests

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.cleaning.clean_social import credentials, headers
from scripts.sentiment.emotion_inference import decode_emotion_probabilities
from scripts.sentiment.emotion_labels import EMOTIONS
from scripts.sentiment.sentiment_keywords import matched_sentiment_keywords
from scripts.sentiment.text_preprocessing import normalize_emoji_tags
from scripts.supabase.twitter_pipeline import previous_month_window

MODEL_PATH = Path(__file__).resolve().parent / "emotion_model.joblib"
UNSPECIFIED_TOPIC = "Unspecified"

# Raw country values seen across platforms (e.g. YouTube stores ISO codes).
COUNTRY_ALIASES = {
    "SG": "Singapore",
    "MY": "Malaysia",
    "ID": "Indonesia",
    "PH": "Philippines",
    "TH": "Thailand",
    "BN": "Brunei",
}


def load_emotion_model() -> Any:
    if not MODEL_PATH.exists():
        raise SystemExit(
            f"{MODEL_PATH} not found. Run scripts/sentiment/train_emotion_model.py first."
        )
    bundle = joblib.load(MODEL_PATH)
    if not isinstance(bundle, dict) or not {"model", "labels", "thresholds"}.issubset(bundle):
        raise SystemExit(
            "The saved emotion model uses the old single-label format. "
            "Retrain it with scripts/sentiment/train_emotion_model.py."
        )
    if tuple(bundle["labels"]) != EMOTIONS:
        raise SystemExit("The saved model labels do not match emotion_labels.py; retrain the model.")
    return bundle


def normalize_country(value: str | None) -> str:
    if not value:
        return "Unspecified"
    return COUNTRY_ALIASES.get(value, value)


def row_topics(row: dict[str, Any]) -> list[str]:
    keywords = row.get("matched_keywords") or []
    if not keywords:
        return [UNSPECIFIED_TOPIC]
    seen: set[str] = set()
    topics: list[str] = []
    for keyword in keywords:
        keyword = str(keyword).strip()
        if keyword and keyword.casefold() not in seen:
            seen.add(keyword.casefold())
            topics.append(keyword)
    return topics or [UNSPECIFIED_TOPIC]


def month_window(month: str) -> tuple[str, str]:
    """Return [start, end) ISO-8601 UTC bounds for a YYYY-MM-01 month string."""
    start = datetime.fromisoformat(f"{month}T00:00:00+00:00")
    end = (start + timedelta(days=32)).replace(day=1)
    return start.isoformat().replace("+00:00", "Z"), end.isoformat().replace("+00:00", "Z")


def fetch_rows_in_window(
    session: requests.Session,
    base_url: str,
    key: str,
    table: str,
    start_time: str,
    end_time: str,
    platform: str | None = None,
    source_type: str | None = None,
) -> list[dict[str, Any]]:
    """Fetch rows for a month; linked comments use their parent post's month."""
    rows: list[dict[str, Any]] = []
    offset = 0
    page_size = 1000
    while True:
        params: dict[str, Any] = {"select": "*", "limit": page_size, "offset": offset}
        if table == "clean_comments":
            params["or"] = (
                f"(and(parent_posted_at.gte.{start_time},"
                f"parent_posted_at.lt.{end_time}),"
                f"and(parent_posted_at.is.null,posted_at.gte.{start_time},"
                f"posted_at.lt.{end_time}))"
            )
        else:
            params["posted_at"] = [f"gte.{start_time}", f"lt.{end_time}"]
        if platform:
            params["platform"] = f"eq.{platform}"
        if source_type:
            params["source_type"] = f"eq.{source_type}"
        response = session.get(
            f"{base_url}/rest/v1/{table}",
            params=params,
            headers=headers(key),
            timeout=60,
        )
        if response.status_code == 404:
            return []
        response.raise_for_status()
        page = response.json()
        rows.extend(page)
        if len(page) < page_size:
            return rows
        offset += page_size


def fetch_all_rows(
    session: requests.Session,
    base_url: str,
    key: str,
    table: str,
    platform: str | None = None,
    source_type: str | None = None,
) -> list[dict[str, Any]]:
    """Fetch every cleaned row, including records outside the monthly window."""
    rows: list[dict[str, Any]] = []
    offset = 0
    page_size = 1000
    while True:
        params: dict[str, Any] = {"select": "*", "limit": page_size, "offset": offset}
        if platform:
            params["platform"] = f"eq.{platform}"
        if source_type:
            params["source_type"] = f"eq.{source_type}"
        response = session.get(
            f"{base_url}/rest/v1/{table}",
            params=params,
            headers=headers(key),
            timeout=60,
        )
        if response.status_code == 404:
            return []
        response.raise_for_status()
        page = response.json()
        rows.extend(page)
        if len(page) < page_size:
            return rows
        offset += page_size


def row_entries(rows: list[dict[str, Any]]) -> list[tuple[str, str, str, int | None, int | None]]:
    """Return country/topic/text/month/year entries for each row/topic pairing."""
    entries: list[tuple[str, str, str, int | None, int | None]] = []
    for row in rows:
        text = (row.get("cleaned_text") or "").strip()
        if not text:
            continue
        timestamp = row.get("parent_posted_at") or row.get("posted_at")
        try:
            created = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            else:
                created = created.astimezone(timezone.utc)
            year, month = created.year, created.month
        except (TypeError, ValueError):
            year, month = None, None
        country = normalize_country(row.get("inferred_country"))
        for topic in row_topics(row):
            entries.append((country, topic, text, year, month))
    return entries


def upsert_sentiment(base_url: str, key: str, rows: list[dict[str, Any]]) -> int:
    if not rows:
        print("environment_sentiment: 0 rows")
        return 0
    session = requests.Session()
    endpoint = f"{base_url}/rest/v1/environment_sentiment?on_conflict=country,topic,month,year"
    written = 0
    batch_size = 100
    for start in range(0, len(rows), batch_size):
        chunk = rows[start : start + batch_size]
        response = session.post(endpoint, json=chunk, headers=headers(key, write=True), timeout=60)
        response.raise_for_status()
        written += len(chunk)
        print(f"environment_sentiment: upserted {written}/{len(rows)}")
    return written


def clear_environment_sentiment(
    base_url: str,
    key: str,
    *,
    year: int | None = None,
    month: int | None = None,
    all_rows: bool = False,
) -> None:
    """Clear all aggregates or just the month being recomputed."""
    session = requests.Session()
    params = {"country": "not.is.null"}
    if not all_rows:
        if year is None or month is None:
            raise ValueError("year and month are required when clearing one month")
        params.update({"year": f"eq.{year}", "month": f"eq.{month}"})
    response = session.delete(
        f"{base_url}/rest/v1/environment_sentiment",
        params=params,
        headers=headers(key, write=True),
        timeout=60,
    )
    response.raise_for_status()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compute emotion aggregates from cleaned social data."
    )
    parser.add_argument("--month", help="YYYY-MM-01 window to score; defaults to the previous calendar month.")
    parser.add_argument("--run-now", action="store_true", help="Run outside the monthly job's 1st-of-month guard.")
    parser.add_argument("--all", action="store_true", help="Recompute sentiment across all cleaned posts and comments.")
    parser.add_argument(
        "--platform",
        choices=("x", "reddit", "youtube", "instagram", "facebook"),
        help="Restrict input rows to one platform.",
    )
    parser.add_argument(
        "--source-type",
        choices=("post", "comment"),
        help="Restrict input rows to posts or comments within the selected table(s).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Classify and summarize rows without changing environment_sentiment.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    today = datetime.now(timezone.utc)
    if today.day != 1 and not (args.run_now or args.all):
        raise SystemExit(
            "Monthly sentiment analysis runs on the 1st of the month. "
            "Pass --run-now to score the previous month, or --all to recompute all cleaned data."
        )

    if not args.all:
        if args.month:
            start_time, end_time = month_window(args.month)
        else:
            start_time, end_time = previous_month_window(today)

    model_bundle = load_emotion_model()
    base_url, key = credentials()
    session = requests.Session()

    if args.all:
        scope = f" for platform {args.platform}" if args.platform else ""
        if args.source_type:
            scope += f" {args.source_type}s only"
        print(f"Scoring all cleaned posts and comments{scope}...")
        posts = (
            fetch_all_rows(session, base_url, key, "clean_posts", args.platform, args.source_type)
            if args.source_type != "comment" else []
        )
        comments = (
            fetch_all_rows(session, base_url, key, "clean_comments", args.platform, args.source_type)
            if args.source_type != "post" else []
        )
    else:
        scope = f" for platform {args.platform}" if args.platform else ""
        if args.source_type:
            scope += f" {args.source_type}s only"
        print(f"Scoring data created between {start_time} and {end_time}{scope}...")
        posts = (
            fetch_rows_in_window(
                session, base_url, key, "clean_posts", start_time, end_time, args.platform, args.source_type
            ) if args.source_type != "comment" else []
        )
        comments = (
            fetch_rows_in_window(
                session, base_url, key, "clean_comments", start_time, end_time, args.platform, args.source_type
            ) if args.source_type != "post" else []
        )
    print(f"Classifying {len(posts)} clean posts and {len(comments)} clean comments...")

    entries = row_entries(posts) + row_entries(comments)
    if not entries:
        print("No cleaned text available to classify.")
        return

    probabilities = model_bundle["model"].predict_proba([entry[2] for entry in entries])
    predicted_emotions = decode_emotion_probabilities(
        probabilities, model_bundle["thresholds"]
    )

    stats: dict[tuple[str, str, int | None, int | None], dict[str, Any]] = {}
    for (country, topic, text, year, month), emotions in zip(entries, predicted_emotions):
        bucket = stats.setdefault(
            (country, topic, month, year),
            {
                "total": 0,
                **{e: 0 for e in EMOTIONS},
                "matched_sentiment_keywords": {e: set() for e in EMOTIONS},
            },
        )
        bucket["total"] += 1
        for emotion in emotions:
            bucket[emotion] += 1
            bucket["matched_sentiment_keywords"][emotion].update(
                matched_sentiment_keywords(text, emotion)
            )

    print("Predicted emotion counts:")
    for emotion in EMOTIONS:
        count = sum(bucket[emotion] for bucket in stats.values())
        if count:
            print(f"  {emotion}: {count}")
    unspecified_country = sum(bucket["total"] for (country, _topic, _month, _year), bucket in stats.items() if country == "Unspecified")
    unspecified_topic = sum(bucket["total"] for (_country, topic, _month, _year), bucket in stats.items() if topic == UNSPECIFIED_TOPIC)
    print(f"Unspecified country: {unspecified_country} items")
    print(f"Unspecified topic: {unspecified_topic} items")

    if args.dry_run:
        print(
            f"Dry run complete: {len(entries)} text/topic rows across {len(stats)} "
            "country/topic/month groups; environment_sentiment was not changed."
        )
        return

    now = datetime.now(timezone.utc).isoformat()
    rows = []
    for (country, topic, month, year), bucket in stats.items():
        dominant_emotions = sorted(
            (emotion for emotion in EMOTIONS if bucket[emotion] > 0),
            key=lambda emotion: (-bucket[emotion], emotion.casefold()),
        )[:3]
        rows.append(
            {
                "country": country,
                "topic": topic,
                "month": month,
                "year": year,
                "total_items": bucket["total"],
                **{f"{emotion}_count": bucket[emotion] for emotion in EMOTIONS},
                "dominant_emotions": dominant_emotions,
                "matched_sentiment_keywords": {
                    emotion: sorted(keywords)
                    for emotion, keywords in bucket["matched_sentiment_keywords"].items()
                    if keywords
                },
                "updated_at": now,
            }
        )

    # A filtered --all run (for example, X comments only) must not erase
    # aggregates belonging to other input sources. Matching aggregate keys
    # are refreshed by the upsert below; unrelated keys are preserved.
    if args.all and not (args.platform or args.source_type):
        clear_environment_sentiment(base_url, key, all_rows=True)
    elif not args.all:
        clear_environment_sentiment(
            base_url,
            key,
            year=int(start_time[:4]),
            month=int(start_time[5:7]),
        )
    upsert_sentiment(base_url, key, rows)
    print(f"Computed emotions for {len(rows)} (country, topic) pairs.")


if __name__ == "__main__":
    main()
