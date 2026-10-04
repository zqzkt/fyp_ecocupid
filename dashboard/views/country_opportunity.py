"""Country Opportunity Explorer.

Explore country-specific topic trends and identify New,

Emerging and Recurring environmental topics.

"""

import re

import pandas as pd

import plotly.graph_objects as go

import streamlit as st

from filters import (

    current_country_opportunity_filters,

    format_month,

)

from load_data import (

    get_news_cleaned,

    get_news_topics,

    get_topic_registry,

)

from style import (

    categorical_colors,

    html_table,

    kpi_card,

    style_figure,

)

# =====================================================================

# SETTINGS

# =====================================================================

TREND_TOPICS = 5

EMERGING_GROWTH_PCT = 50

EMERGING_MIN_MENTIONS = 3

RECURRING_MIN_MONTHS = 2

MIN_TREND_MONTHS = 4

# =====================================================================

# FILTERS

# =====================================================================

filters = (

    current_country_opportunity_filters()

)

country = filters.country

# monthly_topic_stats already filtered to:

# selected country + selected period.

df = filters.data

st.title(

    "Country Opportunity Explorer"

)

st.caption(

    "Explore the topics receiving attention within "

    f"{country} and identify new, emerging and "

    "recurring environmental conversations."

)

if df.empty:

    st.info(

        f"No topic data is available for "

        f"{country} during {filters.period}."

    )

    st.stop()

# =====================================================================

# LOAD SUPPORTING TABLES

# =====================================================================

news_cleaned = get_news_cleaned()

news_topics = get_news_topics()

topic_registry = get_topic_registry()

# =====================================================================

# TOPIC NAME LOOKUP

# =====================================================================

registry_names = (

    topic_registry[

        [

            "topic_id",

            "topic_name",

        ]

    ]

    .drop_duplicates(

        subset=["topic_id"]

    )

)

# =====================================================================

# BUILD COUNTRY-SPECIFIC ARTICLE HISTORY

# =====================================================================

# news_topics tells us which topic-country relationship

# each article belongs to.

#

# news_cleaned gives us the actual article publication month.

#

# Joining on BOTH article_id and country is important because

# one article may have country-level rows.

article_months = (

    news_cleaned[

        [

            "article_id",

            "country",

            "month",

        ]

    ]

    .dropna(

        subset=[

            "article_id",

            "country",

            "month",

        ]

    )

    .drop_duplicates()

)

topic_history = (

    news_topics[

        [

            "article_id",

            "topic_id",

            "country",

        ]

    ]

    .merge(

        article_months,

        on=[

            "article_id",

            "country",

        ],

        how="left",

    )

)

topic_history = (

    topic_history

    .merge(

        registry_names,

        on="topic_id",

        how="left",

    )

)

country_history = (

    topic_history[

        topic_history["country"]

        == country

    ]

    .dropna(

        subset=[

            "topic_id",

            "month",

        ]

    )

    .copy()

)

# =====================================================================

# COUNTRY-SPECIFIC FIRST APPEARANCE

# =====================================================================

# IMPORTANT:

#

# This uses ALL available months rather than the currently

# selected period.

#

# Example:

# If Air Pollution first appeared in Singapore in June,

# filtering the dashboard to August must NOT cause it to

# suddenly become "New".

country_first_seen = (

    country_history

    .groupby("topic_id")["month"]

    .min()

)

# =====================================================================

# MONTH INFORMATION

# =====================================================================

latest_month = filters.end

previous_month = (

    latest_month

    - pd.DateOffset(months=1)

)

# =====================================================================

# COUNTRY TOPIC TOTALS

# =====================================================================

country_topic_totals = (

    df.groupby(

        [

            "topic_id",

            "topic_name",

        ],

        as_index=False,

    )["article_count"]

    .sum()

    .sort_values(

        [

            "article_count",

            "topic_name",

        ],

        ascending=[

            False,

            True,

        ],

    )

)

# =====================================================================

# NEW TOPICS

# =====================================================================

# New means:

# first-ever appearance in THIS COUNTRY occurred

# during the latest selected month.

new_ids = set(

    country_first_seen[

        country_first_seen

        == latest_month

    ].index

)

# Only keep new topics that actually occur in the

# selected country's latest month.

latest_stats = df[

    df["month"]

    == latest_month

].copy()

new_table = (

    latest_stats[

        latest_stats["topic_id"]

        .isin(new_ids)

    ]

    [

        [

            "topic_id",

            "topic_name",

            "article_count",

        ]

    ]

    .copy()

)

