"""EcoCupid country-level channel recommendation analysis.

Requires: pandas, numpy, scipy, requests, streamlit, python-dotenv.
The page should call recommend_channels(data, country, selected_months).
No weighted recommendation score is used.
"""
from __future__ import annotations

import ast
import json
import os
import re
from typing import Any

import numpy as np
import pandas as pd
import requests
import streamlit as st
from dotenv import load_dotenv
from scipy.stats import kruskal, norm, rankdata

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv(os.path.join(REPO_ROOT, ".env"))
PAGE_SIZE = 1000
REQUEST_TIMEOUT = 60
MIN_POSTS = 30
ALPHA = 0.05
# Cliff's delta: negligible < .147, small < .33, moderate < .474, large >= .474
MEANINGFUL_DELTA = 0.33  # at least moderate, used for conservative recommendations
COUNTRY_ALIASES = {
    "BN": "Brunei", "ID": "Indonesia", "MY": "Malaysia",
    "PH": "Philippines", "SG": "Singapore", "TH": "Thailand",
    **{x: x for x in ["Brunei", "Indonesia", "Malaysia",
                      "Philippines", "Singapore", "Thailand"]},
}


class CommunicationChannelsDataError(RuntimeError):
    pass


def _credentials() -> tuple[str, str]:
    url = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
    key = (os.getenv("SUPABASE_SECRET_KEY") or
           os.getenv("SUPABASE_SERVICE_ROLE_KEY") or
           os.getenv("SUPABASE_KEY") or "").strip()
    if not url or not key:
        raise CommunicationChannelsDataError("Set SUPABASE_URL and a Supabase key in .env.")
    return url, key


def _load_table(table: str, columns: str = "*",
                filters: dict[str, str] | None = None) -> pd.DataFrame:
    url, key = _credentials()
    rows: list[dict[str, Any]] = []
    offset = 0
    while True:
        try:
            response = requests.get(
                f"{url}/rest/v1/{table}",
                params={"select": columns, "limit": PAGE_SIZE, "offset": offset,
                        "order": ("id.asc" if table in ("clean_posts", "clean_comments") else
                                  "month.asc,country.asc,topic_id.asc" if table == "monthly_topic_stats" else
                                  "topic_id.asc" if table == "topic_registry" else
                                  "month.asc,country.asc,topic_name.asc"),
                        **(filters or {})},
                headers={"apikey": key, "Authorization": f"Bearer {key}"},
                timeout=REQUEST_TIMEOUT,
            )
            response.raise_for_status()
            page = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise CommunicationChannelsDataError(f"Could not load {table}: {exc}") from exc
        if not page:
            break
        rows.extend(page)
        if len(page) < PAGE_SIZE:
            break
        offset += len(page)
    return pd.DataFrame(rows)


@st.cache_data(ttl=600, show_spinner="Loading communication framework data...")
def load_framework_data() -> dict[str, pd.DataFrame]:
    """Read the four existing Supabase tables; no schema migration needed."""
    return {
        "posts": _load_table("clean_posts", filters={"is_environmental": "eq.true"}),
        "comments": _load_table("clean_comments"),
        "monthly_topics": _load_table("monthly_topic_stats"),
        "topic_registry": _load_table("topic_registry"),
    }


def normalize_country(value: Any) -> str:
    s = str(value).strip() if pd.notna(value) else ""
    return COUNTRY_ALIASES.get(s.upper(), COUNTRY_ALIASES.get(s.title(), s))


def add_date_columns(frame: pd.DataFrame, source_type: str) -> pd.DataFrame:
    result = frame.copy()
    if result.empty:
        result["_month"] = pd.Series(dtype="datetime64[ns]")
        result["_country"] = pd.Series(dtype=str)
        return result
    date = result.get("posted_at", pd.Series(index=result.index, dtype=object))
    if source_type == "comments":
        parent_date = result.get("parent_posted_at", pd.Series(index=result.index, dtype=object))
        date = parent_date.fillna(date)
    timestamp = pd.to_datetime(date, errors="coerce", utc=True)
    result["_year"] = timestamp.dt.year
    result["_month"] = timestamp.dt.tz_localize(None).dt.to_period("M").dt.to_timestamp()
    result["_country"] = result["inferred_country"].map(normalize_country)
    return result


