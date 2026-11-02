import os
import numpy as np
import pandas as pd
import sys
from dotenv import load_dotenv
from google import genai
from supabase import create_client, Client
from datetime import date
import json

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
    response = supabase.table("monthly_topic_stats").select("monthly_keywords").eq("country", country).lte("topic_rank", 3).eq("month", month).execute()
    list_of_keywords = response.data
    return list_of_keywords

def get_analysed_keywords(supabase, month):
    """
    Returns the (country, keyword set) pairs that already have an analysis for the month,
    using frozensets so keyword order does not matter when comparing.
    """
    response = supabase.table("topic_based_analysis").select("country, keywords").eq("month", month).execute()
    return {(row.get("country"), frozenset(row.get("keywords") or [])) for row in response.data}

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
            .select('cleaned_text, total_engagement') \
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
    
    # Extract just the text for the prompt
    top_texts = [p.get('cleaned_text', '') for p in top_posts if p.get('cleaned_text')]
    bottom_texts = [p.get('cleaned_text', '') for p in bottom_posts if p.get('cleaned_text')]
    
    return top_texts, bottom_texts


def generate_engagement_analysis(country, keywords, top_posts, bottom_posts, scope="country"):
    keywords_str = ", ".join(keywords)
    top_str = " | ".join(top_posts)
    bottom_str = " | ".join(bottom_posts)

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
    
    Return EXACTLY a JSON object with the following keys. All values MUST be written in concise, imperative point form. Do not write descriptive or comparative paragraphs. 
    (Example: Write "Utilise dynamic video storytelling." instead of "High-engagement content leans heavily into dynamic video storytelling compared to low-engagement posts.")
    
    {{
        "tone_and_emotion": "Actionable points on the most effective tone (e.g., 'Use urgent, solution-focused language. Avoid passive descriptions.').",
        "content_structure": "Actionable points on optimal length and formatting (e.g., 'Keep sentences under 15 words. Structure for mobile feeds.').",
        "hooks_and_ctas": "Actionable points identifying the best hooks or call-to-actions to replicate.",
        "recommendations": "2-3 highly specific, actionable tips for creators to maximize reach."
    }}
    """
    
    try:
        response = gemini_client.models.generate_content(
            model='gemini-3.1-flash-lite',
            contents=prompt,
        )
        clean_json = response.text.strip().removeprefix("```json").removesuffix("```").strip()
        return clean_json
        
    except Exception as e:
        print(f"Error generating analysis: {e}")
        return None

def main():
    # Optional month override in 'YYYY-MM-01' format, e.g. python topic_based_analysis.py 2026-09-01
    month = sys.argv[1] if len(sys.argv) > 1 else get_previous_month()
    analysed_keywords = get_analysed_keywords(supabase, month)

    for country, region_code in COUNTRIES.items():
        possible_country_spellings = [country, region_code]
        list_of_keywords = get_monthly_keywords(supabase, country, month)

        for row in list_of_keywords:
            keyword_string = row.get("monthly_keywords", "")
            keywords_list = [kw.strip() for kw in keyword_string.split(",") if kw.strip()]
            
            if not keywords_list:
                continue

            # Only analyse topics that are new since the last run
            if (country, frozenset(keywords_list)) in analysed_keywords:
                print(f"Skipping {country} / {keyword_string}: analysis already exists for {month}.")
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
                top_texts, bottom_texts = segment_posts(posts_data)

                if top_texts and bottom_texts:
                    analysis_text = generate_engagement_analysis(country, keywords_list, top_texts, bottom_texts, scope)
                    
                    if analysis_text:
                        try:
                            analysis_dict = json.loads(analysis_text)
                            
                            # Prepare the payload mapping JSON keys to your DB columns
                            payload = {
                                'month': month,
                                'country': country,
                                'keywords': keywords_list,
                                'tone_and_emotion': analysis_dict.get('tone_and_emotion', ''),
                                'content_structure': analysis_dict.get('content_structure', ''),
                                'hooks_and_ctas': analysis_dict.get('hooks_and_ctas', ''),
                                'recommendations': analysis_dict.get('recommendations', '')
                            }
                            
                            # Upsert to Supabase
                            db_response = (
                                supabase
                                .table("topic_based_analysis")
                                .upsert(
                                    payload,
                                    on_conflict="country, keywords, month"
                                )
                                .execute()
                            )
                            print(f"Successfully inserted analysis for {country} / {keyword_string}")
                            
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