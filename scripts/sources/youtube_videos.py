import os
import json
import sys
import googleapiclient.discovery
from supabase import create_client, Client
from dotenv import load_dotenv
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))

# Add it to Python's system path if it's not already there
if project_root not in sys.path:
    sys.path.insert(0, project_root)

def get_monthly_keywords(supabase, country):
    # Returns one list of keywords per topic, so each topic can be searched in a single combined query
    response = supabase.table("monthly_topic_stats").select("monthly_keywords").eq("country", country).lte("topic_rank", 3).execute()
    keyword_groups = []
    for item in response.data:
        group = [kw.strip() for kw in item['monthly_keywords'].split(',') if kw.strip()]
        if group:
            keyword_groups.append(group)
    return keyword_groups

def match_keywords(item, keywords):
    # A combined "a|b|c" query doesn't say which keyword matched, so infer it from the title/description
    snippet = item.get("snippet", {})
    text = f"{snippet.get('title', '')} {snippet.get('description', '')}".casefold()
    matched = [kw for kw in keywords if kw.casefold() in text]
    return matched or keywords

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

def get_current_month_start():
    now = datetime.now()
    return f"{now.year:04d}-{now.month:02d}-01T00:00:00Z"

def format_records(youtube_data, country, token, keywords):
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
            "topic": match_keywords(item, keywords)
        }

        formatted_records.append(record)

    if not formatted_records:
        print("No video records found to insert.")
        return

    return formatted_records


def fetch_videos(youtube, country, country_code, keyword_groups, location, location_radius):
    """
    Fetch videos from YouTube based on a country's location.
    Each keyword group is searched as one OR query ("a|b|c") to save quota (100 units per search call).
    Returns a list of formatted video records.
    """

    all_records = []
    for keywords in keyword_groups:
        query = "|".join(keywords)
        next_page_token = None
        while True:
            request = youtube.search().list(
                part="snippet",
                location=location,
                locationRadius=location_radius,
                pageToken=next_page_token,
                maxResults=50,
                publishedAfter=get_previous_month_start(),
                publishedBefore=get_current_month_start(),
                q=query,
                regionCode=country_code,
                relevanceLanguage="en",
                type="video"
            )

            response = request.execute()

            print(
                f"[{country}] q={query!r}: got {len(response.get('items', []))} videos. "
                f"Next token: {response.get('nextPageToken')}"
            )

            next_page_token = response.get("nextPageToken")

            formatted_records = format_records(
                response,
                country,
                next_page_token,
                keywords
            )

            if formatted_records:
                all_records.extend(formatted_records)

            # No more pages
            if not next_page_token:
                break

            break # Test - will only collect 1 page of results / topic / country
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

def format_comments(youtube_data, country=None):
    formatted_records = []

    # Parse and map the JSON
    for item in youtube_data.get("items", []):

        record = {
            "comment_id": item["id"],
            "video_id": item["snippet"]["videoId"],
            "country": country,
            "comment": item["snippet"]["topLevelComment"]["snippet"]["textOriginal"],
            "like_count": item["snippet"]["topLevelComment"]["snippet"]["likeCount"],
            "reply_count": item["snippet"]["totalReplyCount"]
        }

        formatted_records.append(record)

    if not formatted_records:
        print("No comments found to insert.")
        return

    return formatted_records
    
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

    # Get the directory where the current script is located
    current_dir = os.path.dirname(os.path.abspath(__file__))

    # Build the absolute path to the JSON file
    locations_path = os.path.join(current_dir, "locations.json")

    with open(locations_path, "r") as locations_file:
        all_countries = json.load(locations_file)

    # Fetch videos for each country
    for country, location_data in all_countries.items():

        location = location_data["location"]
        country_code = location_data["regionCode"]
        location_radius = location_data["locationRadius"]
        keyword_groups = get_monthly_keywords(supabase, country)
        video_records = fetch_videos(
            youtube,
            country,
            country_code,
            keyword_groups,
            location,
            location_radius
        )

        # Deduplicate records and merge their keyword lists
        deduplicated_records = {}
        for record in video_records:
            vid = record["video_id"]

            if vid not in deduplicated_records:
                deduplicated_records[vid] = record
            else:
                # Video already exists, append any new keywords to its list
                for kw in record["topic"]:
                    if kw not in deduplicated_records[vid]["topic"]:
                        deduplicated_records[vid]["topic"].append(kw)
                    
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

        for video in video_records:
            try:
                request = youtube.commentThreads().list(
                part="id,snippet,replies",
                videoId=video['video_id']
                )
                
                comments = request.execute()
                formatted_comments = format_comments(comments, video.get("country"))
                if not formatted_comments:
                    print("No comments to insert.")
                else:
                    try:
                        # Insert comments
                        response = supabase.table("youtube_comments").upsert(formatted_comments, on_conflict="comment_id").execute()
                        print(f"Successfully uploaded {len(response.data)} comments.")
                    except Exception as e:
                        print(f"Error occurred when inserting into comments table: {e}")
            except Exception as e:
                print(f"Comments disabled for video: {e}")

    from scripts.supabase.twitter_pipeline import run_cleaner
    run_cleaner()

if __name__ == "__main__":
    main()