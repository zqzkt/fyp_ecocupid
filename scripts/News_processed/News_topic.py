"""

Supabase Monthly Environmental Topic Pipeline

Balanced formatting version:

- same executable logic as the original News_topic.py

- preserves one primary topic per article

- preserves registry matching and monthly country-specific statistics

- removes excessive vertical formatting while keeping readable spacing

"""
import os
import re
import time
import warnings
from collections import defaultdict
from datetime import datetime, timezone
import numpy as np
import pandas as pd
from dotenv import load_dotenv
from supabase import create_client
from sentence_transformers import SentenceTransformer
from sklearn.cluster import AgglomerativeClustering
from sklearn.feature_extraction.text import TfidfVectorizer, ENGLISH_STOP_WORDS
from sklearn.metrics.pairwise import cosine_similarity
from transformers import pipeline
# ==========================================================
# SETTINGS AND ENVIRONMENT
# ==========================================================
warnings.filterwarnings("ignore")
load_dotenv()
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')
if not SUPABASE_URL:
    raise ValueError('SUPABASE_URL is missing from .env')
if not SUPABASE_KEY:
    raise ValueError('SUPABASE_KEY is missing from .env')
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
CLEANED_TABLE = 'news_cleaned'
TOPIC_REGISTRY_TABLE = 'topic_registry'
NEWS_TOPICS_TABLE = 'news_topics'
MONTHLY_STATS_TABLE = 'monthly_topic_stats'
TARGET_COUNTRIES = [
    "Singapore",
    "Malaysia",
    "Indonesia",
    "Thailand",
    "Philippines",
    "Brunei",
]
# Set True only for the one-time historical baseline rebuild.
# After the June-August baseline succeeds, change this to False.
REBUILD_MODE = False
# Topic discovery is similarity-driven. We do NOT force a target number of topics.
# A higher distance allows genuinely related articles to cluster more readily,
# while unique stories are still allowed to remain as one-article topics.
PRIMARY_CLUSTER_DISTANCE = 0.58
TOPIC_MERGE_SIMILARITY = 0.58
# Incremental articles/monthly clusters match the established registry.
REGISTRY_MATCH_THRESHOLD = 0.64
# During a historical baseline rebuild, be stricter when deciding that two
# independently discovered clusters are actually the same reusable topic.
# This prevents unrelated clusters from being merged merely because a generic
# naming rule produced the same label.
BASELINE_TOPIC_DEDUP_SIMILARITY = 0.72
BASELINE_KEYWORD_OVERLAP_THRESHOLD = 0.50
WHOLE_ARTICLE_WEIGHT = 0.45
STRONGEST_CHUNK_WEIGHT = 0.55
CHUNK_SIZE = 100
CHUNK_STRIDE = 60
TOP_KEYWORDS = 3
MAX_KEYWORD_CANDIDATES = 30
PAGE_SIZE = 1000
WRITE_BATCH_SIZE = 100
CUSTOM_STOPWORDS = set(ENGLISH_STOP_WORDS)
CUSTOM_STOPWORDS.update({'said', 'say', 'says', 'according', 'reported', 'report', 'reports', 'told', 'added', 'published', 'updated', 'article', 'news', 'people', 'public', 'year', 'years', 'new', 'government', 'ministry', 'agency', 'official', 'officials', 'singapore', 'singaporean', 'singaporeans', 'malaysia', 'malaysian', 'malaysians', 'indonesia', 'indonesian', 'indonesians', 'thailand', 'thai', 'philippines', 'philippine', 'filipino', 'filipinos', 'brunei', 'bruneian', 'asean'})
print()
print('=' * 70)
print('LOADING NLP MODELS')
print('=' * 70)
print('Loading MiniLM embedding model...')
embedding_model = SentenceTransformer('all-MiniLM-L6-v2')
print('MiniLM loaded.')
print('Loading FLAN-T5...')
text_generator = pipeline('text2text-generation', model='google/flan-t5-base', tokenizer='google/flan-t5-base', device=-1)
print('FLAN-T5 loaded.')
# ==========================================================
# TEXT HELPERS
# ==========================================================
def normalise_text(text):
    if pd.isna(text):
        return ''
    text = str(text)
    text = re.sub('\\s+', ' ', text)
    return text.strip()
def generate_text(prompt, max_new_tokens=60):
    try:
        result = text_generator(prompt, max_new_tokens=max_new_tokens, do_sample=False)
        return normalise_text(result[0]['generated_text'])
    except Exception as e:
        print(f'FLAN-T5 generation failed: {e}')
        return ''
def clean_generated_sentence(text):
    text = normalise_text(text)
    text = re.sub('^(summary|article summary|explanation|relevance|answer)\\s*:\\s*', '', text, flags=re.IGNORECASE).strip()
    match = re.match('^(.+?[.!?])(?:\\s|$)', text)
    if match:
        text = match.group(1).strip()
    if text and text[-1] not in '.!?':
        text += '.'
    return text
# ==========================================================
# SUPABASE HELPERS
# ==========================================================
def fetch_all_rows(table_name, columns="*"):
    rows = []
    start = 0
    while True:
        response = supabase.table(table_name).select(columns).range(start, start + PAGE_SIZE - 1).execute()
        batch = response.data or []
        rows.extend(batch)
        if len(batch) < PAGE_SIZE:
            break
        start += PAGE_SIZE
    return rows
def month_start_string(value):
    dt = pd.to_datetime(value, utc=True, errors='coerce')
    if pd.isna(dt):
        return None
    return f'{dt.year:04d}-{dt.month:02d}-01'
# ==========================================================
# EMBEDDING AND CLUSTERING HELPERS
# ==========================================================
def split_into_chunks(text):
    words = normalise_text(text).split()
    if not words:
        return []
    if len(words) <= CHUNK_SIZE:
        return [' '.join(words)]
    chunks = []
    start = 0
    while start < len(words):
        chunk = words[start:start + CHUNK_SIZE]
        if len(chunk) >= 25:
            chunks.append(' '.join(chunk))
        start += CHUNK_STRIDE
    return chunks
def calculate_centroid(embeddings):
    centroid = np.mean(embeddings, axis=0)
    norm = np.linalg.norm(centroid)
    if norm > 0:
        centroid = centroid / norm
    return centroid
def cluster_articles(embeddings):
    if len(embeddings) == 1:
        return np.array([0])
    clustering_model = AgglomerativeClustering(n_clusters=None, metric='cosine', linkage='average', distance_threshold=PRIMARY_CLUSTER_DISTANCE)
    return clustering_model.fit_predict(embeddings)
def merge_similar_clusters(embeddings, labels):
    unique_labels = sorted(set(labels))
    if len(unique_labels) <= 1:
        return np.zeros(len(labels), dtype=int)
    centroids = []
    for label in unique_labels:
        positions = np.where(labels == label)[0]
        centroid = calculate_centroid(embeddings[positions])
        centroids.append(centroid)
    centroids = np.vstack(centroids)
    merge_model = AgglomerativeClustering(n_clusters=None, metric='cosine', linkage='average', distance_threshold=1 - TOPIC_MERGE_SIMILARITY)
    merged_labels = merge_model.fit_predict(centroids)
    mapping = {original_label: merged_label for original_label, merged_label in zip(unique_labels, merged_labels)}
    return np.array([mapping[label] for label in labels])
