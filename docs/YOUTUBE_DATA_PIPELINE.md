# YouTube Data Collection and Supabase Storage

## Purpose

This document explains how the project collects public YouTube videos and their associated comments, processing them for downstream analysis and storing them in Supabase.

The collector focuses on discovering YouTube videos based on dynamic keywords and geographical bounding, specifically targeting data from the previous calendar month. Following the video collection, the pipeline automatically retrieves the top-level comments for each discovered video.

## Main Components

| Component | Responsibility |
| --- | --- |
| `youtube_videos.py` | Generates search queries based on monthly statistics, calls the YouTube Search and Video APIs, deduplicates videos, fetches engagement stats, upserts to Supabase, and triggers the comment collection.

 |
| `youtube_comments.py` | Reads stored video IDs from Supabase, calls the YouTube CommentThreads API, formats the responses, and upserts comments into Supabase. Note: This is referenced and invoked as `fetch_comments` within the video script.

 |
| `locations.json` | A local JSON file providing the `location` coordinates, `regionCode`, and `locationRadius` for targeted countries.

 |
| Supabase tables | `youtube_videos` stores the video metadata and metrics, `youtube_comments` stores the comment text and engagement, and `monthly_topic_stats` is read to provide the search keywords.

 |

## Data Flow

```text
Scheduled / Triggered job (`youtube_videos.py`)
    |
    v
Read country parameters from `locations.json`
    |
    v
Query `monthly_topic_stats` for top 3 keywords per country
    |
    v
Search YouTube API for videos published since the start of the previous month
    |
    v
Deduplicate videos and aggregate topics in memory
    |
    v
Batch request YouTube Video API for view, like, and comment counts
    |
    v
Upsert video records into Supabase `youtube_videos`
    |
    v
Execute comment collection (`youtube_comments.py` / `fetch_comments`)
    |
    v
Fetch all video IDs from Supabase in chunks of 1,000
    |
    v
Request YouTube CommentThreads API for each video ID
    |
    v
Upsert formatted comments into Supabase `youtube_comments`

```

## 1. Credentials

The scripts load credentials from the environment using `python-dotenv`.

The following variables are required:

* `SUPABASE_URL`: The endpoint URL for the Supabase project.


* `SUPABASE_KEY`: The API key for Supabase authentication.


* `YOUTUBE_KEY`: The developer key used to authenticate with the `googleapiclient.discovery` YouTube API v3 service.



## 2. Search Query and Keyword Generation

Instead of a static list of terms, the pipeline dynamically generates its search queries by reading from the database.

* The script queries the `monthly_topic_stats` table for a specific country.


* It filters for topics where the `topic_rank` is less than or equal to 3 to retreive the top 3 ranked topics
 .


* It splits the comma-separated `monthly_keywords` into a flat list of search terms to use against the YouTube API.



The YouTube API search request is then constructed with the following parameters:

* `publishedAfter`: Dynamically calculated to be the 1st day of the previous calendar month at 00:00:00Z.


* `location` and `locationRadius`: Sourced from the `locations.json` file to bound the geographic area.


* `regionCode`: The specific country code.


* `relevanceLanguage`: English (`"en"`).


* `type`: Restricted to `"video"`.



## 3. Collection Size and Pagination

The pipeline is currently configured with strict limits on data retrieval:

* **Video Search:** The API requests a maximum of 50 results per page (`maxResults=50`) which is the maximum as the YouTube API dictates.


* **Pagination Cap:** While the script is designed to handle a `nextPageToken`, a hardcoded `break` statement currently limits the collection to only one page of results per keyword, per country, to reduce the use of quota in the testing stage.


* **Video Stats Batching:** When requesting metrics (views, likes, comments), the script groups video IDs into batches of 50 to minimize API calls.


* **Database Reads:** When retrieving video IDs to fetch comments, the Supabase query paginates in chunks of 1,000 rows at a time to prevent memory overload.



## 4. Data Transformation

The API responses are parsed and flattened into dictionaries suitable for database insertion.

### Videos (`youtube_videos.py`)

Video records extract data from the `snippet` and `statistics` payloads. The schema includes:

* `video_id`: Extracted from `item["id"]["videoId"]`.


* `title`, `description`, `channel_title`: Extracted from the video snippet.


* `published_date`: Truncated to the first 10 characters (YYYY-MM-DD).


* `country` and `next_page_token`: Passed down from the search parameters.


* `topic`: A list of keywords associated with the video.


* `view_count`, `like_count`, `comment_count`: Integers parsed from the batch statistics request, defaulting to 0 if missing.



### Comments (`youtube_comments.py`)

Comment threads extract data from the `snippet.topLevelComment` payload. The schema includes:

* `comment_id`: The unique ID of the comment thread.


* `video_id`: The ID of the parent video.


* `comment`: The raw text content extracted from `textOriginal`.


* `like_count`: The number of likes on the comment.


* `reply_count`: The total number of replies to the top-level comment.



## 5. Supabase Storage and Deduplication

The pipeline relies on Supabase `upsert` functionality to safely handle repeated data and overlap.

* **In-Memory Video Deduplication:** Because a single video might match multiple keywords, the video script deduplicates records via a Python dictionary before uploading. If a video is found multiple times, the script appends the new keyword to the existing `topic` list rather than creating a duplicate entry.


* **Video Upsert:** Videos are inserted into the `youtube_videos` table using `on_conflict="video_id"`.


* **Comment Upsert:** Comments are inserted into the `youtube_comments` table using `on_conflict="comment_id"`.



## 6. Failure Behavior

The pipeline uses `try-except` blocks to handle expected failure states without crashing the entire run:

* **Disabled Comments:** If a video has comments disabled, the YouTube API will throw an exception. The comment script catches this, prints "Comments disabled for video: {e}", and proceeds to the next video ID.


* **Database Insert Errors:** If Supabase rejects an upsert payload, the scripts catch the exception, print the error message, and continue execution rather than terminating the job.