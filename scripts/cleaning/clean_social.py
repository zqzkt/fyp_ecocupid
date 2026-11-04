"""Normalize social-media posts and comments into shared Supabase tables."""

from __future__ import annotations

import argparse
import json
import re
import os
import time
from importlib import import_module
from datetime import datetime, timezone
from typing import Any, Iterable

import requests
from dotenv import load_dotenv
from lingua import Language, LanguageDetectorBuilder

REPO_ROOT = __import__("pathlib").Path(__file__).resolve().parents[2]
load_dotenv(REPO_ROOT / ".env")
demojize = import_module("emoji").demojize

BATCH_SIZE = 100
PAGE_SIZE = 1000
TRANSLATION_BATCH_SIZE = 50
# Cloud Translation rejects requests over 204,800 bytes; stay well under it.
TRANSLATION_MAX_BATCH_BYTES = 100_000
TRANSLATION_RETRIES = 3
MENTION_RE = re.compile(r"(?<!\w)@[A-Za-z0-9_]{1,50}", re.UNICODE)
WHITESPACE_RE = re.compile(r"\s+")
_translator = None
_language_detector = None
X_LANGUAGE_CODES_WITHOUT_TRANSLATABLE_SOURCE = {"qam", "qct", "qht", "qme", "qst"}
COUNTRY_ALIASES = {
    "sg": "Singapore",
    "my": "Malaysia",
    "id": "Indonesia",
    "ph": "Philippines",
    "th": "Thailand",
    "bn": "Brunei",
}
# Keep high-signal fields for analysis, filtering, grouping, and auditability.
CLEAN_COLUMNS = (
    "source_id",
    "platform",
    "source_type",
    "original_text",
    "cleaned_text",
    "lang",
    "inferred_country",
    "author_id",
    "conversation_id",
    "parent_source_id",
    "posted_at",
    "parent_posted_at",
    "matched_keywords",
    "like_count",
    "reply_count",
    "repost_count",
    "quote_count",
    "impression_count",
    "total_engagement",
    "source_table",
    "post_url",
    "cleaned_at",
)

def credentials() -> tuple[str, str]:
    import os

    url = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
    key = (os.environ.get("SUPABASE_SECRET_KEY") or os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_KEY") or "").strip()
    if not url or not key:
        raise SystemExit("SUPABASE_URL and SUPABASE_KEY are required in .env")
    return url, key


def headers(key: str, *, write: bool = False) -> dict[str, str]:
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=minimal" if write else "return=representation",
    }


def replace_emoji(text: str) -> str:
    return demojize(text, delimiters=("[", "]"), language="en")


def clean_text(text: str | None) -> str:
    text = replace_emoji(text or "")
    text = MENTION_RE.sub("", text)
    return WHITESPACE_RE.sub(" ", text).strip()


class ApiKeyTranslator:
    """Cloud Translation v2 over REST with an API key.

    Mirrors translate_v2.Client.translate(), which only accepts
    service-account or gcloud credentials.
    """

    URL = "https://translation.googleapis.com/language/translate/v2"

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key
        self.session = requests.Session()

    def translate(
        self,
        values: str | list[str],
        target_language: str,
        source_language: str | None = None,
    ) -> dict[str, Any] | list[dict[str, Any]]:
        single = isinstance(values, str)
        payload: dict[str, Any] = {
            "q": [values] if single else list(values),
            "target": target_language,
        }
        if source_language:
            payload["source"] = source_language
        response = self.session.post(
            self.URL, params={"key": self.api_key}, json=payload, timeout=60
        )
        if response.status_code == 400:
            from google.api_core.exceptions import BadRequest

            raise BadRequest(response.text[:500])
        response.raise_for_status()
        translations = response.json()["data"]["translations"]
        return translations[0] if single else translations


def get_translator():
    """Use GOOGLE_TRANSLATE_API_KEY when set, else Google default credentials."""
    global _translator
    if _translator is None:
        api_key = os.environ.get("GOOGLE_TRANSLATE_API_KEY", "").strip()
        if api_key:
            _translator = ApiKeyTranslator(api_key)
        else:
            from google.cloud import translate_v2

            _translator = translate_v2.Client()
    return _translator