def _as_list(value: Any) -> list[str]:
    if isinstance(value, (list, tuple, set, np.ndarray)):
        return [str(v).strip() for v in value if str(v).strip()]
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return []
    s = str(value).strip()
    if not s:
        return []
    for parse in (json.loads, ast.literal_eval):
        try:
            result = parse(s)
            if isinstance(result, (list, tuple, set)):
                return [str(v).strip() for v in result if str(v).strip()]
        except (ValueError, SyntaxError, TypeError):
            pass
    return [part.strip() for part in re.split(r"[,;\n]", s) if part.strip()]


def _norm_keyword(s: str) -> str:
    """Conservative exact normalized keyword matching, not fuzzy substring matching."""
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", str(s).casefold())).strip()


def _keywords_for_topic(row: pd.Series, registry: pd.DataFrame) -> set[str]:
    terms = [_norm_keyword(row["topic_name"])]
    terms += [_norm_keyword(x) for x in _as_list(row.get("monthly_keywords"))]
    if not registry.empty and "topic_id" in registry:
        matches = registry.loc[registry["topic_id"] == row["topic_id"]]
        if not matches.empty:
            record = matches.iloc[0]
            terms += [_norm_keyword(record.get("topic_name", ""))]
            terms += [_norm_keyword(x) for x in _as_list(record.get("topic_keywords"))]
    return {term for term in terms if term}


def _month_start(value: Any) -> pd.Timestamp:
    return pd.Timestamp(value).to_period("M").to_timestamp()


def top_topics_by_month(data: dict[str, pd.DataFrame], country: str,
                        selected_months: tuple[Any, Any]) -> pd.DataFrame:
    """Top three by topic_rank in EACH month; return keyword sets per topic."""
    frame = data["monthly_topics"].copy()
    if frame.empty:
        return pd.DataFrame(columns=["month", "country", "topic_id", "topic_name",
                                     "topic_rank", "article_count", "match_terms"])
    frame["month"] = pd.to_datetime(frame["month"], errors="coerce").dt.to_period("M").dt.to_timestamp()
    frame["country"] = frame["country"].map(normalize_country)
    frame["topic_rank"] = pd.to_numeric(frame["topic_rank"], errors="coerce")
    frame["article_count"] = pd.to_numeric(frame["article_count"], errors="coerce").fillna(0)
    start, end = map(_month_start, selected_months)
    frame = frame.loc[
        (frame["country"] == normalize_country(country)) &
        frame["month"].between(start, end) &
        frame["topic_rank"].notna() & (frame["topic_rank"] <= 3)
    ].copy()
    # If ranks tie at #3, use article_count then topic_id for deterministic three.
    frame = (frame.sort_values(["month", "topic_rank", "article_count", "topic_id"],
                               ascending=[True, True, False, True])
                  .groupby("month", group_keys=False).head(3).reset_index(drop=True))
    registry = data["topic_registry"]
    frame["match_terms"] = frame.apply(lambda row: _keywords_for_topic(row, registry), axis=1)
    return frame


