import os
import requests
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

url: str = os.environ.get("SUPABASE_URL", "")
key: str = os.environ.get("SUPABASE_KEY", "")

supabase: Client = create_client(url, key)

def sync_api_to_supabase():
    # 2. Fetch raw data from external API
    api_url = "https://api.example.com/data"
    response = requests.get(api_url)
    response.raise_for_status()  # Check for HTTP errors
    raw_data = response.json()

    # 3. Pre-process your data
    processed_records = []
    for item in raw_data:
        processed_records.append({
            "title": item["name"].strip().title(),
            "status": item["status"].lower(),
            "created_at": item["timestamp"],
            # Rename keys or apply math/formatting transformations here
        })

    # 4. Insert or Upsert into Supabase
    result = supabase.table("").upsert(processed_records).execute()
    print(f"Successfully synced {len(result.data)} records to Supabase.")

if __name__ == "__main__":
    sync_api_to_supabase()