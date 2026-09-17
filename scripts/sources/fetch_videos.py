import os
import json
import fetch_comments
import googleapiclient.discovery
from supabase import create_client, Client
from dotenv import load_dotenv
from datetime import datetime

def get_previous_month_start():
    now = datetime.now()
    
    # Calculate the year and month for the previous month
    if now.month == 1:
        prev_month = 12
        year = now.year - 1
    else:
        prev_month = now.month - 1
        year = now.year
        
    return f"{year:04d}-{prev_month:02d}-01T00:00:00Z"

def format_records(youtube_data, country, token, keyword):
    formatted_records = []

    # Parse and map the JSON
    for item in youtube_data.get("items", []):
        snippet = item.get("snippet", {})

        record = {
            "video_id": item["id"]["videoId"],
            "title": snippet.get("title"),
            "description": snippet.get("description"),
            "channel_title": snippet.get("channelTitle"),
            "published_date": snippet.get("publishedAt")[:10],
            "country": country,
            "next_page_token": token,
            "topic": keyword
        }

        formatted_records.append(record)

    if not formatted_records:
        print("No video records found to insert.")
        return

    return formatted_records


def fetch_videos(youtube, country, keywords, location, location_radius):
    """
    Fetch videos from YouTube based on a country's location.
    Returns a list of formatted video records.
    """

    all_records = []
    next_page_token = None
    for keyword in keywords:
        while True:
            request = youtube.search().list(
                part="snippet",
                location=location,
                locationRadius=location_radius,
                pageToken=next_page_token,
                maxResults=50,
                publishedAfter=get_previous_month_start(),
                q=keyword,
                regionCode=country,
                relevanceLanguage="en",
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
                next_page_token,
                keyword
            )

            if formatted_records:
                all_records.extend(formatted_records)

            # No more pages
            if not next_page_token:
                break

            break # Test - will only collect 1 page of results / keyword / country
    return all_records


def fetch_video_stats(youtube, video_ids):
    stats = []

    for i in range(0, len(video_ids), 50):
        batch = video_ids[i:i + 50]

        print(
            f"Requesting stats for {len(batch)} videos "
            f"({i + 1}-{i + len(batch)} of {len(video_ids)})"
        )

        request = youtube.videos().batchGetStats(
            id=",".join(batch),
            part="statistics"
        )

        response = request.execute()

        returned = response.get("items", [])

        print(f"YouTube returned {len(returned)} videos")

        for item in returned:
            statistics = item.get("statistics", {})

            stats.append({
                "video_id": item["id"],
                "view_count": int(statistics.get("viewCount", 0)),
                "like_count": int(statistics.get("likeCount", 0)),
                "comment_count": int(statistics.get("commentCount", 0))
            })

    print(f"Total stats returned: {len(stats)}")

    return stats

    
def main():
    load_dotenv()

    # Supabase setup
    url = os.environ.get("SUPABASE_URL", "")
    key = os.environ.get("SUPABASE_KEY", "")

    supabase: Client = create_client(url, key)

    # YouTube setup
    developer_key = os.environ.get("YOUTUBE_KEY", "")

    youtube = googleapiclient.discovery.build(
        "youtube",
        "v3",
        developerKey=developer_key
    )

    with open("locations.json", "r") as locations_file:
        all_countries = json.load(locations_file)

    # Fetch videos for each country
    for country, location_data in all_countries.items():

        location = location_data["location"]
        location_radius = location_data["locationRadius"]
        keywords = location_data["keywords"]

        video_records = fetch_videos(
            youtube,
            country,
            keywords,
            location,
            location_radius
        )

        # Deduplicate records and aggregate topics into a list
        deduplicated_records = {}
        for record in video_records:
            vid = record["video_id"]
            current_topic = record["topic"]
            
            if vid not in deduplicated_records:
                record["topic"] = [current_topic]
                deduplicated_records[vid] = record
            else:
                # Video already exists, append the new topic if it's not already in the list
                if current_topic not in deduplicated_records[vid]["topic"]:
                    deduplicated_records[vid]["topic"].append(current_topic)
                    
        video_records = list(deduplicated_records.values())

        if not video_records:
            continue

        video_ids = [record['video_id'] for record in video_records]

        video_stats = fetch_video_stats(
            youtube, video_ids
        )

        stats_by_video_id = {
            stat["video_id"]: stat
            for stat in video_stats
        }

        for record in video_records:
            stats = stats_by_video_id.get(record["video_id"], {})

            record["view_count"] = stats.get("view_count", 0)
            record["like_count"] = stats.get("like_count", 0)
            record["comment_count"] = stats.get("comment_count", 0)


        # Insert videos into Supabase
        try:
            database_response = (
                supabase
                .table("youtube_videos")
                .upsert(
                    video_records,
                    on_conflict="video_id"
                )
                .execute()
            )

            print(
                f"Successfully inserted "
                f"{len(database_response.data)} records"
            )

        except Exception as e:
            print(f"Error inserting data: {e}")


if __name__ == "__main__":
    main()
    fetch_comments.main()



