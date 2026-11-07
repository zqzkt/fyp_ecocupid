
"""EcoCupid Communication Framework: WHERE to communicate and HOW to communicate.

Uses channel_recommendations.py for statistical decisions and reads the saved
results produced by topic_based_analysis.py from Supabase. Does not call Gemini.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

# views/communication_framework.py -> dashboard/ -> project root
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.communication_framework.channel_recommendations import (
    CommunicationChannelsDataError,
    _load_table,
    load_framework_data,
    normalize_country,
    recommend_channels,
)

COUNTRIES = [
    "Brunei", "Indonesia", "Malaysia",
    "Philippines", "Singapore", "Thailand"
]

st.markdown("""<style>
.ec-heading {font-size:1.06rem;font-weight:750;color:#214b35;margin:0 0 4px}
.ec-muted {color:#606d61;font-size:.88rem}
.ec-channel {background:#dceedd;border:1px solid #b7d3bc;border-left:5px solid #236a47;
  border-radius:12px;padding:17px 19px;min-height:112px}
.ec-channel.secondary {background:#e8f4e6;border-left-color:#7cae77}
.ec-channel.neutral {background:#f2f0e6;border-left-color:#9b9d8b}
.ec-role {font-size:.82rem;color:#496352;font-weight:650}
.ec-name {font-size:1.65rem;color:#164a32;font-weight:800;margin-top:8px}
.ec-note {background:#f4f0e3;border-radius:10px;padding:12px 16px;border-left:4px solid #90aa87}
.ec-tip {background:#eaf3e7;border-radius:10px;padding:12px 15px;border:1px solid #d5e7d1}
</style>""", unsafe_allow_html=True)


def _safe(value, fallback="Not available") -> str:
    if value is None:
        return fallback
    try:
        if pd.isna(value):
            return fallback
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    return text if text else fallback


def _card(role: str, name: str | None, secondary=False) -> None:
    import html

    css = "secondary" if secondary else ("neutral" if not name else "")
    shown = name or ("Not recommended" if secondary else "No clear primary")

    st.html(
        f'<div class="ec-channel {css}">'
        f'<div class="ec-role">{html.escape(role)}</div>'
        f'<div class="ec-name">{html.escape(shown)}</div>'
        f'</div>'
    )


@st.cache_data(ttl=600, show_spinner="Loading saved messaging guidance...")
def _load_guidance() -> pd.DataFrame:
    # Read saved results only; no Gemini calls.
    return _load_table("topic_based_analysis", columns="*")


def _guidance_rows(
    frame: pd.DataFrame,
    country: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
    topic_names: set[str],
) -> pd.DataFrame:

    if frame.empty or not {"country", "topic_name", "month"}.issubset(frame.columns):
        return pd.DataFrame()

    g = frame.copy()
    g["_country"] = g["country"].map(normalize_country)

    g["_month"] = (
        pd.to_datetime(g["month"], errors="coerce", utc=True)
        .dt.tz_localize(None)
        .dt.to_period("M")
        .dt.to_timestamp()
    )

    names = {name.casefold() for name in topic_names}

    g = g[
        (g["_country"] == country)
        & g["_month"].between(start, end)
        & g["topic_name"].fillna("").astype(str).str.casefold().isin(names)
    ].copy()

    return g.sort_values(
        ["_month", "topic_name"],
        ascending=[False, True]
    )


def _show_guidance(record: pd.Series) -> None:
    fields = [
        ("Messaging tone & style", ["tone_and_emotion", "key_message"]),
        ("Content structure", ["narrative_method", "content_type", "story_structure"]),
        ("Hooks & CTAs", ["hooks", "call_to_action", "captions"]),
        ("Specific recommendations", ["recommendations", "what_not_to_do"]),
    ]

    labels = {
        "tone_and_emotion": "Tone and emotion",
        "key_message": "Key message",
        "narrative_method": "Narrative approach",
        "content_type": "Content type",
        "story_structure": "Story structure",
        "hooks": "Hooks",
        "call_to_action": "Call to action",
        "captions": "Captions",
        "recommendations": "Recommendations",
        "what_not_to_do": "Avoid",
    }

    cols = st.columns(4, gap="small")

    for col, (heading, keys) in zip(cols, fields):
        with col:
            with st.container(border=True):
                st.markdown(f"**{heading}**")

                for key in keys:
                    value = _safe(record.get(key), "")

                    if value:
                        st.markdown(f"**{labels[key]}**")
                        st.write(value)

    links = []

    for field in ("top_post_links", "bottom_post_links"):
        value = record.get(field)

        if isinstance(value, list):
            links.extend(
                str(link)
                for link in value
                if str(link).startswith(("https://", "http://"))
            )

    if links:
        with st.expander("Example source posts"):
            for i, link in enumerate(links[:10], start=1):
                st.markdown(f"[{i}. View source post]({link})")


# ============================================================
# PAGE HEADER
# ============================================================

st.title("Communication Framework")

st.caption(
    "Country-level channel selection and practical messaging guidance "
    "for the leading environmental topics."
)

try:
    data = load_framework_data()
except CommunicationChannelsDataError as exc:
    st.error(f"Could not load channel recommendation data: {exc}")
    st.stop()


# ============================================================
# SIDEBAR FILTERS
# ============================================================

st.sidebar.header("Communication Framework Filters")

country = st.sidebar.selectbox(
    "Country",
    COUNTRIES,
    key="cf_country"
)

months_raw = data["monthly_topics"]

if months_raw.empty or not {"country", "month"}.issubset(months_raw.columns):
    st.info("No monthly news topic statistics are available.")
    st.stop()

country_topics = months_raw.loc[
    months_raw["country"].map(normalize_country) == country
].copy()

month_values = (
    pd.to_datetime(country_topics["month"], errors="coerce")
    .dropna()
    .dt.to_period("M")
    .dt.to_timestamp()
)

if month_values.empty:
    st.info(f"No monthly topic statistics are available for {country}.")
    st.stop()

months = pd.date_range(
    month_values.min(),
    month_values.max(),
    freq="MS"
).tolist()

if len(months) == 1:
    selected_months = (months[0], months[0])
    st.sidebar.caption(f"Month: {months[0]:%b %Y}")
else:
    selected_months = st.sidebar.select_slider(
        "Months",
        options=months,
        value=(months[0], months[-1]),
        format_func=lambda m: m.strftime("%b %Y"),
        key="cf_months"
    )

start, end = selected_months

period = (
    start.strftime("%b %Y")
    if start == end
    else f"{start:%b %Y} – {end:%b %Y}"
)

st.markdown(
    f"**Country:** {country} &nbsp;&nbsp; **Time period:** {period}"
)


# ============================================================
# CHANNEL ANALYSIS
# ============================================================

with st.spinner("Analysing channel performance..."):
    try:
        summary, evidence = recommend_channels(
            data,
            country,
            selected_months
        )
    except Exception as exc:
        st.error(f"Channel analysis could not be completed: {exc}")
        st.stop()

topics = evidence.get("topics", pd.DataFrame())

if not topics.empty:
    with st.expander(
        "Environmental topics included in this analysis",
        expanded=False
    ):
        display = topics[
            [
                c for c in [
                    "month", "topic_rank",
                    "topic_name", "article_count"
                ]
                if c in topics.columns
            ]
        ].copy()

        if "month" in display:
            display["month"] = (
                pd.to_datetime(display["month"])
                .dt.strftime("%b %Y")
            )

        st.dataframe(
            display.rename(
                columns={
                    "month": "Month",
                    "topic_rank": "Rank",
                    "topic_name": "Topic",
                    "article_count": "News articles",
                }
            ),
            hide_index=True,
            use_container_width=True
        )
else:
    st.warning(
        "No top-three topics were found for the selected country and period."
    )


# ============================================================
# 1. RECOMMENDED CHANNELS
# ============================================================

st.subheader("1. Recommended Channels")

st.caption(
    "Based on matched post engagement distributions, "
    "data sufficiency and statistical evidence — "
    "not a weighted engagement score."
)

primary = evidence.get("primary_channel")
secondary = evidence.get("secondary_channel")

a, b = st.columns(2, gap="medium")

with a:
    _card("Primary channel", primary)

with b:
    _card("Secondary channel", secondary, secondary=True)

status = evidence.get("analysis_status", "Inconclusive")

st.markdown(f"**Analysis outcome:** {status}")
st.write(evidence.get("explanation", "No explanation available."))

if status in (
    "Inconclusive",
    "Insufficient comparison",
    "Insufficient data"
):
    st.info(
        "The available evidence does not justify naming a clear winning channel. "
        "Comparable candidates are shown below where available."
    )


# ============================================================
# 2. WHY THESE CHANNELS?
# ============================================================

st.subheader("2. Why these channels?")

st.caption(
    "An explanation of the recommended channels, "
    "based on relevant audience engagement and supporting evidence."
)

if summary.empty:
    st.info(
        "There are no qualifying posts for the selected monthly topics. "
        "Try a wider month range."
    )

else:
    eligible = summary.loc[summary["eligible"]].copy()

    if eligible.empty:
        st.info(
            "There is not yet enough topic-matched content on any "
            "single platform to make a reliable channel recommendation."
        )

    else:
        recommended = summary.loc[
            summary["recommendation"].isin(["Primary", "Secondary"])
        ]

        for _, item in recommended.iterrows():
            platform = str(item["platform"])
            role = str(item["recommendation"])

            others = eligible.loc[
                eligible["platform"] != platform
            ]

            reasons = [
                f"{platform} has sufficient relevant content from "
                f"{country} during the selected period, "
                "providing a useful basis for comparison."
            ]

            if not others.empty:
                typical = float(item["median_post_engagement"])
                other_median = float(
                    others["median_post_engagement"].median()
                )

                if typical > other_median:
                    reasons.append(
                        "Its typical posts attract stronger engagement "
                        "than the typical performance of other eligible channels."
                    )
                else:
                    reasons.append(
                        "Its audience engagement is competitive when "
                        "compared with other eligible channels."
                    )

            if float(item["iqr"]) <= float(eligible["iqr"].median()):
                reasons.append(
                    "Engagement is relatively consistent across its posts."
                )
            else:
                reasons.append(
                    "Some posts achieve substantially stronger engagement "
                    "than others, suggesting potential for standout content."
                )

            if role == "Primary":
                reasons.append(
                    "The comparative analysis provides evidence supporting "
                    "it as the leading channel; the decision is not based "
                    "on total engagement alone."
                )
            else:
                reasons.append(
                    "It offers an additional channel with meaningful "
                    "engagement strengths, rather than being chosen "
                    "simply as the runner-up."
                )

            interactions = {
                "discussion": float(item.get("replies", 0)),
                "sharing": (
                    float(item.get("reposts", 0))
                    + float(item.get("quotes", 0))
                ),
            }

            if (
                interactions["discussion"] > interactions["sharing"]
                and interactions["discussion"] > 0
            ):
                reasons.append(
                    "Its audience interactions suggest opportunities "
                    "for discussion and conversation."
                )
            elif interactions["sharing"] > 0:
                reasons.append(
                    "Sharing and reposting activity suggests "
                    "opportunities to amplify messages."
                )

            with st.container(border=True):
                st.markdown(f"**{role} channel: {platform}**")

                for reason in reasons:
                    st.markdown(f"- {reason}")

        if not primary:
            st.info(
                "The current evidence does not clearly distinguish "
                "a leading platform. This is an inconclusive comparison, "
                "not a recommendation to avoid these channels."
            )

            candidates = ", ".join(
                eligible["platform"].astype(str)
            )

            st.write(
                f"Channels with sufficient relevant posts: {candidates}."
            )

        elif not secondary:
            st.write(
                "**Why no secondary channel?** "
                "The available comparisons do not establish another "
                "channel with sufficiently competitive evidence "
                "to justify a separate recommendation."
            )


# ============================================================
# DATA COVERAGE
# ============================================================

with st.expander("Data coverage and recommendation limitations"):

    st.write(
        "Environmental posts in the selected country and period: "
        f"{evidence.get('environmental_posts_in_country_period', 0):,}."
    )

    st.write(
        "Posts matching the monthly top-three news topics: "
        f"{evidence.get('matched_post_count', 0):,}."
    )

    st.write(
        "The analysis uses unique original posts, not individual "
        "comments, for the 30-post eligibility requirement. "
        "Posts about other environmental topics remain available "
        "in Engagement Metrics Overview but are not included here."
    )

    if not summary.empty:
        for _, item in summary.iterrows():
            st.write(
                f"{item['platform']}: "
                f"{int(item['post_count']):,} matching posts "
                f"({'eligible' if item['eligible'] else 'below the 30-post minimum'})."
            )


# ============================================================
# 3. HOW TO COMMUNICATE?
# ============================================================

st.subheader("3. How to communicate?")

st.caption(
    "AI-generated messaging guidance based on contrasting "
    "high- and low-engagement posts. "
    "This guidance is separate from the statistical channel selection."
)

try:
    guidance = _load_guidance()
except CommunicationChannelsDataError as exc:
    guidance = pd.DataFrame()
    st.warning(
        f"Saved messaging guidance could not be loaded: {exc}"
    )

names = (
    set(topics["topic_name"].dropna().astype(str))
    if not topics.empty
    else set()
)

relevant = _guidance_rows(
    guidance,
    country,
    start,
    end,
    names
)

if relevant.empty:
    st.info(
        "No saved topic-based messaging guidance matches the selected "
        "country's top-three topics and months. "
        "The topic_based_analysis.py batch job must generate and store "
        "those results first. Its current upsert may overwrite "
        "earlier months for the same country and topic."
    )

else:
    options = [
        f"{r['_month']:%b %Y} · {r['topic_name']}"
        for _, r in relevant.iterrows()
    ]

    selected = st.selectbox(
        "Topic guidance",
        options,
        key="cf_guidance_topic"
    )

    record = relevant.iloc[options.index(selected)]

    st.markdown(
        f"**{record['topic_name']}** · "
        f"{record['_month']:%B %Y}"
    )

    st.caption(
        "Messaging guidance targets short-form vertical videos "
        "(TikTok / Instagram Reels), even when the recommended "
        "engagement channel is different. "
        "The generator can use regional posts when fewer than "
        "20 country posts exist; the saved table does not record "
        "which scope was used."
    )

    _show_guidance(record)


# ============================================================
# METHODOLOGY
# ============================================================

with st.expander("About the methodology"):
    st.write(
        "WHERE: For each month, select that country's top three "
        "news topics, match post keywords, deduplicate posts, "
        "require at least 30 per platform, then compare "
        "engagement distributions using Kruskal–Wallis, "
        "Dunn–Holm and Cliff's delta. "
        "HOW: Read separately generated Gemini messaging advice "
        "saved in Supabase. No AI generation runs on this page."
    )

