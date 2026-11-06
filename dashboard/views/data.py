"""Collect previous-month data and browse records stored in Supabase."""

import subprocess
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

from previous_month_data import DashboardDataError, load_previous_month_data
from style import kpi_card

REPO_ROOT = Path(__file__).resolve().parents[2]
NEWS_PIPELINE = REPO_ROOT / "scripts" / "news_datapipeline.py"
SOCIAL_PIPELINE = REPO_ROOT / "scripts" / "social_media_pipeline.py"
SOCIAL_PLATFORMS = (
    ("Facebook", "facebook"),
    ("Instagram", "instagram"),
    ("Reddit", "reddit"),
    ("X", "x"),
    ("YouTube", "youtube"),
)
SOCIAL_TABLES = (
    ("Clean posts", "clean_posts"),
    ("Clean comments", "clean_comments"),
    ("Facebook comments", "facebook_comments"),
    ("Facebook posts", "facebook_posts"),
    ("Instagram comments", "instagram_comments"),
    ("Instagram posts", "instagram_posts"),
    ("Reddit comments", "reddit_comments"),
    ("Reddit posts", "reddit_posts"),
    ("X posts", "x_posts"),
    ("X replies", "x_replies"),
    ("YouTube comments", "youtube_comments"),
    ("YouTube videos", "youtube_videos"),
)
DISPLAY_LIMIT = 100


def run_collection(
    label: str,
    script_path: Path,
    args: tuple[str, ...] = (),
) -> None:
    """Run a collection pipeline and retain its output across Streamlit reruns."""
    command = [sys.executable, str(script_path), *args]
    with st.status(f"Running {label}...", expanded=True) as status:
        try:
            result = subprocess.run(
                command,
                cwd=REPO_ROOT,
                capture_output=True,
                check=False,
                text=True,
            )
        except OSError as error:
            output = f"Could not start {label}: {error}"
            succeeded = False
            return_code = None
        else:
            output = "\n".join(
                part for part in (result.stdout, result.stderr) if part
            )
            succeeded = result.returncode == 0
            return_code = result.returncode

        status.update(
            label=f"{label} {'completed' if succeeded else 'failed'}",
            state="complete" if succeeded else "error",
        )

    st.session_state["collection_result"] = {
        "label": label,
        "output": output,
        "succeeded": succeeded,
        "return_code": return_code,
    }
    st.cache_data.clear()


def _show_table_export(
    dataframe: pd.DataFrame,
    *,
    label: str,
    filename: str,
    key: str,
) -> None:
    """Display a bounded table preview and export all returned rows."""
    if dataframe.empty:
        st.info(f"No {label.lower()} found for the previous month.")
        return

    st.caption(
        f"{len(dataframe):,} rows collected. The preview shows at most "
        f"{DISPLAY_LIMIT:,}; the CSV includes every row."
    )
    st.dataframe(
        dataframe.head(DISPLAY_LIMIT),
        hide_index=True,
        width="stretch",
    )
    st.download_button(
        f"Export {label} CSV",
        data=dataframe.to_csv(index=False).encode("utf-8"),
        file_name=filename,
        mime="text/csv",
        key=key,
    )


st.title("Data")
st.caption(
    "Collect and inspect records for the previous calendar month. "
    "Exports include the complete matching Supabase dataset."
)

data_error = None
try:
    (
        month_start,
        news_summary,
        social_summary,
        news_tables,
        social_tables,
    ) = load_previous_month_data()
except DashboardDataError as error:
    data_error = error
    month_start = None
    news_summary = pd.DataFrame()
    social_summary = pd.DataFrame()
    news_tables = {"news_cleaned": pd.DataFrame()}
    social_tables = {table: pd.DataFrame() for _, table in SOCIAL_TABLES}

month_suffix = (
    f" · {month_start:%B %Y}" if month_start is not None else ""
)
news_already_collected = not news_tables["news_cleaned"].empty
social_already_collected = not social_tables["clean_posts"].empty
cannot_check = data_error is not None
news_help = (
    "Previous-month news data is already in Supabase."
    if news_already_collected
    else (
        "Could not check Supabase. Resolve the data access error before "
        "running collection."
        if cannot_check
        else "Collect news articles for the previous calendar month."
    )
)
social_help = (
    "Previous-month social media data is already in Supabase. "
    "Social collection buttons are disabled."
    if social_already_collected
    else (
        "Could not check Supabase. Resolve the data access error before "
        "running collection."
        if cannot_check
        else "Collect data from all five social media platforms."
    )
)