def keep_similarity_driven_clusters(raw_labels):
    """Keep the semantic clusters as discovered.

    No target topic count is imposed. This means a genuinely unique article may

    remain a one-article topic, while articles that are semantically related are

    grouped by the two similarity stages above.

    """
    raw_labels = np.asarray(raw_labels)
    unique_labels = sorted(set(raw_labels))
    remap = {old: new for new, old in enumerate(unique_labels)}
    return np.array([remap[label] for label in raw_labels])
# ==========================================================
# TOPIC KEYWORDS AND NAMING
# ==========================================================
def clean_keyword(phrase):
    phrase = normalise_text(phrase).lower()
    words = []
    for word in phrase.split():
        word = re.sub('[^a-zA-Z\\\\-]', '', word)
        if not word:
            continue
        if word in CUSTOM_STOPWORDS:
            continue
        if len(word) <= 2:
            continue
        if re.fullmatch('(19|20)\\d{2}', word):
            continue
        words.append(word)
    if not words:
        return None
    return ' '.join(words)
def remove_redundant_keywords(keywords):
    selected = []
    for candidate in keywords:
        candidate_words = set(candidate.split())
        redundant = False
        for existing in selected:
            existing_words = set(existing.split())
            intersection = len(candidate_words & existing_words)
            smaller = min(len(candidate_words), len(existing_words))
            if smaller > 0 and intersection / smaller >= 0.8:
                redundant = True
                break
        if not redundant:
            selected.append(candidate)
        if len(selected) >= TOP_KEYWORDS:
            break
    return selected
def extract_topic_keywords(documents, topic_centroid):
    documents = [normalise_text(document) for document in documents if normalise_text(document)]
    if not documents:
        return []
    vectorizer = TfidfVectorizer(stop_words=list(CUSTOM_STOPWORDS), ngram_range=(1, 3), min_df=1, max_df=1.0, max_features=5000)
    try:
        matrix = vectorizer.fit_transform(documents)
    except ValueError:
        return []
    features = vectorizer.get_feature_names_out()
    tfidf_scores = np.asarray(matrix.mean(axis=0)).flatten()
    ranked_positions = np.argsort(tfidf_scores)[::-1]
    candidates = []
    for position in ranked_positions:
        phrase = clean_keyword(features[position])
        if not phrase:
            continue
        if phrase not in candidates:
            candidates.append(phrase)
        if len(candidates) >= MAX_KEYWORD_CANDIDATES:
            break
    if not candidates:
        return []
    candidate_embeddings = embedding_model.encode(candidates, convert_to_numpy=True, normalize_embeddings=True, show_progress_bar=False)
    semantic_scores = cosine_similarity(candidate_embeddings, topic_centroid.reshape(1, -1)).flatten()
    semantic_order = np.argsort(semantic_scores)[::-1]
    ranked_keywords = [candidates[position] for position in semantic_order]
    return remove_redundant_keywords(ranked_keywords)[:TOP_KEYWORDS]
ENVIRONMENTAL_SEARCH_TERMS = {
    'biodiversity and conservation': [
        'wildlife conservation', 'species conservation', 'habitat protection',
        'endangered species', 'biodiversity conservation', 'wildlife protection'
    ],
    'agriculture and food sustainability': [
        'sustainable agriculture', 'food security', 'sustainable farming',
        'climate resilient agriculture', 'agricultural sustainability'
    ],
    'climate change': [
        'climate change', 'climate adaptation', 'climate mitigation',
        'carbon emissions', 'climate resilience'
    ],
    'deforestation and forest conservation': [
        'forest conservation', 'deforestation', 'illegal logging',
        'forest protection', 'forest restoration', 'land encroachment'
    ],
    'energy and fossil fuels': [
        'energy transition', 'fossil fuels', 'decarbonization',
        'clean energy', 'energy security'
    ],
    'environmental health': [
        'environmental health', 'heat exposure', 'pollution health impacts',
        'climate health', 'environmental risk'
    ],
    'extreme weather and natural hazards': [
        'extreme weather', 'natural disasters', 'flood risk', 'drought',
        'disaster resilience', 'climate hazards'
    ],
    'green finance and environmental policy': [
        'green finance', 'environmental policy', 'carbon tax',
        'climate finance', 'environmental regulation'
    ],
    'oceans and marine conservation': [
        'marine conservation', 'marine biodiversity', 'ocean conservation',
        'coastal protection', 'sustainable fisheries'
    ],
    'pollution': [
        'air pollution', 'water pollution', 'plastic pollution',
        'air quality', 'water quality', 'waste pollution', 'haze'
    ],
    'renewable energy': [
        'renewable energy', 'solar energy', 'clean energy',
        'green electricity', 'energy transition'
    ],
    'sustainable transport': [
        'sustainable transport', 'public transport', 'electric vehicles',
        'transport emissions', 'low carbon transport'
    ],
    'waste management': [
        'waste management', 'recycling', 'plastic waste',
        'food waste', 'circular economy', 'waste reduction'
    ],
}
GENERIC_ENTITY_WORDS = {
    'minister','government','department','authority','company','group','village',
    'city','province','district','island','country','festival','farmers','farmer',
    'people','officials','malaysia','indonesia','thailand','singapore','philippines',
    'brunei','sulawesi','sumatra','sabah','sarawak','cpi'
}
def _contains_phrase(text, phrase):
    return re.search(r'(?<!\w)' + re.escape(phrase.lower()) + r'(?!\w)', text.lower()) is not None
