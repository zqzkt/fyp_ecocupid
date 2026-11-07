-- =============================================================================
-- Project EcoCupid: initial database schema
-- =============================================================================
-- Creates every table the pipelines and dashboard read or write. It replaces
-- the earlier numbered migrations (001 to 007) referred to in the docs.
--
-- How to apply
--   Supabase CLI:       supabase db push
--   Supabase dashboard: SQL Editor > New query > paste this file > Run
--
-- Safe to re-run: every statement uses IF NOT EXISTS.
--
-- Notes
--   * Tables are created in dependency order (parents before children).
--   * Array columns are text[] (element types inferred from the code).
--   * The legacy tables sentiment_analysis_1 and sentiment_analysis_2 are not
--     used by any script and are intentionally left out.
--   * A unique index on clean_comments.source_id was added. clean_social.py
--     upserts with on_conflict=source_id, which needs it.
--   * Row Level Security is NOT enabled here. See the optional block at the end.
-- =============================================================================


-- -----------------------------------------------------------------------------
-- 1. News pipeline
-- -----------------------------------------------------------------------------

create table if not exists public.news_raw (
  news_id          bigint generated always as identity primary key,
  source_country   text not null
                   check (source_country in ('Singapore','Malaysia','Indonesia','Thailand','Philippines','Brunei')),
  title            text not null,
  source           text not null,
  published_at     timestamptz not null,
  countries        text,
  environment_keywords text,
  article_text     text not null,
  url              text not null unique,
  scraped_at       timestamptz not null default now(),
  cleaning_status  text default 'pending',
  cleaned_at       timestamptz
);

create table if not exists public.news_cleaned (
  article_id           bigint not null,
  title                text not null,
  source               text not null,
  source_country       text not null,
  published_at         timestamptz not null,
  country              text not null
                       check (country in ('Singapore','Malaysia','Indonesia','Thailand','Philippines','Brunei')),
  cleaned_text         text not null,
  environment_category text not null,
  environment_keywords text,
  semantic_score       double precision,
  confidence_score     double precision,
  url                  text not null,
  constraint news_cleaned_pkey primary key (article_id, country),
  constraint fk_news_cleaned_article foreign key (article_id) references public.news_raw (news_id)
);

create table if not exists public.topic_registry (
  topic_id             text primary key,
  environment_category text not null,
  topic_name           text not null,
  topic_keywords       text not null,
  topic_centroid       jsonb not null,
  first_detected_at    timestamptz not null,
  last_detected_at     timestamptz not null,
  created_at           timestamptz not null default now(),
  updated_at           timestamptz not null default now()
);

create table if not exists public.news_topics (
  article_id                  bigint not null,
  topic_id                    text not null,
  country                     text not null
                              check (country in ('Singapore','Malaysia','Indonesia','Thailand','Philippines','Brunei')),
  article_topic_similarity    double precision not null
                              check (article_topic_similarity >= -1 and article_topic_similarity <= 1),
  article_summary             text,
  topic_relevance_explanation text,
  created_at                  timestamptz not null default now(),
  constraint news_topics_pkey primary key (article_id, topic_id, country),
  constraint fk_news_topics_article foreign key (article_id) references public.news_raw (news_id),
  constraint fk_news_topics_topic   foreign key (topic_id)   references public.topic_registry (topic_id)
);

-- Drives social collection (top-ranked keywords per country and month) and the dashboard.
create table if not exists public.monthly_topic_stats (
  month             date not null,
  country           text not null
                    check (country in ('Singapore','Malaysia','Indonesia','Thailand','Philippines','Brunei')),
  topic_id          text not null,
  topic_name        text not null,
  article_count     integer not null default 0 check (article_count >= 0),
  monthly_keywords  text,
  topic_rank        integer check (topic_rank is null or topic_rank >= 1),
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now(),
  constraint monthly_topic_stats_pkey primary key (month, country, topic_id),
  constraint fk_monthly_topic_stats_topic foreign key (topic_id) references public.topic_registry (topic_id)
);


