
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
from style import CARD_BG, HAIRLINE, series_color, text_color, theme

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
.ec-channel {min-height:150px}
.ec-chips {display:flex;flex-wrap:wrap;gap:6px;margin:12px 0 0 !important;padding:0 !important;list-style:none}
.ec-chips li {background:rgba(255,255,255,.7);border:1px solid #b7d3bc;color:#214b35;border-radius:999px;
  padding:3px 11px;font-size:.82rem;font-weight:600;margin:0 !important}
.ec-outcome {display:inline-block;font-size:.82rem;font-weight:700;color:#214b35;background:#e8f3e7;
  border:1px solid #d5e4d2;border-radius:999px;padding:3px 12px;margin:10px 0 4px}
.ec-tone {font-size:.95rem;color:#38483c;margin:4px 0 10px}
</style>""", unsafe_allow_html=True)

# The styles above are tuned for light mode; swap to the dark theme's surfaces
# and light text in dark mode so cards and the report stay readable.
if theme() == "dark":
    _text, _brand = text_color(), series_color()
    _muted, _line = "rgba(240,237,230,.72)", HAIRLINE["dark"]
    st.markdown(f"""<style>
.ec-channel, .ec-channel.secondary, .ec-channel.neutral, .ec-report-header, .ec-report-key,
.ec-report-step-title, .ec-outcome {{background:{CARD_BG['dark']};border-color:{_line}}}
.ec-channel, .ec-report-key {{border-left-color:{_brand}}}
.ec-channel.secondary {{border-left-color:#5c8e48}}
.ec-channel.neutral {{border-left-color:#8a8a86}}
.ec-name, .ec-report-title, .ec-report-key-text, .ec-report-step-text, .ec-outcome, .ec-tone {{color:{_text}}}
.ec-role, .ec-report-kicker, .ec-report-meta, .ec-report-key-label {{color:{_muted}}}
.ec-report-step-title {{color:{_brand}}}
.ec-report-step {{border-bottom-color:{_line}}}
.ec-chips li {{background:rgba(172,209,71,.12);border-color:rgba(172,209,71,.35);color:{_text}}}
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


def _card(role: str, name: str | None, secondary=False, chips: list[str] | None = None) -> None:
    css = "secondary" if secondary else ("neutral" if not name else "")
    shown = name or ("Not recommended" if secondary else "No clear primary")
    chip_html = "".join(f"<li>{html.escape(c)}</li>" for c in (chips or []))

    st.html(
        f'<div class="ec-channel {css}">'
        f'<div class="ec-role">{html.escape(role)}</div>'
        f'<div class="ec-name">{html.escape(shown.title() if name else shown)}</div>'
        + (f'<ul class="ec-chips">{chip_html}</ul>' if chip_html else "")
        + '</div>'
    )


def _channel_reasons(item: pd.Series, eligible: pd.DataFrame) -> list[str]:
    """Short reason tags for a recommended channel (same rules as before, fewer words)."""
    reasons = ["30+ local posts"]
    others = eligible.loc[eligible["platform"] != item["platform"]]
    if not others.empty:
        stronger = float(item["median_post_engagement"]) > float(others["median_post_engagement"].median())
        reasons.append("Stronger typical engagement" if stronger else "Competitive engagement")
    if not eligible.empty:
        consistent = float(item["iqr"]) <= float(eligible["iqr"].median())
        reasons.append("Consistent results" if consistent else "Room for standout posts")
    discussion = float(item.get("replies", 0))
    sharing = float(item.get("reposts", 0)) + float(item.get("quotes", 0))
    if discussion > sharing and discussion > 0:
        reasons.append("Sparks discussion")
    elif sharing > 0:
        reasons.append("Gets shared")
    return reasons


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
    """Messaging report: key message up front, details split into tabs."""
    topic = html.escape(str(record.get("topic_name") or "Environmental topic"))
    country = html.escape(selected_country)
    month = pd.Timestamp(record["_month"]).strftime("%B %Y")

    st.html(
        '<div class="ec-report-header">'
        '<div class="ec-report-kicker">Messaging Strategy</div>'
        f'<div class="ec-report-title">{topic}</div>'
        f'<div class="ec-report-meta">{country} · {html.escape(month)}</div>'
        '</div>'
    )

    key_message = _safe(record.get("key_message"), "")
    if key_message:
        st.html(
            '<div class="ec-report-key">'
            '<div class="ec-report-key-label">KEY MESSAGE</div>'
            f'<div class="ec-report-key-text">{html.escape(key_message)}</div>'
            '</div>'
        )
    tone = _report_items(record.get("tone_and_emotion"))
    if tone:
        st.html(f'<div class="ec-tone"><b>Tone:</b> {html.escape(" · ".join(tone))}</div>')

    content_tab, copy_tab, dos_tab, sources_tab = st.tabs(
        ["🎬 Content & story", "✍️ Hooks & captions", "✅ Do's & don'ts", "🔗 Source posts"]
    )

    with content_tab:
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

    with copy_tab:
        hooks = _report_items(record.get("hooks"))
        if hooks:
            st.markdown("**Opening hooks**")
            for i, hook in enumerate(hooks, 1):
                st.markdown(f"**{i}.** {hook}")
        _report_field(record, "call_to_action", "Call to action")
        _report_field(record, "captions", "Caption guidance")

    with dos_tab:
        do_col, dont_col = st.columns(2, gap="medium")
        with do_col:
            with st.container(border=True):
                st.markdown("**Do**")
                for item in _report_items(record.get("recommendations")) or ["Not available"]:
                    st.markdown(f"✅ {item}")
        with dont_col:
            with st.container(border=True):
                st.markdown("**Avoid**")
                for item in _report_items(record.get("what_not_to_do")) or ["Not available"]:
                    st.markdown(f"❌ {item}")

    with sources_tab:
        links = []
        for field in ("top_post_links", "bottom_post_links"):
            links.extend(_example_links(record.get(field)))
        links = list(dict.fromkeys(links))[:10]

        if not links:
            st.caption("No supporting source links were saved for this topic.")
            return

        st.caption("Posts that informed this guidance. Country labels come from the collected data.")
        local_count = _local_topic_post_count(record, selected_country, posts, monthly_topics)
        if local_count is not None and local_count < 20:
            st.info(
                f"**Limited local data:** only {local_count} relevant posts from "
                f"{selected_country} in {record['_month']:%B %Y} (minimum 20), so this "
                "guidance may draw on posts from other ASEAN countries."
            )
        countries_by_url = _example_country_map(posts)
        lines = []
        for i, link in enumerate(links, 1):
            source_country = countries_by_url.get(_post_url_key(link))
            if source_country is None:
                label = "Country unknown"
            elif source_country == selected_country:
                label = "Local example"
            else:
                label = "Regional example"
            lines.append(f"{i}. [{label}]({link})")
        st.markdown("\n".join(lines))


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
# 1. WHERE TO COMMUNICATE
# ============================================================

st.subheader("1. Where to communicate")
st.caption("Chosen by comparing engagement on local environmental posts. "
           "A platform needs 30+ posts to qualify.")

primary = evidence.get("primary_channel")
secondary = evidence.get("secondary_channel")
status = evidence.get("analysis_status", "Inconclusive")
fallback = bool(evidence.get("used_activity_fallback", False))

# Short reason tags per role, using the same rules as the old paragraphs.
reasons: dict[str, list[str]] = {}
if not summary.empty:
    eligible = summary.loc[summary["eligible"]].copy()
    for _, item in summary.iterrows():
        rec = str(item["recommendation"])
        if rec in ("Primary", "Secondary"):
            reasons[rec] = _channel_reasons(item, eligible)
        elif rec == "Primary (activity fallback)":
            reasons["Primary"] = [f"Most posts ({int(item['post_count']):,})", "Limited data"]

# Matches main's "Why no Secondary?" wording: the activity fallback only ever
# assigns a Primary channel, otherwise no other channel had enough evidence.
if reasons.get("Secondary"):
    secondary_chips = reasons["Secondary"]
elif primary and fallback:
    secondary_chips = ["Fallback assigns a primary only"]
elif primary:
    secondary_chips = ["Not enough evidence for a second channel"]
else:
    secondary_chips = []

a, b = st.columns(2, gap="medium")
with a:
    _card("Primary channel", primary, chips=reasons.get("Primary", []))
with b:
    _card("Secondary channel", secondary, secondary=True, chips=secondary_chips)

st.html(f'<span class="ec-outcome">Outcome: {html.escape(str(status))}</span>')

if summary.empty:
    st.info("No environmental original posts were found for this country and period.")
elif fallback:
    st.warning(
        "**Limited data:** the primary channel is suggested because it has the most "
        "environmental posts, not because it has shown stronger engagement."
    )
elif status in ("Inconclusive", "Insufficient comparison", "Insufficient data"):
    st.info("**No clear winner:** the evidence doesn't separate the channels enough to name one.")

with st.expander("How this was decided"):
    st.write(evidence.get("explanation", "No explanation available."))
    st.markdown(
        "**Environmental original posts analysed:** "
        f"{evidence.get('environmental_posts_in_country_period', 0):,}"
    )
    if not summary.empty:
        coverage = summary[["platform", "post_count", "eligible"]].copy()
        coverage["platform"] = coverage["platform"].astype(str).str.title()
        coverage["eligible"] = coverage["eligible"].map({True: "Yes", False: "No (under 30)"})
        st.dataframe(
            coverage.rename(columns={
                "platform": "Platform",
                "post_count": "Original posts",
                "eligible": "Qualifies",
            }),
            hide_index=True,
            use_container_width=True,
        )
    st.caption(
        "Uses all environmental original posts from the selected country and period, "
        "not only the top-three news topics. Comment reactions count towards engagement, "
        "but comments are not counted as posts."
    )


# ============================================================
# 2. HOW TO COMMUNICATE
# ============================================================

st.subheader("2. How to communicate")
st.caption("AI-generated guidance for short-form vertical video (TikTok / Instagram Reels), "
           "based on what separated high- and low-engagement posts.")

try:
    guidance = _load_guidance()
except CommunicationChannelsDataError as exc:
    guidance = pd.DataFrame()
    st.warning(f"Saved messaging guidance could not be loaded: {exc}")

names = (
    set(topics["topic_name"].dropna().astype(str))
    if not topics.empty
    else set()
)

relevant = _guidance_rows(guidance, country, start, end, names)

if relevant.empty:
    st.info(
        "No saved messaging guidance matches this country's top topics for the "
        "selected months. Run `topic_based_analysis.py` to generate it "
        "(re-running may overwrite earlier months for the same topic)."
    )
else:
    options = [
        f"{r['_month']:%b %Y} · {r['topic_name']}"
        for _, r in relevant.iterrows()
    ]
    selected = st.selectbox("Topic", options, key="cf_guidance_topic")
    record = relevant.iloc[options.index(selected)]

    _show_guidance(
        record,
        selected_country=country,
        posts=data["posts"],
        monthly_topics=data["monthly_topics"],
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