def _specific_environmental_phrases(category, combined_text, raw_keywords):
    """Create environmentally meaningful search phrases from article evidence.

    Raw KeyBERT terms such as 'sloth' or 'Sulawesi' are not emitted directly.

    When a species/crop/entity is useful, it is paired with an environmental

    concept, e.g. 'sloth conservation' rather than simply 'sloth'.

    """
    category_l = normalise_text(category).lower()
    text_l = normalise_text(combined_text).lower()
    candidates = []
    # First preserve explicit environmental phrases that actually occur.
    for phrase in ENVIRONMENTAL_SEARCH_TERMS.get(category_l, []):
        if _contains_phrase(text_l, phrase):
            candidates.append(phrase)
    # Useful issue signals across categories.
    issue_phrases = [
        'illegal wildlife trade','wildlife trafficking','wildlife rescue',
        'habitat loss','habitat destruction','species extinction','endangered species',
        'protected areas','national park','forest restoration','forest conservation',
        'illegal logging','land encroachment','mangrove conservation',
        'mangrove restoration','coral reef conservation','marine biodiversity',
        'coastal erosion','sustainable fisheries','overfishing','air pollution',
        'air quality','pm2.5','haze','water pollution','water quality','arsenic pollution',
        'plastic pollution','plastic waste','waste management','recycling',
        'climate change','climate adaptation','climate resilience','heat stress',
        'extreme heat','flood risk','drought','forest fires','wildfires',
        'renewable energy','solar energy','nuclear energy','energy transition',
        'fossil fuels','carbon emissions','carbon tax','sustainable agriculture',
        'organic farming','food security','climate resilient agriculture'
    ]
    for phrase in issue_phrases:
        if _contains_phrase(text_l, phrase):
            candidates.append(phrase)
    # If KeyBERT found a specific subject, keep specificity but attach an
    # environmental intent so downstream social searches remain relevant.
    raw_clean = []
    for kw in raw_keywords:
        kw = clean_keyword(kw)
        if not kw or kw in GENERIC_ENTITY_WORDS or len(kw) < 3:
            continue
        if any(token in GENERIC_ENTITY_WORDS for token in kw.split()) and len(kw.split()) == 1:
            continue
        raw_clean.append(kw)
    if category_l == 'biodiversity and conservation':
        for kw in raw_clean[:3]:
            if not any(x in kw for x in ['conservation','biodiversity','habitat','endangered','wildlife','protection','trafficking','trade']):
                candidates.append(f'{kw} conservation')
    elif category_l == 'oceans and marine conservation':
        for kw in raw_clean[:3]:
            if not any(x in kw for x in ['conservation','marine','ocean','coastal','fisher']):
                candidates.append(f'{kw} marine conservation')
    elif category_l == 'deforestation and forest conservation':
        for kw in raw_clean[:2]:
            if not any(x in kw for x in ['forest','logging','deforestation','conservation']):
                candidates.append(f'{kw} forest conservation')
    elif category_l == 'agriculture and food sustainability':
        for kw in raw_clean[:2]:
            if not any(x in kw for x in ['sustainable','agriculture','farming','food security']):
                candidates.append(f'{kw} sustainable agriculture')
    # Add category-level fallbacks only when needed.
    for phrase in ENVIRONMENTAL_SEARCH_TERMS.get(category_l, []):
        candidates.append(phrase)
    cleaned = []
    for phrase in candidates:
        phrase = normalise_text(phrase).lower().strip(' ,.;:-')
        if phrase and phrase not in cleaned:
            cleaned.append(phrase)
        if len(cleaned) >= TOP_KEYWORDS:
            break
    return cleaned
def extract_environmental_topic_keywords(environment_category, documents, topic_centroid):
    raw_keywords = extract_topic_keywords(documents, topic_centroid)
    combined_text = ' '.join(normalise_text(d) for d in documents if normalise_text(d))
    return _specific_environmental_phrases(environment_category, combined_text, raw_keywords)
def generate_issue_topic_name(environment_category, keywords):
    """Deterministic topic naming from environmental search phrases.

    Avoids FLAN outputs such as place names, 'dashboard-level environmental

    issues', or copied headlines. Unique clusters still receive normal topic IDs.

    """
    if not keywords:
        return keyword_topic_name([environment_category])
    first = normalise_text(keywords[0])
    # Keep common acronyms readable.
    name = first.title().replace('Pm2.5', 'PM2.5')
    return name
def keyword_topic_name(keywords):
    if not keywords:
        return 'Unlabelled Topic'
    name = normalise_text(keywords[0])
    if not name:
        return 'Unlabelled Topic'
    return name.title()
def generate_topic_name(environment_category, keywords, titles):
    keyword_text = ', '.join(keywords[:5])
    title_text = ' | '.join(
        normalise_text(title) for title in titles[:8] if normalise_text(title)
    )
    prompt = f"""Create ONE dashboard-level environmental topic name for this group of news articles.
Environmental category: {environment_category}
Representative keywords: {keyword_text}
Representative article titles: {title_text}
The name must describe the SHARED environmental theme across the articles, not one article.
Good examples:
- tiger, elephant, orangutan protection -> Wildlife Conservation
- turtles, dugongs, coral and marine species -> Marine Biodiversity Conservation
- mangrove restoration, mangrove loss, coastal habitat -> Mangrove and Coastal Conservation
- poaching, wildlife seizures, illegal animal trade -> Wildlife Crime and Trafficking
- newly discovered frogs, snakes and other species -> Species Discovery and Biodiversity
- haze, PM2.5 and air quality -> Air Pollution and Haze
- sustainable farming, organic agriculture, crop resilience -> Sustainable Agriculture
Strict rules:
- Use 2 to 5 words.
- Name a reusable environmental THEME suitable for a dashboard.
- Be broader than a single species, crop, company, person, park, village, city or country.
- Do NOT use a person's name, organisation name, place name or country name.
- Do NOT use a single species or single crop as the topic name.
- Do NOT copy an article headline.
- Do NOT simply repeat the environmental category.
- Do NOT say 'environmental issue', 'news', 'article' or 'topic'.
- Return only the topic name."""
    topic_name = generate_text(prompt, max_new_tokens=16)
    topic_name = re.sub('[\n\r]+', ' ', topic_name)
    topic_name = re.sub(r'\s+', ' ', topic_name).strip(" .,:;-/\\\"'")
    prefixes = ['topic:', 'topic name:', 'subtopic:', 'subtopic name:']
    for prefix in prefixes:
        if topic_name.lower().startswith(prefix):
            topic_name = topic_name[len(prefix):].strip()
    topic_name = re.sub(r'\b(?:19|20)\d{2}\b', '', topic_name)
    topic_name = re.sub(r'\s+', ' ', topic_name).strip(" .,:;-/\\\"'")
    invalid_names = {
        '', 'environment', 'environmental issue', 'environmental issues',
        'environmental problem', 'environmental problems', 'environmental topic',
        'environmental topics', environment_category.lower()
    }
    # A keyword fallback is preferable to an unusable sentence, although the
    # stricter prompt should make this uncommon.
    if topic_name.lower() in invalid_names or len(topic_name.split()) > 6:
        topic_name = keyword_topic_name(keywords)
    return topic_name
# ==========================================================
# ARTICLE-TOPIC SCORING AND GENERATED TEXT
# ==========================================================
def calculate_article_topic_score(article_text, article_embedding, topic_centroid):
    whole_similarity = float(cosine_similarity(article_embedding.reshape(1, -1), topic_centroid.reshape(1, -1))[0][0])
    chunks = split_into_chunks(article_text)
    if not chunks:
        return whole_similarity
    chunk_embeddings = embedding_model.encode(chunks, convert_to_numpy=True, normalize_embeddings=True, show_progress_bar=False)
    chunk_scores = cosine_similarity(chunk_embeddings, topic_centroid.reshape(1, -1)).flatten()
    strongest_chunk = float(np.max(chunk_scores))
    final_score = WHOLE_ARTICLE_WEIGHT * whole_similarity + STRONGEST_CHUNK_WEIGHT * strongest_chunk
    return float(final_score)
def generate_article_summary(title, article_text):
    title = normalise_text(title)
    article_text = normalise_text(article_text)
    article_for_prompt = article_text[:3500]
    prompt = f'Summarize this environmental news article in exactly one concise factual sentence. State the main issue or development. Do not add information that is not stated in the article. Return only one sentence.\n\nTitle: {title}\n\nArticle: {article_for_prompt}'
    summary = generate_text(prompt, max_new_tokens=70)
    summary = clean_generated_sentence(summary)
    if not summary:
        summary = clean_generated_sentence(title)
    if not summary:
        summary = 'The article discusses an environmental development.'
    return summary
