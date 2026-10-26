"""Data page: the filtered rows, for checking the numbers behind the charts."""

import streamlit as st

from filters import current_filters

filters = current_filters()
df = filters.data

st.title("Data")
st.caption(f"{len(df):,} rows · {filters.period}")

_, export_column = st.columns([5, 1])
with export_column:
    st.download_button(
        "Export to CSV",
        data=df.to_csv(index=False).encode("utf-8-sig"),
        file_name="news_filtered_data.csv",
        mime="text/csv",
        key="export_filtered_data",
        width="stretch",
    )

st.dataframe(
    df,
    hide_index=True,
    width="stretch",
    column_config={"month": st.column_config.DateColumn("month", format="YYYY-MM")},
)
