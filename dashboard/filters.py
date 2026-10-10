"""Sidebar filters shared by dashboard pages."""

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


# =====================================================================
# STANDARD DASHBOARD FILTERS
# =====================================================================

@dataclass(frozen=True)
class Filters:
    data: pd.DataFrame
    countries: list[str]
    all_countries: list[str]
    start: pd.Timestamp
    end: pd.Timestamp
    months: list[pd.Timestamp]

    @property
    def period(self) -> str:
        return format_period(self.start, self.end)


def sidebar_filters(df: pd.DataFrame) -> Filters:
    """Multi-country filters used by the standard dashboard pages."""
    st.sidebar.header("Filters")

    all_countries = sorted(df["country"].dropna().unique())
    countries = st.sidebar.pills(
        "Countries",
        all_countries,
        selection_mode="multi",
        default=all_countries,
        key="countries",
    )

    months = sorted(pd.to_datetime(df["month"].dropna().unique()))

    if len(months) > 1:
        start, end = st.sidebar.select_slider(
            "Months",
            options=months,
            value=(months[0], months[-1]),
            format_func=format_month,
            key="month_range",
        )
    else:
        start = end = months[0]
        st.sidebar.caption(f"Months: {format_month(start)}")

    if not countries:
        st.warning("Select at least one country in the sidebar.")
        st.stop()

    mask = (
        df["country"].isin(countries)
        & df["month"].between(start, end)
    )

    return Filters(
        data=df[mask],
        countries=list(countries),
        all_countries=all_countries,
        start=start,
        end=end,
        months=[m for m in months if start <= m <= end],
    )


def current_filters() -> Filters:
    """Return the standard filters created by app.py."""
    return st.session_state["filters"]


# =====================================================================
# COUNTRY OPPORTUNITY FILTERS
# =====================================================================

@dataclass(frozen=True)
class CountryOpportunityFilters:
    data: pd.DataFrame
    country: str
    start: pd.Timestamp
    end: pd.Timestamp
    months: list[pd.Timestamp]

    @property
    def period(self) -> str:
        return format_period(self.start, self.end)


def country_opportunity_filters(
    df: pd.DataFrame,
) -> CountryOpportunityFilters:
    """
    Filters for Country Opportunity Explorer.

    Exactly one country can be selected at a time. The Overview map can
    preselect both the country and date range through Streamlit session state.
    """
    st.sidebar.header("Filters")

    countries = sorted(df["country"].dropna().unique())
    if not countries:
        st.warning("No countries are available for the Country Opportunity Explorer.")
        st.stop()

    # overview.py writes the clicked country directly to this widget key.
    stored_country = st.session_state.get("opportunity_country")
    if stored_country not in countries:
        st.session_state["opportunity_country"] = countries[0]

    country = st.sidebar.selectbox(
        "Country",
        countries,
        key="opportunity_country",
    )

    months = sorted(pd.to_datetime(df["month"].dropna().unique()))
    if not months:
        st.warning("No months are available for the Country Opportunity Explorer.")
        st.stop()

    if len(months) > 1:
        stored_range = st.session_state.get("opportunity_month_range")
        valid_range = (months[0], months[-1])

        if isinstance(stored_range, (tuple, list)) and len(stored_range) == 2:
            requested_start = pd.Timestamp(stored_range[0])
            requested_end = pd.Timestamp(stored_range[1])
            available = set(months)

            if (
                requested_start in available
                and requested_end in available
                and requested_start <= requested_end
            ):
                valid_range = (requested_start, requested_end)

        current_range = st.session_state.get("opportunity_month_range")
        if current_range is None or tuple(current_range) != valid_range:
            st.session_state["opportunity_month_range"] = valid_range

        start, end = st.sidebar.select_slider(
            "Months",
            options=months,
            value=valid_range,
            format_func=format_month,
            key="opportunity_month_range",
        )
    else:
        start = end = months[0]
        st.session_state["opportunity_month_range"] = (start, end)
        st.sidebar.caption(f"Months: {format_month(start)}")

    mask = (
        (df["country"] == country)
        & df["month"].between(start, end)
    )

    return CountryOpportunityFilters(
        data=df[mask],
        country=country,
        start=start,
        end=end,
        months=[m for m in months if start <= m <= end],
    )


def current_country_opportunity_filters() -> CountryOpportunityFilters:
    """Return Country Opportunity Explorer filters."""
    return st.session_state["country_opportunity_filters"]