def generate_topic_relevance_explanation(article_summary, topic_name, topic_keywords):
    keyword_text = ', '.join(topic_keywords)
    prompt = f'Explain in exactly one concise factual sentence why this article belongs to the assigned environmental topic. Use only the information provided. Do not introduce new facts. Return only one sentence.\n\nArticle summary: {article_summary}\n\nAssigned topic: {topic_name}\n\nTopic keywords: {keyword_text}'
    explanation = generate_text(prompt, max_new_tokens=70)
    explanation = clean_generated_sentence(explanation)
    if not explanation:
        explanation = f'The article relates to {topic_name} through the environmental issue described in its content.'
    return explanation
# ==========================================================
# LOAD PIPELINE DATA
# ==========================================================
def load_cleaned_rows():
    print()
    print('=' * 70)
    print('LOADING NEWS_CLEANED')
    print('=' * 70)
    rows = fetch_all_rows(CLEANED_TABLE, 'article_id,title,published_at,country,cleaned_text,environment_category')
    df = pd.DataFrame(rows)
    if df.empty:
        print('No news_cleaned rows found.')
        return df
    df['article_id'] = pd.to_numeric(df['article_id'], errors='coerce')
    df = df[df['article_id'].notna()].copy()
    df['article_id'] = df['article_id'].astype(int)
    for column in ['title', 'country', 'cleaned_text', 'environment_category']:
        df[column] = df[column].fillna('').astype(str)
    df = df[df['country'].isin(TARGET_COUNTRIES) & (df['cleaned_text'].str.strip() != '') & (df['environment_category'].str.strip() != '')].copy()
    print(f'Valid cleaned rows loaded: {len(df)}')
    print(f"Unique articles: {df['article_id'].nunique()}")
    return df
def load_processed_pairs():
    rows = fetch_all_rows(NEWS_TOPICS_TABLE, 'article_id,country')
    processed_pairs = set()
    for row in rows:
        article_id = row.get('article_id')
        country = row.get('country')
        if article_id is None or country is None:
            continue
        processed_pairs.add((int(article_id), str(country)))
    print(f'Previously processed article-country pairs: {len(processed_pairs)}')
    return processed_pairs
def load_topic_registry():
    rows = fetch_all_rows(TOPIC_REGISTRY_TABLE, 'topic_id,environment_category,topic_name,topic_keywords,topic_centroid,first_detected_at,last_detected_at')
    registry = []
    for row in rows:
        centroid = row.get('topic_centroid')
        if not isinstance(centroid, list):
            continue
        try:
            centroid_array = np.asarray(centroid, dtype=float)
        except Exception:
            continue
        if centroid_array.ndim != 1:
            continue
        if centroid_array.size == 0:
            continue
        norm = np.linalg.norm(centroid_array)
        if norm > 0:
            centroid_array = centroid_array / norm
        row['centroid_array'] = centroid_array
        registry.append(row)
    print(f'Registry topics loaded: {len(registry)}')
    return registry
# ==========================================================
# TOPIC REGISTRY
# ==========================================================
def get_next_topic_number(registry):
    highest = 0
    for topic in registry:
        topic_id = str(topic.get('topic_id', '')).strip()
        match = re.fullmatch('T(\\d+)', topic_id)
        if match:
            highest = max(highest, int(match.group(1)))
    return highest + 1
def find_registry_match(environment_category, new_centroid, registry):
    candidates = [topic for topic in registry if topic.get('environment_category') == environment_category]
    if not candidates:
        return (None, None)
    best_topic = None
    best_similarity = -1.0
    for topic in candidates:
        existing_centroid = topic['centroid_array']
        if existing_centroid.shape != new_centroid.shape:
            continue
        similarity = float(cosine_similarity(new_centroid.reshape(1, -1), existing_centroid.reshape(1, -1))[0][0])
        if similarity > best_similarity:
            best_similarity = similarity
            best_topic = topic
    if best_topic is not None and best_similarity >= REGISTRY_MATCH_THRESHOLD:
        return (best_topic, best_similarity)
    return (None, best_similarity)
def _normalised_topic_label(value):
    value = normalise_text(value).lower()
    value = re.sub(r'[^a-z0-9]+', ' ', value)
    return re.sub(r'\s+', ' ', value).strip()
def _keyword_set(keywords):
    if isinstance(keywords, str):
        keywords = [part.strip() for part in keywords.split(',')]
    return {
        _normalised_topic_label(keyword)
        for keyword in (keywords or [])
        if _normalised_topic_label(keyword)
    }
def _keyword_overlap(left_keywords, right_keywords):
    left = _keyword_set(left_keywords)
    right = _keyword_set(right_keywords)
    if not left or not right:
        return 0.0
    return len(left & right) / min(len(left), len(right))
def find_baseline_concept_match(environment_category, proposed_name, proposed_keywords, new_centroid, registry):
    """Find an already-created baseline topic representing the same concept.

    Exact duplicate labels alone are NOT enough to merge. We require either

    strong semantic centroid similarity or substantial overlap between the

    environmental search phrases. This lets legitimate singleton topics remain

    independent while preventing duplicate registry rows for the same theme.

    """
    candidates = [
        topic for topic in registry
        if topic.get('environment_category') == environment_category
    ]
    if not candidates:
        return None, None, None
    proposed_label = _normalised_topic_label(proposed_name)
    best = None
    best_similarity = -1.0
    best_overlap = 0.0
    for topic in candidates:
        existing_centroid = topic.get('centroid_array')
        if existing_centroid is None or existing_centroid.shape != new_centroid.shape:
            similarity = -1.0
        else:
            similarity = float(cosine_similarity(
                new_centroid.reshape(1, -1),
                existing_centroid.reshape(1, -1)
            )[0][0])
        overlap = _keyword_overlap(proposed_keywords, topic.get('topic_keywords', ''))
        same_label = _normalised_topic_label(topic.get('topic_name', '')) == proposed_label
        # A same label still needs evidence that the underlying concept matches.
        concept_match = (
            similarity >= BASELINE_TOPIC_DEDUP_SIMILARITY or
            overlap >= BASELINE_KEYWORD_OVERLAP_THRESHOLD
        )
        if concept_match and (similarity, overlap) > (best_similarity, best_overlap):
            best = topic
            best_similarity = similarity
            best_overlap = overlap
    return best, best_similarity, best_overlap
def make_distinct_topic_name(base_name, keywords, registry, environment_category):
    """Avoid duplicate display names when clusters are genuinely different."""
    existing_names = {
        _normalised_topic_label(topic.get('topic_name', ''))
        for topic in registry
        if topic.get('environment_category') == environment_category
    }
    if _normalised_topic_label(base_name) not in existing_names:
        return base_name
    base_norm = _normalised_topic_label(base_name)
    qualifiers = []
    for keyword in keywords or []:
        keyword = normalise_text(keyword)
        keyword_norm = _normalised_topic_label(keyword)
        if not keyword_norm or keyword_norm == base_norm:
            continue
        # Skip a phrase that merely repeats the base label plus one filler word.
        if keyword_norm in base_norm or base_norm in keyword_norm:
            extra = [w for w in keyword_norm.split() if w not in base_norm.split()]
            if not extra:
                continue
        qualifiers.append(keyword)
    for qualifier in qualifiers:
        qualifier_title = qualifier.title().replace('Pm2.5', 'PM2.5')
        # Prefer an issue-style combined label rather than parentheses/place-like labels.
        candidate = f'{base_name} & {qualifier_title}'
        if len(candidate.split()) <= 7 and _normalised_topic_label(candidate) not in existing_names:
            return candidate
    # Last-resort deterministic distinction. This should be uncommon, but is
    # preferable to multiple different topic_ids carrying exactly the same name.
    suffix = 2
    while _normalised_topic_label(f'{base_name} {suffix}') in existing_names:
        suffix += 1
    return f'{base_name} {suffix}'
