"""Classify unlabelled clean_posts rows as environmentally related using Gemini."""

import argparse
import json
import os
import time

from dotenv import load_dotenv
from google import genai
from supabase import create_client


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
load_dotenv(os.path.join(PROJECT_ROOT, ".env"), override=True)
supabase = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
gemini_client = genai.Client()

PAGE_SIZE = 1000
BATCH_SIZE = 50
MAX_TEXT_CHARS = 1000
GEMINI_RETRIES = 5


def fetch_posts(reclassify: bool = False) -> list[dict]:
    """Fetch only unclassified rows unless reclassification is requested."""
    posts, offset = [], 0
    while True:
        query = supabase.table("clean_posts").select("id, cleaned_text, platform")
        if not reclassify:
            query = query.is_("is_environmental", "null")
        page = query.order("id").range(offset, offset + PAGE_SIZE - 1).execute().data
        posts.extend(page)
        if len(page) < PAGE_SIZE:
            return posts
        offset += PAGE_SIZE


def classify_batch(posts: list[dict]) -> set | None:
    post_text = "\n".join(
        f"#{index} [{post.get('platform') or 'Unknown'}] {(post.get('cleaned_text') or '')[:MAX_TEXT_CHARS]}"
        for index, post in enumerate(posts, start=1)
    )
    prompt = f'''You are screening social media posts for an environmental storytelling non-profit in Southeast Asia.

Decide for each post whether its content is genuinely about the environment, e.g. climate change, extreme weather, pollution, haze, waste and recycling, conservation, wildlife and biodiversity, forests, oceans and marine life, energy transition, sustainability, or environmental health.

Exclude posts that only mention an environmental word incidentally, such as unrelated news, politics, entertainment, sports, product sales, promotions, spam, or posts with too little text to judge.

Posts:
{post_text}

Return EXACTLY a JSON object of the form {{"environmental_post_numbers": [1, 4, 7]}} listing the numbers of the environmentally related posts. Return an empty list if none qualify.'''

    for attempt in range(1, GEMINI_RETRIES + 1):
        try:
            response = gemini_client.models.generate_content(
                model="gemini-3.1-flash-lite",
                contents=prompt,
                config={"response_mime_type": "application/json"},
            )
            text = response.text.strip().removeprefix("```json").removesuffix("```").strip()
            numbers = json.loads(text).get("environmental_post_numbers") or []
            environmental_ids = set()
            for number in numbers:
                try:
                    index = int(number)
                except (TypeError, ValueError):
                    continue
                if 1 <= index <= len(posts):
                    environmental_ids.add(posts[index - 1]["id"])
            return environmental_ids
        except json.JSONDecodeError:
            print(
                f"Failed to parse Gemini JSON (attempt {attempt}/{GEMINI_RETRIES}): "
                f"{response.text}",
                flush=True,
            )
            if attempt < GEMINI_RETRIES:
                continue
            return None
        except Exception as error:
            retryable = any(code in str(error) for code in ("503", "429", "UNAVAILABLE", "RESOURCE_EXHAUSTED"))
            if retryable and attempt < GEMINI_RETRIES:
                delay = 2 ** attempt * 5
                print(f"Gemini busy (attempt {attempt}/{GEMINI_RETRIES}), retrying in {delay}s...", flush=True)
                time.sleep(delay)
                continue
            print(f"Error classifying batch: {error}", flush=True)
            return None


def save_labels(ids: list, value: bool) -> int:
    if not ids:
        return 0
    response = supabase.table("clean_posts").update({"is_environmental": value}).in_("id", ids).execute()
    return len(response.data)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reclassify", action="store_true")
    args = parser.parse_args()
    posts = fetch_posts(reclassify=args.reclassify)
    print(f"{len(posts)} post(s) to classify.", flush=True)

    empty_ids = [post["id"] for post in posts if not (post.get("cleaned_text") or "").strip()]
    posts = [post for post in posts if (post.get("cleaned_text") or "").strip()]
    save_labels(empty_ids, False)

    environmental_total = written_total = 0
    failed_batches = 0
    for start in range(0, len(posts), BATCH_SIZE):
        batch = posts[start:start + BATCH_SIZE]
        environmental_ids = classify_batch(batch)
        if environmental_ids is None:
            print(f"Skipping posts {start + 1}-{start + len(batch)}: classification failed.", flush=True)
            failed_batches += 1
            continue
        other_ids = [post["id"] for post in batch if post["id"] not in environmental_ids]
        written = save_labels(list(environmental_ids), True) + save_labels(other_ids, False)
        environmental_total += len(environmental_ids)
        written_total += written
        print(f"Posts {start + 1}-{start + len(batch)}: {len(environmental_ids)} environmental.", flush=True)

    print(f"Done. {environmental_total} environmental post(s); {written_total} row(s) updated, plus {len(empty_ids)} empty post(s) marked not environmental.", flush=True)
    if failed_batches:
        raise SystemExit(
            f"Environmental classification incomplete: {failed_batches} batch(es) failed. "
            "Run the classifier again to retry remaining null rows."
        )


if __name__ == "__main__":
    main()