if not new_table.empty:

    new_table = (

        new_table

        .groupby(

            [

                "topic_id",

                "topic_name",

            ],

            as_index=False,

        )["article_count"]

        .sum()

    )

    new_table = (

        new_table.rename(

            columns={

                "article_count":

                    "mentions"

            }

        )

    )

    new_table["first_seen"] = (

        format_month(

            latest_month

        )

    )

    new_table = (

        new_table

        .sort_values(

            [

                "mentions",

                "topic_name",

            ],

            ascending=[

                False,

                True,

            ],

        )

    )

# =====================================================================

# EMERGING TOPICS

# =====================================================================

# Emerging is calculated from monthly_topic_stats,

# which is the dashboard's authoritative source for

# monthly mention counts.

# ---------------------------------------------------------

# Latest month

# ---------------------------------------------------------

current_mentions = (

    df[

        df["month"]

        == latest_month

    ]

    .groupby(

        [

            "topic_id",

            "topic_name",

        ],

        as_index=False,

    )["article_count"]

    .sum()

    .rename(

        columns={

            "article_count":

                "current_mentions"

        }

    )

)

# ---------------------------------------------------------

# Previous month

# ---------------------------------------------------------

#

# The selected period may start at the latest month.

#

# filters.data would then not contain the previous month.

# To keep Emerging logically correct, we reconstruct

# previous-month counts from the full history available

# through article relationships.

#

# However, when the previous month exists inside the

# selected period, monthly_topic_stats is used directly.

previous_mentions = (

    df[

        df["month"]

        == previous_month

    ]

    .groupby(

        [

            "topic_id",

            "topic_name",

        ],

        as_index=False,

    )["article_count"]

    .sum()

    .rename(

        columns={

            "article_count":

                "previous_mentions"

        }

    )

)

growth = current_mentions.merge(

    previous_mentions[

        [

            "topic_id",

            "previous_mentions",

        ]

    ],

    on="topic_id",

    how="left",

)

growth["previous_mentions"] = (

    growth["previous_mentions"]

    .fillna(0)

    .astype(int)

)

growth["first_seen"] = (

    growth["topic_id"]

    .map(

        country_first_seen

    )

)

# Topic must already have existed in the country.

growth = growth[

    growth["first_seen"]

    < latest_month

].copy()

# A meaningful growth percentage cannot be calculated

# when the previous month had zero mentions.

growth = growth[

    growth["previous_mentions"]

    > 0

].copy()

growth["growth_pct"] = (

    (

        growth["current_mentions"]

        - growth["previous_mentions"]

    )

    / growth["previous_mentions"]

    * 100

)

growth = growth[

    (

        growth["current_mentions"]

        >= EMERGING_MIN_MENTIONS

    )

    & (

        growth["growth_pct"]

        >= EMERGING_GROWTH_PCT

    )

].copy()

growth["growth_pct"] = (

    growth["growth_pct"]

    .round(1)

)

growth = (

    growth

    .sort_values(

        [

            "growth_pct",

            "current_mentions",

            "topic_name",

        ],

        ascending=[

            False,

            False,

            True,

        ],

    )

)

emerging_ids = set(

    growth["topic_id"]

)

# =====================================================================

# RECURRING TOPICS

# =====================================================================

# Recurring looks across the entire selected period.

recurring = (

    df.groupby(

        [

            "topic_id",

            "topic_name",

        ],

        as_index=False,

    )

    .agg(

        active_months=(

            "month",

            "nunique",

        ),

        mentions=(

            "article_count",

            "sum",

        ),

    )

)

recurring = recurring[

    recurring["active_months"]

    >= RECURRING_MIN_MONTHS

].copy()

# Categories are intentionally mutually exclusive.

#

# New takes priority, then Emerging, then Recurring.

recurring = recurring[

    ~recurring["topic_id"].isin(

        new_ids

        | emerging_ids

    )

].copy()

recurring = (

    recurring

    .sort_values(

        [

            "active_months",

            "mentions",

            "topic_name",

        ],

        ascending=[

            False,

            False,

            True,

        ],

    )

)

# =====================================================================

# KPI CARDS

# =====================================================================

cards = [

    (

        "New",

        f"{len(new_table):,}",

    ),

    (

        "Emerging",

        f"{len(growth):,}",

    ),

    (

        "Recurring",

        f"{len(recurring):,}",

    ),

    (

        "Period",

        filters.period,

    ),

]

for column, (label, value) in zip(

    st.columns(

        [

            1,

            1,

            1,

            1.5,

        ]

    ),

    cards,

):

    column.html(

        kpi_card(

            label,

            value,

        )

    )