-- -----------------------------------------------------------------------------
-- 2. Raw social-media data
-- -----------------------------------------------------------------------------

-- Facebook
create table if not exists public.facebook_posts (
  post_id          text primary key,
  platform         text,
  country          text,
  source_name      text,
  page_name        text,
  published_at     timestamptz,
  url              text,
  text             text,
  likes            bigint default 0,
  comments_count   bigint default 0,
  shares           bigint default 0,
  primary_topic    text,
  matched_topics   jsonb,
  created_at       timestamptz default now(),
  original_text    text,
  lang             text,
  matched_keywords text[]
);

create table if not exists public.facebook_comments (
  comment_id       text primary key,
  parent_post_id   text,
  platform         text,
  post_url         text,
  country          text,
  source_name      text,
  primary_topic    text,
  published_at     timestamptz,
  text             text,
  likes            bigint default 0,
  created_at       timestamptz default now(),
  matched_keywords text[]
);

-- Instagram
create table if not exists public.instagram_posts (
  post_id               text primary key,
  topic                 text,
  country               text,
  hashtag               text,
  post_url              text,
  caption               text,
  posted_at             timestamptz,
  author_username       text,
  author_full_name      text,
  author_follower_count bigint,
  author_is_verified    boolean,
  like_count            bigint,
  comment_count         bigint,
  engagement_count      bigint,
  engagement_rate       numeric,
  media_type            text,
  is_reel               boolean,
  play_count            bigint
);

create table if not exists public.instagram_comments (
  comment_id            text primary key,
  topic                 text,
  country               text,
  hashtag               text,
  post_id               text,
  post_url              text,
  post_author_username  text,
  comment_text          text,
  comment_username      text,
  comment_created_at    timestamptz,
  comment_like_count    bigint,
  constraint instagram_comments_post_id_fkey foreign key (post_id) references public.instagram_posts (post_id)
);

-- Reddit
create table if not exists public.reddit_posts (
  post_id         text primary key,
  post_url        text,
  created_at      timestamptz,
  author_name     text,
  title           text,
  body            text,
  community_name  text,
  data_type       text,
  flair           text,
  comments_count  bigint,
  subreddit       text,
  score           bigint,
  upvote_ratio    double precision,
  domain          text,
  topic           text,
  country         text
);

create table if not exists public.reddit_comments (
  comment_id          text primary key,
  comment_url         text,
  comment_created_at  timestamptz,
  author_name         text,
  post_id             text,
  post_title          text,
  body                text,
  subreddit_name      text,
  parent_id           text,
  data_type           text,
  score               bigint,
  parent_kind         text,
  depth               bigint,
  topic               text,
  country             text,
  constraint reddit_comments_post_id_fkey foreign key (post_id) references public.reddit_posts (post_id)
);

-- X (Twitter)
create table if not exists public.x_posts (
  post_id             text primary key,
  author_id           text,
  conversation_id     text,
  text                text not null,
  lang                text,
  inferred_country    text,
  like_count          integer not null default 0,
  reply_count         integer not null default 0,
  repost_count        integer not null default 0,
  quote_count         integer not null default 0,
  bookmark_count      integer,
  impression_count    integer,
  total_engagement    integer,
  discussion_ratio    double precision,
  amplification_ratio double precision,
  is_reply            boolean not null default false,
  possibly_sensitive  boolean,
  reply_settings      text,
  source              text,
  query               text,
  hashtags            text[] not null default '{}',
  mentions            text[] not null default '{}',
  urls                text[] not null default '{}',
  media_keys          text[] not null default '{}',
  media_types         text[] not null default '{}',
  parent_tweet_id     text,
  geo                 jsonb,
  place               jsonb,
  media               jsonb,
  referenced_tweets   jsonb,
  annotations         jsonb,
  context_annotations jsonb,
  created_at          timestamptz not null,
  collected_at        timestamptz not null,
  ingested_at         timestamptz not null default timezone('utc', now()),
  updated_at          timestamptz not null default timezone('utc', now()),
  matched_keywords    text[]
);

