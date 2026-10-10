"""Text normalization shared by emotion model training and inference."""

from __future__ import annotations

import re

import emoji


_EMOJI_ALIAS = re.compile(r"\[([a-zA-Z0-9_]+)\]")


def prepare_text(text: str) -> str:
    """Normalize source emoji and cleaned square-bracket emoji aliases alike."""
    demojized = emoji.demojize(text, delimiters=("[", "]"), language="en")
    return normalize_emoji_tags(demojized)


def normalize_emoji_tags(text: str) -> str:
    """Expand cleaned emoji aliases into words for the text vectorizer.

    For example, ``[tears_with_joy]`` becomes ``tears with joy`` and
    ``[red_heart]`` becomes ``red heart``. This lets the vectorizer use both
    the alias meaning and its component emotion words.
    """
    return _EMOJI_ALIAS.sub(lambda match: match.group(1).replace("_", " "), text)