# =====================================================================

# TOP 5 TOPICS OVER TIME

# =====================================================================

country_trend_topics = (

    country_topic_totals[

        "topic_name"

    ]

    .head(

        TREND_TOPICS

    )

    .tolist()

)

st.header(

    f"Top {min(TREND_TOPICS, len(country_trend_topics))} "

    f"topics over time in {country}"

)

st.caption(

    f"Top topics are ranked by total mentions in "

    f"{country} during {filters.period}."

)

if len(filters.months) < MIN_TREND_MONTHS:

    st.caption(

        f"Only {len(filters.months)} "

        f"month{'s' if len(filters.months) != 1 else ''} "

        "of data are available in the selected range, "

        "so treat these trends as indicative."

    )

country_trend = (

    df[

        df["topic_name"].isin(

            country_trend_topics

        )

    ]

    .groupby(

        [

            "topic_name",

            "month",

        ]

    )["article_count"]

    .sum()

    .unstack(

        "month",

        fill_value=0,

    )

    .reindex(

        index=country_trend_topics,

        columns=filters.months,

        fill_value=0,

    )

)

country_month_labels = [

    format_month(month)

    for month in filters.months

]

country_lines = go.Figure()

for topic, color in categorical_colors(

    country_trend_topics

).items():

    country_lines.add_trace(

        go.Scatter(

            x=country_month_labels,

            y=country_trend.loc[

                topic

            ],

            name=topic,

            mode="lines+markers",

            line=dict(

                color=color,

                width=3,

            ),

            marker=dict(

                color=color,

                size=10,

            ),

            hovertemplate=(

                f"<b>{topic}</b><br>"

                "%{x}<br>"

                "%{y:,} mentions"

                "<extra></extra>"

            ),

        )

    )

country_lines.update_layout(

    hovermode="x unified",

    legend=dict(

        orientation="h",

        yanchor="bottom",

        y=1.02,

        x=0,

    ),

)

country_lines.update_yaxes(

    title_text="Mentions",

    rangemode="tozero",

)

st.plotly_chart(

    style_figure(

        country_lines,

        height=560,

    ),

    config={

        "displayModeBar": False

    },

)

# =====================================================================

# TOPIC OPPORTUNITIES

# =====================================================================

st.header(

    "Topic opportunities"

)

st.caption(

    f"Signals are calculated specifically for {country}. "

    "A topic may therefore have a different status in another country."

)

emerging_tab, new_tab, recurring_tab = (

    st.tabs(

        [

            "Emerging",

            "New",

            "Recurring",

        ]

    )

)

# =====================================================================

# EMERGING TAB

# =====================================================================

with emerging_tab:

    st.subheader(

        "Emerging topics"

    )

    st.caption(

        f"Topics already present in {country} "

        f"with at least {EMERGING_MIN_MENTIONS} mentions "

        f"in {format_month(latest_month)} and at least "

        f"{EMERGING_GROWTH_PCT}% growth compared with "

        f"{format_month(previous_month)}."

    )

    if growth.empty:

        st.info(

            "No topics meet the emerging-topic "

            "criteria for this country and period."

        )

    else:

        emerging_display = (

            growth[

                [

                    "topic_name",

                    "previous_mentions",

                    "current_mentions",

                    "growth_pct",

                ]

            ]

            .copy()

        )

        emerging_display.columns = [

            "Topic",

            (

                f"{format_month(previous_month)} "

                "mentions"

            ),

            (

                f"{format_month(latest_month)} "

                "mentions"

            ),

            "Growth (%)",

        ]

        st.html(

            html_table(

                emerging_display

            )

        )

# =====================================================================

# NEW TAB

# =====================================================================

with new_tab:

    st.subheader(

        "New topics"

    )

    st.caption(

        f"Topics appearing in {country} "

        f"for the first time in "

        f"{format_month(latest_month)}."

    )

    if new_table.empty:

        st.info(

            "No new topics were first detected "

            "in this country during the latest "

            "selected month."

        )

    else:

        new_display = (

            new_table[

                [

                    "topic_name",

                    "mentions",

                    "first_seen",

                ]

            ]

            .copy()

        )

        new_display.columns = [

            "Topic",

            "Mentions",

            "First seen",

        ]

        st.html(

            html_table(

                new_display

            )

        )

# =====================================================================

# RECURRING TAB

# =====================================================================