create table if not exists public.x_replies (
  reply_id         text primary key,
  post_id          text,
  parent_tweet_id  text,
  conversation_id  text,
  author_id        text,
  text             text not null,
  lang             text,
  inferred_country text,
  like_count       integer not null default 0,
  reply_count      integer not null default 0,
  repost_count     integer not null default 0,
  quote_count      integer not null default 0,
  hashtags         text[] not null default '{}',
  mentions         text[] not null default '{}',
  urls             text[] not null default '{}',
  media            jsonb,
  created_at       timestamptz not null,
  collected_at     timestamptz not null,
  ingested_at      timestamptz not null default timezone('utc', now()),
  updated_at       timestamptz not null default timezone('utc', now())
);

-- YouTube
create table if not exists public.youtube_videos (
  video_id        text primary key,
  created_at      timestamptz not null default now(),
  title           text,
  description     text,
  channel_title   text,
  published_date  date,
  country         text,
  next_page_token text,
  view_count      bigint,
  like_count      bigint,
  comment_count   bigint,
  topic           text[]
);

create table if not exists public.youtube_comments (
  comment_id   text primary key,
  created_at   timestamptz not null default now(),
  video_id     text,
  comment      text,
  like_count   bigint not null default 0,
  reply_count  bigint default 0,
  country      text,
  constraint youtube_comments_video_id_fkey foreign key (video_id) references public.youtube_videos (video_id)
);


-- -----------------------------------------------------------------------------
-- 3. Shared cleaned social data
-- -----------------------------------------------------------------------------

create table if not exists public.clean_posts (
  id                bigint generated always as identity primary key,
  source_id         text not null unique,
  platform          text,
  source_type       text default 'post',
  original_text     text,
  cleaned_text      text,
  lang              text,
  inferred_country  text,
  author_id         text,
  conversation_id   text,
  parent_source_id  text,
  matched_keywords  text[] default '{}',
  like_count        bigint default 0,
  reply_count       bigint default 0,
  repost_count      bigint default 0,
  quote_count       bigint default 0,
  impression_count  bigint,
  total_engagement  bigint default 0,
  source_table      text,
  cleaned_at        timestamptz default now(),
  posted_at         timestamptz,
  post_url          text,
  is_environmental  boolean
);

create table if not exists public.clean_comments (
  id                 bigint generated always as identity primary key,
  source_id          text,
  platform           text,
  source_type        text default 'comment',
  original_text      text,
  cleaned_text       text,
  lang               text,
  inferred_country   text,
  author_id          text,
  conversation_id    text,
  parent_source_id   text,
  matched_keywords   text[] default '{}',
  like_count         bigint default 0,
  reply_count        bigint default 0,
  repost_count       bigint default 0,
  quote_count        bigint default 0,
  impression_count   bigint,
  total_engagement   bigint default 0,
  source_table       text,
  cleaned_at         timestamptz default now(),
  posted_at          timestamptz,
  parent_posted_at   timestamptz
);

-- Needed for upserts with on_conflict=source_id (see clean_social.py).
create unique index if not exists clean_comments_source_id_key
  on public.clean_comments (source_id);


-- -----------------------------------------------------------------------------
-- 4. Analysis results
-- -----------------------------------------------------------------------------

