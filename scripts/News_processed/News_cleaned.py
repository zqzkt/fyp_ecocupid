import os
import re
import html
import numpy as np
import torch
from datetime import datetime, timezone
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from supabase import create_client, Client
from transformers import pipeline, AutoTokenizer, AutoModelForSeq2SeqLM
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity
from keybert import KeyBERT
from langdetect import detect, DetectorFactory
# ==========================================================
# SETTINGS AND SUPABASE
# ==========================================================

load_dotenv()
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')
if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError('SUPABASE_URL or SUPABASE_KEY is missing. Check your .env file.')

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
RAW_TABLE = 'news_raw'
CLEANED_TABLE = 'news_cleaned'
MIN_WORD_COUNT = 20
MIN_CATEGORY_CONFIDENCE = 0.3
KEYWORD_TOP_N = 5
SUPABASE_BATCH_SIZE = 1000
NLLB_MODEL_NAME = 'facebook/nllb-200-distilled-600M'
TRANSLATION_CHUNK_SIZE = 1200
NLLB_MAX_INPUT_TOKENS = 512
NLLB_MAX_NEW_TOKENS = 512
NLLB_LANGUAGE_CODES = {
    "en": "eng_Latn",
    "ms": "zsm_Latn",
    "id": "ind_Latn",
    "th": "tha_Thai",
}
TARGET_COUNTRIES = [
    'Singapore',
    'Malaysia',
    'Indonesia',
    'Thailand',
    'Philippines',
    'Brunei',
]
TARGET_COUNTRY_SET = set(TARGET_COUNTRIES)
ENVIRONMENT_CATEGORIES = [
    'Climate Change',
    'Renewable Energy',
    'Pollution',
    'Waste Management',
    'Biodiversity and Conservation',
    'Extreme Weather and Natural Hazards',
    'Sustainable Transport',
    'Green Buildings',
    'Green Finance',
]
LOW_INFORMATION_WORDS = {'said', 'says', 'say', 'according', 'reported', 'report', 'reports', 'reporting', 'added', 'told', 'also', 'would', 'could', 'may', 'might'}
DetectorFactory.seed = 0
if torch.cuda.is_available():
    DEVICE = torch.device('cuda')

    PIPELINE_DEVICE = 0

    print()

    print('CUDA GPU detected.')
else:
    DEVICE = torch.device('cpu')

    PIPELINE_DEVICE = -1

    print()

    print('CUDA GPU not detected. Models will run on CPU.')

print()
print('==========================================')
print('LOADING NLP MODELS')
print('==========================================')
print('Loading BART zero-shot classifier...')
category_classifier = pipeline('zero-shot-classification', model='facebook/bart-large-mnli', device=PIPELINE_DEVICE)
print('Loading MiniLM embedding model...')
embedding_model = SentenceTransformer('all-MiniLM-L6-v2', device=str(DEVICE))
print('Loading KeyBERT...')
keyword_model = KeyBERT(model=embedding_model)
print('Loading NLLB local translation model...')
print('The first run may take a while because the model must be downloaded.')
nllb_tokenizer = AutoTokenizer.from_pretrained(NLLB_MODEL_NAME)
nllb_model = AutoModelForSeq2SeqLM.from_pretrained(NLLB_MODEL_NAME)
nllb_model = nllb_model.to(DEVICE)
nllb_model.eval()
print('Models loaded.')

# ==========================================================
# COUNTRY HANDLING
# ==========================================================

def normalize_country(country):

    if not country:
        return None

    country = str(country).strip()

    lookup = {'singapore': 'Singapore', 'malaysia': 'Malaysia', 'indonesia': 'Indonesia', 'thailand': 'Thailand', 'philippines': 'Philippines', 'philippine': 'Philippines', 'brunei': 'Brunei', 'brunei darussalam': 'Brunei'}

    return lookup.get(country.lower())

def parse_countries(countries_value):

    if countries_value is None:
        return []

    text = str(countries_value).strip()

    if not text:
        return []

    parts = re.split('[,;|]', text)

    countries = []

    for part in parts:
        country = normalize_country(part)

        if country and country in TARGET_COUNTRY_SET and (country not in countries):
            countries.append(country)
    return countries

# ==========================================================
# LANGUAGE DETECTION
# ==========================================================

def detect_language(text):

    if not text:
        return 'unknown'

    sample = re.sub('\\s+', ' ', str(text)).strip()

    if len(sample) < 20:
        return 'unknown'

    try:
        return detect(sample[:5000])
    except Exception as e:
        print('  Language detection error:', e)

        return 'unknown'