def match_monthly_posts(data: dict[str, pd.DataFrame], country: str,
                        selected_months: tuple[Any, Any]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Only posts matching their OWN month's top-three topic keywords, once per source_id."""
    topics = top_topics_by_month(data, country, selected_months)
    posts = add_date_columns(data["posts"], "posts")
    if posts.empty or topics.empty:
        return posts.iloc[0:0].copy(), topics
    start, end = map(_month_start, selected_months)
    posts = posts.loc[(posts["_country"] == normalize_country(country)) &
                      posts["_month"].between(start, end)].copy()
    terms_by_month = {
        month: set().union(*subset["match_terms"].tolist())
        for month, subset in topics.groupby("month")
    }
    def matched(row: pd.Series) -> bool:
        month_terms = terms_by_month.get(row["_month"], set())
        post_terms = {_norm_keyword(k) for k in _as_list(row.get("matched_keywords"))}
        if post_terms & month_terms:
            return True
        # Match whole-word keyword variants, e.g. "air pollution" to "pollution".
        # Avoid substring matching such as "gas" to "Madagascar".
        for a in post_terms:
            a_words = set(a.split())
            if not a_words:
                continue
            for t in month_terms:
                t_words = set(t.split())
                if a_words <= t_words or t_words <= a_words:
                    # Single generic tokens create false matches; only accept a
                    # shared single word if it has at least 5 characters.
                    shared = a_words & t_words
                    if len(shared) > 1 or any(len(w) >= 5 for w in shared):
                        return True
        return False
    posts = posts.loc[posts.apply(matched, axis=1)].copy()
    posts = posts.drop_duplicates(subset=["source_id"], keep="first")
    posts["platform"] = posts["platform"].fillna("").astype(str).str.strip()
    posts = posts.loc[posts["platform"] != ""].copy()
    posts["_engagement"] = pd.to_numeric(posts["total_engagement"], errors="coerce")
    # Missing engagement is unknown, NOT zero. Keep genuine zero observations.
    posts = posts.loc[posts["_engagement"].notna() & (posts["_engagement"] >= 0)].copy()
    return posts, topics

def _cliffs_delta(a: np.ndarray, b: np.ndarray) -> float:
    """(P(a>b) - P(a<b)), efficient even for thousands of posts."""
    sorted_b = np.sort(b)
    less = np.searchsorted(sorted_b, a, side="left").sum()
    greater = (len(b) - np.searchsorted(sorted_b, a, side="right")).sum()
    return float((less - greater) / (len(a) * len(b)))


def _effect_label(delta: float) -> str:
    d = abs(delta)
    return ("Negligible" if d < .147 else "Small" if d < .33
            else "Moderate" if d < .474 else "Large")


def _holm(pvalues: list[float]) -> list[float]:
    """Holm step-down adjusted p values; monotonic in sorted order."""
    n = len(pvalues)
    order = np.argsort(pvalues)
    adjusted = [1.0] * n
    prev = 0.0
    for rank, idx in enumerate(order):
        prev = max(prev, min(1.0, (n - rank) * pvalues[idx]))
        adjusted[idx] = prev
    return adjusted


def _pairwise_dunn(groups: dict[str, np.ndarray]) -> pd.DataFrame:
    """Dunn rank-sum comparisons with pooled ranks, tie correction and Holm adjustment."""
    from itertools import combinations
    names = list(groups)
    sizes = {k: len(groups[k]) for k in names}
    all_values = np.concatenate([groups[k] for k in names])
    ranks = rankdata(all_values, method="average")
    n = len(all_values)
    counts = pd.Series(all_values).value_counts().to_numpy(dtype=float)
    tie_term = np.sum(counts**3 - counts) / (12 * (n - 1)) if n > 1 else 0
    variance = n * (n + 1) / 12 - tie_term
    means = {}
    offset = 0
    for k in names:
        means[k] = ranks[offset:offset + sizes[k]].mean()
        offset += sizes[k]
    rows = []
    for a, b in combinations(names, 2):
        denom = np.sqrt(variance * (1 / sizes[a] + 1 / sizes[b]))
        z = (means[a] - means[b]) / denom if denom > 0 else 0.0
        p = float(2 * norm.sf(abs(z))) if denom > 0 else 1.0
        delta = _cliffs_delta(groups[a], groups[b])
        rows.append({"platform_a": a, "platform_b": b, "dunn_z": z,
                     "p_raw": p, "cliffs_delta": delta,
                     "effect_magnitude": _effect_label(delta)})
    if rows:
        adjusted = _holm([row["p_raw"] for row in rows])
        for row, p in zip(rows, adjusted):
            row["p_holm"] = p
            row["significant"] = p < ALPHA
            row["meaningful"] = p < ALPHA and abs(row["cliffs_delta"]) >= MEANINGFUL_DELTA
            row["direction"] = (row["platform_a"] if row["cliffs_delta"] > 0
                                else row["platform_b"]) if row["meaningful"] else None
    return pd.DataFrame(rows)


def _summary(posts: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for platform, frame in posts.groupby("platform"):
        e = frame["_engagement"].to_numpy(dtype=float)
        q1, median, q3 = np.percentile(e, [25, 50, 75])
        impressions = pd.to_numeric(frame["impression_count"], errors="coerce")
        # Reach metrics only when every selected post has valid exposure.
        reach_available = platform.casefold() in ("youtube", "x") and impressions.notna().all() and (impressions > 0).all()
        exposure = float(impressions.sum()) if reach_available else np.nan
        total = float(e.sum())
        row = {
            "platform": platform, "post_count": len(frame), "eligible": len(frame) >= MIN_POSTS,
            "total_engagement": total, "avg_engagement_per_post": float(np.mean(e)),
            "median_post_engagement": float(median), "q1": float(q1), "q3": float(q3),
            "iqr": float(q3 - q1), "p75": float(q3),
            "total_impressions": exposure,
            "engagement_rate_pct": 100 * total / exposure if reach_available else np.nan,
            "reach_to_engagement_ratio": exposure / total if reach_available and total > 0 else np.nan,
        }
        for metric, column in (("likes", "like_count"), ("replies", "reply_count"),
                               ("reposts", "repost_count"), ("quotes", "quote_count")):
            row[metric] = float(pd.to_numeric(frame[column], errors="coerce").fillna(0).sum())
        rows.append(row)
    return pd.DataFrame(rows).sort_values(["eligible", "median_post_engagement", "post_count"],
                                           ascending=[False, False, False]).reset_index(drop=True) if rows else pd.DataFrame()


def _decide(summary: pd.DataFrame, pairs: pd.DataFrame,
            kw_significant: bool) -> tuple[pd.DataFrame, str, str]:
    """Evidence-informed candidates, not statistical significance as a gate.

    A candidate must have 30 original posts. Use median, lower quartile,
    upper quartile, and breadth of performance; do not rank by volume.
    A clearly statistically/practically inferior channel cannot be primary.
    When descriptive evidence is indistinguishable, report inconclusive.
    """
    summary = summary.copy()
    summary["recommendation"] = "Not eligible (<30 posts)"
    summary["evidence_strength"] = "Insufficient"
    eligible = summary.loc[summary["eligible"]].copy()
    if eligible.empty:
        return summary, "Insufficient data", "No platform has at least 30 original environmental posts."
    if len(eligible) == 1:
        name = eligible.iloc[0]["platform"]
        summary.loc[summary["platform"] == name, ["recommendation", "evidence_strength"]] = [
            "Only eligible candidate", "Limited"]
        return summary, "Insufficient comparison", (
            f"{name} meets the minimum post requirement, but no other platform is eligible for comparison.")

    # A meaningful loss requires BOTH corrected statistical evidence and
    # moderate/large practical effect. Pairwise tests are supporting evidence.
    losses = {name: set() for name in eligible["platform"]}
    wins = {name: set() for name in eligible["platform"]}
    if kw_significant and not pairs.empty:
        for _, row in pairs.iterrows():
            if not bool(row.get("meaningful", False)):
                continue
            winner = row["direction"]
            loser = row["platform_b"] if winner == row["platform_a"] else row["platform_a"]
            wins[winner].add(loser)
            losses[loser].add(winner)

    # Descriptive comparison across the distribution, NOT a weighted score.
    # A leads B when at least two of (Q1, median, Q3) are strictly higher.
    def breadth(a: pd.Series, b: pd.Series) -> int:
        return sum(float(a[k]) > float(b[k]) for k in
                   ("q1", "median_post_engagement", "q3"))

    candidates = []
    for _, row in eligible.iterrows():
        name = row["platform"]
        if losses[name]:
            continue
        comparisons = [other for _, other in eligible.iterrows()
                       if other["platform"] != name]
        breadth_wins = sum(breadth(row, other) >= 2 for other in comparisons)
        breadth_losses = sum(breadth(other, row) >= 2 for other in comparisons)
        candidates.append((name, breadth_wins, breadth_losses,
                           len(wins[name]), row["median_post_engagement"]))

    if not candidates:
        summary.loc[summary["eligible"], "recommendation"] = "Comparable candidate (inconclusive)"
        return summary, "Inconclusive", "No eligible platform avoids a meaningful pairwise disadvantage."

    # Prefer the broadest distribution advantage, then statistical wins.
    # If multiple platforms tie on both, do not use median to manufacture a winner.
    candidates.sort(key=lambda x: (x[1], -x[2], x[3]), reverse=True)
    top = candidates[0]
    leaders = [c for c in candidates if c[1:4] == top[1:4]]
    if len(leaders) != 1 or (top[1] == 0 and top[3] == 0):
        summary.loc[summary["eligible"], "recommendation"] = "Comparable candidate (inconclusive)"
        return summary, "Inconclusive", (
            "Leading platforms are too similar across their engagement distributions to name one primary.")
    primary = top[0]
    summary.loc[summary["platform"] == primary, "recommendation"] = "Primary"
    strong = bool(kw_significant and wins[primary])
    summary.loc[summary["platform"] == primary, "evidence_strength"] = (
        "Strong" if strong else "Indicative")

    # Secondary must not have a meaningful statistical/practical loss to primary.
    # Its distribution must be competitive: at least one quartile >= primary,
    # OR it must have a supported advantage against a third eligible platform.
    primary_row = eligible.loc[eligible["platform"] == primary].iloc[0]
    options = []
    for _, row in eligible.iterrows():
        name = row["platform"]
        if name == primary or primary in losses[name]:
            continue
        competitive = any(float(row[k]) >= float(primary_row[k])
                          for k in ("q1", "median_post_engagement", "q3"))
        if competitive or wins[name]:
            options.append((name, breadth(row, primary_row), len(wins[name])))
    options.sort(key=lambda x: (x[1], x[2]), reverse=True)
    if options:
        best = options[0]
        if sum(x[1:] == best[1:] for x in options) == 1:
            secondary = best[0]
            summary.loc[summary["platform"] == secondary, "recommendation"] = "Secondary"
            summary.loc[summary["platform"] == secondary, "evidence_strength"] = (
                "Strong" if wins[secondary] else "Indicative")
    summary.loc[summary["eligible"] &
                ~summary["recommendation"].isin(["Primary", "Secondary"]),
                "recommendation"] = "Comparable / not selected"
    secondary_rows = summary.loc[summary["recommendation"] == "Secondary", "platform"]
    second_text = (f"{secondary_rows.iloc[0]} is a competitive secondary candidate."
                   if len(secondary_rows) else "No secondary channel meets the competitive-performance rule.")
    confidence = "strong" if strong else "indicative"
    return summary, "Primary identified", (
        f"{primary} has the broadest supported engagement distribution advantage "
        f"({confidence} evidence). {second_text} "
        "Statistical significance is supporting evidence, not a prerequisite.")

def _apply_activity_fallback(summary: pd.DataFrame, status: str,
                             explanation: str) -> tuple[pd.DataFrame, str, str]:
    """Last-resort primary: largest observed posting volume, NOT engagement superiority.

    Apply only if the normal recommendation has no Primary. Do not weaken the
    30-post rule or automatically recommend a Secondary. A tie remains unresolved.
    """
    if summary.empty or (summary["recommendation"] == "Primary").any():
        return summary, status, explanation

    counts = pd.to_numeric(summary["post_count"], errors="coerce").fillna(0)
    if not counts.gt(0).any():
        return summary, status, explanation
    maximum = int(counts.max())
    leaders = summary.loc[counts == maximum]
    if len(leaders) != 1:
        names = ", ".join(sorted(leaders["platform"].astype(str)))
        return summary, "Inconclusive — posting activity tied", (
            f"No platform met the normal Primary recommendation criteria. "
            f"{names} each have {maximum} environmental posts, so posting "
            "frequency cannot distinguish a single fallback channel.")

    summary = summary.copy()
    winner = str(leaders.iloc[0]["platform"])
    summary.loc[summary["platform"] == winner, "recommendation"] = "Primary (activity fallback)"
    summary.loc[summary["platform"] == winner, "evidence_strength"] = "Limited — activity only"
    return summary, "Limited-data recommendation", (
        f"{winner} is suggested as a provisional Primary channel because it has "
        f"the most observed environmental posts ({maximum}) in the selected "
        "country and period. It did not qualify for a Primary recommendation "
        "under the normal engagement-distribution and statistical rules. "
        "Posting frequency indicates observed activity, not stronger audience "
        "engagement or effectiveness. No Secondary channel is assigned by this fallback.")


def _prepare_country_posts(data: dict[str, pd.DataFrame], country: str,
                           selected_months: tuple[Any, Any]) -> pd.DataFrame:
    """All environmental original posts, regardless of top-three topic matches."""
    posts = add_date_columns(data["posts"], "posts")
    if posts.empty:
        return posts
    start, end = map(_month_start, selected_months)
    posts = posts.loc[
        posts["_country"].eq(normalize_country(country)) &
        posts["_month"].between(start, end)
    ].copy()
    if "is_environmental" in posts:
        posts = posts.loc[posts["is_environmental"].astype(str).str.lower().isin(
            ("true", "1", "t"))].copy()
    if "source_type" in posts:
        posts = posts.loc[posts["source_type"].fillna("post").str.lower().eq("post")].copy()
    posts = posts.loc[posts["source_id"].notna()].drop_duplicates("source_id").copy()
    posts["platform"] = posts["platform"].fillna("").astype(str).str.strip().str.lower()
    posts = posts.loc[posts["platform"] != ""].copy()
    for column in ("total_engagement", "like_count", "reply_count", "repost_count",
                   "quote_count", "impression_count"):
        posts[column] = pd.to_numeric(posts[column], errors="coerce")
    # Original post total_engagement is the primary engagement measure.
    posts["_engagement"] = posts["total_engagement"]
    posts = posts.loc[posts["_engagement"].notna() & posts["_engagement"].ge(0)].copy()
    return posts


def _attach_comment_reactions(posts: pd.DataFrame, comments: pd.DataFrame) -> pd.DataFrame:
    """Attach comment RECEIVED reactions to parent posts, never count comments as posts.

    parent_source_id must match clean_posts.source_id and platform. We do not
    add comment count or comment reply_count: parent reply_count already captures
    direct replies, and nested replies may overlap.
    """
    posts = posts.copy()
    posts["_comment_reactions"] = 0.0
    posts["_linked_comments"] = 0
    if posts.empty or comments.empty:
        return posts
    c = comments.copy()
    c["platform"] = c["platform"].fillna("").astype(str).str.strip().str.lower()
    c = c.loc[c["parent_source_id"].notna()].copy()
    if c.empty:
        return posts
    if "source_id" in c:
        c = c.drop_duplicates(subset=["platform", "source_id"])
    for metric in ("like_count", "repost_count", "quote_count"):
        c[metric] = pd.to_numeric(c[metric], errors="coerce").fillna(0).clip(lower=0)
    c["_comment_reactions"] = c[["like_count", "repost_count", "quote_count"]].sum(axis=1)
    grouped = (c.groupby(["platform", "parent_source_id"], as_index=False)
               .agg(_comment_reactions=("_comment_reactions", "sum"),
                    _linked_comments=("parent_source_id", "size")))
    posts = posts.merge(grouped, how="left", left_on=["platform", "source_id"],
                        right_on=["platform", "parent_source_id"], suffixes=("", "_linked"))
    posts["_comment_reactions"] = posts["_comment_reactions_linked"].fillna(0)
    posts["_linked_comments"] = posts["_linked_comments_linked"].fillna(0).astype(int)
    posts.drop(columns=["parent_source_id", "_comment_reactions_linked",
                        "_linked_comments_linked"], inplace=True)
    posts["_engagement"] += posts["_comment_reactions"]
    return posts


def recommend_channels(data: dict[str, pd.DataFrame], country: str,
                       selected_months: tuple[Any, Any]) -> tuple[pd.DataFrame, dict[str, Any]]:
    """WHERE: all environmental posts; HOW: top-three news topics kept in evidence."""
    topics = top_topics_by_month(data, country, selected_months)
    posts = _prepare_country_posts(data, country, selected_months)
    posts = _attach_comment_reactions(posts, data.get("comments", pd.DataFrame()))
    evidence: dict[str, Any] = {
        "country": normalize_country(country), "selected_months": selected_months,
        "topics": topics, "matched_posts": posts,
        "environmental_posts_in_country_period": len(posts),
        "matched_post_count": len(posts), "activity_rows": len(posts),
        "unmatched_posts": 0, "pairwise_tests": pd.DataFrame(),
        "kruskal_h": np.nan, "kruskal_p": np.nan,
        "analysis_status": "Insufficient data", "explanation": "",
        "primary_channel": None, "secondary_channel": None, "min_posts": MIN_POSTS,
        "used_activity_fallback": False,
        "topic_match_method": "WHERE: all environmental posts. HOW: monthly top-three news topics.",
        "total_linked_comments": int(posts["_linked_comments"].sum()) if not posts.empty else 0,
        "total_comment_reactions": float(posts["_comment_reactions"].sum()) if not posts.empty else 0,
    }
    if posts.empty:
        evidence["explanation"] = "No environmental original posts found for this country and period."
        return pd.DataFrame(), evidence
    summary = _summary(posts)
    eligible = summary.loc[summary["eligible"], "platform"].tolist()
    if len(eligible) >= 2:
        groups = {name: posts.loc[posts["platform"] == name, "_engagement"].to_numpy(dtype=float)
                  for name in eligible}
        if len(np.unique(np.concatenate(list(groups.values())))) > 1:
            h, p = kruskal(*groups.values())
            evidence["kruskal_h"], evidence["kruskal_p"] = float(h), float(p)
            if p < ALPHA:
                evidence["pairwise_tests"] = _pairwise_dunn(groups)
    significant = bool(pd.notna(evidence["kruskal_p"]) and evidence["kruskal_p"] < ALPHA)
    summary, status, explanation = _decide(summary, evidence["pairwise_tests"], significant)
    summary, status, explanation = _apply_activity_fallback(summary, status, explanation)
    evidence["analysis_status"], evidence["explanation"] = status, explanation
    evidence["used_activity_fallback"] = status == "Limited-data recommendation"
    primary = summary.loc[summary["recommendation"].isin(
        ["Primary", "Primary (activity fallback)"]), "platform"]
    secondary = summary.loc[summary["recommendation"] == "Secondary", "platform"]
    evidence["primary_channel"] = primary.iloc[0] if len(primary) else None
    evidence["secondary_channel"] = secondary.iloc[0] if len(secondary) else None
    return summary, evidence


def topic_options(data: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Legacy helper retained for imports by the old page; new page doesn't need it."""
    rows = []
    for kind in ("posts", "comments"):
        frame = data[kind]
        if frame.empty:
            continue
        for _, row in frame.iterrows():
            rows.extend({"country": normalize_country(row.get("inferred_country")), "topic": keyword}
                        for keyword in _as_list(row.get("matched_keywords")))
    return pd.DataFrame(rows, columns=["country", "topic"]).drop_duplicates()