import os
import numpy as np
import pandas as pd
import sys
from dotenv import load_dotenv
from google import genai
from supabase import create_client, Client
from datetime import date
import json
import time

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

# inferred_country may hold either the full name or the region code
COUNTRIES = {
    "Brunei": "BN",
    "Indonesia": "ID",
    "Malaysia": "MY",
    "Philippines": "PH",
    "Singapore": "SG",
    "Thailand": "TH",
}

# Below this many posts for a country-keywords-month pair, fall back to posts from all countries
MIN_POSTS = 20

# Number of top- and bottom-performing post links stored with each analysis
TOP_POST_LINKS = 5
BOTTOM_POST_LINKS = 5

# Attempts per Gemini call before giving up on a topic
GEMINI_RETRIES = 5

def get_previous_month():
    """
    Returns the first day of the previous month in 'YYYY-MM-01' format.
    """
    today = date.today()
    
    if today.month == 1:
        prev_month = 12
        prev_year = today.year - 1
    else:
        prev_month = today.month - 1
        prev_year = today.year

    return f"{prev_year}-{prev_month:02d}-01"

def get_monthly_keywords(supabase, country, month):
    response = supabase.table("monthly_topic_stats").select("topic_name, monthly_keywords").eq("country", country).lte("topic_rank", 3).eq("month", month).execute()
    list_of_keywords = response.data
    return list_of_keywords

def get_analysed_topics(supabase, month):
    """
    Returns the (country, topic_name) pairs that already have an analysis for the month.
    Topics last analysed in an earlier month are not returned, so they are re-analysed
    and the newer result replaces the old row.
    """
    response = supabase.table("topic_based_analysis").select("country, topic_name").eq("month", month).execute()
    return {(row.get("country"), row.get("topic_name")) for row in response.data}

def fetch_posts_by_country_keyword(supabase, countries, keywords, month):
    """
    Fetches posts matching the keywords for the month.
    Pass countries=None to fetch posts from every country.
    """
    year, month_num, _ = month.split('-')
    y, m = int(year), int(month_num)
    
    if m == 12:
        next_y, next_m = y + 1, 1
    else:
        next_y, next_m = y, m + 1
        
    start_timestamp = f"{y}-{m:02d}-01T00:00:00+00:00"
    end_timestamp = f"{next_y}-{next_m:02d}-01T00:00:00+00:00"

    # Supabase caps each request at 1000 rows, so page through until exhausted.
    # Ordering by the unique source_id keeps pages from overlapping or skipping rows.
    all_posts = []
    offset = 0
    while True:
        query = supabase.table('clean_posts') \
            .select('cleaned_text, total_engagement, platform, post_url') \
            .overlaps('matched_keywords', keywords) \
            .gte('posted_at', start_timestamp) \
            .lt('posted_at', end_timestamp)

        if countries is not None:
            query = query.in_('inferred_country', countries)

        response = query \
            .order('source_id') \
            .range(offset, offset + PAGE_SIZE - 1) \
            .execute()

        all_posts.extend(response.data)
        if len(response.data) < PAGE_SIZE:
            break
        offset += PAGE_SIZE

    return all_posts

