# -*- coding: utf-8 -*-

# Sample Python code for youtube.search.list
# See instructions for running these code samples locally:
# https://developers.google.com/explorer-help/code-samples#python

import os
import googleapiclient.discovery
from supabase import create_client, Client
from dotenv import load_dotenv
import json

def format_records(youtube_data, country, token):
    formatted_records = []
    
    # 2. Parse and map the JSON
    for item in youtube_data.get("items", []):
        snippet = item.get("snippet", {})
        record = {
            "video_id": item["id"]["videoId"],
            "title": snippet.get("title"),
            "description": snippet.get("description"),
            "channel_title": snippet.get("channelTitle"),
            "published_date": snippet.get("publishedAt")[:10],
            "country": country,
            "next_page_token": token   
        }
        formatted_records.append(record)

    if not formatted_records:
        print("No video records found to insert.")
        return
    return formatted_records

def main():
    load_dotenv()

    url = os.environ.get("SUPABASE_URL", "")
    key = os.environ.get("SUPABASE_KEY", "")

    supabase: Client = create_client(url, key)

    DEVELOPER_KEY = os.environ.get("YOUTUBE_KEY", "")

    youtube = googleapiclient.discovery.build(
        "youtube",
        "v3",
        developerKey=DEVELOPER_KEY
    )

    next_page_token = None
    with open('locations.json', 'r') as locations_file:
        all_countries = json.load(locations_file)
        
    for country, location_data in all_countries.items():
        
        location = location_data["location"]
        location_radius = location_data["locationRadius"]

        while True:

            request = youtube.search().list(
                part="snippet",
                location=location,
                locationRadius=location_radius,
                pageToken=next_page_token,
                maxResults=50,
                publishedAfter="2021-01-01T00:00:00Z",
                q="environment|climate change|global warming",
                regionCode=country,
                type="video"
            )

            response = request.execute()

            print(
                f"Got {len(response.get('items', []))} videos. "
                f"Next token: {response.get('nextPageToken')}"
            )

            next_page_token = response.get("nextPageToken")

            formatted_records = format_records(
                response,
                country,
                next_page_token
            )

            if formatted_records:
                try:
                    database_response = (
                        supabase
                        .table("youtube_videos")
                        .upsert(formatted_records, on_conflict="video_id", ignore_duplicates=True)
                        .execute()
                    )

                    print(
                        f"Successfully inserted "
                        f"{len(database_response.data)} records"
                    )

                except Exception as e:
                    print(f"Error inserting data: {e}")

            # No more pages
            if not next_page_token:
                break


if __name__ == "__main__":
    main()