-- Emotion counts per country, topic and month (GoEmotions labels plus neutral).
create table if not exists public.sentiment_analysis (
  country                    text not null,
  topic                      text not null,
  month                      integer not null check (month >= 1 and month <= 12),
  year                       integer not null,
  total_items                bigint not null default 0,
  updated_at                 timestamptz not null default now(),
  anger_count                bigint not null default 0,
  fear_count                 bigint not null default 0,
  joy_count                  bigint not null default 0,
  love_count                 bigint not null default 0,
  sadness_count              bigint not null default 0,
  surprise_count             bigint not null default 0,
  disgust_count              integer not null default 0,
  admiration_count           integer not null default 0,
  amusement_count            integer not null default 0,
  annoyance_count            integer not null default 0,
  approval_count             integer not null default 0,
  caring_count               integer not null default 0,
  confusion_count            integer not null default 0,
  curiosity_count            integer not null default 0,
  desire_count               integer not null default 0,
  disappointment_count       integer not null default 0,
  disapproval_count          integer not null default 0,
  embarrassment_count        integer not null default 0,
  excitement_count           integer not null default 0,
  gratitude_count            integer not null default 0,
  grief_count                integer not null default 0,
  nervousness_count          integer not null default 0,
  optimism_count             integer not null default 0,
  pride_count                integer not null default 0,
  realization_count          integer not null default 0,
  relief_count               integer not null default 0,
  remorse_count              integer not null default 0,
  neutral_count              integer not null default 0,
  matched_sentiment_keywords jsonb not null default '{}'::jsonb,
  dominant_emotions          text[] not null default '{}',
  constraint sentiment_analysis_pkey primary key (country, topic, month, year)
);

-- AI-written summaries per topic, country and month.
create table if not exists public.summary (
  country     text not null,
  keywords    text not null,
  summary     jsonb,
  month       date not null,
  created_at  timestamptz not null default now(),
  topic_name  text not null,
  constraint summary_pkey primary key (topic_name, country, month)
);

-- AI-written communication guidance per topic and country.
create table if not exists public.topic_based_analysis (
  created_at         timestamptz not null default now(),
  month              timestamptz not null,
  keywords           text[] not null,
  tone_and_emotion   text,
  recommendations    text,
  country            text not null,
  topic_name         text not null,
  key_message        text,
  narrative_method   text,
  content_type       text,
  story_structure    text,
  hooks              text,
  call_to_action     text,
  captions           text,
  what_not_to_do     text,
  top_post_links     text[],
  bottom_post_links  text[] default '{}',
  updated_at         timestamptz default now(),
  constraint topic_based_analysis_pkey primary key (topic_name, country)
);


-- -----------------------------------------------------------------------------
-- 5. Indexes for common lookups
-- -----------------------------------------------------------------------------

create index if not exists news_topics_topic_id_idx         on public.news_topics (topic_id);
create index if not exists monthly_topic_stats_month_idx    on public.monthly_topic_stats (month, country);
create index if not exists instagram_comments_post_id_idx   on public.instagram_comments (post_id);
create index if not exists reddit_comments_post_id_idx      on public.reddit_comments (post_id);
create index if not exists youtube_comments_video_id_idx    on public.youtube_comments (video_id);
create index if not exists clean_posts_posted_at_idx        on public.clean_posts (posted_at);
create index if not exists clean_comments_posted_at_idx     on public.clean_comments (posted_at);
create index if not exists clean_comments_parent_source_idx on public.clean_comments (parent_source_id);


-- -----------------------------------------------------------------------------
-- 6. OPTIONAL: Row Level Security (left commented out on purpose)
-- -----------------------------------------------------------------------------
-- With RLS on and no policies, only a server-side key (secret or service-role)
-- can read or write these tables. The publishable (anon) key is then blocked.
-- Uncomment ONLY after confirming that SUPABASE_KEY (or SUPABASE_SECRET_KEY /
-- SUPABASE_SERVICE_ROLE_KEY) in every .env is a server-side key, including the
-- one the dashboard uses.
--
-- do $$
-- declare t text;
-- begin
--   for t in
--     select tablename from pg_tables where schemaname = 'public'
--   loop
--     execute format('alter table public.%I enable row level security', t);
--   end loop;
-- end $$;