def resolve_language(detected_language, source_country, text):
    detected_language = (detected_language or 'unknown').lower()

    source_country = (source_country or '').strip()

    if detected_language == 'en':
        return 'en'

    if detected_language == 'th':
        return 'th'

    if detected_language in {'ms', 'id'}:
        if source_country == 'Malaysia':
            print('  Malay/Indonesian ambiguity detected.')

            print('  source_country is Malaysia -> using Malay.')

            return 'ms'

        if source_country == 'Indonesia':
            print('  Malay/Indonesian ambiguity detected.')

            print('  source_country is Indonesia -> using Indonesian.')

            return 'id'

        if source_country == 'Brunei':
            print('  Malay/Indonesian ambiguity detected.')

            print('  source_country is Brunei -> using Malay.')

            return 'ms'

        return detected_language

    if detected_language == 'unknown':
        if source_country == 'Malaysia':
            print('  Language unknown; source_country suggests Malay.')

            return 'ms'

        if source_country == 'Indonesia':
            print('  Language unknown; source_country suggests Indonesian.')

            return 'id'

        if source_country == 'Brunei':
            print('  Language unknown; source_country suggests Malay.')

            return 'ms'

        if source_country == 'Thailand':
            print('  Language unknown; source_country suggests Thai.')

            return 'th'

    return detected_language

def split_text_for_translation(text, max_chars=TRANSLATION_CHUNK_SIZE):
    text = str(text).strip()

    if not text:
        return []

    if len(text) <= max_chars:
        return [text]

    sentences = re.split('(?<=[.!?])\\s+', text)

    chunks = []

    current_chunk = ''

    for sentence in sentences:
        sentence = sentence.strip()

        if not sentence:
            continue

        if len(sentence) > max_chars:
            if current_chunk:
                chunks.append(current_chunk.strip())
                current_chunk = ''

            for start in range(0, len(sentence), max_chars):
                piece = sentence[start:start + max_chars].strip()

                if piece:
                    chunks.append(piece)
            continue

        proposed = (current_chunk + ' ' + sentence).strip()

        if len(proposed) <= max_chars:
            current_chunk = proposed
        else:
            if current_chunk:
                chunks.append(current_chunk.strip())
            current_chunk = sentence

    if current_chunk:
        chunks.append(current_chunk.strip())
    return chunks

# ==========================================================
# NLLB TRANSLATION
# ==========================================================

def translate_nllb_chunk(text, source_language):

    if source_language not in NLLB_LANGUAGE_CODES:
        raise ValueError(f'Unsupported NLLB source language: {source_language}')

    source_code = NLLB_LANGUAGE_CODES[source_language]

    target_code = NLLB_LANGUAGE_CODES['en']

    nllb_tokenizer.src_lang = source_code

    inputs = nllb_tokenizer(text, return_tensors='pt', truncation=True, max_length=NLLB_MAX_INPUT_TOKENS)

    inputs = {key: value.to(DEVICE) for key, value in inputs.items()}

    target_token_id = nllb_tokenizer.convert_tokens_to_ids(target_code)

    with torch.no_grad():
        generated_tokens = nllb_model.generate(**inputs, forced_bos_token_id=target_token_id, max_new_tokens=NLLB_MAX_NEW_TOKENS, num_beams=1)

    translated = nllb_tokenizer.decode(generated_tokens[0], skip_special_tokens=True)

    return translated.strip()

def translate_to_english(text, language):

    if not text:
        return ''

    if language == 'en':
        print('  Translation not required.')

        return str(text)

    if language not in NLLB_LANGUAGE_CODES:
        print('  Unsupported translation language:', language)

        return None

    source_code = NLLB_LANGUAGE_CODES[language]

    print(f'  Translating locally from {language} ({source_code}) to English...')

    chunks = split_text_for_translation(text)

    if not chunks:
        return ''

    print(f'  Translation chunks: {len(chunks)}')

    translated_chunks = []

    for number, chunk in enumerate(chunks, start=1):
        print(f'    Translating chunk {number}/{len(chunks)}...')

        try:
            translated = translate_nllb_chunk(chunk, language)

            if not translated:
                raise ValueError('NLLB returned empty translation.')

            translated_chunks.append(translated)
            print(f'    Chunk {number} completed.')
        except Exception as e:
            print(f'    NLLB translation error on chunk {number}:')

            print(f'    {e}')

            return None

    return ' '.join(translated_chunks).strip()

# ==========================================================
# TEXT CLEANING
# ==========================================================

