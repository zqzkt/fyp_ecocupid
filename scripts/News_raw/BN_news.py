import requests
from bs4 import BeautifulSoup
import pandas as pd
import time
import re
import os
import json
from datetime import datetime
from urllib.parse import urljoin, urlparse, urlunparse
from dotenv import load_dotenv
from supabase import create_client, Client
# ==========================================================
# SETTINGS
# ==========================================================

BASE_URL = "https://www.pelitabrunei.gov.bn"
CATEGORY_URLS = {
    "Nasional": "https://www.pelitabrunei.gov.bn/berita/nasional",
}
START_DATE = os.getenv('NEWS_START_DATE', '2026-08-01')
END_DATE = os.getenv('NEWS_END_DATE', '2026-08-31')
START_DATE = datetime.strptime(START_DATE, '%Y-%m-%d')
END_DATE = datetime.strptime(END_DATE, '%Y-%m-%d')
load_dotenv()
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')
if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError('Missing SUPABASE_URL or SUPABASE_KEY in .env')

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
RAW_TABLE = 'news_raw'
SOURCE_COUNTRY = 'Brunei'
MAX_PAGES = 50
INSERT_BATCH_SIZE = 100
# ==========================================================
# REQUEST HEADERS
# ==========================================================

HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36', 'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8', 'Accept-Language': 'ms-MY,ms;q=0.9,en-US;q=0.8,en;q=0.7', 'Connection': 'keep-alive'}
session = requests.Session()
session.headers.update(HEADERS)
# ==========================================================
# ENVIRONMENT KEYWORDS
# ==========================================================

ENVIRONMENT_KEYWORDS = ['alam sekitar', 'kelestarian', 'lestari', 'mampan', 'kemampanan', 'sustainability', 'sustainable', 'environment', 'environmental', 'perubahan iklim', 'krisis iklim', 'pemanasan global', 'iklim global', 'tindakan iklim', 'ketahanan iklim', 'adaptasi iklim', 'mitigasi iklim', 'cuaca ekstrem', 'cuaca melampau', 'climate change', 'climate crisis', 'global warming', 'karbon', 'pelepasan karbon', 'emisi karbon', 'gas rumah hijau', 'neutral karbon', 'sifar bersih', 'net zero', 'carbon emissions', 'greenhouse gas', 'hutan', 'kebakaran hutan', 'kebakaran hutan dan lahan', 'penebangan hutan', 'penebangan pokok', 'pembalakan', 'pemulihan hutan', 'penghutanan semula', 'deforestasi', 'deforestation', 'forest fire', 'wildfire', 'reforestation', 'biodiversiti', 'kepelbagaian biologi', 'pemuliharaan', 'konservasi', 'hidupan liar', 'spesies terancam', 'habitat', 'ekosistem', 'kawasan perlindungan', 'biodiversity', 'conservation', 'wildlife', 'ecosystem', 'pencemaran', 'pencemaran udara', 'pencemaran air', 'pencemaran laut', 'kualiti udara', 'jerebu', 'asap jerebu', 'pm2.5', 'bahan pencemar', 'pollution', 'air pollution', 'water pollution', 'haze', 'sisa', 'sisa pepejal', 'e-sisa', 'sisa elektronik', 'sampah', 'sampah sarap', 'sisa plastik', 'plastik', 'kitar semula', 'pelupusan sisa', 'pengurusan sisa', 'waste', 'plastic waste', 'plastic pollution', 'recycling', 'e-waste', 'sumber air', 'kualiti air', 'keselamatan air', 'pemuliharaan air', 'sungai', 'tasik', 'air tercemar', 'water conservation', 'water security', 'alam sekitar marin', 'ekosistem marin', 'marin', 'laut', 'lautan', 'pesisir', 'pantai', 'hakisan pantai', 'terumbu karang', 'karang', 'bakau', 'paya bakau', 'perikanan', 'marine', 'ocean', 'coastal', 'coral reef', 'mangrove', 'tenaga boleh diperbaharui', 'tenaga diperbaharui', 'tenaga bersih', 'tenaga solar', 'tenaga suria', 'tenaga angin', 'peralihan tenaga', 'bahan api fosil', 'arang batu', 'renewable energy', 'clean energy', 'solar energy', 'wind energy', 'fossil fuel', 'banjir', 'risiko banjir', 'mitigasi banjir', 'kemarau', 'tanah runtuh', 'gelombang haba', 'kenaikan paras laut', 'paras laut meningkat', 'hakisan', 'flood', 'flooding', 'drought', 'landslide', 'heatwave', 'sea level rise', 'flora', 'fauna', 'tumbuhan hijau', 'sumber semula jadi', 'sumber asli', 'ekologi', 'ecology', 'jastre', 'jabatan alam sekitar, taman dan rekreasi', 'jabatan alam sekitar', 'brunei climate change secretariat', 'bccs', 'brunei darussalam national council on climate change', 'bdnccc']
# ==========================================================
# TARGET ASEAN COUNTRY KEYWORDS
# ==========================================================

