import os
import sys
import googleapiclient.discovery
from supabase import create_client, Client
from dotenv import load_dotenv

def main():

    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))

    if project_root not in sys.path:
        sys.path.insert(0, project_root)

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
    try:
        videos = fetch_ids(supabase)

        for video in videos:
            try:
                request = youtube.commentThreads().list(
                part="id,snippet,replies",
                videoId=video['video_id']
                )
                
                comments = request.execute()
                formatted_comments = format_records(comments, video.get("country"))
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

    except Exception as e:
        print(f"Error encountered when retrieving IDs: {e}")

    from scripts.supabase.twitter_pipeline import run_cleaner

    run_cleaner()

def format_records(youtube_data, country=None):
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

def fetch_ids(supabase):
    all_records = []
    page_size = 1000
    current_page = 0

    while True:
        start_row = current_page * page_size
        end_row = start_row + page_size - 1
        
        # Query specific chunk of data
        response = (
            supabase.table("youtube_videos")
            .select("video_id,country")
            .range(start_row, end_row)
            .execute()
        )
        
        data = response.data
        all_records.extend(data)
        
        # If fewer records than page_size are returned, we have reached the end
        if len(data) < page_size:
            break
            
        current_page += 1
    print(f"Successfully retrieved {len(all_records)} total records.")
    return all_records

    
if __name__ == "__main__":
    main()
