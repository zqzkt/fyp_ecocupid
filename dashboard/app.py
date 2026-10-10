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

data_page = st.Page(
    "views/data.py",
    title="Data",
)


page = st.navigation(
    [
        overview_page,
        country_opportunity_page,
        data_page,
    ]
)


# =====================================================================
# PAGE-SPECIFIC FILTERS
# =====================================================================

if page == country_opportunity_page:

    st.session_state[
        "country_opportunity_filters"
    ] = country_opportunity_filters(df)

else:

    st.session_state["filters"] = (
        sidebar_filters(df)
    )


page.run()