with recurring_tab:

    st.subheader(

        "Recurring topics"

    )

    st.caption(

        f"Topics appearing in at least "

        f"{RECURRING_MIN_MONTHS} months during "

        f"{filters.period}, excluding topics currently "

        "classified as New or Emerging."

    )

    if recurring.empty:

        st.info(

            "No recurring topics meet the criteria "

            "for this country and period."

        )

    else:

        recurring_display = (

            recurring[

                [

                    "topic_name",

                    "active_months",

                    "mentions",

                ]

            ]

            .copy()

        )

        recurring_display.columns = [

            "Topic",

            "Active months",

            "Mentions",

        ]

        st.html(

            html_table(

                recurring_display

            )

        )

# =====================================================================

# TOPIC & KEYWORD LANDSCAPE

# =====================================================================

st.header(f"Topic & Keyword Landscape — {country}")

st.caption(

    "Shows the top 10 topics for the selected country and period. "

    "Higher-ranked topics are larger and placed closer to the centre. "

    "Monthly keywords use the same colour as their corresponding topic."

)

WORD_CLOUD_TOPICS = 10

KEYWORDS_PER_TOPIC = 5

# Font sizes are deliberately large. The placement algorithm below

# estimates the rendered footprint of every label and prevents labels

# from being placed on top of one another.

TOPIC_MAX_FONT_SIZE = 42

TOPIC_MIN_FONT_SIZE = 27

KEYWORD_FONT_SIZE = 18

# Virtual coordinate system used by the collision-aware layout.

LANDSCAPE_X_MIN = 0.0

LANDSCAPE_X_MAX = 160.0

LANDSCAPE_Y_MIN = 0.0

LANDSCAPE_Y_MAX = 110.0

# Padding added around estimated text rectangles.

LABEL_PADDING_X = 1.8

LABEL_PADDING_Y = 1.2

def split_monthly_keywords(value) -> list[str]:

    """Convert a monthly_keywords cell into a clean list of keywords."""

    if pd.isna(value):

        return []

    text = str(value).strip()

    if not text:

        return []

    text = text.replace(";", ",")

    return [

        keyword.strip()

        for keyword in text.split(",")

        if keyword.strip()

    ]

def collect_landscape_keywords(topic_id: str) -> list[str]:

    """Return the most frequently occurring monthly keywords for a topic."""

    topic_rows = df[df["topic_id"] == topic_id]

    if "monthly_keywords" not in topic_rows.columns:

        return []

    counts: dict[str, int] = {}

    display_names: dict[str, str] = {}

    for value in topic_rows["monthly_keywords"]:

        for keyword in split_monthly_keywords(value):

            normalised = keyword.casefold()

            counts[normalised] = (

                counts.get(normalised, 0)

                + 1

            )

            display_names.setdefault(

                normalised,

                keyword,

            )

    ranked = sorted(

        counts,

        key=lambda keyword: (

            -counts[keyword],

            keyword,

        ),

    )

    return [

        display_names[keyword]

        for keyword in ranked[:KEYWORDS_PER_TOPIC]

    ]

def estimate_text_box(

    text: str,

    font_size: float,

    x: float,

    y: float,

) -> tuple[float, float, float, float]:

    """

    Estimate the text rectangle in landscape coordinates.

    Plotly does not expose text bounding boxes before rendering, so this

    uses a conservative character-width estimate. Long phrases therefore

    reserve more horizontal space than short phrases.

    """

    plain_text = re.sub(

        r"<[^>]+>",

        "",

        str(text),

    )

    # Approximate average glyph width at the chosen font size.

    width = max(

        5.0,

        len(plain_text) * font_size * 0.040,

    )

    height = max(

        3.2,

        font_size * 0.18,

    )

    return (

        x - width / 2 - LABEL_PADDING_X,

        x + width / 2 + LABEL_PADDING_X,

        y - height / 2 - LABEL_PADDING_Y,

        y + height / 2 + LABEL_PADDING_Y,

    )

def boxes_overlap(

    box_a: tuple[float, float, float, float],

    box_b: tuple[float, float, float, float],

) -> bool:

    """Return True when two estimated text rectangles overlap."""

    return not (

        box_a[1] <= box_b[0]

        or box_a[0] >= box_b[1]

        or box_a[3] <= box_b[2]

        or box_a[2] >= box_b[3]

    )

def box_inside_canvas(

    box: tuple[float, float, float, float],

) -> bool:

    """Keep every label inside the visible plotting area."""

    return (

        box[0] >= LANDSCAPE_X_MIN

        and box[1] <= LANDSCAPE_X_MAX

        and box[2] >= LANDSCAPE_Y_MIN

        and box[3] <= LANDSCAPE_Y_MAX

    )