def clean_text(text):

    if text is None:
        return ''

    text = str(text)

    text = html.unescape(text)

    text = BeautifulSoup(text, 'html.parser').get_text(' ')

    text = re.sub('https?://\\S+|www\\.\\S+', ' ', text)

    text = re.sub('\\S+@\\S+', ' ', text)

    text = text.lower()

    text = re.sub('[^a-z0-9\\s\\-]', ' ', text)

    text = re.sub('\\s+', ' ', text).strip()

    words = text.split()

    words = [word for word in words if word not in LOW_INFORMATION_WORDS]

    return ' '.join(words)

def assign_environment_category(text):

    if not text.strip():
        return (None, None)

    text_for_classification = text[:4000]

    try:
        result = category_classifier(text_for_classification, candidate_labels=ENVIRONMENT_CATEGORIES, hypothesis_template='This news article is mainly about {}.')

        category = result['labels'][0]

        confidence = result['scores'][0]

        return (category, round(float(confidence), 4))
    except Exception as e:
        print('  Classification error:', e)

        return (None, None)

def extract_keywords(text, top_n=KEYWORD_TOP_N):

    if not text.strip():
        return ''

    try:
        keywords = keyword_model.extract_keywords(text, keyphrase_ngram_range=(1, 2), stop_words='english', top_n=top_n, use_mmr=True, diversity=0.5)

        keyword_names = [keyword for keyword, score in keywords]

        return ', '.join(keyword_names)
    except Exception as e:
        print('  Keyword extraction error:', e)

        return ''

# ==========================================================
# SUPABASE DATA ACCESS
# ==========================================================

def get_pending_raw_articles():
    print()

    print('==========================================')

    print('LOADING PENDING RAW ARTICLES')

    print('==========================================')

    all_rows = []

    start = 0

    while True:
        response = supabase.table(RAW_TABLE).select('news_id,source_country,title,source,published_at,countries,article_text,url,cleaning_status').eq('cleaning_status', 'pending').order('news_id').range(start, start + SUPABASE_BATCH_SIZE - 1).execute()

        rows = response.data or []

        all_rows.extend(rows)
        if len(rows) < SUPABASE_BATCH_SIZE:
            break

        start += SUPABASE_BATCH_SIZE
    print(f'{len(all_rows)} pending raw article(s) found.')

    return all_rows

def get_existing_cleaned_rows():
    print()

    print('==========================================')

    print('LOADING EXISTING CLEANED DATA')

    print('==========================================')

    all_rows = []

    start = 0

    while True:
        response = supabase.table(CLEANED_TABLE).select('article_id,title,source,source_country,published_at,country,cleaned_text,environment_category,environment_keywords,semantic_score,confidence_score,url').order('article_id').range(start, start + SUPABASE_BATCH_SIZE - 1).execute()

        rows = response.data or []

        all_rows.extend(rows)
        if len(rows) < SUPABASE_BATCH_SIZE:
            break

        start += SUPABASE_BATCH_SIZE
    print(f'{len(all_rows)} existing cleaned row(s) found.')

    return all_rows

def set_raw_status(news_id, status):
    timestamp = datetime.now(timezone.utc).isoformat()

    response = supabase.table(RAW_TABLE).update({'cleaning_status': status, 'cleaned_at': timestamp}).eq('news_id', news_id).execute()

    return response

def insert_cleaned_rows(rows):

    if not rows:
        return 0

    response = supabase.table(CLEANED_TABLE).insert(rows).execute()

    if response.data:
        return len(response.data)

    return len(rows)

# ==========================================================
# SEMANTIC SCORE CALCULATION
# ==========================================================

def calculate_semantic_scores(cleaned_rows):
    print()

    print('==========================================')

    print('CALCULATING SEMANTIC SCORES')

    print('==========================================')

    if not cleaned_rows:
        print('No cleaned rows available.')

        return {}

    unique_articles = {}

    for row in cleaned_rows:
        article_id = row.get('article_id')

        if article_id is None:
            continue

        if article_id not in unique_articles:
            unique_articles[article_id] = {'article_id': article_id, 'cleaned_text': row.get('cleaned_text', '') or '', 'environment_category': row.get('environment_category')}

    article_list = list(unique_articles.values())

    if not article_list:
        return {}

    print(f'Unique articles used for semantic calculation: {len(article_list)}')

    texts = [article['cleaned_text'] for article in article_list]

    print('Generating article embeddings...')

    embeddings = embedding_model.encode(texts, show_progress_bar=True, convert_to_numpy=True)

    semantic_scores = {}

    for category in ENVIRONMENT_CATEGORIES:
        category_indices = [index for index, article in enumerate(article_list) if article['environment_category'] == category]

        if not category_indices:
            continue

        print(f'{category}: {len(category_indices)} article(s)')

        if len(category_indices) == 1:
            article_id = article_list[category_indices[0]]['article_id']

            semantic_scores[article_id] = 1.0

            continue

        category_embeddings = embeddings[category_indices]

        category_centroid = np.mean(category_embeddings, axis=0).reshape(1, -1)

        similarities = cosine_similarity(category_embeddings, category_centroid).flatten()

        for index, similarity in zip(category_indices, similarities):
            article_id = article_list[index]['article_id']

            semantic_scores[article_id] = round(float(similarity), 4)

    return semantic_scores