def merge_topic_keywords(existing_keywords, new_keywords):
    combined = []
    if isinstance(existing_keywords, str):
        existing_keywords = [x.strip() for x in existing_keywords.split(',') if x.strip()]
    for keyword in list(existing_keywords or []) + list(new_keywords or []):
        keyword = normalise_text(keyword)
        if keyword and _normalised_topic_label(keyword) not in {
            _normalised_topic_label(x) for x in combined
        }:
            combined.append(keyword)
    return combined[:TOP_KEYWORDS]
def update_registry_topic_baseline(topic, new_keywords, new_centroid, detected_at):
    """Refresh a reused baseline registry topic with combined evidence."""
    merged_keywords = merge_topic_keywords(topic.get('topic_keywords', ''), new_keywords)
    old_centroid = topic.get('centroid_array')
    if old_centroid is not None and old_centroid.shape == new_centroid.shape:
        merged_centroid = old_centroid + new_centroid
        norm = np.linalg.norm(merged_centroid)
        if norm > 0:
            merged_centroid = merged_centroid / norm
    else:
        merged_centroid = new_centroid.copy()
    payload = {
        'topic_keywords': ', '.join(merged_keywords),
        'topic_centroid': merged_centroid.astype(float).tolist(),
        'last_detected_at': detected_at,
        'updated_at': datetime.now(timezone.utc).isoformat()
    }
    supabase.table(TOPIC_REGISTRY_TABLE).update(payload).eq('topic_id', topic['topic_id']).execute()
    topic['topic_keywords'] = payload['topic_keywords']
    topic['topic_centroid'] = payload['topic_centroid']
    topic['centroid_array'] = merged_centroid
    topic['last_detected_at'] = detected_at
    return topic
def insert_registry_topic(topic_id, environment_category, topic_name, topic_keywords, centroid, first_detected_at, last_detected_at):
    payload = {'topic_id': topic_id, 'environment_category': environment_category, 'topic_name': topic_name, 'topic_keywords': ', '.join(topic_keywords), 'topic_centroid': centroid.astype(float).tolist(), 'first_detected_at': first_detected_at, 'last_detected_at': last_detected_at}
    supabase.table(TOPIC_REGISTRY_TABLE).insert(payload).execute()
    return {**payload, 'centroid_array': centroid.copy()}
def update_registry_last_detected(topic_id, detected_at):
    supabase.table(TOPIC_REGISTRY_TABLE).update({'last_detected_at': detected_at, 'updated_at': datetime.now(timezone.utc).isoformat()}).eq('topic_id', topic_id).execute()
# ==========================================================
# MONTHLY TOPIC DISCOVERY
# ==========================================================
def discover_topics_for_month(month_df, registry, next_topic_number, baseline_mode=False):
    modelling_df = month_df.sort_values(['article_id', 'country']).drop_duplicates(
        subset=['article_id']
    ).reset_index(drop=True)
    article_category_data = {}
    for category, category_df in modelling_df.groupby('environment_category', sort=True):
        category_df = category_df.reset_index(drop=True)
        print()
        print('=' * 70)
        print(f'CATEGORY: {category}')
        print(f'Unique articles: {len(category_df)}')
        print('=' * 70)
        documents = category_df['cleaned_text'].tolist()
        print('Generating article embeddings...')
        embeddings = embedding_model.encode(
            documents, convert_to_numpy=True, normalize_embeddings=True,
            show_progress_bar=True
        )
        # Stage 1: deliberately fine semantic clusters.
        initial_labels = cluster_articles(embeddings)
        print(f'Initial raw clusters: {len(set(initial_labels))}')
        merged_labels = merge_similar_clusters(embeddings, initial_labels)
        print(f'Raw clusters after close semantic merging: {len(set(merged_labels))}')
        # Stage 2: keep similarity-driven clusters. No forced topic count.
        # Unique stories may remain as one-article topics.
        final_labels = keep_similarity_driven_clusters(merged_labels)
        unique_labels = sorted(set(final_labels))
        print(f'Final similarity-driven topics: {len(unique_labels)}')
        # Diagnostic preview before registry writes.
        print('\nTOPIC CLUSTER PREVIEW')
        print('-' * 70)
        for preview_number, cluster_label in enumerate(unique_labels, start=1):
            positions = np.where(final_labels == cluster_label)[0]
            preview_titles = [
                normalise_text(category_df.iloc[p]['title']) for p in positions[:3]
            ]
            print(f'  Cluster {preview_number}: {len(positions)} article(s)')
            for title in preview_titles:
                if title:
                    print(f'    - {title[:120]}')
        category_topics = []
        for cluster_number, cluster_label in enumerate(unique_labels, start=1):
            print()
            print(f'Processing topic cluster {cluster_number}/{len(unique_labels)}...')
            positions = np.where(final_labels == cluster_label)[0]
            print(f'  Articles in cluster: {len(positions)}')
            cluster_embeddings = embeddings[positions]
            centroid = calculate_centroid(cluster_embeddings)
            cluster_documents = [documents[position] for position in positions]
            cluster_titles = [
                str(category_df.iloc[position]['title']) for position in positions
            ]
            print('  Extracting keywords...')
            monthly_keywords = extract_environmental_topic_keywords(category, cluster_documents, centroid)
            print('  Keywords: ' + (', '.join(monthly_keywords) if monthly_keywords else 'None'))
            published_dates = pd.to_datetime(
                category_df.iloc[positions]['published_at'],
                utc=True, errors='coerce'
            ).dropna()
            if len(published_dates) > 0:
                first_detected_at = published_dates.min().isoformat()
                last_detected_at = published_dates.max().isoformat()
            else:
                now = datetime.now(timezone.utc).isoformat()
                first_detected_at = now
                last_detected_at = now
            if baseline_mode:
                # First name the independently discovered cluster, then deduplicate
                # at the TOPIC-CONCEPT level. A duplicate label by itself never
                # forces a merge; centroid/keyword evidence must support it.
                proposed_name = generate_issue_topic_name(category, monthly_keywords)
                print(f'  Proposed topic name: {proposed_name}')
                registry_match, registry_similarity, keyword_overlap = find_baseline_concept_match(
                    category, proposed_name, monthly_keywords, centroid, registry
                )
            else:
                print('  Comparing with established topic_registry...')
                registry_match, registry_similarity = find_registry_match(
                    category, centroid, registry
                )
                keyword_overlap = None
                proposed_name = generate_issue_topic_name(category, monthly_keywords)
            if registry_match is not None:
                topic_id = registry_match['topic_id']
                topic_name = registry_match['topic_name']
                if baseline_mode:
                    registry_match = update_registry_topic_baseline(
                        registry_match, monthly_keywords, centroid, last_detected_at
                    )
                    print(f'  Reusing baseline topic: {topic_id} - {topic_name}')
                    print(f'  Semantic similarity: {registry_similarity:.4f}')
                    print(f'  Keyword overlap: {keyword_overlap:.2f}')
                else:
                    print(f'  Existing topic: {topic_id} - {topic_name}')
                    print(f'  Registry similarity: {registry_similarity:.4f}')
                stored_keywords = normalise_text(registry_match.get('topic_keywords', ''))
                topic_keywords = [
                    keyword.strip() for keyword in stored_keywords.split(',') if keyword.strip()
                ]
            else:
                topic_id = f'T{next_topic_number:04d}'
                next_topic_number += 1
                # If another semantically different cluster happened to receive the
                # same generic label, give this one a meaningful qualifier instead
                # of storing duplicate names with different topic IDs.
                topic_name = make_distinct_topic_name(
                    proposed_name, monthly_keywords, registry, category
                )
                new_registry_topic = insert_registry_topic(
                    topic_id=topic_id,
                    environment_category=category,
                    topic_name=topic_name,
                    topic_keywords=monthly_keywords,
                    centroid=centroid,
                    first_detected_at=first_detected_at,
                    last_detected_at=last_detected_at
                )
                registry.append(new_registry_topic)
                topic_keywords = monthly_keywords
                print(f'  New registry topic: {topic_id} - {topic_name}')
                if baseline_mode and topic_name != proposed_name:
                    print(f'  Renamed from duplicate generic label: {proposed_name}')
                elif registry_similarity is not None:
                    print(f'  Best previous registry similarity: {registry_similarity:.4f}')
            category_topics.append({
                'environment_category': category,
                'cluster_label': cluster_label,
                'topic_id': topic_id,
                'topic_name': topic_name,
                'topic_keywords': topic_keywords,
                'monthly_keywords': monthly_keywords,
                'centroid': centroid,
                'article_positions': positions
            })
        article_category_data[category] = {
            'df': category_df,
            'embeddings': embeddings,
            'labels': final_labels,
            'topics': category_topics
        }
    return article_category_data, next_topic_number