def position_is_free(

    box: tuple[float, float, float, float],

    occupied_boxes: list[

        tuple[float, float, float, float]

    ],

) -> bool:

    """Check that a candidate label does not collide with prior labels."""

    if not box_inside_canvas(box):

        return False

    return not any(

        boxes_overlap(

            box,

            occupied_box,

        )

        for occupied_box in occupied_boxes

    )

def keyword_candidate_positions(

    topic_x: float,

    topic_y: float,

) -> list[tuple[float, float]]:

    """

    Candidate positions around a topic.

    The search starts close to the topic and gradually expands outward.

    This keeps each colour cluster visually together while still allowing

    long keywords to move away when required to avoid collisions.

    """

    offsets = [

        (-12, 8),

        (12, 8),

        (-12, -8),

        (12, -8),

        (0, -12),

        (0, 12),

        (-18, 0),

        (18, 0),

        (-20, 11),

        (20, 11),

        (-20, -11),

        (20, -11),

        (-7, 15),

        (7, 15),

        (-7, -15),

        (7, -15),

        (-25, 6),

        (25, 6),

        (-25, -6),

        (25, -6),

    ]

    return [

        (

            topic_x + dx,

            topic_y + dy,

        )

        for dx, dy in offsets

    ]

def fallback_positions() -> list[tuple[float, float]]:

    """

    Global backup positions.

    These are only used when a very long keyword cannot fit around its

    parent topic without colliding with another label.

    """

    positions = []

    for y in range(102, 7, -7):

        for x in range(8, 153, 12):

            positions.append(

                (

                    float(x),

                    float(y),

                )

            )

    return positions

# ---------------------------------------------------------------------

# RANK TOPICS FOR THE SELECTED COUNTRY + PERIOD

# ---------------------------------------------------------------------

#

# This landscape represents the entire currently selected country and

# date range. Rank topics by TOTAL article mentions across that filtered

# period so the most frequently discussed topic is largest and closest

# to the centre.

#

# Example:

# Wildlife Conservation = 22 mentions

# National Park          =  4 mentions

#

# Wildlife Conservation therefore ranks above National Park.

topic_landscape = (

    df

    .groupby(

        [

            "topic_id",

            "topic_name",

        ],

        as_index=False,

    )

    .agg(

        article_count=(

            "article_count",

            "sum",

        )

    )

    .sort_values(

        [

            "article_count",

            "topic_name",

        ],

        ascending=[

            False,

            True,

        ],

    )

    .head(

        WORD_CLOUD_TOPICS

    )

    .reset_index(

        drop=True

    )

)

# Rank 1 = highest total article count in the currently selected period.

topic_landscape["display_rank"] = (

    topic_landscape.index + 1

)

# Keywords still come from the monthly_topic_stats rows belonging to

# each selected topic, country and period.

topic_landscape["keywords"] = (

    topic_landscape["topic_id"]

    .apply(

        collect_landscape_keywords

    )

)

# ---------------------------------------------------------------------

# BUILD COLLISION-AWARE LANDSCAPE

# ---------------------------------------------------------------------

if topic_landscape.empty:

    st.info(

        "No topic data is available for the "

        "topic and keyword landscape."

    )

