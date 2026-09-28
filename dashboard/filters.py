"""Sidebar filters shared by every dashboard page."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
import streamlit as st


def format_month(month: pd.Timestamp) -> str:
    return f"{month:%b %Y}"


def format_period(start: pd.Timestamp, end: pd.Timestamp) -> str:
    if start == end:
        return format_month(start)
    if start.year == end.year:
        return f"{start:%b} – {format_month(end)}"
    return f"{format_month(start)} – {format_month(end)}"


@dataclass(frozen=True)
class Filters:
    data: pd.DataFrame  # rows matching the current selection
    countries: list[str]  # selected countries
    all_countries: list[str]  # every country in the dataset, for stable per-country colours
    start: pd.Timestamp
    end: pd.Timestamp
    months: list[pd.Timestamp]  # months in the dataset between start and end, inclusive

    @property
    def period(self) -> str:
        return format_period(self.start, self.end)


def sidebar_filters(df: pd.DataFrame) -> Filters:
    """Render the country and month-range filters and return the filtered rows."""
    st.sidebar.header("Filters")

    all_countries = sorted(df["country"].unique())
    # Toggle chips wrap within the narrow sidebar, so every country stays visible.
    countries = st.sidebar.pills(
        "Countries", all_countries, selection_mode="multi", default=all_countries, key="countries"
    )

    months = sorted(pd.to_datetime(df["month"].unique()))
    if len(months) > 1:
        start, end = st.sidebar.select_slider(
            "Months", options=months, value=(months[0], months[-1]),
            format_func=format_month, key="month_range",
        )
    else:
        start = end = months[0]
        st.sidebar.caption(f"Months: {format_month(start)}")

    if not countries:
        st.warning("Select at least one country in the sidebar.")
        st.stop()

    mask = df["country"].isin(countries) & df["month"].between(start, end)
    return Filters(
        data=df[mask],
        countries=countries,
        all_countries=all_countries,
        start=start,
        end=end,
        months=[m for m in months if start <= m <= end],
    )


def current_filters() -> Filters:
    """The filters app.py computed for this run, for use inside a page."""
    return st.session_state["filters"]