def segment_posts(posts_data):
    # Sort posts by the pre-existing total_engagement column descending
    # Default to 0 if the value is somehow None/Null
    sorted_posts = sorted(posts_data, key=lambda x: x.get('total_engagement') or 0, reverse=True)
    
    # Split into top 25% and bottom 25% for stark contrast
    quarter_index = max(1, len(sorted_posts) // 4)
    top_posts = sorted_posts[:quarter_index]
    bottom_posts = sorted_posts[-quarter_index:]
    
    top_posts = [p for p in top_posts if p.get('cleaned_text')]
    # Lowest engagement first, so the worst performers are linked first
    bottom_posts = [p for p in reversed(bottom_posts) if p.get('cleaned_text')]

    # Tag each text with its platform so the model can account for platform conventions
    top_texts = [f"[{p.get('platform') or 'Unknown'}] {p['cleaned_text']}" for p in top_posts]
    bottom_texts = [f"[{p.get('platform') or 'Unknown'}] {p['cleaned_text']}" for p in bottom_posts]

    # URLs aligned with the texts, so the model's chosen post numbers can be mapped back to links
    top_urls = [p.get('post_url') for p in top_posts]
    bottom_urls = [p.get('post_url') for p in bottom_posts]

    return top_texts, bottom_texts, top_urls, bottom_urls

def select_links(urls, environmental_post_numbers, limit):
    """
    Keeps links only for the posts the model judged to be about the environment,
    in the order given, capped at limit.
    """
    numbers = set()
    for n in environmental_post_numbers or []:
        try:
            numbers.add(int(n))
        except (TypeError, ValueError):
            continue

    links = [url for i, url in enumerate(urls, start=1) if i in numbers and url]
    return links[:limit]


def generate_engagement_analysis(country, keywords, top_posts, bottom_posts, scope="country"):
    keywords_str = ", ".join(keywords)
    # Number the posts so the model can say which ones are environment-related
    top_str = " | ".join(f"#{i} {text}" for i, text in enumerate(top_posts, start=1))
    bottom_str = " | ".join(f"#{i} {text}" for i, text in enumerate(bottom_posts, start=1))

    if scope == "regional":
        source = f"across Southeast Asia (there are too few posts from {country} alone, so treat these as a regional proxy for {country} audiences)"
    else:
        source = f"from {country}"

    prompt = f"""You are a social media strategist for an environmental storytelling non-profit analyzing posts {source} about: {keywords_str}.
    
    Compare these HIGH engagement posts:
    {top_str}
    
    Against these LOW engagement posts:
    {bottom_str}
    
    Extract the key communication features that drive high engagement.

    The creators acting on your advice produce SHORT-FORM VERTICAL VIDEO for TikTok and Instagram Reels (9:16, roughly 15-60 seconds, viewed with sound on but often skipped within 1-3 seconds).
    The posts above may come from other platforms or formats; translate what works in them into short-form video terms. Every value must be something a creator can film, edit or post as a Reel/TikTok:
    - Think in seconds and shots (e.g. "0-2s: show the flooded street", "cut every 2-3 seconds").
    - Cover on-screen text overlays, voiceover vs. talking-to-camera, trending sounds/audio, jump cuts, captions burned into the video, and loop-friendly endings where relevant.
    - Do not recommend long-form formats (articles, threads, long YouTube videos, carousels) or platform features outside TikTok/Reels.

    Return EXACTLY a JSON object with the following keys. All values MUST be written in concise, imperative point form. Do not write descriptive or comparative paragraphs.
    (Example: Write "Open on a close-up of the bleached coral with a bold text overlay." instead of "High-engagement content leans heavily into dynamic visuals compared to low-engagement posts.")

    Each post is prefixed with its number within its group, e.g. #3, and its platform in square brackets, e.g. [YouTube].

    For "environmental_top_post_numbers" and "environmental_bottom_post_numbers", list the numbers of HIGH and LOW engagement posts respectively whose content is genuinely about the environment (e.g. climate, conservation, pollution, biodiversity, sustainability). Exclude posts that only match the keywords incidentally, such as unrelated news, entertainment, sales or spam. Return an empty list if none qualify.

    {{
        "environmental_top_post_numbers": [1, 2, 5],
        "environmental_bottom_post_numbers": [3, 4],
        "tone_and_emotion": "Actionable points on tone, delivery and pacing on camera (e.g., 'Speak fast and urgently to camera. Shift to hopeful music for the solution.').",
        "recommendations": "2-3 highly specific, actionable tips for maximising reach on TikTok/Reels (e.g., 'Post a 20-second reaction to local haze news using a trending sound.').",
        "key_message": "The one core message the video should land, short enough for a text overlay (e.g., 'Mangrove loss threatens local fishing livelihoods.').",
        "narrative_method": "The on-camera storytelling approach (e.g., 'Follow one fisherman through his day. Use first-person talking-to-camera clips.').",
        "content_type": "The short-form video format to produce (e.g., 'Make a 30-second on-the-ground explainer. Duet or stitch a viral clip with local data.').",
        "story_structure": "A second-by-second beat outline with total length (e.g., '0-3s hook on the problem, 3-20s human impact, 20-30s solution and CTA. Keep under 30 seconds. End on a frame that loops back to the start.').",
        "hooks": "Specific first 1-3 second hooks: opening line, visual and text overlay (e.g., 'Say: \\"This beach was white sand last year.\\" while panning across plastic waste.').",
        "call_to_action": "Specific CTAs suited to TikTok/Reels, said on screen or in the caption (e.g., 'Ask viewers to comment their city. Prompt saves with \\"Save this for your next beach trip.\\"').",
        "captions": "Actionable points on the post caption and on-screen text: length, keywords for search, hashtags and emojis.",
        "what_not_to_do": "Short-form video mistakes to avoid, drawn from the LOW engagement posts (e.g., 'Do not open with a logo or slow intro.')."
    }}
    """
    
    # Gemini returns 503/429 under high demand, so retry with exponential backoff
    for attempt in range(1, GEMINI_RETRIES + 1):
        try:
            response = gemini_client.models.generate_content(
                model='gemini-3.1-flash-lite',
                contents=prompt,
            )
            clean_json = response.text.strip().removeprefix("```json").removesuffix("```").strip()
            return clean_json

        except Exception as e:
            retryable = any(code in str(e) for code in ("503", "429", "UNAVAILABLE", "RESOURCE_EXHAUSTED"))
            if retryable and attempt < GEMINI_RETRIES:
                wait = 2 ** attempt * 5
                print(f"Gemini busy (attempt {attempt}/{GEMINI_RETRIES}), retrying in {wait}s...")
                time.sleep(wait)
                continue
            print(f"Error generating analysis: {e}")
            return None

def main():
    # Optional month override in 'YYYY-MM-01' format, e.g. python topic_based_analysis.py 2026-09-01
    month = sys.argv[1] if len(sys.argv) > 1 else get_previous_month()
    analysed_topics = get_analysed_topics(supabase, month)

    for country, region_code in COUNTRIES.items():
        possible_country_spellings = [country, region_code]
        list_of_keywords = get_monthly_keywords(supabase, country, month)

        for row in list_of_keywords:
            topic_name = row.get("topic_name")
            keyword_string = row.get("monthly_keywords", "")
            keywords_list = [kw.strip() for kw in keyword_string.split(",") if kw.strip()]

            if not keywords_list:
                continue

            # Only analyse topics that are new since the last run
            if (country, topic_name) in analysed_topics:
                print(f"Skipping {country} / {topic_name}: analysis already exists for {month}.")
                continue

            posts_data = fetch_posts_by_country_keyword(supabase, possible_country_spellings, keywords_list, month)
            scope = "country"

            # Too few country posts for a reliable contrast, so widen to every country
            if len(posts_data) < MIN_POSTS:
                regional_posts = fetch_posts_by_country_keyword(supabase, None, keywords_list, month)
                if len(regional_posts) > len(posts_data):
                    print(f"Only {len(posts_data)} post(s) for {country} / {keyword_string}; using {len(regional_posts)} regional posts.")
                    posts_data = regional_posts
                    scope = "regional"

            if posts_data:
                top_texts, bottom_texts, top_urls, bottom_urls = segment_posts(posts_data)

                if top_texts and bottom_texts:
                    analysis_text = generate_engagement_analysis(country, keywords_list, top_texts, bottom_texts, scope)
                    
                    if analysis_text:
                        try:
                            analysis_dict = json.loads(analysis_text)
                            top_links = select_links(top_urls, analysis_dict.get('environmental_top_post_numbers'), TOP_POST_LINKS)
                            bottom_links = select_links(bottom_urls, analysis_dict.get('environmental_bottom_post_numbers'), BOTTOM_POST_LINKS)

                            # Prepare the payload mapping JSON keys to your DB columns
                            payload = {
                                'month': month,
                                'country': country,
                                'topic_name': topic_name,
                                'keywords': keywords_list,
                                'tone_and_emotion': analysis_dict.get('tone_and_emotion', ''),
                                'recommendations': analysis_dict.get('recommendations', ''),
                                'key_message': analysis_dict.get('key_message', ''),
                                'narrative_method': analysis_dict.get('narrative_method', ''),
                                'content_type': analysis_dict.get('content_type', ''),
                                'story_structure': analysis_dict.get('story_structure', ''),
                                'hooks': analysis_dict.get('hooks', ''),
                                'call_to_action': analysis_dict.get('call_to_action', ''),
                                'captions': analysis_dict.get('captions', ''),
                                'what_not_to_do': analysis_dict.get('what_not_to_do', ''),
                                'top_post_links': top_links,
                                'bottom_post_links': bottom_links
                            }
                            
                            # Upsert to Supabase
                            db_response = (
                                supabase
                                .table("topic_based_analysis")
                                .upsert(
                                    payload,
                                    on_conflict="topic_name,country"
                                )
                                .execute()
                            )
                            # RLS can silently block a write, returning no rows instead of raising
                            if db_response.data:
                                print(f"Successfully inserted analysis for {country} / {keyword_string}")
                            else:
                                print(f"No rows written for {country} / {keyword_string}: check RLS insert/update policies on 'topic_based_analysis'.")
                            
                        except json.JSONDecodeError:
                            print(f"Failed to parse JSON for {country} / {keyword_string}. Raw output: {analysis_text}")
                        except Exception as e:
                            print(f"Database error for {country} / {keyword_string}: {e}")
                else:
                    print(f"Not enough posts to perform contrastive analysis for {country} / {keyword_string}.")
            else:
                print(f"No posts found for {country} / {keyword_string}.")

if __name__ == "__main__":
    main()