# ==========================================================
# ARTICLE-TOPIC ASSIGNMENT
# ==========================================================
def assign_primary_topics(article_category_data):
    assignments = []
    total_articles = sum(len(data['df']) for data in article_category_data.values())
    processed = 0
    stage_start = time.perf_counter()
    print(f'Articles to assign: {total_articles}', flush=True)
    print('Note: similarity scoring embeds article chunks, so long articles can take a few seconds.', flush=True)
    for category_number, (category, category_data) in enumerate(article_category_data.items(), start=1):
        category_df = category_data['df']
        embeddings = category_data['embeddings']
        labels = category_data['labels']
        topics = category_data['topics']
        topic_by_label = {topic['cluster_label']: topic for topic in topics}
        print('', flush=True)
        print(f'[{category_number}/{len(article_category_data)}] Assigning category: {category} ({len(category_df)} articles)', flush=True)
        for article_position in range(len(category_df)):
            row = category_df.iloc[article_position]
            article_id = int(row['article_id'])
            article_text = row['cleaned_text']
            article_embedding = embeddings[article_position]
            primary_label = labels[article_position]
            primary_topic = topic_by_label[primary_label]
            processed += 1
            item_start = time.perf_counter()
            print(
                f'  [{processed}/{total_articles}] article_id={article_id} -> '
                f"{primary_topic['topic_id']} {primary_topic['topic_name']} | scoring...",
                end='', flush=True
            )
            score = calculate_article_topic_score(article_text, article_embedding, primary_topic['centroid'])
            item_elapsed = time.perf_counter() - item_start
            total_elapsed = time.perf_counter() - stage_start
            print(f' done ({item_elapsed:.1f}s, similarity={score:.4f}, elapsed={total_elapsed/60:.1f}m)', flush=True)
            assignments.append({'article_id': article_id, 'environment_category': category, 'topic': primary_topic, 'score': score})
    print(f'Primary-topic assignment finished in {(time.perf_counter()-stage_start)/60:.1f} minutes.', flush=True)
    return assignments
def build_news_topic_rows(month_df, assignments, pending_pairs):
    article_lookup = month_df.sort_values(['article_id', 'country']).drop_duplicates(subset=['article_id']).set_index('article_id').to_dict('index')
    countries_by_article = month_df.groupby('article_id')['country'].apply(lambda values: sorted(set(values))).to_dict()
    summary_cache = {}
    explanation_cache = {}
    output_rows = []
    total_assignments = len(assignments)
    for assignment_number, assignment in enumerate(assignments, start=1):
        article_id = assignment['article_id']
        topic = assignment['topic']
        target_countries = [country for country in countries_by_article.get(article_id, []) if (article_id, country) in pending_pairs]
        if not target_countries:
            continue
        article = article_lookup[article_id]
        print()
        print(f'Preparing article {assignment_number}/{total_assignments}: {article_id}')
        if article_id not in summary_cache:
            print('  Generating article summary...', end='', flush=True)
            _summary_start = time.perf_counter()
            summary_cache[article_id] = generate_article_summary(article.get('title', ''), article.get('cleaned_text', ''))
            print(f' done ({time.perf_counter() - _summary_start:.1f}s)', flush=True)
        explanation_key = (article_id, topic['topic_id'])
        if explanation_key not in explanation_cache:
            print('  Generating topic relevance explanation...', end='', flush=True)
            _explanation_start = time.perf_counter()
            explanation_cache[explanation_key] = generate_topic_relevance_explanation(article_summary=summary_cache[article_id], topic_name=topic['topic_name'], topic_keywords=topic['topic_keywords'])
            print(f' done ({time.perf_counter() - _explanation_start:.1f}s)', flush=True)
        for country in target_countries:
            output_rows.append({'article_id': article_id, 'topic_id': topic['topic_id'], 'country': country, 'article_topic_similarity': round(float(assignment['score']), 4), 'article_summary': summary_cache[article_id], 'topic_relevance_explanation': explanation_cache[explanation_key]})
    return output_rows
def upsert_news_topics(rows):
    if not rows:
        print('No news_topics rows to insert.')
        return
    unique_rows = {}
    for row in rows:
        key = (row['article_id'], row['topic_id'], row['country'])
        unique_rows[key] = row
    rows = list(unique_rows.values())
    print()
    print('=' * 70)
    print('WRITING NEWS_TOPICS')
    print('=' * 70)
    print(f'Rows to write: {len(rows)}')
    for start in range(0, len(rows), WRITE_BATCH_SIZE):
        batch = rows[start:start + WRITE_BATCH_SIZE]
        supabase.table(NEWS_TOPICS_TABLE).upsert(batch, on_conflict='article_id,topic_id,country').execute()
        print(f'Written: {min(start + WRITE_BATCH_SIZE, len(rows))}/{len(rows)}')