def translate_to_english(
    text: str,
    source_language: str | None = None,
) -> tuple[str, str]:
    """Detect the source language and translate comment text with Cloud Translation."""
    normalized_language = str(source_language or "").strip().lower()
    if normalized_language == "zxx":
        # ISO 639-2 uses zxx for text with no linguistic content. Preserve
        # emoji-only and other non-linguistic comments without calling Translate.
        return text, "zxx"
    translator = get_translator()
    options: dict[str, str] = {"target_language": "en"}
    if source_language and normalized_language not in {
        "en",
        "und",
        "mul",
        *X_LANGUAGE_CODES_WITHOUT_TRANSLATABLE_SOURCE,
    }:
        # X still labels Indonesian as "in"; Cloud Translation expects "id".
        options["source_language"] = {"in": "id"}.get(normalized_language, source_language)
    from google.api_core.exceptions import BadRequest

    try:
        result = translator.translate(text, **options)
    except BadRequest:
        # X-specific codes such as qme are not Google language codes. Retry
        # with source-language detection if an explicit code was rejected.
        if "source_language" in options:
            options.pop("source_language")
            try:
                result = translator.translate(text, **options)
            except BadRequest:
                print(
                    f"Skipping translation for unsupported language code "
                    f"{source_language!r}; preserving the original comment."
                )
                return text, str(source_language or "und")
        else:
            print(
                f"Skipping translation for unsupported language code "
                f"{source_language!r}; preserving the original comment."
            )
            return text, str(source_language or "und")
    detected_language = (
        result.get("detectedSourceLanguage")
        or source_language
        or "und"
    )
    return str(result.get("translatedText") or text), str(detected_language)


def translate_comments_batch(comments: list[dict[str, Any]]) -> list[tuple[str, str] | None]:
    """Translate eligible comments in batches, retaining originals on API failure."""
    results: list[tuple[str, str] | None] = [None] * len(comments)
    eligible: list[tuple[int, str, str | None]] = []
    for index, row in enumerate(comments):
        text = first(row, "text", "body", "selftext", "comment", "comment_text", "caption", "title")
        if text is None:
            continue
        language = str(first(row, "lang", "language") or "").strip().lower()
        if language in {"en", "zxx"}:
            continue
        eligible.append((index, str(text), language or None))

    if not eligible:
        return results

    from google.api_core.exceptions import BadRequest

    translator = get_translator()
    batches = translation_batches(eligible)

    for batch_number, batch in enumerate(batches, start=1):
        texts = [text for _, text, _ in batch]
        for attempt in range(TRANSLATION_RETRIES):
            try:
                translated = translator.translate(texts, target_language="en")
                if isinstance(translated, dict):
                    translated = [translated]
                for (row_index, original, source_language), item in zip(batch, translated):
                    results[row_index] = (
                        str(item.get("translatedText") or original),
                        str(item.get("detectedSourceLanguage") or source_language or "und"),
                    )
                break
            except BadRequest as exc:
                # A rejected request fails the same way every time, so
                # retrying cannot help.
                print(
                    f"Translation batch rejected ({exc}); preserving originals "
                    f"for {len(batch)} comments.",
                    flush=True,
                )
                for row_index, original, language in batch:
                    results[row_index] = (original, language or "und")
                break
            except Exception as exc:
                if attempt + 1 < TRANSLATION_RETRIES:
                    delay = 2 ** attempt
                    print(
                        f"Translation batch failed ({exc}); retrying in {delay}s "
                        f"({attempt + 1}/{TRANSLATION_RETRIES - 1})",
                        flush=True,
                    )
                    time.sleep(delay)
                else:
                    print(
                        f"Translation batch failed after {TRANSLATION_RETRIES} attempts "
                        f"({exc}); preserving originals for {len(batch)} comments.",
                        flush=True,
                    )
                    for row_index, original, language in batch:
                        results[row_index] = (original, language or "und")
        # Keep well below Google's documented per-second request quota.
        if batch_number < len(batches):
            time.sleep(0.25)
    return results