def update_semantic_scores(semantic_scores):
    print()

    print('==========================================')

    print('UPDATING SEMANTIC SCORES IN SUPABASE')

    print('==========================================')

    if not semantic_scores:
        print('No semantic scores to update.')

        return
    total = len(semantic_scores)

    total_rows_updated = 0

    for number, (article_id, score) in enumerate(semantic_scores.items(), start=1):
        try:
            response = supabase.table(CLEANED_TABLE).update({'semantic_score': score}).eq('article_id', article_id).execute()

            rows_updated = len(response.data or [])

            total_rows_updated += rows_updated
            print(f'Semantic update {number}/{total}: article_id={article_id}, score={score}, rows={rows_updated}')
        except Exception as e:
            print(f'ERROR updating semantic score for article {article_id}:')

            print(e)

    print()

    print('Semantic score update finished.')

    print(f'Rows updated: {total_rows_updated}')

# ==========================================================
# PROCESS ONE ARTICLE
# ==========================================================

def process_article(article, existing_pairs):
    news_id = article.get('news_id')

    title = article.get('title') or ''

    article_text = article.get('article_text') or ''

    source_country = article.get('source_country') or ''

    print()

    print('------------------------------------------')

    print(f'ARTICLE {news_id}')

    print(title[:150])

    print('  Source country:', source_country)

    countries = parse_countries(article.get('countries'))

    print('  Raw countries:', article.get('countries'))

    print('  Parsed countries:', ', '.join(countries) if countries else 'None')

    if not countries:
        print('  REJECTED: No target ASEAN country detected.')

        return {'status': 'rejected', 'reason': 'no_country', 'rows': []}

    modelling_text = (title.strip() + '. ' + article_text.strip()).strip()

    if not modelling_text:
        print('  REJECTED: Empty article text.')

        return {'status': 'rejected', 'reason': 'empty_text', 'rows': []}

    detected_language = detect_language(modelling_text)

    print('  langdetect result:', detected_language)

    language = resolve_language(detected_language, source_country, modelling_text)

    print('  Final language:', language)

    print('  Processing title translation...')

    translated_title = translate_to_english(title, language)

    if translated_title is None:
        print('  PROCESSING FAILED: Title translation failed.')

        return {'status': 'pending', 'reason': 'translation_failed', 'rows': []}

    translated_title = translated_title.strip()

    print('  English title:', translated_title)

    print('  Processing article text translation...')

    translated_article_text = translate_to_english(article_text, language)

    if translated_article_text is None:
        print('  PROCESSING FAILED: Article translation failed.')

        return {'status': 'pending', 'reason': 'translation_failed', 'rows': []}

    translated_text = (translated_title.strip() + '. ' + translated_article_text.strip()).strip()

    cleaned_text = clean_text(translated_text)

    word_count = len(cleaned_text.split())

    print('  Cleaned word count:', word_count)

    if word_count < MIN_WORD_COUNT:
        print('  REJECTED: Insufficient usable text.')

        return {'status': 'rejected', 'reason': 'insufficient_text', 'rows': []}

    print('  Classifying environmental category...')

    category, confidence = assign_environment_category(cleaned_text)

    if category is None or confidence is None:
        print('  PROCESSING FAILED: Classification failed.')

        return {'status': 'pending', 'reason': 'classification_failed', 'rows': []}

    print('  Category:', category)

    print('  Confidence:', confidence)

    if confidence < MIN_CATEGORY_CONFIDENCE:
        print(f'  REJECTED: Category confidence {confidence} is below {MIN_CATEGORY_CONFIDENCE}.')

        return {'status': 'rejected', 'reason': 'low_confidence', 'rows': []}

    print('  Extracting environmental keywords...')

    keywords = extract_keywords(cleaned_text)

    print('  Keywords:', keywords if keywords else 'None')

    cleaned_rows = []

    for country in countries:
        pair = (news_id, country)

        if pair in existing_pairs:
            print(f'  Already exists: {news_id} / {country}')

            continue

        row = {'article_id': news_id, 'title': translated_title, 'source': article.get('source') or '', 'source_country': source_country, 'published_at': article.get('published_at'), 'country': country, 'cleaned_text': cleaned_text, 'environment_category': category, 'environment_keywords': keywords, 'semantic_score': None, 'confidence_score': confidence, 'url': article.get('url') or ''}

        cleaned_rows.append(row)

    if not cleaned_rows:
        print('  All required cleaned rows already exist.')

        return {'status': 'accepted', 'reason': 'already_exists', 'rows': []}

    return {'status': 'accepted', 'reason': 'accepted', 'rows': cleaned_rows}