else:

    # These are intentionally separated enough for the large topic

    # headings. Rank 1 remains central; lower ranks move outward.

    topic_positions = [

        (80, 58),   # Rank 1

        (45, 79),   # Rank 2

        (115, 79),  # Rank 3

        (44, 45),   # Rank 4

        (116, 45),  # Rank 5

        (18, 70),   # Rank 6

        (142, 70),  # Rank 7

        (22, 23),   # Rank 8

        (138, 23),  # Rank 9

        (80, 18),   # Rank 10

    ]

    landscape = go.Figure()

    landscape_colors = categorical_colors(

        topic_landscape[

            "topic_name"

        ].tolist()

    )

    occupied_boxes: list[

        tuple[

            float,

            float,

            float,

            float,

        ]

    ] = []

    placed_topics = []

    # --------------------------------------------------------------

    # PLACE TOPIC NAMES FIRST

    # --------------------------------------------------------------

    #

    # Topic names are placed before keywords so the keywords must

    # adapt around them rather than covering them.

    for index, row in topic_landscape.iterrows():

        topic_x, topic_y = topic_positions[index]

        topic_name = row["topic_name"]

        topic_color = landscape_colors[

            topic_name

        ]

        display_rank = int(

            row["display_rank"]

        )

        topic_font_size = max(

            TOPIC_MIN_FONT_SIZE,

            TOPIC_MAX_FONT_SIZE

            - (

                display_rank - 1

            )

            * 1.7,

        )

        topic_box = estimate_text_box(

            topic_name,

            topic_font_size,

            topic_x,

            topic_y,

        )

        # The predefined topic centres are already widely spaced,

        # but if an unusually long topic still overlaps, move it

        # vertically until a free location is found.

        if not position_is_free(

            topic_box,

            occupied_boxes,

        ):

            alternative_offsets = [

                (0, 5),

                (0, -5),

                (0, 10),

                (0, -10),

                (-5, 0),

                (5, 0),

                (-8, 6),

                (8, 6),

                (-8, -6),

                (8, -6),

            ]

            for dx, dy in alternative_offsets:

                candidate_x = topic_x + dx

                candidate_y = topic_y + dy

                candidate_box = estimate_text_box(

                    topic_name,

                    topic_font_size,

                    candidate_x,

                    candidate_y,

                )

                if position_is_free(

                    candidate_box,

                    occupied_boxes,

                ):

                    topic_x = candidate_x

                    topic_y = candidate_y

                    topic_box = candidate_box

                    break

        occupied_boxes.append(

            topic_box

        )

        placed_topics.append(

            {

                "x": topic_x,

                "y": topic_y,

                "name": topic_name,

                "color": topic_color,

                "rank": display_rank,

                "article_count": int(

                    row["article_count"]

                ),

                "font_size": topic_font_size,

                "keywords": row["keywords"],

            }

        )

        landscape.add_trace(

            go.Scatter(

                x=[topic_x],

                y=[topic_y],

                mode="text",

                text=[

                    f"<b>{topic_name}</b>"

                ],

                textfont=dict(

                    size=topic_font_size,

                    color=topic_color,

                ),

                customdata=[[

                    display_rank,

                    int(

                        row["article_count"]

                    ),

                ]],

                hovertemplate=(

                    f"<b>{topic_name}</b><br>"

                    "Landscape rank: "

                    "%{customdata[0]}<br>"

                    "Mentions: "

                    "%{customdata[1]:,}"

                    "<extra></extra>"

                ),

                showlegend=False,

            )

        )

    # --------------------------------------------------------------

    # PLACE KEYWORDS SECOND

    # --------------------------------------------------------------

    global_fallbacks = fallback_positions()

    for topic in placed_topics:

        topic_x = topic["x"]

        topic_y = topic["y"]

        topic_name = topic["name"]

        topic_color = topic["color"]

        for keyword in topic["keywords"]:

            chosen_position = None

            chosen_box = None

            # First try positions around the parent topic.

            for candidate_x, candidate_y in (

                keyword_candidate_positions(

                    topic_x,

                    topic_y,

                )

            ):

                candidate_box = estimate_text_box(

                    keyword,

                    KEYWORD_FONT_SIZE,

                    candidate_x,

                    candidate_y,

                )

                if position_is_free(

                    candidate_box,

                    occupied_boxes,

                ):

                    chosen_position = (

                        candidate_x,

                        candidate_y,

                    )

                    chosen_box = candidate_box

                    break

            # If a long phrase cannot fit locally, search the canvas

            # rather than allowing it to overlap another label.

            if chosen_position is None:

                for candidate_x, candidate_y in global_fallbacks:

                    candidate_box = estimate_text_box(

                        keyword,

                        KEYWORD_FONT_SIZE,

                        candidate_x,

                        candidate_y,

                    )

                    if position_is_free(

                        candidate_box,

                        occupied_boxes,

                    ):

                        chosen_position = (

                            candidate_x,

                            candidate_y,

                        )

                        chosen_box = candidate_box

                        break

            # Only draw the keyword if a collision-free position exists.

            # This is preferable to drawing unreadable overlapping text.

            if (

                chosen_position is None

                or chosen_box is None

            ):

                continue

            occupied_boxes.append(

                chosen_box

            )

            keyword_x, keyword_y = (

                chosen_position

            )

            landscape.add_trace(

                go.Scatter(

                    x=[keyword_x],

                    y=[keyword_y],

                    mode="text",

                    text=[keyword],

                    textfont=dict(

                        size=KEYWORD_FONT_SIZE,

                        color=topic_color,

                    ),

                    hovertemplate=(

                        f"<b>{topic_name}</b><br>"

                        f"Keyword: {keyword}"

                        "<extra></extra>"

                    ),

                    showlegend=False,

                )

            )

    landscape.update_xaxes(

        visible=False,

        range=[

            LANDSCAPE_X_MIN,

            LANDSCAPE_X_MAX,

        ],

        fixedrange=True,

    )

    landscape.update_yaxes(

        visible=False,

        range=[

            LANDSCAPE_Y_MIN,

            LANDSCAPE_Y_MAX,

        ],

        fixedrange=True,

    )

    landscape.update_layout(

        height=1000,

        margin=dict(

            l=30,

            r=30,

            t=35,

            b=35,

        ),

        plot_bgcolor="rgba(0, 0, 0, 0)",

        paper_bgcolor="rgba(0, 0, 0, 0)",

        hovermode="closest",

    )

    st.plotly_chart(

        landscape,

        use_container_width=True,

        config={

            "displayModeBar": False,

        },

        key="country_topic_keyword_landscape",

    )