def translation_batches(
    eligible: list[tuple[int, str, str | None]],
) -> list[list[tuple[int, str, str | None]]]:
    """Group texts by count and encoded size so each request stays under Google's limit."""
    batches: list[list[tuple[int, str, str | None]]] = []
    batch: list[tuple[int, str, str | None]] = []
    batch_bytes = 0
    for item in eligible:
        # JSON-escaped length: non-ASCII text grows to \uXXXX in the request body.
        item_bytes = len(json.dumps(item[1]))
        if batch and (
            len(batch) >= TRANSLATION_BATCH_SIZE
            or batch_bytes + item_bytes > TRANSLATION_MAX_BATCH_BYTES
        ):
            batches.append(batch)
            batch, batch_bytes = [], 0
        batch.append(item)
        batch_bytes += item_bytes
    if batch:
        batches.append(batch)
    return batches


def first(row: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if row.get(key) is not None:
            return row[key]
    return None


def matched_topics(row: dict[str, Any]) -> list[str]:
    """Read topic metadata across platform-specific source column names."""
    for key in ("matched_keywords", "keywords", "topic"):
        value = row.get(key)
        if isinstance(value, (list, tuple, set)):
            topics = [str(item).strip() for item in value if str(item).strip()]
        elif value is None:
            continue
        else:
            topic = str(value).strip()
            topics = [topic] if topic else []
        if topics:
            return list(dict.fromkeys(topics))
    return []


def inferred_country(row: dict[str, Any]) -> Any:
    """Return the first usable inferred country or country field."""
    for key in ("inferred_country", "country"):
        value = row.get(key)
        if str(value or "").strip().casefold() not in {
            "",
            "none",
            "null",
            "unknown",
            "unspecified",
            "n/a",
        }:
            country = str(value).strip()
            return COUNTRY_ALIASES.get(country.casefold(), country)
    return None


def is_english_youtube_post(row: dict[str, Any]) -> bool:
    """Keep YouTube posts only when their language is known to be English."""
    language = str(first(row, "lang", "language") or "").strip().casefold()
    if language:
        return language == "english" or language == "en" or language.startswith("en-")

    text = " ".join(
        str(row.get(key) or "").strip()
        for key in ("title", "description")
    ).strip()
    if len(text) < 10:
        return False

    global _language_detector
    if _language_detector is None:
        _language_detector = (
            LanguageDetectorBuilder
            .from_all_languages()
            .with_minimum_relative_distance(0.25)
            .build()
        )
    return _language_detector.detect_language_of(text) == Language.ENGLISH


def source_id(row: dict[str, Any], platform: str, source_type: str) -> str | None:
    keys = (
        ("reply_id", "comment_id", "id", "post_id", "name")
        if source_type == "comment"
        else ("post_id", "video_id", "media_id", "id", "name", "comment_id")
    )
    value = first(row, *keys)
    return f"{platform}:{source_type}:{value}" if value else None


def post_url(row: dict[str, Any], platform: str) -> str | None:
    """Use the stored link when the source has one, otherwise build it from the id."""
    url = first(row, "post_url", "url", "postUrl", "permalink")
    if url:
        return str(url)
    if platform == "youtube" and row.get("video_id"):
        return f"https://www.youtube.com/watch?v={row['video_id']}"
    if platform == "x":
        tweet_id = first(row, "post_id", "tweet_id", "id")
        if tweet_id:
            return f"https://x.com/i/status/{tweet_id}"
    return None


def posted_at(row: dict[str, Any], source_type: str, platform: str = "") -> str | None:
    """Normalize the source post/comment timestamp for timestamptz columns."""
    timestamp_keys = (
        (
            "comment_created_at",
            "created_at",
            "created_utc",
            "timestamp",
            "published",
            "published_date",
            "posted_at",
            "published_at",
        )
        if source_type == "comment"
        else (
            "published_at",
            "published_date",
            "published",
            "posted_at",
            "created_utc",
            "timestamp",
            "created_at",
        )
    )
    if platform == "youtube" and source_type == "post":
        # youtube_videos.created_at is the Supabase upload time, not the publish time.
        timestamp_keys = tuple(key for key in timestamp_keys if key != "created_at")
    value = first(row, *timestamp_keys)
    if value is None:
        return None

    try:
        if isinstance(value, (int, float)):
            timestamp = datetime.fromtimestamp(float(value), timezone.utc)
        else:
            text = str(value).strip()
            try:
                timestamp = datetime.fromisoformat(text.replace("Z", "+00:00"))
            except ValueError:
                timestamp = datetime.fromtimestamp(float(text), timezone.utc)
    except (OverflowError, OSError, ValueError) as exc:
        raise ValueError(f"Unsupported source timestamp: {value!r}") from exc

    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return timestamp.astimezone(timezone.utc).isoformat()


def inherit_parent_post_metadata(
    comment: dict[str, Any],
    parent_id: Any,
    post_countries: dict[str, Any],
    post_topics: dict[str, list[str]],
    post_timestamps: dict[str, str | None],
) -> None:
    """Assign linked post metadata used for comment topic and month grouping."""
    if parent_id is None:
        return

    parent_key = str(parent_id)
    parent_country = post_countries.get(parent_key)
    if parent_country:
        comment["inferred_country"] = parent_country
        comment["country"] = parent_country

    inherited_topics = post_topics.get(parent_key, [])
    if inherited_topics:
        comment["matched_keywords"] = list(
            dict.fromkeys(matched_topics(comment) + inherited_topics)
        )
    comment["parent_posted_at"] = post_timestamps.get(parent_key)


def normalize_row(
    row: dict[str, Any],
    platform: str,
    source_type: str,
    source_table: str,
    *,
    translate_comment: bool = False,
    translated_comment: tuple[str, str] | None = None,
) -> dict[str, Any] | None:
    identifier = source_id(row, platform, source_type)
    original_text = first(row, "text", "body", "selftext", "comment", "comment_text", "caption", "title")
    if platform == "youtube" and source_type == "post":
        title = str(row.get("title") or "").strip()
        description = str(row.get("description") or "").strip()
        original_text = "\n\n".join(part for part in (title, description) if part)
    if not identifier or original_text is None:
        return None
    original_text = str(original_text)
    lang = first(row, "lang", "language")
    if translated_comment is not None:
        original_text, lang = translated_comment
    elif translate_comment:
        normalized_language = str(lang or "").strip().lower()
        if normalized_language == "zxx":
            # The text has no natural language to translate; keep it for emoji
            # and other non-linguistic sentiment cues.
            lang = "zxx"
        elif not normalized_language or normalized_language == "und":
            translated_text, detected_language = translate_to_english(original_text)
            lang = detected_language
            if str(lang).lower() != "en":
                original_text = translated_text
        elif normalized_language != "en":
            original_text, lang = translate_to_english(original_text, str(lang))
    likes_value = first(
        row,
        "like_count",
        "likeCount",
        "likes",
        "comment_like_count",
        "score",
        "ups",
    )
    replies_value = first(
        row,
        "reply_count",
        "comments_count",
        "commentsCount",
        "comment_count",
        "commentCount",
        "total_reply_count",
        "num_comments",
    )
    reposts_value = first(row, "repost_count", "retweet_count", "shares")
    quotes_value = first(row, "quote_count")
    likes = int(likes_value) if likes_value is not None else None
    replies = int(replies_value) if replies_value is not None else None
    reposts = int(reposts_value) if reposts_value is not None else None
    quotes = int(quotes_value) if quotes_value is not None else None
    total = first(row, "total_engagement")
    if total is None:
        available_counts = (likes, replies, reposts, quotes)
        if any(value is not None for value in available_counts):
            total = sum(value or 0 for value in available_counts)
    normalized = {
        "source_id": identifier,
        "platform": platform,
        "source_type": source_type,
        "original_text": str(first(row, "text", "body", "selftext", "comment", "comment_text", "caption", "title")),
        "cleaned_text": clean_text(original_text),
        "lang": lang,
        "inferred_country": inferred_country(row),
        "author_id": first(row, "author_id", "user_id", "author", "author_fullname", "username"),
        "conversation_id": first(row, "conversation_id", "video_id", "media_id", "link_id", "post_id", "parent_post_id"),
        "parent_source_id": first(row, "parent_tweet_id", "parent_id", "parent_post_id"),
        "posted_at": posted_at(row, source_type, platform),
        "matched_keywords": matched_topics(row) or None,
        "like_count": likes,
        "reply_count": replies,
        "repost_count": reposts,
        "quote_count": quotes,
        "impression_count": first(row, "impression_count", "view_count", "viewCount"),
        "total_engagement": total,
        "source_table": source_table,
        "cleaned_at": datetime.now(timezone.utc).isoformat(),
    }
    if source_type == "post":
        # clean_comments has no post_url column, so only posts carry it
        normalized["post_url"] = post_url(row, platform)
    if source_type == "comment":
        normalized["parent_posted_at"] = first(row, "parent_posted_at")
        if platform == "youtube":
            # youtube_comments has no publish time; follow the video's published date.
            normalized["posted_at"] = normalized["parent_posted_at"]
    return normalized


def fetch_rows(session: requests.Session, base_url: str, key: str, table: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    offset = 0
    while True:
        response = session.get(
            f"{base_url}/rest/v1/{table}",
            params={"select": "*", "limit": PAGE_SIZE, "offset": offset},
            headers=headers(key),
            timeout=60,
        )
        if response.status_code == 404:
            return []
        response.raise_for_status()
        page = response.json()
        rows.extend(page)
        if len(page) < PAGE_SIZE:
            return rows
        offset += PAGE_SIZE


def upsert(session: requests.Session, base_url: str, key: str, table: str, rows: list[dict[str, Any]]) -> int:
    for start in range(0, len(rows), BATCH_SIZE):
        chunk = rows[start : start + BATCH_SIZE]
        response = session.post(
            f"{base_url}/rest/v1/{table}?on_conflict=source_id",
            json=chunk,
            headers=headers(key, write=True),
            timeout=60,
        )
        if not response.ok:
            raise SystemExit(
                f"{table} upsert failed ({response.status_code}): "
                f"{response.text[:1200]}"
            )
    return len(rows)


def delete_source_ids(
    session: requests.Session,
    base_url: str,
    key: str,
    table: str,
    source_ids: list[str],
) -> int:
    """Remove previously-cleaned rows that no longer meet metadata rules."""
    unique_ids = list(dict.fromkeys(source_ids))
    for start in range(0, len(unique_ids), BATCH_SIZE):
        chunk = unique_ids[start : start + BATCH_SIZE]
        response = session.delete(
            f"{base_url}/rest/v1/{table}",
            params={"source_id": f"in.({','.join(chunk)})"},
            headers=headers(key, write=True),
            timeout=60,
        )
        response.raise_for_status()
    return len(unique_ids)


def clear_cleaned_tables(
    session: requests.Session,
    base_url: str,
    key: str,
) -> dict[str, int]:
    """Delete existing cleaned rows before an explicit full refresh."""
    deleted: dict[str, int] = {}
    for table in ("clean_posts", "clean_comments"):
        source_ids: list[str] = []
        offset = 0
        while True:
            response = session.get(
                f"{base_url}/rest/v1/{table}",
                params={
                    "select": "source_id",
                    "limit": PAGE_SIZE,
                    "offset": offset,
                },
                headers=headers(key),
                timeout=60,
            )
            response.raise_for_status()
            page = response.json()
            source_ids.extend(
                str(row["source_id"])
                for row in page
                if row.get("source_id") is not None
            )
            if len(page) < PAGE_SIZE:
                break
            offset += PAGE_SIZE
        deleted[table] = delete_source_ids(
            session,
            base_url,
            key,
            table,
            source_ids,
        )
        print(f"{table}: cleared {deleted[table]} existing rows", flush=True)
    return deleted


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Normalize social-media rows into shared Supabase tables."
    )
    parser.add_argument(
        "--full-refresh",
        action="store_true",
        help="Delete all existing clean_posts and clean_comments rows before rebuilding them.",
    )
    args = parser.parse_args()

    base_url, key = credentials()
    session = requests.Session()
    if args.full_refresh:
        clear_cleaned_tables(session, base_url, key)

    platform_tables = (
        ("x", "x_posts", "x_replies"),
        ("reddit", "reddit_posts", "reddit_comments"),
        ("youtube", "youtube_videos", "youtube_comments"),
        ("instagram", "instagram_posts", "instagram_comments"),
        ("facebook", "facebook_posts", "facebook_comments"),
    )
    counts = {"clean_posts": 0, "clean_comments": 0}
    for platform, post_table, comment_table in platform_tables:
        print(
            f"Processing {platform}: reading {post_table} and {comment_table}...",
            flush=True,
        )
        posts = fetch_rows(session, base_url, key, post_table)
        comments = fetch_rows(session, base_url, key, comment_table)
        print(
            f"{platform}: fetched {len(posts)} posts and {len(comments)} comments",
            flush=True,
        )
        post_countries = {
            str(first(row, "post_id", "video_id", "media_id", "id", "name")): inferred_country(row)
            for row in posts
            if first(row, "post_id", "video_id", "media_id", "id", "name") is not None
        }
        post_topics = {
            str(first(row, "post_id", "video_id", "media_id", "id", "name")): matched_topics(row)
            for row in posts
            if first(row, "post_id", "video_id", "media_id", "id", "name") is not None
        }
        post_timestamps = {
            str(first(row, "post_id", "video_id", "media_id", "id", "name")): posted_at(row, "post", platform)
            for row in posts
            if first(row, "post_id", "video_id", "media_id", "id", "name") is not None
        }
        cleaned_posts = []
        excluded_posts = []
        for item in posts:
            if inferred_country(item) is None or (
                platform == "youtube" and not is_english_youtube_post(item)
            ):
                identifier = source_id(item, platform, "post")
                if identifier:
                    excluded_posts.append(identifier)
                continue
            normalized = normalize_row(item, platform, "post", post_table)
            if normalized:
                cleaned_posts.append(normalized)
        cleaned_comments = []
        excluded_comments = []
        eligible_comments = []
        for item in comments:
            comment = dict(item)
            parent_id = first(
                comment,
                "post_id",
                "video_id",
                "media_id",
                "parent_post_id",
                "link_id",
                "conversation_id",
            )
            inherit_parent_post_metadata(
                comment,
                parent_id,
                post_countries,
                post_topics,
                post_timestamps,
            )
            if not matched_topics(comment):
                identifier = source_id(comment, platform, "comment")
                if identifier:
                    excluded_comments.append(identifier)
                continue
            eligible_comments.append(comment)

        translations = translate_comments_batch(eligible_comments)
        for comment, translation in zip(eligible_comments, translations):
            normalized = normalize_row(
                comment,
                platform,
                "comment",
                comment_table,
                translate_comment=translation is None,
                translated_comment=translation,
            )
            if normalized:
                cleaned_comments.append(normalized)
        counts["clean_posts"] += upsert(session, base_url, key, "clean_posts", cleaned_posts)
        counts["clean_comments"] += upsert(session, base_url, key, "clean_comments", cleaned_comments)
        deleted_posts = delete_source_ids(
            session, base_url, key, "clean_posts", excluded_posts
        )
        deleted_comments = delete_source_ids(
            session, base_url, key, "clean_comments", excluded_comments
        )
        print(f"{post_table} -> clean_posts: {len(cleaned_posts)} rows", flush=True)
        print(f"{comment_table} -> clean_comments: {len(cleaned_comments)} rows", flush=True)
        print(
            f"{platform}: excluded {deleted_posts} posts without inferred country and "
            f"{deleted_comments} replies without topic metadata",
            flush=True,
        )
    print(counts)


if __name__ == "__main__":
    main()
