import requests
import feedparser
import pandas as pd

url = "https://www.reddit.com/r/singapore/.rss?limit=100"

session = requests.Session()

session.headers.update({
    "User-Agent": "python:my-reddit-reader:v1.0 (by /u/zenzen__)",
    "Accept": "application/rss+xml",
})

response = session.get(url)

print("Status:", response.status_code)
print("Retry-After:", response.headers.get("Retry-After"))
print("Rate Limit:", response.headers.get("X-Ratelimit-Remaining"))

# Parse RSS content
feed = feedparser.parse(response.content)

post = feed.entries[0]

print("Title:", post.title)
print("Link:", post.link)
print("Published:", post.published)
print("Author:", post.author)