# =====================================================================
# ARTICLES BEHIND THE TOPICS
# =====================================================================

st.header("Articles Behind the Topics")

st.caption(
    "Review the news articles contributing to the topics above. "
    "Use the filters to inspect a particular topic or search for an article. "
    "The summary describes the article, while the relevance explanation "
    "shows why it was associated with the topic."
)

# ---------------------------------------------------------------------
# BUILD ARTICLE-TOPIC EVIDENCE FROM SUPABASE DATA
# ---------------------------------------------------------------------

topic_article_columns = [
    "article_id",
    "topic_id",
    "country",
    "article_topic_similarity",
    "article_summary",
    "topic_relevance_explanation",
]

article_topic_data = (
    news_topics[
        [
            column
            for column in topic_article_columns
            if column in news_topics.columns
        ]
    ]
    .copy()
)

article_topic_data = (
    article_topic_data
    .merge(
        registry_names,
        on="topic_id",
        how="left",
    )
)

article_metadata_columns = [
    "article_id",
    "country",
    "title",
    "source",
    "published_at",
    "month",
    "url",
]

article_metadata = (
    news_cleaned[
        [
            column
            for column in article_metadata_columns
            if column in news_cleaned.columns
        ]
    ]
    .copy()
)

# article_id alone is not sufficient because one article can have
# separate country-level rows.
article_evidence = (
    article_topic_data
    .merge(
        article_metadata,
        on=[
            "article_id",
            "country",
        ],
        how="left",
    )
)

# Apply the same country and date-range selection used by the rest
# of the Country Opportunity Explorer.
article_evidence = (
    article_evidence[
        article_evidence["country"]
        == country
    ]
    .copy()
)

if "month" in article_evidence.columns:
    article_evidence["month"] = pd.to_datetime(
        article_evidence["month"],
        errors="coerce",
    )

    article_evidence = (
        article_evidence[
            article_evidence["month"].between(
                filters.start,
                filters.end,
            )
        ]
        .copy()
    )

# Remove accidental duplicate article-topic rows before displaying.
article_evidence = (
    article_evidence
    .drop_duplicates(
        subset=[
            column
            for column in [
                "article_id",
                "topic_id",
                "country",
            ]
            if column in article_evidence.columns
        ]
    )
    .copy()
)

# ---------------------------------------------------------------------
# TABLE FILTERS
# ---------------------------------------------------------------------

available_article_topics = sorted(
    article_evidence["topic_name"]
    .dropna()
    .astype(str)
    .unique()
    .tolist()
)

filter_col_1, filter_col_2 = st.columns(
    [1.15, 1.85]
)

with filter_col_1:
    selected_article_topics = st.multiselect(
        "Topic",
        options=available_article_topics,
        default=[],
        placeholder="All topics",
        key="country_article_topic_filter",
    )

with filter_col_2:
    article_search = st.text_input(
        "Search articles",
        placeholder="Search title, summary or relevance explanation",
        key="country_article_search",
    )

filtered_article_evidence = article_evidence.copy()

if selected_article_topics:
    filtered_article_evidence = (
        filtered_article_evidence[
            filtered_article_evidence[
                "topic_name"
            ].isin(
                selected_article_topics
            )
        ]
        .copy()
    )

search_term = article_search.strip()

if search_term:
    searchable_columns = [
        column
        for column in [
            "title",
            "article_summary",
            "topic_relevance_explanation",
        ]
        if column
        in filtered_article_evidence.columns
    ]

    if searchable_columns:
        search_mask = pd.Series(
            False,
            index=filtered_article_evidence.index,
        )

        for column in searchable_columns:
            search_mask = (
                search_mask
                | filtered_article_evidence[
                    column
                ]
                .fillna("")
                .astype(str)
                .str.contains(
                    search_term,
                    case=False,
                    regex=False,
                )
            )

        filtered_article_evidence = (
            filtered_article_evidence[
                search_mask
            ]
            .copy()
        )