with st.container(border=True):
    st.subheader(f"Collect previous month's data{month_suffix}")
    st.caption(
        "Collection may take several minutes and use paid API credits."
    )
    collection_columns = st.columns(2)
    with collection_columns[0]:
        if st.button(
            "Run news collection",
            key="run_news_collection",
            type="primary",
            width="stretch",
            disabled=news_already_collected or cannot_check,
            help=news_help,
        ):
            run_collection("News collection", NEWS_PIPELINE)
            st.rerun()
    with collection_columns[1]:
        if st.button(
            "Run all social media collections",
            key="run_all_social_collections",
            type="primary",
            width="stretch",
            disabled=social_already_collected or cannot_check,
            help=social_help,
        ):
            run_collection("Social media collection", SOCIAL_PIPELINE)
            st.rerun()

    st.caption(
        "If a platform fails in the full run, fix the issue and rerun it "
        "individually. Each platform run also performs shared cleaning, "
        "environmental classification, and sentiment analysis."
    )
    platform_columns = st.columns(len(SOCIAL_PLATFORMS))
    for column, (platform_name, platform_id) in zip(
        platform_columns,
        SOCIAL_PLATFORMS,
    ):
        with column:
            if st.button(
                f"Run {platform_name}",
                key=f"run_{platform_id}_collection",
                width="stretch",
                disabled=social_already_collected or cannot_check,
                help=social_help,
            ):
                run_collection(
                    f"{platform_name} collection and processing",
                    SOCIAL_PIPELINE,
                    ("--platform", platform_id),
                )
                st.rerun()

if data_error is not None:
    st.error(f"Could not load previous month's data. {data_error}")
else:
    month_label = month_start.strftime("%B %Y")
    st.header(f"Collected data{month_suffix}")

    with st.container(border=True):
        st.subheader("News")
        news_records = news_tables["news_cleaned"]
        if news_records.empty:
            st.info(f"No news records found in Supabase for {month_label}.")
        else:
            st.success(f"News data collected for {month_label}.")
            topic_count = int(news_summary["topic_count"].sum())
            topic_assignments = int(
                news_summary["topic_article_assignments"].sum()
            )
            kpi_columns = st.columns(3)
            kpi_columns[0].html(kpi_card("News articles", f"{len(news_records):,}"))
            kpi_columns[1].html(
                kpi_card("Countries", f"{len(news_summary):,}")
            )
            kpi_columns[2].html(
                kpi_card("Topic-article assignments", f"{topic_assignments:,}")
            )
            st.caption(
                "Topic-article assignments may count an article more than "
                "once when it belongs to multiple topics."
            )
            st.dataframe(
                news_summary.rename(
                    columns={
                        "country": "Country",
                        "topic_count": "Country-topic entries",
                        "topic_article_assignments": "Topic-article assignments",
                        "top_topic": "Top topic",
                        "top_topic_article_count": "Top topic article count",
                    }
                ),
                hide_index=True,
                width="stretch",
            )
            _show_table_export(
                news_records,
                label="News articles",
                filename=f"news_cleaned_{month_start:%Y_%m}.csv",
                key="download_news_records",
            )

    with st.container(border=True):
        st.subheader("Social media")
        if social_already_collected:
            st.success(f"Social media data collected for {month_label}.")
        else:
            st.info(
                f"No social media records found in Supabase for {month_label}."
            )
        st.dataframe(
            social_summary.rename(
                columns={
                    "platform": "Platform",
                    "environmental_posts": "Environmental posts",
                    "comments": "Comments",
                }
            ),
            hide_index=True,
            width="stretch",
        )

        tabs = st.tabs([label for label, _ in SOCIAL_TABLES])
        for tab, (label, table) in zip(tabs, SOCIAL_TABLES):
            with tab:
                _show_table_export(
                    social_tables[table],
                    label=label,
                    filename=f"{table}_{month_start:%Y_%m}.csv",
                    key=f"download_{table}",
                )

if st.session_state.get("collection_result"):
    collection_result = st.session_state["collection_result"]
    if collection_result["succeeded"]:
        st.success(f"{collection_result['label']} completed.")
    else:
        st.error(
            f"{collection_result['label']} failed"
            + (
                f" (exit code {collection_result['return_code']})."
                if collection_result["return_code"] is not None
                else "."
            )
        )
    if collection_result["output"]:
        with st.expander(
            "Collection log",
            expanded=not collection_result["succeeded"],
        ):
            st.code(collection_result["output"], language="text")
