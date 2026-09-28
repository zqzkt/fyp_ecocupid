"""EcoCupid dashboard. Run from the repo root with: streamlit run dashboard/app.py"""

import streamlit as st

from filters import sidebar_filters
from load_data import get_data
from style import apply_style

st.set_page_config(page_title="EcoCupid Dashboard", layout="wide")
apply_style()

df = get_data()
if df.empty:
    st.info("monthly_topic_stats has no rows yet.")
    st.stop()

page = st.navigation(
    [
        st.Page("views/overview.py", title="Overview", default=True),
        st.Page("views/trends.py", title="Trends"),
        st.Page("views/data.py", title="Data"),
    ]
)
# Filters live in the entry point so every page shares them and they persist across pages.
st.session_state["filters"] = sidebar_filters(df)
page.run()
