"""Communication Framework: engagement comparison across platforms and countries."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# Allow this page to import the calculation module under scripts/.
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.communication_framework.engagement_metric_comparison import (
    EngagementDataError,
    compare_countries_within_platform,
    compare_platforms,
    compare_platforms_by_country,
    filter_content,
    load_engagement_data,
    prepare_content,
)
from style import (
    FONT_PX,
    categorical_colors,
    kpi_card,
    sequential_colorscale,
    series_color,
    style_figure,
)


# =====================================================================
# HELPERS
# =====================================================================

def _format_number(value) -> str:
    if value is None or pd.isna(value):
        return "N/A"
    value = float(value)
    if abs(value) >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if abs(value) >= 1_000:
        return f"{value / 1_000:.1f}K"
    return f"{value:,.0f}"


def _format_ratio(value) -> str:
    if value is None or pd.isna(value):
        return "N/A"
    return f"{float(value):,.1f}:1"


def _keyword_options(df: pd.DataFrame) -> list[str]:
    """Temporary topic options from matched_keywords."""
    options: set[str] = set()

    for value in df.get("matched_keywords", pd.Series(dtype=object)).dropna():
        if isinstance(value, list):
            values = value
        else:
            text = str(value).strip()
            if text.startswith("[") and text.endswith("]"):
                import json
                try:
                    parsed = json.loads(text)
                    values = parsed if isinstance(parsed, list) else [text]
                except json.JSONDecodeError:
                    values = [text]
            else:
                values = [text]

        for item in values:
            item = str(item).strip()
            if item:
                options.add(item)

    return sorted(options, key=str.casefold)


def _compact_table(df: pd.DataFrame, include_country: bool) -> pd.DataFrame:
    if df.empty:
        return df

    columns = ["platform"]
    if include_country:
        columns.append("country")

    columns += [
        "post_count",
        "total_engagement",
        "avg_engagement_per_post",
        "median_post_engagement",
        "total_impressions",
        "reach_to_engagement_ratio",
        "engagement_rate_pct",
    ]

    result = df[[c for c in columns if c in df.columns]].copy()

    result = result.rename(
        columns={
            "platform": "Platform",
            "country": "Country",
            "post_count": "Posts",
            "total_engagement": "Total Engagement",
            "avg_engagement_per_post": "Avg / Post",
            "median_post_engagement": "Median / Post",
            "total_impressions": "Views / Impressions",
            "reach_to_engagement_ratio": "Reach : Engagement",
            "engagement_rate_pct": "Engagement Rate (%)",
        }
    )

    if "Reach : Engagement" in result:
        result["Reach : Engagement"] = result["Reach : Engagement"].apply(_format_ratio)

    return result


# =====================================================================
# LOAD SOCIAL DATA
# =====================================================================

st.title("Engagement Comparison")
st.caption(
    "Compare how environmental content performs across media platforms and ASEAN countries."
)

try:
    raw_posts, raw_comments = load_engagement_data()
except EngagementDataError as exc:
    st.error(f"Could not load social engagement data from Supabase. {exc}")
    st.stop()

posts = prepare_content(raw_posts, "post")
comments = prepare_content(raw_comments, "comment")

if posts.empty:
    st.info("No social posts are available.")
    st.stop()


# =====================================================================
# PAGE-SPECIFIC FILTERS
# =====================================================================

st.sidebar.header("Engagement Filters")

topic_options = _keyword_options(posts)
selected_topic_label = st.sidebar.selectbox(
    "Topic",
    ["All topics"] + topic_options,
    key="engagement_topic",
)
selected_topic = None if selected_topic_label == "All topics" else selected_topic_label

platform_options = sorted(posts["platform"].dropna().unique().tolist())
selected_platform = st.sidebar.selectbox(
    "Platform for country comparison",
    platform_options,
    key="engagement_platform",
)

country_options = sorted(posts["country"].dropna().unique().tolist())
selected_countries = st.sidebar.multiselect(
    "Countries",
    country_options,
    default=country_options,
    key="engagement_countries",
)

include_comments = st.sidebar.toggle(
    "Include comment engagement",
    value=False,
    key="engagement_include_comments",
    help=(
        "When enabled, likes, replies, reposts and quotes received by comments "
        "are added to engagement received by the original posts."
    ),
)

valid_dates = posts["posted_at"].dropna()
start_date = None
end_date = None

if not valid_dates.empty:
    min_date = valid_dates.min().date()
    max_date = valid_dates.max().date()

    selected_dates = st.sidebar.date_input(
        "Date range",
        value=(min_date, max_date),
        min_value=min_date,
        max_value=max_date,
        key="engagement_date_range",
    )

    if isinstance(selected_dates, (tuple, list)) and len(selected_dates) == 2:
        start_date, end_date = selected_dates

if not selected_countries:
    st.warning("Select at least one country in the sidebar.")
    st.stop()

filter_args = {
    "topic": selected_topic,
    "countries": selected_countries,
    "start_date": str(start_date) if start_date else None,
    "end_date": str(end_date) if end_date else None,
}

filtered_posts = filter_content(posts, **filter_args)
filtered_comments = filter_content(comments, **filter_args)

if filtered_posts.empty:
    st.info("No posts match the selected filters.")
    st.stop()


# =====================================================================
# SUMMARY
# =====================================================================

overall = compare_platforms(
    filtered_posts,
    filtered_comments,
    include_comment_engagement=include_comments,
)

total_posts = int(overall["post_count"].sum())
total_engagement = int(overall["total_engagement"].sum())
avg_engagement = total_engagement / total_posts if total_posts else 0

total_impressions = overall["total_impressions"].sum(min_count=1)
platform_count = int(overall["platform"].nunique())

cards = [
    ("Posts", f"{total_posts:,}"),
    ("Total Engagement", _format_number(total_engagement)),
    ("Avg Engagement / Post", f"{avg_engagement:,.1f}"),
    ("Platforms", f"{platform_count:,}"),
    ("Views / Impressions", _format_number(total_impressions)),
]

for column, (label, value) in zip(
    st.columns([1, 1.25, 1.45, 1, 1.4]),
    cards,
):
    column.html(kpi_card(label, value))

comment_note = (
    "Post + comment engagement"
    if include_comments
    else "Post engagement only"
)
st.caption(
    f"{comment_note} · "
    f"{selected_topic_label} · "
    f"{len(selected_countries)} selected "
    f"{'country' if len(selected_countries) == 1 else 'countries'}"
)


# =====================================================================
# 1. WITHIN-PLATFORM COMPARISON
# =====================================================================

st.header(f"1. {selected_platform} engagement by country")
st.caption(
    "Average engagement per post is used for the chart so countries with more "
    "collected posts do not automatically appear stronger."
)

within = compare_countries_within_platform(
    filtered_posts,
    filtered_comments,
    selected_platform,
    include_comment_engagement=include_comments,
)

if within.empty:
    st.info(f"No {selected_platform} posts match the current filters.")
else:
    within = within.sort_values(
        "avg_engagement_per_post",
        ascending=True,
    )

    country_bar = go.Figure(
        go.Bar(
            x=within["avg_engagement_per_post"],
            y=within["country"],
            orientation="h",
            marker=dict(color=series_color()),
            text=within["avg_engagement_per_post"].map(lambda x: f"{x:,.1f}"),
            textposition="outside",
            cliponaxis=False,
            customdata=np.column_stack(
                [
                    within["post_count"],
                    within["total_engagement"],
                ]
            ),
            hovertemplate=(
                "<b>%{y}</b><br>"
                "Average engagement/post: %{x:,.1f}<br>"
                "Posts: %{customdata[0]:,.0f}<br>"
                "Total engagement: %{customdata[1]:,.0f}"
                "<extra></extra>"
            ),
        )
    )
    country_bar.update_xaxes(
        title_text="Average engagement per post",
        rangemode="tozero",
    )
    country_bar.update_yaxes(title_text="")
    country_bar.update_layout(bargap=0.35)

    st.plotly_chart(
        style_figure(country_bar, height=180 + 65 * len(within)),
        config={"displayModeBar": False},
    )

    with st.expander("View country metrics"):
        st.dataframe(
            _compact_table(
                within.sort_values(
                    "avg_engagement_per_post",
                    ascending=False,
                ),
                include_country=True,
            ),
            hide_index=True,
            width="stretch",
        )


# =====================================================================
# 2. CROSS-PLATFORM COMPARISON
# =====================================================================

st.header("2. Engagement across platforms")
st.caption(
    "Compare engagement intensity rather than raw totals alone. "
    "Reach-based metrics are available only where views/impressions exist."
)

platform_chart_data = overall.sort_values(
    "avg_engagement_per_post",
    ascending=True,
)

platform_colors = categorical_colors(
    sorted(platform_chart_data["platform"].tolist())
)

platform_bar = go.Figure(
    go.Bar(
        x=platform_chart_data["avg_engagement_per_post"],
        y=platform_chart_data["platform"],
        orientation="h",
        marker=dict(
            color=[
                platform_colors[p]
                for p in platform_chart_data["platform"]
            ]
        ),
        text=platform_chart_data["avg_engagement_per_post"].map(
            lambda x: f"{x:,.1f}"
        ),
        textposition="outside",
        cliponaxis=False,
        customdata=np.column_stack(
            [
                platform_chart_data["post_count"],
                platform_chart_data["total_engagement"],
            ]
        ),
        hovertemplate=(
            "<b>%{y}</b><br>"
            "Average engagement/post: %{x:,.1f}<br>"
            "Posts: %{customdata[0]:,.0f}<br>"
            "Total engagement: %{customdata[1]:,.0f}"
            "<extra></extra>"
        ),
    )
)

platform_bar.update_xaxes(
    title_text="Average engagement per post",
    rangemode="tozero",
)
platform_bar.update_yaxes(title_text="")
platform_bar.update_layout(bargap=0.35)

st.plotly_chart(
    style_figure(
        platform_bar,
        height=220 + 70 * len(platform_chart_data),
    ),
    config={"displayModeBar": False},
)

st.dataframe(
    _compact_table(
        overall.sort_values(
            "avg_engagement_per_post",
            ascending=False,
        ),
        include_country=False,
    ),
    hide_index=True,
    width="stretch",
)


# =====================================================================
# 3. PLATFORM x COUNTRY
# =====================================================================

st.header("3. Platform × country comparison")
st.caption(
    "Each cell shows average engagement per post. Darker cells indicate "
    "stronger engagement for that platform-country combination."
)

platform_country = compare_platforms_by_country(
    filtered_posts,
    filtered_comments,
    include_comment_engagement=include_comments,
)

if platform_country.empty:
    st.info("No platform-country combinations match the current filters.")
else:
    heat = platform_country.pivot_table(
        index="platform",
        columns="country",
        values="avg_engagement_per_post",
        aggfunc="mean",
    )

    # Keep selected countries in a predictable order where data exists.
    heat = heat.reindex(
        columns=[
            country
            for country in selected_countries
            if country in heat.columns
        ]
    )

    text = heat.map(
        lambda value: ""
        if pd.isna(value)
        else f"{value:,.1f}"
    )

    heatmap = go.Figure(
        go.Heatmap(
            z=heat.to_numpy(dtype=float),
            x=heat.columns.tolist(),
            y=heat.index.tolist(),
            text=text.to_numpy(),
            texttemplate="%{text}",
            textfont_size=FONT_PX,
            colorscale=sequential_colorscale(),
            showscale=False,
            xgap=3,
            ygap=3,
            hovertemplate=(
                "<b>%{y} · %{x}</b><br>"
                "Average engagement/post: %{z:,.1f}"
                "<extra></extra>"
            ),
        )
    )

    heatmap.update_xaxes(side="top")
    heatmap.update_yaxes(
        autorange="reversed",
        ticksuffix="  ",
    )

    st.plotly_chart(
        style_figure(
            heatmap,
            height=190 + 75 * len(heat.index),
        ),
        config={"displayModeBar": False},
    )

    with st.expander("View platform × country metrics"):
        st.dataframe(
            _compact_table(
                platform_country,
                include_country=True,
            ),
            hide_index=True,
            width="stretch",
        )


# =====================================================================
# INTERPRETATION NOTE
# =====================================================================

st.info(
    "Total engagement shows overall activity, while average engagement per post "
    "helps compare channels with different content volumes. Reach : Engagement "
    "and Engagement Rate are shown only for YouTube and X because the other "
    "platforms currently do not provide views/impressions in the collected data."
)