ASEAN_COUNTRY_KEYWORDS = {'Brunei': ['brunei', 'brunei darussalam', 'negara brunei darussalam', 'nbd', 'bruneian', 'bandar seri begawan', 'tutong', 'temburong', 'belait', 'kuala belait', 'seria', 'muara', 'berakas', 'jerudong'], 'Indonesia': ['indonesia', 'indonesian', 'jakarta', 'sumatra', 'sumatera', 'kalimantan', 'jawa', 'java', 'sulawesi', 'bali'], 'Malaysia': ['malaysia', 'malaysian', 'kuala lumpur', 'johor', 'selangor', 'sabah', 'sarawak', 'penang', 'pulau pinang', 'pahang', 'kelantan', 'terengganu', 'perak', 'kedah', 'melaka'], 'Philippines': ['philippines', 'philippine', 'filipino', 'filipina', 'manila', 'luzon', 'visayas', 'mindanao', 'cebu', 'palawan', 'davao'], 'Singapore': ['singapore', 'singapura', 'singaporean'], 'Thailand': ['thailand', 'thai', 'bangkok']}
# ==========================================================
# MALAY MONTHS
# ==========================================================

MALAY_MONTHS = {'jan': 1, 'januari': 1, 'feb': 2, 'februari': 2, 'mac': 3, 'apr': 4, 'april': 4, 'mei': 5, 'jun': 6, 'jul': 7, 'julai': 7, 'og': 8, 'ogos': 8, 'sep': 9, 'sept': 9, 'september': 9, 'okt': 10, 'oktober': 10, 'nov': 11, 'november': 11, 'dis': 12, 'disember': 12}

# ==========================================================
# URL AND CATEGORY HELPERS
# ==========================================================

def clean_url(url):
    parsed = urlparse(url)

    cleaned = parsed._replace(query='', fragment='')

    return urlunparse(cleaned).rstrip('/')

def is_article_url(url):
    path = urlparse(url).path.lower().rstrip('/')

    prefixes = ['/berita/nasional/', '/berita/global/', '/berita/rencana/']

    return any((path.startswith(prefix) and len(path) > len(prefix) for prefix in prefixes))

def extract_article_urls(html):
    soup = BeautifulSoup(html, 'html.parser')

    article_urls = []

    for link in soup.find_all('a', href=True):
        full_url = clean_url(urljoin(BASE_URL, link['href']))

        if not is_article_url(full_url):
            continue

        if full_url not in article_urls:
            article_urls.append(full_url)
    return article_urls

def get_category_page(category_name, category_url, page_number):
    print()

    print(f'Loading {category_name} page {page_number}...')

    try:
        response = session.get(category_url, params={'page': page_number}, timeout=30)

        print('Status:', response.status_code)

        if response.status_code != 200:
            print('Category request failed.')

            return []

        urls = extract_article_urls(response.text)

        print('Article URLs found:', len(urls))

        return urls
    except Exception as e:
        print('Category page error:', e)

        return []