# ==========================================================
# MAIN PIPELINE
# ==========================================================

def main():
    print()

    print('==========================================')

    print('ASEAN NEWS CLEANING PIPELINE')

    print('==========================================')

    print('Raw table:', RAW_TABLE)

    print('Cleaned table:', CLEANED_TABLE)

    print('Minimum word count:', MIN_WORD_COUNT)

    print('Minimum category confidence:', MIN_CATEGORY_CONFIDENCE)

    print('Translation model:', NLLB_MODEL_NAME)

    print('Processing device:', DEVICE)
    # Load existing cleaned rows so duplicate article-country pairs are skipped.
    existing_cleaned_rows = get_existing_cleaned_rows()

    existing_pairs = set()

    for row in existing_cleaned_rows:
        article_id = row.get('article_id')

        country = row.get('country')

        if article_id is not None and country:
            existing_pairs.add((article_id, country))
    # Load only raw rows that still need cleaning.
    pending_articles = get_pending_raw_articles()

    if not pending_articles:
        print()

        print('No pending raw articles.')

        print('No article cleaning is required.')

        print('Semantic scores will still be recalculated.')

    stats = {'pending': len(pending_articles), 'accepted': 0, 'rejected': 0, 'failed': 0, 'inserted_rows': 0, 'translation_failed': 0, 'classification_failed': 0, 'no_country': 0, 'empty_text': 0, 'insufficient_text': 0, 'low_confidence': 0}

    for number, article in enumerate(pending_articles, start=1):
        news_id = article.get('news_id')

        print()

        print('==========================================')

        print(f'PROCESSING {number}/{len(pending_articles)}')

        print('==========================================')

        try:
            result = process_article(article, existing_pairs)

            status = result['status']

            reason = result['reason']

            rows = result['rows']

            if status == 'accepted':
                if rows:
                    inserted = insert_cleaned_rows(rows)

                    stats['inserted_rows'] += inserted
                    for row in rows:
                        existing_pairs.add((row['article_id'], row['country']))
                set_raw_status(news_id, 'accepted')
                stats['accepted'] += 1
                print('  RAW STATUS -> accepted')
            elif status == 'rejected':
                set_raw_status(news_id, 'rejected')
                stats['rejected'] += 1
                if reason in stats:
                    stats[reason] += 1
                print('  RAW STATUS -> rejected')
            else:
                stats['failed'] += 1
                if reason in stats:
                    stats[reason] += 1
                print('  RAW STATUS remains pending.')

                print('  This article can be retried on the next run.')
        except Exception as e:
            stats['failed'] += 1
            print('  UNEXPECTED PROCESSING ERROR:')

            print(e)

            print('  RAW STATUS remains pending.')

    all_cleaned_rows = get_existing_cleaned_rows()
    # Recalculate semantic similarity after new rows have been inserted.
    semantic_scores = calculate_semantic_scores(all_cleaned_rows)

    update_semantic_scores(semantic_scores)
    print()

    print('==========================================')

    print('CLEANING FINISHED')

    print('==========================================')

    print('Pending raw articles found:', stats['pending'])

    print('Accepted articles this run:', stats['accepted'])

    print('Rejected articles this run:', stats['rejected'])

    print('Processing failures / retry later:', stats['failed'])

    print('Cleaned country rows inserted:', stats['inserted_rows'])

    print()

    print('REJECTION BREAKDOWN')

    print('No target country:', stats['no_country'])

    print('Empty text:', stats['empty_text'])

    print('Insufficient text:', stats['insufficient_text'])

    print('Low category confidence:', stats['low_confidence'])

    print()

    print('RETRY BREAKDOWN')

    print('Translation failures:', stats['translation_failed'])

    print('Classification failures:', stats['classification_failed'])

    print()

    print('Supabase raw table:', RAW_TABLE)

    print('Supabase cleaned table:', CLEANED_TABLE)

    print()

if __name__ == '__main__':
    main()
