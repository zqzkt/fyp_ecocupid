"""Data page: the filtered rows, for checking the numbers behind the charts."""

import streamlit as st

from filters import current_filters

filters = current_filters()
df = filters.data

st.title("Data")
st.caption(f"{len(df):,} rows · {filters.period}")
st.dataframe(
    df,
    hide_index=True,
    width="stretch",
    column_config={"month": st.column_config.DateColumn("month", format="YYYY-MM")},
)
