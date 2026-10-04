"""Load monthly topic statistics for the dashboard directly from Supabase."""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import requests
import streamlit as st
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(REPO_ROOT / ".env")

TABLE = "monthly_topic_stats"
COLUMNS = (
    "month",
    "country",
    "topic_id",
    "topic_name",
    "article_count",
    "monthly_keywords",
    "topic_rank",
)
PAGE_SIZE = 1000
REQUEST_TIMEOUT = 60


class DashboardDataError(RuntimeError):
    """Raised when the dashboard cannot load its data from Supabase."""


def _credentials() -> tuple[str, str]:
    # Same variable names and precedence as scripts/supabase/*_pipeline.py.
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
            "SUPABASE_URL and SUPABASE_KEY (or SUPABASE_SECRET_KEY / SUPABASE_SERVICE_ROLE_KEY) "
            "are required in .env"
        )
    return url, key


def _headers(key: str, *, with_bearer: bool) -> dict[str, str]:
    headers = {"apikey": key}
    if with_bearer:
        headers["Authorization"] = f"Bearer {key}"
    return headers


def _get_page(base_url: str, key: str, offset: int) -> list[dict]:
    params = {
        "select": ",".join(COLUMNS),
        # A stable, unique ordering so offset paging never skips or repeats rows.
        "order": "month.asc,country.asc,topic_id.asc",
        "limit": str(PAGE_SIZE),
        "offset": str(offset),
    }
    endpoint = f"{base_url}/rest/v1/{TABLE}"
    try:
        response = requests.get(
            endpoint, params=params, headers=_headers(key, with_bearer=True), timeout=REQUEST_TIMEOUT
        )
        # New sb_secret_ keys are not JWTs, so retry without the Bearer header.
        if response.status_code in {401, 403} and "jwt" in response.text.lower():
            response = requests.get(
                endpoint, params=params, headers=_headers(key, with_bearer=False), timeout=REQUEST_TIMEOUT
            )
    except requests.RequestException as exc:
        raise DashboardDataError(f"Could not reach Supabase: {type(exc).__name__}") from exc
    if not response.ok:
        raise DashboardDataError(
            f"{TABLE} lookup failed ({response.status_code}): {response.text[:500]}"
        )
    try:
        return response.json()
    except ValueError as exc:
        raise DashboardDataError(f"{TABLE} returned a response that is not JSON") from exc


@st.cache_data(ttl=600, show_spinner="Loading topic statistics from Supabase...")
def load_data() -> pd.DataFrame:
    """Return every row of monthly_topic_stats, without created_at/updated_at.

    Raises DashboardDataError on failure. Exceptions are not cached, so the
    next rerun tries Supabase again.
    """
    base_url, key = _credentials()
    rows: list[dict] = []
    offset = 0
    while True:
        page = _get_page(base_url, key, offset)
        if not page:
            break
        rows.extend(page)
        # Advance by what the server actually returned, in case its max-rows is below PAGE_SIZE.
        offset += len(page)

    df = pd.DataFrame(rows, columns=list(COLUMNS))
    df["month"] = pd.to_datetime(df["month"], format="%Y-%m-%d")
    df["article_count"] = pd.to_numeric(df["article_count"]).astype("int64")
    return df


def get_data() -> pd.DataFrame:
    """Load the data, or show an error and stop the app if Supabase is unavailable."""
    try:
        return load_data()
    except DashboardDataError as exc:
        st.error(f"Could not load dashboard data from Supabase. {exc}")
        st.stop()
