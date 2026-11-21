import os
import numpy as np
import pandas as pd
import json
import sys
import argparse
import time
import requests
from dotenv import load_dotenv
from google import genai
from supabase import create_client, Client
from datetime import date, datetime, timezone

load_dotenv()
gemini_client = genai.Client()

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))

if project_root not in sys.path:
    sys.path.insert(0, project_root)

from scripts.cleaning.clean_social import credentials
from scripts.sentiment.sentiment_analysis import (
    fetch_rows_in_window,
    fetch_topic_lookup,
    filter_environmental,
    month_window,
    row_entries,
)

# Supabase setup
url = os.environ.get("SUPABASE_URL", "")
key = os.environ.get("SUPABASE_KEY", "")

supabase: Client = create_client(url, key)

with open(os.path.join(project_root, 'scripts', 'sources', 'locations.json'), "r") as locations_file:
    COUNTRIES = json.load(locations_file)

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
        
    # Format with zero-padding for single-digit months
    return f"{prev_year}-{prev_month:02d}-01"

def normalize_month(month_str):
    """
    Accepts 'YYYY-MM' or 'YYYY-MM-DD' and returns 'YYYY-MM-01'.
    """
    parts = month_str.strip().split('-')
    if len(parts) < 2:
        raise argparse.ArgumentTypeError(f"Invalid month '{month_str}', expected YYYY-MM")
    try:
        y, m = int(parts[0]), int(parts[1])
    except ValueError:
        raise argparse.ArgumentTypeError(f"Invalid month '{month_str}', expected YYYY-MM")
    if not 1 <= m <= 12:
        raise argparse.ArgumentTypeError(f"Invalid month '{month_str}', month must be 01-12")
    return f"{y}-{m:02d}-01"

def get_existing_summaries(supabase, month):
    """
    Returns a set of (country, topic_name) pairs that already have a summary for the given month.
    """
    response = supabase.table("summary").select("country, topic_name").eq("month", month).execute()
    return {(row["country"], row["topic_name"]) for row in response.data}

def get_monthly_keywords(supabase, country, month):
    # keywords = []
    response = supabase.table("monthly_topic_stats").select("topic_name, monthly_keywords").eq("country", country).lte("topic_rank", 3).eq("month", month).execute()
    list_of_keywords = response.data
    # keywords = [kw.strip()
    #     for item in list_of_keywords
    #     for kw in item['monthly_keywords'].split(',')]
    return list_of_keywords

def fetch_topic_texts(month):
    """
    Returns {(country, topic_name): [cleaned_text, ...]} for the month.
    Uses sentiment_analysis.py's own fetching, environmental filter and topic matching
    (all pages, comments dated by their parent post, case-insensitive keywords) so each
    summary describes exactly the discussions counted on the dashboard.
    """
    base_url, key = credentials()
    session = requests.Session()
    start_time, end_time = month_window(month)
    posts, comments = filter_environmental(
        session, base_url, key,
        fetch_rows_in_window(session, base_url, key, "clean_posts", start_time, end_time),
        fetch_rows_in_window(session, base_url, key, "clean_comments", start_time, end_time),
    )
    rows = posts + comments
    texts = {}
    for country, topic, text, _, _ in row_entries(rows, fetch_topic_lookup(session, base_url, key)):
        texts.setdefault((country, topic), []).append(text)
    return texts

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
    
    # Gemini returns 503/429 under high demand, so retry with exponential backoff
    for attempt in range(1, GEMINI_RETRIES + 1):
        try:
            response = gemini_client.models.generate_content(
                model='gemini-3.1-flash-lite',
                contents=prompt,
            )
            return response.text
        except Exception as e:
            retryable = any(code in str(e) for code in ("503", "429", "UNAVAILABLE", "RESOURCE_EXHAUSTED"))
            if retryable and attempt < GEMINI_RETRIES:
                wait = 2 ** attempt * 5
                print(f"Gemini busy (attempt {attempt}/{GEMINI_RETRIES}), retrying in {wait}s...")
                time.sleep(wait)
                continue
            print(f"Error generating summary: {e}")
            return None


def parse_args():
    parser = argparse.ArgumentParser(description="Generate monthly discussion summaries per country and topic.")
    parser.add_argument(
        "--months",
        nargs="+",
        type=normalize_month,
        help="Months to summarise in YYYY-MM format (e.g. --months 2026-08 2026-09). "
             "Explicitly specified months are always regenerated. "
             "Defaults to the previous month, skipping summaries that already exist.",
    )
    parser.add_argument(
        "--countries",
        nargs="+",
        choices=list(COUNTRIES),
        help="Only summarise these countries (e.g. --countries Malaysia). Defaults to all countries.",
    )
    return parser.parse_args()

def main():
    args = parse_args()
    # Explicitly requested months are force-rerun; the default run skips existing summaries
    force = args.months is not None
    months = args.months if force else [get_previous_month()]
    for month in months:
        print(f"=== Processing month {month} ===")
        summarize_month(month, force=force, countries=args.countries)

def summarize_month(month, force=False, countries=None):
    existing = set() if force else get_existing_summaries(supabase, month)
    topic_texts = fetch_topic_texts(month)
    for country in countries or COUNTRIES:
        list_of_keywords = get_monthly_keywords(supabase, country, month)

        for row in list_of_keywords:
            topic_name = (row.get("topic_name") or "").strip()
            keyword_string = row.get("monthly_keywords", "")
            keywords_list = [kw.strip() for kw in keyword_string.split(",") if kw.strip()]

            if not keywords_list:
                continue

            if (country, topic_name) in existing:
                print(f"Skipping {country} [{topic_name}] for {month}: summary already exists.")
                continue

            sample_texts = topic_texts.get((country, topic_name), [])
            if not sample_texts:
                print(f"No posts or comments found for {country} [{topic_name}] in {month}.")
                continue

            summary_text = generate_discussion_summary(sample_texts, keywords_list)

            # Don't store a placeholder when Gemini failed; the next run will retry this topic
            if summary_text is None:
                print(f"Skipping {country} [{topic_name}] for {month}: no summary generated.")
                continue

            # Convert the string from Gemini into a real Python dictionary
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
                        # updated_at is set explicitly: the column default only applies on insert, not when the upsert overwrites a row
                        {'country': country, 'topic_name': topic_name, 'keywords': keyword_string, 'month': month, 'summary': summary_dict,
                         'updated_at': datetime.now(timezone.utc).isoformat()},
                        on_conflict="topic_name,country,month"
                    )
                    .execute()
                )

                # RLS can silently block a write, returning no rows instead of raising
                if database_response.data:
                    print(f"Successfully inserted {len(database_response.data)} records")
                else:
                    print(f"No rows written for {country} [{topic_name}] {month}: check RLS insert/update policies on 'summary'.")

            except Exception as e:
                print(f"Error inserting data: {e}")

if __name__ == "__main__":
    main()