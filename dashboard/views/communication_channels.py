"""Communication Channels page."""

from __future__ import annotations

import streamlit as st

from communication_channels_data import (
    CommunicationChannelsDataError,
    add_date_columns,
    load_framework_data,
    recommend_channels,
    topic_options,
)
from filters import format_month


st.set_page_config(
    page_title="Communication Channels",
    page_icon="📣",
    layout="wide",
)

st.title("Communication Channels")
st.caption(
    "Identify recommended communication channels associated with environmental topics "
    "for each country."
)

try:
    data = load_framework_data()
except CommunicationChannelsDataError as exc:
    st.error(f"Could not load communication channel data: {exc}")
    st.stop()

topics = topic_options(data)
if topics.empty:
    st.info("No matched topics are available in clean_posts or clean_comments.")
    st.stop()

st.sidebar.header("Filters")
countries = [
    "Brunei",
    "Indonesia",
    "Malaysia",
    "Philippines",
    "Singapore",
    "Thailand",
]
country = st.sidebar.selectbox("Country", countries)
country_topics = topics[topics["country"].astype(str) == country]
if country_topics.empty:
    st.info(f"No cleaned activity is available for {country}.")
    st.stop()
topic_labels = country_topics["topic"].astype(str).tolist()
selected_label = st.sidebar.selectbox("Topic keyword", topic_labels)

all_activity = [
    add_date_columns(data[source_type], source_type)
    for source_type in ("posts", "comments")
    if not data[source_type].empty
]
months = sorted(
    {
        month
        for frame in all_activity
        for month in frame["_month"].dropna().unique()
    }
)
if not months:
    st.sidebar.info("No valid activity months are available.")
    selected_months = None
elif len(months) == 1:
    selected_months = (months[0], months[0])
    st.sidebar.caption(f"Months: {format_month(months[0])}")
else:
    selected_months = st.sidebar.select_slider(
        "Months",
        options=months,
        value=(months[0], months[-1]),
        format_func=format_month,
        key="communication_channels_month_range",
    )

filtered_data = {}
for source_type in ("posts", "comments"):
    frame = add_date_columns(data[source_type], source_type)
    if selected_months is not None:
        frame = frame[frame["_month"].between(*selected_months)]
    filtered_data[source_type] = frame

st.divider()
st.subheader(f"Recommended channels for {selected_label} in {country}")
st.caption(
    "Ranking uses 60% total engagement and 40% activity volume among matched "
    "cleaned posts and comments."
)

recommendations, evidence = recommend_channels(
    filtered_data,
    country,
    selected_label,
)
if recommendations.empty:
    st.warning(
        "No cleaned activity matched this country and topic. "
        "Try another top-three topic or confirm the cleaning pipeline has run."
    )
    st.stop()

evidence_table = {
    "Metric": [
        "Matched activity items",
        "Platforms identified",
        "Recommendation basis",
    ],
    "Value": [
        f"{evidence['activity_rows']:,}",
        f"{recommendations['platform'].nunique():,}",
        "60% engagement + 40% activity",
    ],
}
st.table(evidence_table)

display_columns = {
    "recommendation": "Recommendation",
    "platform": "Channel",
    "recommendation_score": "Score",
    "activity_items": "Activity items",
    "total_engagement": "Total engagement",
    "avg_engagement": "Average engagement",
    "posts": "Posts",
    "comments": "Comments",
}
st.dataframe(
    recommendations[list(display_columns)].rename(columns=display_columns),
    hide_index=True,
    width="stretch",
    column_config={
        "Score": st.column_config.ProgressColumn(
            "Score",
            min_value=0,
            max_value=100,
            format="%.1f",
        ),
        "Total engagement": st.column_config.NumberColumn(format="%,d"),
        "Average engagement": st.column_config.NumberColumn(format="%.1f"),
    },
)

st.subheader("How to use this insight")
st.markdown(
    "- Use the **Primary channel** as the first platform for topic messaging.\n"
    "- Use **Secondary channels** to extend reach or test a different format.\n"
    "- Treat the ranking as an evidence-based starting point: high activity "
    "does not guarantee that every audience segment will respond equally."
)