def update_registry_dates(month_df, assignments):
    published_lookup = month_df.sort_values('published_at').drop_duplicates(subset=['article_id'], keep='last').set_index('article_id')['published_at'].to_dict()
    latest_by_topic = {}
    for assignment in assignments:
        topic_id = assignment['topic']['topic_id']
        article_id = assignment['article_id']
        dt = pd.to_datetime(published_lookup.get(article_id), utc=True, errors='coerce')
        if pd.isna(dt):
            continue
        previous = latest_by_topic.get(topic_id)
        if previous is None or dt > previous:
            latest_by_topic[topic_id] = dt
    for topic_id, dt in latest_by_topic.items():
        update_registry_last_detected(topic_id, dt.isoformat())
# ==========================================================
# MONTHLY TOPIC STATISTICS
# ==========================================================
def rebuild_monthly_stats(month_string, month_df):
    print()
    print('=' * 70)
    print('REBUILDING MONTHLY TOPIC STATS')
    print('=' * 70)
    month_article_ids = set(month_df['article_id'].astype(int).tolist())
    topic_rows = fetch_all_rows(NEWS_TOPICS_TABLE, 'article_id,topic_id,country,article_topic_similarity')
    valid_month_pairs = set(zip(month_df['article_id'].astype(int), month_df['country'].astype(str)))
    topic_rows = [row for row in topic_rows if int(row['article_id']) in month_article_ids and (int(row['article_id']), str(row['country'])) in valid_month_pairs]
    if not topic_rows:
        print('No topic rows found for this month.')
        return
    registry_rows = fetch_all_rows(
        TOPIC_REGISTRY_TABLE,
        'topic_id,topic_name,environment_category,topic_keywords'
    )
    topic_name_lookup = {row['topic_id']: row['topic_name'] for row in registry_rows}
    topic_category_lookup = {row['topic_id']: row['environment_category'] for row in registry_rows}
    topic_keywords_lookup = {row['topic_id']: row.get('topic_keywords', '') for row in registry_rows}
    cleaned_lookup = {(int(row.article_id), row.country): row.cleaned_text for row in month_df.itertuples(index=False)}
    grouped_articles = defaultdict(set)
    grouped_similarities = defaultdict(list)
    for row in topic_rows:
        country = str(row['country'])
        topic_id = str(row['topic_id'])
        article_id = int(row['article_id'])
        key = (country, topic_id)
        grouped_articles[key].add(article_id)
        similarity = row.get('article_topic_similarity')
        if similarity is not None:
            grouped_similarities[key].append(float(similarity))
    stat_rows = []
    total_stat_groups = len(grouped_articles)
    print(f'Country-topic groups to calculate: {total_stat_groups}', flush=True)
    for group_number, ((country, topic_id), article_ids) in enumerate(grouped_articles.items(), start=1):
        print(f'  [{group_number}/{total_stat_groups}] {country} / {topic_id}: {len(article_ids)} article(s) | calculating monthly keywords...', end='', flush=True)
        documents = [cleaned_lookup[article_id, country] for article_id in article_ids if (article_id, country) in cleaned_lookup]
        if documents:
            document_embeddings = embedding_model.encode(
                documents,
                convert_to_numpy=True,
                normalize_embeddings=True,
                show_progress_bar=False
            )
            monthly_centroid = calculate_centroid(document_embeddings)
            # 1) Preferred: environmentally meaningful phrases from this
            #    country/topic/month's articles.
            monthly_keywords = extract_environmental_topic_keywords(
                topic_category_lookup.get(topic_id, ''),
                documents,
                monthly_centroid
            )
            # 2) Fallback: still use this month/country's articles, but use
            #    general TF-IDF + semantic keywords if the stricter extractor
            #    returns nothing.
            if not monthly_keywords:
                print(
                    f'\n    No environmental monthly keywords for {country} / {topic_id}; '
                    f'using monthly TF-IDF/semantic keywords.',
                    end='',
                    flush=True
                )
                monthly_keywords = extract_topic_keywords(
                    documents,
                    monthly_centroid
                )
        else:
            monthly_keywords = []
        # 3) Final safety fallback: use registry keywords only if both monthly
        #    extraction methods failed.
        if not monthly_keywords:
            stored_keywords = normalise_text(topic_keywords_lookup.get(topic_id, ''))
            monthly_keywords = [
                keyword.strip()
                for keyword in stored_keywords.split(',')
                if keyword.strip()
            ][:TOP_KEYWORDS]
            if monthly_keywords:
                print(
                    f'\n    Monthly extraction still empty for {country} / {topic_id}; '
                    f'using topic_registry keywords as final fallback.',
                    end='',
                    flush=True
                )
            else:
                print(
                    f'\n    WARNING: no monthly or registry keywords available for '
                    f'{country} / {topic_id}.',
                    end='',
                    flush=True
                )
        print(' done', flush=True)
        similarities = grouped_similarities[country, topic_id]
        if similarities:
            average_similarity = float(np.mean(similarities))
        else:
            average_similarity = 0.0
        stat_rows.append({'month': month_string, 'country': country, 'topic_id': topic_id, 'topic_name': topic_name_lookup.get(topic_id, 'Unlabelled Topic'), 'article_count': len(article_ids), 'monthly_keywords': ', '.join(monthly_keywords), '_average_similarity': average_similarity})
    stats_df = pd.DataFrame(stat_rows)
    if stats_df.empty:
        print('No monthly statistics were produced.')
        return
    # Rank topics independently for every month and country.
    # rebuild_monthly_stats() is called one month at a time, but including
    # 'month' explicitly here makes the intended ranking scope unambiguous.
    stats_df = stats_df.sort_values(
        by=['month', 'country', 'article_count', '_average_similarity', 'topic_id'],
        ascending=[True, True, False, False, True]
    ).reset_index(drop=True)
    stats_df['topic_rank'] = (
        stats_df.groupby(['month', 'country']).cumcount() + 1
    )
    print()
    print('COUNTRY-SPECIFIC TOPIC COUNTS')
    print('-' * 70)
    for country in TARGET_COUNTRIES:
        country_df = stats_df[stats_df['country'] == country]
        if country_df.empty:
            continue
        print()
        print(country)
        for row in country_df.head(5).itertuples(index=False):
            print(f'  #{row.topic_rank} {row.topic_id} - {row.topic_name}: {row.article_count} article(s)')
    supabase.table(MONTHLY_STATS_TABLE).delete().eq('month', month_string).execute()
    payload_df = stats_df.drop(columns=['_average_similarity'])
    payload = payload_df[['month', 'country', 'topic_id', 'topic_name', 'article_count', 'monthly_keywords', 'topic_rank']].to_dict('records')
    for start in range(0, len(payload), WRITE_BATCH_SIZE):
        batch = payload[start:start + WRITE_BATCH_SIZE]
        print(f'Writing monthly stats batch {start + 1}-{min(start + len(batch), len(payload))}/{len(payload)}...', end='', flush=True)
        supabase.table(MONTHLY_STATS_TABLE).upsert(batch, on_conflict='month,country,topic_id').execute()
        print(' done', flush=True)
    print()
    print(f'Monthly stats written: {len(payload)}')
    print()
    print('=' * 70)
    print('TOP 3 TOPICS BY COUNTRY')
    print('=' * 70)
    top_three = stats_df[stats_df['topic_rank'] <= 3]
    for country in TARGET_COUNTRIES:
        country_df = top_three[top_three['country'] == country].sort_values('topic_rank')
        if country_df.empty:
            continue
        print()
        print(country)
        for row in country_df.itertuples(index=False):
            print(f'  #{row.topic_rank} {row.topic_id} - {row.topic_name}')
            print(f'     Articles: {row.article_count}')
            print(f'     Keywords: {row.monthly_keywords}')