# ==========================================================
# ARTICLE EXTRACTION HELPERS
# ==========================================================

def extract_title(soup):
    h1 = soup.find('h1')

    if h1:
        title = h1.get_text(' ', strip=True)

        if title:
            return title

    meta = soup.find('meta', attrs={'property': 'og:title'})

    if meta and meta.get('content'):
        return meta['content'].strip()

    return ''

def get_json_ld_objects(soup):
    results = []

    for script in soup.find_all('script', attrs={'type': 'application/ld+json'}):
        try:
            data = json.loads(script.string or script.get_text())

            if isinstance(data, list):
                results.extend(data)
            else:
                results.append(data)
        except Exception:
            continue

    return results

def walk_json(data):

    if isinstance(data, dict):
        yield data
        for value in data.values():
            yield from walk_json(value)
    elif isinstance(data, list):
        for value in data:
            yield from walk_json(value)

def parse_malay_date(text):

    if not text:
        return None

    pattern = '\\b(\\d{1,2})\\s+([A-Za-z]+)\\s+(\\d{4})\\b'

    for match in re.finditer(pattern, text):
        month_text = match.group(2).lower()

        if month_text not in MALAY_MONTHS:
            continue

        try:
            return datetime(int(match.group(3)), MALAY_MONTHS[month_text], int(match.group(1)))
        except Exception:
            continue

    return None

def extract_published_date(soup):
    candidates = [soup.find('meta', attrs={'property': 'article:published_time'}), soup.find('meta', attrs={'itemprop': 'datePublished'}), soup.find('meta', attrs={'name': 'date'})]

    for meta in candidates:
        if meta and meta.get('content'):
            try:
                dt = pd.to_datetime(meta['content'])

                return dt.to_pydatetime().replace(tzinfo=None)
            except Exception:
                pass

    for obj in get_json_ld_objects(soup):
        for item in walk_json(obj):
            value = item.get('datePublished')

            if value:
                try:
                    dt = pd.to_datetime(value)

                    return dt.to_pydatetime().replace(tzinfo=None)
                except Exception:
                    pass
    page_text = soup.get_text(' ', strip=True)

    return parse_malay_date(page_text)

def extract_article_text(soup):
    selectors = ["[itemprop='articleBody']", '.article-content', '.article-body', '.news-content', '.entry-content', '.content-body', 'article', 'main']

    unwanted_phrases = ['bagi siaran akhbar', 'bagi liputan', 'bagi rencana', 'bagi iklan', 'pelita.brunei@information.gov.bn', 'bahagian pelita brunei', 'jabatan penerangan', 'copyright ©', 'all rights reserved', 'jawatan kosong', 'iklan tawaran', 'berita terkini']

    best_paragraphs = []

    for selector in selectors:
        container = soup.select_one(selector)

        if not container:
            continue

        paragraphs = []

        for p in container.find_all('p'):
            text = p.get_text(' ', strip=True)

            if len(text) < 25:
                continue

            if any((phrase in text.lower() for phrase in unwanted_phrases)):
                continue

            if text not in paragraphs:
                paragraphs.append(text)
        if len(' '.join(paragraphs)) > len(' '.join(best_paragraphs)):
            best_paragraphs = paragraphs

    if not best_paragraphs:
        for p in soup.find_all('p'):
            text = p.get_text(' ', strip=True)

            if len(text) < 25:
                continue

            if any((phrase in text.lower() for phrase in unwanted_phrases)):
                continue

            if text not in best_paragraphs:
                best_paragraphs.append(text)
    return ' '.join(best_paragraphs)

# ==========================================================
# RELEVANCE AND COUNTRY DETECTION
# ==========================================================

def find_environment_keywords(text):
    lower_text = text.lower()

    return [keyword for keyword in ENVIRONMENT_KEYWORDS if keyword.lower() in lower_text]

