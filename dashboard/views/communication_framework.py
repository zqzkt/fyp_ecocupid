
"""EcoCupid Communication Framework: WHERE to communicate and HOW to communicate.

Uses channel_recommendations.py for statistical decisions and reads the saved
results produced by topic_based_analysis.py from Supabase. Does not call Gemini.
"""
from __future__ import annotations

import sys
import ast
import json
import html
import re
from urllib.parse import urlsplit, parse_qs
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

.ec-report-header {background:#edf4e9;border:1px solid #d5e4d2;border-radius:14px;padding:22px 25px;margin:12px 0 18px}
.ec-report-kicker {font-size:.76rem;font-weight:750;letter-spacing:.11em;color:#597360;text-transform:uppercase}
.ec-report-title {font-size:1.55rem;font-weight:800;color:#214b35;margin:7px 0}
.ec-report-meta {font-size:.92rem;color:#53685a}
.ec-report-section {font-size:1.1rem;font-weight:750;color:#214b35;margin:24px 0 10px}
.ec-report-key {background:#e8f3e7;border-left:5px solid #2a784f;padding:17px 20px;border-radius:10px;margin:10px 0}
.ec-report-key-label {color:#56725c;font-size:.78rem;font-weight:750;letter-spacing:.07em}
.ec-report-key-text {font-size:1.13rem;font-weight:700;color:#214b35;margin-top:7px;line-height:1.5}
.ec-report-step {display:flex;align-items:flex-start;gap:18px;padding:13px 6px;border-bottom:1px solid #d7dfd0}
.ec-report-step:last-child {border-bottom:none}
.ec-report-step-title {flex:0 0 100px;box-sizing:border-box;text-align:center;background:#e3f0e3;border-radius:10px;padding:13px 8px;font-size:1rem;font-weight:750;color:#236a47}
.ec-report-step-text {flex:1;font-size:.96rem;color:#38483c;line-height:1.6;padding-top:9px;white-space:pre-wrap}
.ec-report-warning {background:#f5f2e8;border-left:4px solid #a3a278;padding:13px 17px;border-radius:8px}
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


# ============================================================
# EXAMPLE SOURCE POST HELPERS
# ============================================================

def _post_url_key(value) -> str:
    if not isinstance(value, str) or not value.strip():
        return ""

    try:
        parts = urlsplit(value.strip())

        host = (parts.hostname or "").lower()
        host = host.removeprefix("www.")
        host = host.removeprefix("m.")

        path = parts.path.rstrip("/")
        query = parse_qs(parts.query)

        if host in ("youtube.com", "music.youtube.com"):
            if path == "/watch":
                video_id = query.get("v", [""])[0]
                return f"youtube:{video_id}" if video_id else ""

            if path.startswith(("/shorts/", "/live/", "/embed/")):
                video_id = path.split("/")[2]
                return f"youtube:{video_id}"

        if host == "youtu.be":
            video_id = path.strip("/")
            return f"youtube:{video_id}" if video_id else ""

        if host in ("x.com", "twitter.com"):
            segments = path.split("/")
            if "status" in segments:
                idx = segments.index("status")
                if idx + 1 < len(segments):
                    return f"x:{segments[idx + 1]}"

        if host == "instagram.com":
            segments = path.strip("/").split("/")
            if len(segments) >= 2 and segments[0] in ("p", "reel", "tv"):
                return f"instagram:{segments[1]}"

        if host.endswith("tiktok.com"):
            if "/video/" in path:
                return f"tiktok:{path.split('/video/')[-1]}"

        return f"{host}{path}"

    except (ValueError, IndexError):
        return ""


def _example_links(value) -> list[str]:
    if isinstance(value, (list, tuple)):
        items = value
    elif isinstance(value, str) and value.strip():
        try:
            items = json.loads(value)
        except (ValueError, TypeError):
            try:
                items = ast.literal_eval(value)
            except (ValueError, SyntaxError):
                items = []
    else:
        items = []
    return [str(x).strip() for x in items
            if isinstance(x, str) and x.strip().startswith(("https://", "http://"))]


def _local_topic_post_count(record: pd.Series, selected_country: str,
                            posts: pd.DataFrame, monthly_topics: pd.DataFrame) -> int | None:
    """Reconstruct the HOW generator's local keyword/date filter (MIN_POSTS=20).

    This is a current-data estimate, not saved historical batch provenance.
    """
    required_posts = {"inferred_country", "posted_at", "matched_keywords", "is_environmental"}
    required_topics = {"country", "month", "topic_name", "monthly_keywords"}
    if not required_posts.issubset(posts.columns) or not required_topics.issubset(monthly_topics.columns):
        return None
    month = pd.Timestamp(record["_month"]).to_period("M")
    topic_rows = monthly_topics.loc[
        monthly_topics["country"].map(normalize_country).eq(selected_country)
        & pd.to_datetime(monthly_topics["month"], errors="coerce", utc=True)
            .dt.tz_localize(None).dt.to_period("M").eq(month)
        & monthly_topics["topic_name"].astype(str).str.casefold()
            .eq(str(record["topic_name"]).casefold())
    ]
    if topic_rows.empty:
        return None
    # The batch generator splits monthly_keywords on commas and uses
    # Supabase's array-overlap operation against matched_keywords.
    keywords = set()
    for value in topic_rows["monthly_keywords"].dropna():
        if isinstance(value, str):
            keywords.update(k.strip() for k in value.split(",") if k.strip())
        elif isinstance(value, (list, tuple)):
            keywords.update(str(k).strip() for k in value if str(k).strip())
    if not keywords:
        return None
    dates = pd.to_datetime(posts["posted_at"], errors="coerce", utc=True)
    within_month = dates.dt.tz_localize(None).dt.to_period("M").eq(month)
    local = posts["inferred_country"].map(normalize_country).eq(selected_country)
    environmental = posts["is_environmental"].astype(str).str.lower().isin(("true", "1", "t"))

    def has_keyword(value) -> bool:
        if isinstance(value, (list, tuple, set)):
            return bool(set(map(str, value)) & keywords)
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
                return isinstance(parsed, list) and bool(set(map(str, parsed)) & keywords)
            except (ValueError, TypeError):
                return False
        return False

    matched = posts["matched_keywords"].map(has_keyword)
    return int((within_month & local & environmental & matched).sum())


def _example_country_map(posts: pd.DataFrame) -> dict[str, str | None]:
    if posts.empty or not {"post_url", "inferred_country"}.issubset(posts.columns):
        return {}
    result = {}
    for url, country in zip(posts["post_url"], posts["inferred_country"]):
        key = _post_url_key(url)
        if key:
            normalized = normalize_country(country)
            if key not in result or result[key] is None:
                result[key] = normalized if normalized in COUNTRIES else None
    return result


# ============================================================
# DISPLAY HOW GUIDANCE
# ============================================================

def _report_items(value) -> list[str]:
    """Render Supabase JSON arrays as individual readable suggestions."""
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        values = value
    elif isinstance(value, str):
        raw = value.strip()
        if not raw or raw.casefold() in ("none", "null", "nan"):
            return []
        if raw.startswith("["):
            try:
                values = json.loads(raw)
            except (ValueError, TypeError):
                try:
                    values = ast.literal_eval(raw)
                except (ValueError, SyntaxError):
                    values = [raw]
        else:
            values = [raw]
    else:
        values = [value]
    if not isinstance(values, (list, tuple)):
        values = [values]
    return [str(item).strip() for item in values if str(item).strip()]


def _report_field(record: pd.Series, key: str, label: str) -> None:
    items = _report_items(record.get(key))
    if not items:
        return
    st.markdown(f"**{label}**")
    if len(items) == 1:
        st.write(items[0])
    else:
        for item in items:
            st.markdown(f"- {item}")



# Split only when a comma or semicolon introduces the NEXT timed stage.
# A regular comma inside a description is left untouched.
_STORY_BOUNDARY = re.compile(
    r"\s*[;,]\s*(?=(?:\d{1,3}\s*[-–—]\s*\d{1,3}\s*(?:s|sec|seconds)?\s*:))",
    re.IGNORECASE,
)
_STORY_TIME = re.compile(
    r"^\s*(\d{1,3}\s*[-–—]\s*\d{1,3}\s*(?:s|sec|seconds)?)\s*:\s*(.*)$",
    re.IGNORECASE | re.DOTALL,
)


def _story_steps(value) -> list[str]:
    """Split semicolon stages and comma-separated timed stages safely."""
    stages = []
    for item in _report_items(value):
        # First split at semicolons; then split comma-separated timed stages.
        for section in item.split(";"):
            for stage in _STORY_BOUNDARY.split(section):
                if stage.strip():
                    stages.append(stage.strip())
    return stages


def _story_stage_parts(step: str, index: int) -> tuple[str, str]:
    """Return (time label, description), preserving original Gemini wording."""
    match = _STORY_TIME.match(step)
    if match:
        label = re.sub(r"\s*[-–—]\s*", "–", match.group(1).strip())
        return label, match.group(2).strip()
    return f"Stage {index}", step.strip()


def _show_guidance(record: pd.Series, selected_country: str,
                   posts: pd.DataFrame, monthly_topics: pd.DataFrame) -> None:
    """Five-section report; WHERE and Why These Channels remain unchanged."""
    topic = html.escape(str(record.get("topic_name") or "Environmental topic"))
    country = html.escape(selected_country)
    month = pd.Timestamp(record["_month"]).strftime("%B %Y")

    st.html(
        '<div class="ec-report-header">'
        '<div class="ec-report-kicker">EcoCupid / Communication Framework</div>'
        '<div class="ec-report-title">Messaging Strategy Report</div>'
        f'<div class="ec-report-meta">{country} · {html.escape(month)} · {topic}</div>'
        '</div>'
    )

    # 01: The core message and desired delivery style.
    st.markdown('<div class="ec-report-section">01 / Communication Objective</div>',
                unsafe_allow_html=True)
    key_message = _safe(record.get("key_message"), "")
    if key_message:
        st.html(
            '<div class="ec-report-key">'
            '<div class="ec-report-key-label">KEY MESSAGE</div>'
            f'<div class="ec-report-key-text">{html.escape(key_message)}</div>'
            '</div>'
        )
    _report_field(record, "tone_and_emotion", "Recommended tone and emotion")

    st.divider()
    # 02: Production guidance, followed by a step-by-step storyline.
    st.markdown('<div class="ec-report-section">02 / Content & Storytelling Strategy</div>',
                unsafe_allow_html=True)
    left, right = st.columns(2, gap="medium")
    with left:
        with st.container(border=True):
            _report_field(record, "content_type", "Content format")
    with right:
        with st.container(border=True):
            _report_field(record, "narrative_method", "Narrative approach")

    
    steps = _story_steps(record.get("story_structure"))

    if steps:
        st.markdown("**Suggested video structure**")

        for i, step in enumerate(steps, 1):

            timestamp, description = _story_stage_parts(step, i)

            st.html(
                '<div class="ec-report-step">'
                f'<div class="ec-report-step-title">{html.escape(timestamp.strip())}</div>'
                f'<div class="ec-report-step-text">{html.escape(description.strip())}</div>'
                '</div>'
            )


    st.divider()
    # 03: Copyable examples and instructions for posting.
    st.markdown('<div class="ec-report-section">03 / Ready-to-Use Messaging</div>',
                unsafe_allow_html=True)
    hooks = _report_items(record.get("hooks"))
    if hooks:
        st.markdown("**Suggested opening hooks**")
        for i, hook in enumerate(hooks, 1):
            st.markdown(f"**{i}.** {hook}")
    _report_field(record, "call_to_action", "Call to action")
    _report_field(record, "captions", "Caption guidance")

    st.divider()
    # 04: Practical do's and don'ts.
    st.markdown('<div class="ec-report-section">04 / Actionable Recommendations</div>',
                unsafe_allow_html=True)
    recommendations = _report_items(record.get("recommendations"))
    if recommendations:
        for item in recommendations:
            st.markdown(f"- ✅ {item}")
    avoid = _report_items(record.get("what_not_to_do"))
    if avoid:
        with st.container(border=True):
            st.markdown("**What to avoid**")
            for item in avoid:
                st.write(item)

    st.divider()
    # 05: Existing country-attributed example links and conditional disclaimer.
    st.markdown('<div class="ec-report-section">05 / Supporting Source Posts</div>',
                unsafe_allow_html=True)
    st.caption("Posts that informed the saved messaging analysis. Country labels are based on the collected data.")
    links = []
    for field in ("top_post_links", "bottom_post_links"):
        links.extend(_example_links(record.get(field)))
    links = list(dict.fromkeys(links))[:10]

    if links:
        countries_by_url = _example_country_map(posts)
        local_count = _local_topic_post_count(record, selected_country, posts, monthly_topics)
        with st.expander(f"Example source posts ({len(links)})", expanded=False):
            if local_count is not None and local_count < 20:
                st.info(
                    f"**Limited local data:** Only {local_count} relevant posts "
                    f"were found for this topic in {selected_country} during "
                    f"{record['_month']:%B %Y} (minimum: 20). "
                    "The messaging analysis may therefore use relevant posts "
                    "from other ASEAN countries. Regional examples may not "
                    "fully reflect local audience preferences."
                )
            for i, link in enumerate(links, 1):
                source_country = countries_by_url.get(_post_url_key(link))
                if source_country is None:
                    label = "Country unknown"
                elif source_country == selected_country:
                    label = "Local example"
                else:
                    label = "Regional example"
                st.markdown(f"**{i}. {label}**")
                st.markdown(f"[View source post]({link})")
    else:
        st.caption("No supporting source links were saved for this topic.")


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
    "Based on environmental post engagement distributions, "
    "data sufficiency and statistical evidence. "
    "Where those rules cannot identify a Primary Channel, a "
    "posting-activity fallback may be shown."
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

if evidence.get("used_activity_fallback", False):
    st.warning(
        "**Limited-data recommendation:** This Primary channel did not pass the "
        "normal recommendation rules. It is suggested only because it has the "
        "most observed environmental posts in the selected country and period. "
        "Posting frequency does not demonstrate superior engagement."
    )

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
        "No environmental original posts were found for the selected "
        "country and period."
    )
else:
    fallback = bool(evidence.get("used_activity_fallback", False))

    recommended = summary.loc[
        summary["recommendation"].isin(
            ["Primary", "Secondary", "Primary (activity fallback)"]
        )
    ]

    if fallback:
        chosen = recommended.loc[
            recommended["recommendation"] == "Primary (activity fallback)"
        ]

        if not chosen.empty:
            item = chosen.iloc[0]

            st.markdown(
                f"**{str(item['platform']).title()} — provisional Primary channel:** "
                f"This platform has the highest observed posting activity for "
                f"environmental content in {country} during the selected period "
                f"({int(item['post_count']):,} original posts). "
                "The available data did not satisfy the normal channel-selection "
                "rules, so this is a practical starting point rather than "
                "evidence of stronger audience engagement."
            )

            st.write(
                "**Why no Secondary?** There is not enough supporting evidence "
                "to recommend an additional channel confidently."
            )

    elif recommended.empty:
        st.info(
            "The current evidence does not clearly distinguish a Primary channel. "
            "No platform is being presented as an engagement leader."
        )

    else:
        eligible = summary.loc[summary["eligible"]].copy()

        for _, item in recommended.iterrows():
            platform = str(item["platform"])
            role = str(item["recommendation"])

            others = eligible.loc[
                eligible["platform"] != platform
            ]

            reasons = [
                f"{platform.title()} has at least 30 original environmental posts "
                f"from {country} in the selected period, allowing its audience "
                "engagement to be compared with other eligible channels."
            ]

            if not others.empty:
                typical = float(item["median_post_engagement"])
                other_median = float(
                    others["median_post_engagement"].median()
                )

                if typical > other_median:
                    reasons.append(
                        "Its typical posts show comparatively stronger engagement."
                    )
                else:
                    reasons.append(
                        "Its engagement remains competitive across the observed posts."
                    )

            if float(item["iqr"]) <= float(eligible["iqr"].median()):
                reasons.append(
                    "Engagement is relatively consistent across posts."
                )
            else:
                reasons.append(
                    "Performance varies between posts, with potential "
                    "for standout content."
                )

            if role == "Primary":
                reasons.append(
                    "It has the strongest overall supporting evidence across the "
                    "engagement distribution; this is not based on posting volume alone."
                )
            else:
                reasons.append(
                    "It offers a competitive alternative or complementary channel."
                )

            discussion = float(item.get("replies", 0))
            sharing = (
                float(item.get("reposts", 0))
                + float(item.get("quotes", 0))
            )

            if discussion > sharing and discussion > 0:
                reasons.append(
                    "Audience replies suggest opportunities for discussion."
                )
            elif sharing > 0:
                reasons.append(
                    "Sharing activity suggests opportunities for message amplification."
                )

            with st.container(border=True):
                st.markdown(
                    f"**{role} channel: {platform.title()}**"
                )

                for reason in reasons:
                    st.write(reason)

        if primary and not secondary:
            st.write(
                "**Why no Secondary?** No other channel had sufficiently "
                "competitive supporting evidence to justify a separate recommendation."
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
        "Original environmental posts used for channel analysis: "
        f"{evidence.get('environmental_posts_in_country_period', 0):,}."
    )

    st.write(
        "WHERE uses all environmental original posts from the selected country "
        "and period, not only the top-three news topics. The 30-post minimum "
        "applies to the normal recommendation rules. Linked comment reactions "
        "can contribute to engagement, but comments do not count as original posts. "
        "The top-three monthly topics are used separately for HOW guidance."
    )

    if not summary.empty:
        for _, item in summary.iterrows():
            st.write(
                f"{item['platform']}: "
                f"{int(item['post_count']):,} environmental original posts "
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

    st.caption(
        "Messaging guidance targets short-form vertical videos "
        "(TikTok / Instagram Reels), even when the recommended "
        "engagement channel is different. "
        "The generator can use regional posts when fewer than "
        "20 matching country posts exist. Example source countries "
        "and local-data sufficiency are checked below."
    )

    _show_guidance(
        record,
        selected_country=country,
        posts=data["posts"],
        monthly_topics=data["monthly_topics"]
    )

# ============================================================
# METHODOLOGY
# ============================================================

with st.expander("About the methodology"):
    st.write(
        "WHERE: Use all environmental original posts in the selected country "
        "and period, deduplicate posts, and require at least 30 per platform "
        "for the normal recommendation. Compare engagement distributions "
        "using Kruskal–Wallis, Dunn–Holm and Cliff's delta as supporting evidence. "
        "If no Primary is identified, the platform with the most observed "
        "original environmental posts can be shown as a limited-data fallback "
        "(provided there is no tie). This is not an engagement-performance claim. "
        "HOW: Read separately generated Gemini messaging advice "
        "saved in Supabase."
    )

