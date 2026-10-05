"""Load EcoCupid news dashboard data directly from Supabase."""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import requests
import streamlit as st
from dotenv import load_dotenv


REPO_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(REPO_ROOT / ".env")

PAGE_SIZE = 1000
REQUEST_TIMEOUT = 60


# ---------------------------------------------------------------------
# Supabase table definitions
# ---------------------------------------------------------------------

MONTHLY_TOPIC_STATS_TABLE = "monthly_topic_stats"
MONTHLY_TOPIC_STATS_COLUMNS = (
    "month",
    "country",
    "topic_id",
    "topic_name",
    "article_count",
    "monthly_keywords",
    "topic_rank",
)

NEWS_CLEANED_TABLE = "news_cleaned"
NEWS_CLEANED_COLUMNS = (
    "article_id",
    "title",
    "source",
    "source_country",
    "published_at",
    "country",
    "cleaned_text",
    "environment_category",
    "environment_keywords",
    "semantic_score",
    "confidence_score",
    "url",
)

NEWS_TOPICS_TABLE = "news_topics"
NEWS_TOPICS_COLUMNS = (
    "article_id",
    "topic_id",
    "country",
    "article_topic_similarity",
    "article_summary",
    "topic_relevance_explanation",
    "created_at",
)

TOPIC_REGISTRY_TABLE = "topic_registry"
TOPIC_REGISTRY_COLUMNS = (
    "topic_id",
    "environment_category",
    "topic_name",
    "topic_keywords",
    "first_detected_at",
    "last_detected_at",
    "created_at",
    "updated_at",
)


class DashboardDataError(RuntimeError):
    """Raised when the dashboard cannot load its data from Supabase."""


# ---------------------------------------------------------------------
# Supabase connection
# ---------------------------------------------------------------------

def _credentials() -> tuple[str, str]:
    url = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")

    if url.endswith("/rest/v1"):
        url = url[: -len("/rest/v1")].rstrip("/")

    key = (
        os.environ.get("SUPABASE_SECRET_KEY")
        or os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
        or os.environ.get("SUPABASE_KEY")
        or ""
    ).strip()

    if not url or not key:
        raise DashboardDataError(
            "SUPABASE_URL and SUPABASE_KEY "
            "(or SUPABASE_SECRET_KEY / SUPABASE_SERVICE_ROLE_KEY) "
            "are required in .env"
        )

    return url, key


def _headers(key: str, *, with_bearer: bool) -> dict[str, str]:
    headers = {"apikey": key}

    if with_bearer:
        headers["Authorization"] = f"Bearer {key}"

    return headers


# ---------------------------------------------------------------------
# Generic paginated table loader
# ---------------------------------------------------------------------

def _get_page(
    base_url: str,
    key: str,
    table: str,
    columns: tuple[str, ...],
    order: str,
    offset: int,
) -> list[dict]:

    params = {
        "select": ",".join(columns),
        "order": order,
        "limit": str(PAGE_SIZE),
        "offset": str(offset),
    }

    endpoint = f"{base_url}/rest/v1/{table}"

    try:
        response = requests.get(
            endpoint,
            params=params,
            headers=_headers(key, with_bearer=True),
            timeout=REQUEST_TIMEOUT,
        )

        # sb_secret_ keys are not JWTs.
        if (
            response.status_code in {401, 403}
            and "jwt" in response.text.lower()
        ):
            response = requests.get(
                endpoint,
                params=params,
                headers=_headers(key, with_bearer=False),
                timeout=REQUEST_TIMEOUT,
            )

    except requests.RequestException as exc:
        raise DashboardDataError(
            f"Could not reach Supabase: {type(exc).__name__}"
        ) from exc

    if not response.ok:
        raise DashboardDataError(
            f"{table} lookup failed "
            f"({response.status_code}): {response.text[:500]}"
        )

    try:
        return response.json()

    except ValueError as exc:
        raise DashboardDataError(
            f"{table} returned a response that is not JSON"
        ) from exc


def _load_table(
    table: str,
    columns: tuple[str, ...],
    order: str,
) -> pd.DataFrame:
    """Load all rows from one Supabase table."""

    base_url, key = _credentials()

    rows: list[dict] = []
    offset = 0

    while True:
        page = _get_page(
            base_url,
            key,
            table,
            columns,
            order,
            offset,
        )

        if not page:
            break

        rows.extend(page)
        offset += len(page)

    return pd.DataFrame(rows, columns=list(columns))


