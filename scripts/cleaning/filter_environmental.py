import os
import sys
import json
import time
import argparse
from dotenv import load_dotenv
from google import genai
from supabase import create_client, Client

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))

load_dotenv(os.path.join(project_root, '.env'), override=True)
gemini_client = genai.Client()

if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Supabase setup
url = os.environ.get("SUPABASE_URL", "")
key = os.environ.get("SUPABASE_KEY", "")

supabase: Client = create_client(url, key)

PAGE_SIZE = 1000

# Posts classified per Gemini call
BATCH_SIZE = 50

# Long posts are truncated; the opening is enough to judge the subject
MAX_TEXT_CHARS = 1000

# Attempts per Gemini call before giving up on a batch
GEMINI_RETRIES = 5

def fetch_posts(supabase, reclassify=False):
    """
    Fetches posts to classify. By default only posts not yet classified
    (is_environmental is null); pass reclassify=True to fetch every post.
    """
    # Supabase caps each request at 1000 rows, so page through until exhausted.
    # Ordering by the unique id keeps pages from overlapping or skipping rows.
    all_posts = []
    offset = 0
    while True:
        query = supabase.table('clean_posts').select('id, cleaned_text, platform')

        if not reclassify:
            query = query.is_('is_environmental', 'null')

        response = query \
            .order('id') \
            .range(offset, offset + PAGE_SIZE - 1) \
            .execute()

        all_posts.extend(response.data)
        if len(response.data) < PAGE_SIZE:
            break
        offset += PAGE_SIZE

    return all_posts

def classify_batch(posts):
    """
    Returns the set of post ids Gemini judged to be environmentally related,
    or None if the call failed.
    """
    posts_str = "\n".join(
        f"#{i} [{p.get('platform') or 'Unknown'}] {(p.get('cleaned_text') or '')[:MAX_TEXT_CHARS]}"
        for i, p in enumerate(posts, start=1)
    )

    prompt = f"""You are screening social media posts for an environmental storytelling non-profit in Southeast Asia.

    Decide for each post whether its content is genuinely about the environment, e.g. climate change, extreme weather, pollution, haze, waste and recycling, conservation, wildlife and biodiversity, forests, oceans and marine life, energy transition, sustainability, or environmental health.

    Exclude posts that only mention an environmental word incidentally, such as unrelated news, politics, entertainment, sports, product sales, promotions, spam, or posts with too little text to judge.

    Each post is prefixed with its number, e.g. #3, and its platform in square brackets, e.g. [YouTube].

    Posts:
    {posts_str}

    Return EXACTLY a JSON object of the form {{"environmental_post_numbers": [1, 4, 7]}} listing the numbers of the environmentally related posts. Return an empty list if none qualify.
    """

    # Gemini returns 503/429 under high demand, so retry with exponential backoff
    for attempt in range(1, GEMINI_RETRIES + 1):
        try:
            response = gemini_client.models.generate_content(
                model='gemini-3.1-flash-lite',
                contents=prompt,
                config={'response_mime_type': 'application/json'},
            )
            clean_json = response.text.strip().removeprefix("```json").removesuffix("```").strip()
            numbers = json.loads(clean_json).get('environmental_post_numbers') or []
            break

        except json.JSONDecodeError:
            print(f"Failed to parse JSON from Gemini. Raw output: {response.text}")
            return None
        except Exception as e:
            retryable = any(code in str(e) for code in ("503", "429", "UNAVAILABLE", "RESOURCE_EXHAUSTED"))
            if retryable and attempt < GEMINI_RETRIES:
                wait = 2 ** attempt * 5
                print(f"Gemini busy (attempt {attempt}/{GEMINI_RETRIES}), retrying in {wait}s...")
                time.sleep(wait)
                continue
            print(f"Error classifying batch: {e}")
            return None

    environmental_ids = set()
    for n in numbers:
        try:
            i = int(n)
        except (TypeError, ValueError):
            continue
        if 1 <= i <= len(posts):
            environmental_ids.add(posts[i - 1]['id'])
    return environmental_ids

def save_labels(supabase, ids, value):
    """
    Sets is_environmental on the given post ids. Returns the number of rows written.
    """
    if not ids:
        return 0
    response = supabase.table('clean_posts').update({'is_environmental': value}).in_('id', ids).execute()
    return len(response.data)

def parse_args():
    parser = argparse.ArgumentParser(description="Flag clean_posts as environmentally related using Gemini.")
    parser.add_argument(
        "--reclassify",
        action="store_true",
        help="Classify every post again, not just posts that have not been classified yet.",
    )
    return parser.parse_args()

def main():
    args = parse_args()
    posts = fetch_posts(supabase, reclassify=args.reclassify)
    print(f"{len(posts)} post(s) to classify.")

    # Posts with no text cannot be judged, so mark them as not environmental without a Gemini call
    empty_ids = [p['id'] for p in posts if not (p.get('cleaned_text') or '').strip()]
    posts = [p for p in posts if (p.get('cleaned_text') or '').strip()]
    save_labels(supabase, empty_ids, False)

    environmental_total = 0
    written_total = 0
    for start in range(0, len(posts), BATCH_SIZE):
        batch = posts[start:start + BATCH_SIZE]
        environmental_ids = classify_batch(batch)

        # Leave the batch unclassified (null) so the next run retries it
        if environmental_ids is None:
            print(f"Skipping posts {start + 1}-{start + len(batch)}: classification failed.")
            continue

        other_ids = [p['id'] for p in batch if p['id'] not in environmental_ids]
        written = save_labels(supabase, list(environmental_ids), True) + save_labels(supabase, other_ids, False)

        # RLS can silently block a write, returning no rows instead of raising
        if written < len(batch):
            print(f"Only {written}/{len(batch)} rows written for posts {start + 1}-{start + len(batch)}: check RLS update policies on 'clean_posts'.")

        environmental_total += len(environmental_ids)
        written_total += written
        print(f"Posts {start + 1}-{start + len(batch)}: {len(environmental_ids)} environmental.")

    print(f"Done. {environmental_total} environmental post(s); {written_total} row(s) updated, plus {len(empty_ids)} empty post(s) marked not environmental.")

if __name__ == "__main__":
    main()