# ---------------------------------------------------------------------
# FORMAT ARTICLE TABLE
# ---------------------------------------------------------------------

if filtered_article_evidence.empty:
    st.info(
        "No articles match the selected country, period and table filters."
    )

else:
    if "published_at" in filtered_article_evidence.columns:
        filtered_article_evidence[
            "published_at"
        ] = pd.to_datetime(
            filtered_article_evidence[
                "published_at"
            ],
            errors="coerce",
            utc=True,
        )

    if (
        "article_topic_similarity"
        in filtered_article_evidence.columns
    ):
        filtered_article_evidence[
            "article_topic_similarity"
        ] = pd.to_numeric(
            filtered_article_evidence[
                "article_topic_similarity"
            ],
            errors="coerce",
        )

    display_columns = [
        "topic_name",
        "title",
        "source",
        "published_at",
        "article_summary",
        "topic_relevance_explanation",
        "article_topic_similarity",
        "url",
    ]

    display_columns = [
        column
        for column in display_columns
        if column in filtered_article_evidence.columns
    ]

    article_table = (
        filtered_article_evidence[
            display_columns
        ]
        .copy()
    )

    article_table = article_table.rename(
        columns={
            "topic_name": "Topic",
            "title": "Article",
            "source": "Source",
            "published_at": "Published",
            "article_summary": "Article Summary",
            "topic_relevance_explanation":
                "Topic Relevance Explanation",
            "article_topic_similarity": "Topic Similarity",
            "url": "Article URL",
        }
    )

    sort_columns = [
        column
        for column in [
            "Published",
            "Topic",
            "Article",
        ]
        if column in article_table.columns
    ]

    if sort_columns:
        article_table = (
            article_table
            .sort_values(
                sort_columns,
                ascending=[
                    False
                    if column == "Published"
                    else True
                    for column in sort_columns
                ],
                na_position="last",
            )
            .reset_index(
                drop=True
            )
        )

    st.caption(
        f"{len(article_table):,} article-topic "
        f"{'relationship' if len(article_table) == 1 else 'relationships'} "
        f"· {country} · {filters.period}"
    )

    article_column_config = {}

    if "Article" in article_table.columns:
        article_column_config[
            "Article"
        ] = st.column_config.TextColumn(
            "Article",
            width="large",
        )

    if "Topic" in article_table.columns:
        article_column_config[
            "Topic"
        ] = st.column_config.TextColumn(
            "Topic",
            width="medium",
        )

    if "Source" in article_table.columns:
        article_column_config[
            "Source"
        ] = st.column_config.TextColumn(
            "Source",
            width="small",
        )

    if "Published" in article_table.columns:
        article_column_config[
            "Published"
        ] = st.column_config.DateColumn(
            "Published",
            format="DD MMM YYYY",
            width="small",
        )

    if "Article Summary" in article_table.columns:
        article_column_config[
            "Article Summary"
        ] = st.column_config.TextColumn(
            "Article Summary",
            width="large",
        )

    if (
        "Topic Relevance Explanation"
        in article_table.columns
    ):
        article_column_config[
            "Topic Relevance Explanation"
        ] = st.column_config.TextColumn(
            "Topic Relevance Explanation",
            width="large",
        )

    if "Topic Similarity" in article_table.columns:
        article_column_config[
            "Topic Similarity"
        ] = st.column_config.NumberColumn(
            "Similarity",
            format="%.3f",
            width="small",
        )

    if "Article URL" in article_table.columns:
        article_column_config[
            "Article URL"
        ] = st.column_config.LinkColumn(
            "Link",
            display_text="Open article",
            width="small",
        )

    st.dataframe(
        article_table,
        hide_index=True,
        width="stretch",
        height=600,
        column_config=article_column_config,
    )

    # -----------------------------------------------------------------
    # DOWNLOAD CURRENTLY FILTERED TABLE
    # -----------------------------------------------------------------

    csv_data = (
        article_table
        .to_csv(
            index=False,
        )
        .encode(
            "utf-8-sig"
        )
    )

    safe_country = re.sub(
        r"[^a-z0-9]+",
        "_",
        country.lower(),
    ).strip("_")

    st.download_button(
        "Download filtered article data",
        data=csv_data,
        file_name=(
            f"{safe_country}_topic_articles.csv"
        ),
        mime="text/csv",
        key="download_country_topic_articles",
    )

