import os
import numpy as np
import pandas as pd
import json
import sys
from dotenv import load_dotenv
from google import genai
from supabase import create_client, Client
from datetime import date

load_dotenv()
gemini_client = genai.Client()

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))

if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Supabase setup
url = os.environ.get("SUPABASE_URL", "")
key = os.environ.get("SUPABASE_KEY", "")

supabase: Client = create_client(url, key)

with open('../sources/locations.json', "r") as locations_file:
    COUNTRIES = json.load(locations_file)

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
        
    # Format with zero-padding for single-digit months
    return f"{prev_year}-{prev_month:02d}-01"

def get_monthly_keywords(supabase, country, month):
    # keywords = []
    response = supabase.table("monthly_topic_stats").select("monthly_keywords").eq("country", country).lte("topic_rank", 3).eq("month", month).execute()
    list_of_keywords = response.data
    # keywords = [kw.strip()
    #     for item in list_of_keywords
    #     for kw in item['monthly_keywords'].split(',')]
    return list_of_keywords

def fetch_posts_by_country_keyword(supabase, countries, keywords, month):
    # 1. Parse the year and month
    year, month_num, _ = month.split('-')
    y, m = int(year), int(month_num)
    
    # 2. Calculate the first day of the NEXT month
    if m == 12:
        next_y, next_m = y + 1, 1
    else:
        next_y, next_m = y, m + 1
        
    start_timestamp = f"{y}-{m:02d}-01T00:00:00+00:00"
    end_timestamp = f"{next_y}-{next_m:02d}-01T00:00:00+00:00"

    # 3. Fetch data using list and timestamp filters
    response = supabase.table('clean_posts') \
        .select('cleaned_text') \
        .in_('inferred_country', countries) \
        .overlaps('matched_keywords', keywords) \
        .gte('posted_at', start_timestamp) \
        .lt('posted_at', end_timestamp) \
        .execute()
        
    return response.data

def fetch_comments_by_country_keyword(supabase, country, keywords, month):
    # 1. Parse the year and month from your 'YYYY-MM-01' string
    year, month_num, _ = month.split('-')
    y, m = int(year), int(month_num)
    
    # 2. Calculate the first day of the NEXT month for the strict cutoff
    if m == 12:
        next_y, next_m = y + 1, 1
    else:
        next_y, next_m = y, m + 1
        
    # Format timestamps for Supabase (e.g., 2026-09-01T00:00:00+00:00)
    start_timestamp = f"{y}-{m:02d}-01T00:00:00+00:00"
    end_timestamp = f"{next_y}-{next_m:02d}-01T00:00:00+00:00"

    # 3. Use .gte() and .lt() to capture everything inside that month
    response = supabase.table('clean_comments') \
        .select('cleaned_text') \
        .in_('inferred_country', country) \
        .overlaps('matched_keywords', keywords) \
        .gte('parent_posted_at', start_timestamp) \
        .lt('parent_posted_at', end_timestamp) \
        .execute()
        
    return response.data
    
def generate_discussion_summary(sample_texts, keywords):
    # Join all comments together. No need to restrict to sample_texts[:5] anymore.
    # ~200 comments will easily fit within Gemini's context window.
    combined_comments = " | ".join(sample_texts)
    keywords = " | ".join(keywords)
    
    prompt = f"""Read the following social media comments and extract only those related to {keywords}.
    Summarize the main consensus, overall sentiment, and primary concerns expressed by the users in up to 3 bullet points. 
    Avoid points with repeated content. Give the results in the following format {{ "Topic1":"Summary1", "Topic2":"Summary2", "Topic3":"Summary3"}}
    Where comments give no meaningful information, just return {{}}.
    Comments: {combined_comments}
    """
    
    try:
        response = gemini_client.models.generate_content(
            model='gemini-3.1-flash-lite',
            contents=prompt,
        )
        return response.text
    except Exception as e:
        print(f"Error generating summary: {e}")
        return "Summary could not be generated."


def main():
    month = get_previous_month()
    for country, country_info in COUNTRIES.items():
        possible_country_spellings = [country, country_info["regionCode"]]
        list_of_keywords = get_monthly_keywords(supabase, country, month)
        
        for row in list_of_keywords:
            keyword_string = row.get("monthly_keywords", "")
            keywords_list = [kw.strip() for kw in keyword_string.split(",") if kw.strip()]
            
            if not keywords_list:
                continue

            comments_data = fetch_comments_by_country_keyword(
                supabase, 
                possible_country_spellings, 
                keywords_list, 
                month
            )
            posts_data = fetch_posts_by_country_keyword(supabase, possible_country_spellings, keywords_list, month)
            combined_data = (comments_data or []) + (posts_data or [])
            
            if combined_data:
                sample_texts = [item.get('cleaned_text', '') for item in combined_data if item.get('cleaned_text')]
                
                if sample_texts:
                    summary_text = generate_discussion_summary(sample_texts, keywords_list)# Convert the string from Gemini into a real Python dictionary
                
                    try:
                        summary_dict = json.loads(summary_text)
                    except json.JSONDecodeError:
                        summary_dict = {"Raw_Summary": summary_text} # Fallback if Gemini messes up the formatting

                    try:
                        database_response = (
                            supabase
                            .table("summary")
                            .upsert(
                                # Store the string version of the keywords in the DB
                                {'country': country, 'keywords': keyword_string, 'month': month, 'summary': summary_dict},
                                on_conflict="country, keywords, month"
                            )
                            .execute()
                        )
            
                        print(f"Successfully inserted {len(database_response.data)} records")
            
                    except Exception as e:
                        print(f"Error inserting data: {e}")
                else:
                    print("No valid text found in the fetched posts.")
            else:
                print("No posts found matching your criteria.")

if __name__ == "__main__":
    main()