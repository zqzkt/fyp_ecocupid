"""EcoCupid dashboard.

Run from the repo root with:
streamlit run dashboard/app.py
"""

import pandas as pd
import streamlit as st

from filters import (
    country_opportunity_filters,
    sidebar_filters,
)
from load_data import get_data
from style import apply_style


st.set_page_config(
    page_title="EcoCupid Dashboard",
    layout="wide",
)

apply_style()

st.markdown("""
<style>
/* Target Streamlit navigation page labels directly */
[data-testid="stSidebarNav"] a span,
[data-testid="stSidebarNav"] a span[data-testid="stSidebarNavLinkLabel"],
[data-testid="stSidebarNav"] a [data-testid="stSidebarNavLinkLabel"],
[data-testid="stSidebarNav"] a p {
    white-space: normal !important;
    text-overflow: unset !important;
    overflow: visible !important;
    overflow-wrap: break-word !important;
    word-break: normal !important;
    display: block !important;
    max-width: 100% !important;
}

/* Allow navigation links to expand in height */
[data-testid="stSidebarNav"] a {
    height: auto !important;
    min-height: 2.5rem !important;
    overflow: visible !important;
}

/* Override truncation on nested page-label containers */
[data-testid="stSidebarNav"] a > div,
[data-testid="stSidebarNav"] a > div > div {
    min-width: 0 !important;
    height: auto !important;
    overflow: visible !important;
    white-space: normal !important;
}

/* Allow section headings to wrap */
[data-testid="stSidebarNav"] [data-testid="stNavSectionHeader"],
[data-testid="stSidebarNav"] [data-testid="stNavSectionHeader"] * {
    white-space: normal !important;
    text-overflow: unset !important;
    overflow: visible !important;
    overflow-wrap: break-word !important;
}

/* Ensure navigation items can grow vertically */
[data-testid="stSidebarNav"] li {
    height: auto !important;
}
</style>
""", unsafe_allow_html=True)
# =====================================================================
# LOAD MAIN DASHBOARD DATA
# =====================================================================

df = get_data()

if df.empty:
    st.info(
        "monthly_topic_stats has no rows yet."
    )
    st.stop()


# =====================================================================
# NAVIGATION
# =====================================================================

overview_page = st.Page(
    "views/overview.py",
    title="Coverage Overview",
    default=True,
)

country_opportunity_page = st.Page(
    "views/country_opportunity.py",
    title="Country-Specific Explorer",
)

engagement_comparison_page = st.Page(
    "views/engagement_comparison.py",
    title="Engagement Metrics Overview",
)

data_page = st.Page(
    "views/data.py",
    title="Data",
)

communication_framework_page = st.Page(
    "views/communication_framework.py",
    title="Communication Framework",
)

sentiment_analysis_page = st.Page(
    "views/sentiment_analysis.py",
    title="Sentiment Analysis",
)


page = st.navigation(
    {
        "News": [
            overview_page,
            country_opportunity_page,
        ],
        "Social Media": [
            engagement_comparison_page,
            sentiment_analysis_page,
            communication_framework_page,
        ],
        "Raw Data": [
            data_page,
        ],
    }
)


# =====================================================================
# PAGE-SPECIFIC FILTERS
# =====================================================================

if page == country_opportunity_page:

    st.session_state[
        "country_opportunity_filters"
    ] = country_opportunity_filters(df)

elif page == engagement_comparison_page:

    # Engagement Comparison uses its own sidebar filters
    # inside engagement_comparison.py.
    pass

elif page == communication_framework_page:

    # Communication Framework has its own country and month filters.
    pass

elif page == sentiment_analysis_page:

    # Sentiment Analysis uses its own month and multi-country filters.
    pass

elif page == data_page:

    st.session_state["data_months"] = sorted(
        pd.to_datetime(df["month"].dropna().unique())
    )

else:

    st.session_state["filters"] = sidebar_filters(df)

page.run()