# =====================================================================
# MONTHLY TOPIC STATS
# =====================================================================

@st.cache_data(
    ttl=600,
    show_spinner="Loading topic statistics from Supabase...",
)
def load_data() -> pd.DataFrame:
    """Return every row of monthly_topic_stats."""

    df = _load_table(
        MONTHLY_TOPIC_STATS_TABLE,
        MONTHLY_TOPIC_STATS_COLUMNS,
        "month.asc,country.asc,topic_id.asc",
    )

    if df.empty:
        return df

    df["month"] = pd.to_datetime(
        df["month"],
        format="%Y-%m-%d",
    )

    df["article_count"] = pd.to_numeric(
        df["article_count"]
    ).astype("int64")

    return df


def get_data() -> pd.DataFrame:
    """
    Existing dashboard entry point.

    Keep this returning monthly_topic_stats so trends.py,
    data.py and sidebar_filters continue working unchanged.
    """

    try:
        return load_data()

    except DashboardDataError as exc:
        st.error(
            f"Could not load dashboard data from Supabase. {exc}"
        )
        st.stop()


# =====================================================================
# NEWS CLEANED
# =====================================================================

@st.cache_data(
    ttl=600,
    show_spinner="Loading cleaned news articles...",
)
def load_news_cleaned() -> pd.DataFrame:

    df = _load_table(
        NEWS_CLEANED_TABLE,
        NEWS_CLEANED_COLUMNS,
        "published_at.asc,article_id.asc,country.asc",
    )

    if df.empty:
        return df

    df["published_at"] = pd.to_datetime(
        df["published_at"],
        errors="coerce",
        utc=True,
    )

    # Month without timezone so it matches monthly_topic_stats.
    df["month"] = (
        df["published_at"]
        .dt.tz_convert(None)
        .dt.to_period("M")
        .dt.to_timestamp()
    )

    return df


def get_news_cleaned() -> pd.DataFrame:

    try:
        return load_news_cleaned()

    except DashboardDataError as exc:
        st.error(
            f"Could not load news_cleaned from Supabase. {exc}"
        )
        st.stop()


# =====================================================================
# NEWS TOPICS
# =====================================================================

@st.cache_data(
    ttl=600,
    show_spinner="Loading article-topic assignments...",
)
def load_news_topics() -> pd.DataFrame:

    df = _load_table(
        NEWS_TOPICS_TABLE,
        NEWS_TOPICS_COLUMNS,
        "article_id.asc,country.asc,topic_id.asc",
    )

    if df.empty:
        return df

    df["created_at"] = pd.to_datetime(
        df["created_at"],
        errors="coerce",
        utc=True,
    )

    return df


def get_news_topics() -> pd.DataFrame:

    try:
        return load_news_topics()

    except DashboardDataError as exc:
        st.error(
            f"Could not load news_topics from Supabase. {exc}"
        )
        st.stop()


# =====================================================================
# TOPIC REGISTRY
# =====================================================================

@st.cache_data(
    ttl=600,
    show_spinner="Loading topic registry...",
)
def load_topic_registry() -> pd.DataFrame:

    df = _load_table(
        TOPIC_REGISTRY_TABLE,
        TOPIC_REGISTRY_COLUMNS,
        "topic_id.asc",
    )

    if df.empty:
        return df

    for column in (
        "first_detected_at",
        "last_detected_at",
        "created_at",
        "updated_at",
    ):
        df[column] = pd.to_datetime(
            df[column],
            errors="coerce",
            utc=True,
        )

    # Month versions are convenient for dashboard comparisons.
    df["first_detected_month"] = (
        df["first_detected_at"]
        .dt.tz_convert(None)
        .dt.to_period("M")
        .dt.to_timestamp()
    )

    df["last_detected_month"] = (
        df["last_detected_at"]
        .dt.tz_convert(None)
        .dt.to_period("M")
        .dt.to_timestamp()
    )

    return df


def get_topic_registry() -> pd.DataFrame:

    try:
        return load_topic_registry()

    except DashboardDataError as exc:
        st.error(
            f"Could not load topic_registry from Supabase. {exc}"
        )
        st.stop()