# ==========================================================
# MAIN PIPELINE
# ==========================================================
def ensure_rebuild_tables_are_empty():
    """Prevent a baseline rebuild from mixing old derived rows with new topics."""
    counts = {
        TOPIC_REGISTRY_TABLE: len(fetch_all_rows(TOPIC_REGISTRY_TABLE, 'topic_id')),
        NEWS_TOPICS_TABLE: len(fetch_all_rows(NEWS_TOPICS_TABLE, 'article_id')),
        MONTHLY_STATS_TABLE: len(fetch_all_rows(MONTHLY_STATS_TABLE, 'month')),
    }
    non_empty = {table: count for table, count in counts.items() if count > 0}
    if non_empty:
        details = ', '.join(f'{table}={count}' for table, count in non_empty.items())
        raise RuntimeError(
            'REBUILD_MODE=True requires empty derived topic tables. '
            f'Existing rows found: {details}. Reset topic_registry, news_topics '
            'and monthly_topic_stats in Supabase, then run this script again.'
        )
def run_baseline_rebuild(cleaned_df):
    """Discover one baseline registry from all historical cleaned months."""
    print()
    print('=' * 70)
    print('BASELINE REBUILD MODE')
    print('=' * 70)
    print('Discovering topics from all cleaned months together.')
    ensure_rebuild_tables_are_empty()
    cleaned_df = cleaned_df.copy()
    cleaned_df['month'] = cleaned_df['published_at'].apply(month_start_string)
    invalid_dates = int(cleaned_df['month'].isna().sum())
    if invalid_dates > 0:
        print(f'Warning: {invalid_dates} rows have invalid published_at and will be skipped.')
        cleaned_df = cleaned_df[cleaned_df['month'].notna()].copy()
    if cleaned_df.empty:
        print('No cleaned rows with valid dates are available for rebuilding.')
        return
    registry = []
    next_topic_number = 1
    article_category_data, next_topic_number = discover_topics_for_month(
        cleaned_df, registry, next_topic_number, baseline_mode=True
    )
    print()
    print('=' * 70)
    print('ASSIGNING BASELINE PRIMARY TOPICS')
    print('=' * 70)
    assignments = assign_primary_topics(article_category_data)
    print(f'Unique article-topic assignments: {len(assignments)}')
    all_pairs = {(int(row.article_id), row.country) for row in cleaned_df.itertuples(index=False)}
    news_topic_rows = build_news_topic_rows(cleaned_df, assignments, all_pairs)
    upsert_news_topics(news_topic_rows)
    update_registry_dates(cleaned_df, assignments)
    months = sorted(cleaned_df['month'].unique())
    for month_string in months:
        month_df = cleaned_df[cleaned_df['month'] == month_string].copy()
        print()
        print('=' * 70)
        print(f'REBUILDING STATS FOR: {month_string}')
        print('=' * 70)
        rebuild_monthly_stats(month_string, month_df)
    print()
    print('=' * 70)
    print('BASELINE REBUILD FINISHED')
    print('=' * 70)
    print(f'Topics created: {len(registry)}')
    print(f'Historical months rebuilt: {len(months)}')
    print('Change REBUILD_MODE = False before processing future incremental months.')
def run_incremental(cleaned_df):
    """Process only new article-country pairs against the established registry."""
    processed_pairs = load_processed_pairs()
    cleaned_df = cleaned_df.copy()
    cleaned_df['is_processed'] = cleaned_df.apply(
        lambda row: (int(row['article_id']), row['country']) in processed_pairs, axis=1
    )
    pending_df = cleaned_df[~cleaned_df['is_processed']].copy()
    print()
    print('=' * 70)
    print('PROCESSING STATUS')
    print('=' * 70)
    print(f'news_cleaned rows: {len(cleaned_df)}')
    print(f"Unique articles: {cleaned_df['article_id'].nunique()}")
    print(f"Already processed article-country rows: {int(cleaned_df['is_processed'].sum())}")
    print(f'Unprocessed article-country rows: {len(pending_df)}')
    if pending_df.empty:
        print()
        print('No new article-country pairs need topic modelling.')
        return
    pending_df['month'] = pending_df['published_at'].apply(month_start_string)
    invalid_dates = int(pending_df['month'].isna().sum())
    if invalid_dates > 0:
        print(f'Warning: {invalid_dates} rows have invalid published_at.')
    pending_df = pending_df[pending_df['month'].notna()].copy()
    if pending_df.empty:
        print('No pending rows have valid dates.')
        return
    registry = load_topic_registry()
    next_topic_number = get_next_topic_number(registry)
    print(f'Next topic ID: T{next_topic_number:04d}')
    affected_months = sorted(pending_df['month'].unique())
    print()
    print('Months requiring processing:')
    for month_string in affected_months:
        print(f'  {month_string}')
    cleaned_months = cleaned_df['published_at'].apply(month_start_string)
    for month_string in affected_months:
        print()
        print('=' * 70)
        print(f'PROCESSING MONTH: {month_string}')
        print('=' * 70)
        month_df = cleaned_df[cleaned_months == month_string].copy()
        pending_month_df = pending_df[pending_df['month'] == month_string].copy()
        pending_pairs = {(int(row.article_id), row.country) for row in pending_month_df.itertuples(index=False)}
        print(f'Cleaned article-country rows in month: {len(month_df)}')
        print(f"Unique articles in month: {month_df['article_id'].nunique()}")
        print(f'Pending article-country pairs: {len(pending_pairs)}')
        article_category_data, next_topic_number = discover_topics_for_month(
            month_df, registry, next_topic_number
        )
        print()
        print('=' * 70)
        print('ASSIGNING PRIMARY TOPICS')
        print('=' * 70)
        assignments = assign_primary_topics(article_category_data)
        print(f'Unique article-topic assignments: {len(assignments)}')
        news_topic_rows = build_news_topic_rows(month_df, assignments, pending_pairs)
        upsert_news_topics(news_topic_rows)
        update_registry_dates(month_df, assignments)
        rebuild_monthly_stats(month_string, month_df)
        processed_pairs.update(pending_pairs)
def main():
    print()
    print('=' * 70)
    print('ASEAN ENVIRONMENTAL TOPIC MODELLING')
    print('=' * 70)
    print(f'REBUILD_MODE: {REBUILD_MODE}')
    cleaned_df = load_cleaned_rows()
    if cleaned_df.empty:
        print('Nothing to process.')
        return
    if REBUILD_MODE:
        run_baseline_rebuild(cleaned_df)
    else:
        run_incremental(cleaned_df)
    print()
    print('=' * 70)
    print('TOPIC PIPELINE FINISHED')
    print('=' * 70)
    print('Updated topic_registry')
    print('Updated news_topics')
    print('Updated monthly_topic_stats')
    print()
    print('One primary topic was assigned to each unique article.')
    print('monthly_topic_stats counts are country-specific.')
    print('topic_rank is sequential, so rank <= 3 gives at most 3 topics per country.')
if __name__ == '__main__':
    main()