def find_asean_countries(text):
    lower_text = text.lower()

    countries = []

    for country, keywords in ASEAN_COUNTRY_KEYWORDS.items():
        if any((keyword.lower() in lower_text for keyword in keywords)):
            countries.append(country)
    return countries

# ==========================================================
# SCRAPE ARTICLE
# ==========================================================

def scrape_article(url, category):
    print()

    print(url)

    try:
        response = session.get(url, timeout=30)

        print('  Status:', response.status_code)

        if response.status_code != 200:
            print('  Article request failed.')

            return None

        soup = BeautifulSoup(response.text, 'html.parser')

        title = extract_title(soup)

        if not title:
            print('  No title - skipped')

            return None

        published_date = extract_published_date(soup)

        if published_date is None:
            print('  No date - skipped')

            return None

        article_text = extract_article_text(soup)

        if len(article_text) < 200:
            print('  Too little article text:', len(article_text))

            return None

        combined_text = title + ' ' + article_text

        environment_matches = find_environment_keywords(combined_text)

        asean_countries = find_asean_countries(combined_text)

        if not environment_matches:
            print('  Not environmental - skipped')

            return {'keep': False, 'reason': 'not_environmental', 'published_at': published_date}

        if 'Brunei' not in asean_countries:
            print('  Environmental but not related to Brunei - skipped')

            return {'keep': False, 'reason': 'not_brunei', 'published_at': published_date}

        return {'keep': True, 'title': title, 'source': 'Pelita Brunei', 'published_at': published_date, 'countries': ', '.join(asean_countries), 'environment_keywords': ', '.join(environment_matches), 'article_text': article_text, 'url': clean_url(url)}
    except Exception as e:
        print('  Error:', e)

        return None

# ==========================================================
# SUPABASE HELPERS
# ==========================================================

def load_existing_urls():
    print()

    print('Loading existing Brunei URLs from Supabase...')

    existing_urls = set()

    start = 0

    page_size = 1000

    while True:
        try:
            response = supabase.table(RAW_TABLE).select('url').eq('source_country', SOURCE_COUNTRY).range(start, start + page_size - 1).execute()

            rows = response.data or []

            if not rows:
                break

            for row in rows:
                url = row.get('url')

                if url:
                    existing_urls.add(clean_url(url))
            if len(rows) < page_size:
                break

            start += page_size
        except Exception as e:
            print('Error loading existing Supabase URLs:', e)

            break

    print('Existing Brunei URLs:', len(existing_urls))

    return existing_urls

def insert_articles(articles):

    if not articles:
        print()

        print('No new articles to insert.')

        return 0

    inserted = 0

    for i in range(0, len(articles), INSERT_BATCH_SIZE):
        batch = articles[i:i + INSERT_BATCH_SIZE]

        try:
            supabase.table(RAW_TABLE).insert(batch).execute()

            inserted += len(batch)
            print(f'Inserted batch of {len(batch)} articles.')
        except Exception as e:
            print()

            print('Batch insert failed:', e)

            print('Trying articles one-by-one...')

            for article in batch:
                try:
                    supabase.table(RAW_TABLE).insert(article).execute()

                    inserted += 1
                except Exception as inner_e:
                    print()

                    print('FAILED INSERT:')

                    print(article.get('title'))

                    print(article.get('url'))

                    print(inner_e)

    return inserted

# ==========================================================
# MAIN
# ==========================================================

