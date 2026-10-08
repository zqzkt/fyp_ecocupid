"""Aggregations shared by the dashboard pages. Always sum article_count; never use topic_rank."""

import pandas as pd


def topic_totals(df: pd.DataFrame) -> pd.DataFrame:
    """Total articles per topic_name, largest first (ties alphabetical)."""
    return (
        df.groupby("topic_name", as_index=False)["article_count"].sum()
        .sort_values(["article_count", "topic_name"], ascending=[False, True])
        .reset_index(drop=True)
    )
