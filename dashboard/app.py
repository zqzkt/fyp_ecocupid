"""EcoCupid dashboard.

Run from the repo root with:
streamlit run dashboard/app.py
"""

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
    title="Overview",
    default=True,
)

country_opportunity_page = st.Page(
    "views/country_opportunity.py",
    title="Country Opportunity Explorer",
)

engagement_comparison_page = st.Page(
    "views/engagement_comparison.py",
    title="Engagement Comparison",
)

data_page = st.Page(
    "views/data.py",
    title="Data",
)

communication_channels_page = st.Page(
    "views/communication_channels.py",
    title="Communication Channels",
)

communication_insights_page = st.Page(
    "views/communication_insights.py",
    title="Communication Insights",
)

sentiment_analysis_page = st.Page(
    "views/sentiment_analysis.py",
    title="Sentiment Analysis",
)


page = st.navigation(
    [
        overview_page,
        country_opportunity_page,
        engagement_comparison_page,
        data_page,
        communication_channels_page,
        communication_insights_page,
        sentiment_analysis_page,
    ]
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

elif page == communication_insights_page:

    # Communication Insights uses its own single-country filters
    # inside communication_insights.py.
    pass

elif page == sentiment_analysis_page:

    # Sentiment Analysis uses its own month and multi-country filters.
    pass

elif page != communication_channels_page:

    st.session_state["filters"] = (
        sidebar_filters(df)
    )

else:

    st.session_state["filters"] = (
        sidebar_filters(df)
    )
    
page.run()