def main():
    print()

    print('========================================')

    print('PELITA BRUNEI ENVIRONMENT SCRAPER')

    print('========================================')

    print('Start:', START_DATE.date())

    print('End:', END_DATE.date())

    print('Source country:', SOURCE_COUNTRY)

    print('Destination:', 'Supabase news_raw')

    print('Maximum pages to check:', MAX_PAGES)

    existing_urls = load_existing_urls()

    results = []

    seen_urls = set()

    stats = {'scraped': 0, 'saved': 0, 'not_environmental': 0, 'not_brunei': 0, 'too_new': 0, 'too_old': 0, 'failed': 0, 'already_exists': 0}

    for category_name, category_url in CATEGORY_URLS.items():
        print()

        print('========================================')

        print('CATEGORY:', category_name)

        print('========================================')

        for page_number in range(1, MAX_PAGES + 1):
            print()

            print('========================================')

            print(f'>>> STARTING PAGE {page_number} OF {MAX_PAGES}')

            print('========================================')

            urls = get_category_page(category_name, category_url, page_number)

            print(f'Page {page_number} returned {len(urls)} article URLs.')

            if not urls:
                print(f'No article URLs returned on page {page_number}.')

                print('Continuing to next page...')

                time.sleep(1)
                continue

            new_urls = [clean_url(url) for url in urls if clean_url(url) not in seen_urls]

            print(f'New URLs not seen previously: {len(new_urls)}')

            if urls:
                print('First URL on page:', urls[0])

                print('Last URL on page:', urls[-1])

            page_dates = []

            for url in urls:
                url = clean_url(url)

                if url in seen_urls:
                    print('Already seen this run:', url)

                    continue

                seen_urls.add(url)
                if url in existing_urls:
                    stats['already_exists'] += 1
                    print('Already in Supabase:', url)

                    continue

                article = scrape_article(url, category_name)

                if article is None:
                    stats['failed'] += 1
                    continue

                stats['scraped'] += 1
                article_date = article['published_at']

                page_dates.append(article_date)
                print('  Date:', article_date.date())

                if article_date > END_DATE:
                    stats['too_new'] += 1
                    print('  Newer than END_DATE')

                    continue

                if article_date < START_DATE:
                    stats['too_old'] += 1
                    print('  Older than START_DATE')

                    continue

                if not article.get('keep'):
                    reason = article.get('reason')

                    if reason == 'not_environmental':
                        stats['not_environmental'] += 1
                    elif reason == 'not_brunei':
                        stats['not_brunei'] += 1
                    continue

                supabase_article = {'source_country': SOURCE_COUNTRY, 'title': article['title'], 'source': article['source'], 'published_at': article_date.isoformat(), 'countries': article['countries'], 'environment_keywords': article['environment_keywords'], 'article_text': article['article_text'], 'url': article['url']}

                results.append(supabase_article)
                stats['saved'] += 1
                print('  READY FOR SUPABASE')

                print('  Target countries:', supabase_article['countries'])

                print('  Environment keywords:', supabase_article['environment_keywords'])

                time.sleep(1)
            print()

            print('----------------------------------------')

            print(f'PAGE {page_number} COMPLETE')

            if page_dates:
                newest_date = max(page_dates)

                oldest_date = min(page_dates)

                print('Newest date on page:', newest_date.date())

                print('Oldest date on page:', oldest_date.date())

                if oldest_date < START_DATE:
                    print('Page contains article(s) older than START_DATE.')

                    print('Continuing pagination anyway.')
            else:
                print('No new article dates collected from this page.')

            print(f'Finished page {page_number}. Next page will be {page_number + 1}.')

            print('----------------------------------------')

            time.sleep(1)
    unique_results = {}

    for article in results:
        unique_results[article['url']] = article

    results = list(unique_results.values())

    print()

    print('========================================')

    print('INSERTING INTO SUPABASE')

    print('========================================')

    inserted = insert_articles(results)

    print()

    print('========================================')

    print('SCRAPING SUMMARY')

    print('========================================')

    print('Unique URLs encountered:', len(seen_urls))

    print('Successfully scraped:', stats['scraped'])

    print('Not environmental:', stats['not_environmental'])

    print('Environmental but not Brunei:', stats['not_brunei'])

    print('Newer than END_DATE:', stats['too_new'])

    print('Older than START_DATE:', stats['too_old'])

    print('Already in Supabase:', stats['already_exists'])

    print('Failed:', stats['failed'])

    print('Valid Brunei environment articles:', stats['saved'])

    print('Inserted into Supabase:', inserted)

    print()

    print('========================================')

    print('FINISHED')

    print('========================================')

if __name__ == '__main__':
    main()
