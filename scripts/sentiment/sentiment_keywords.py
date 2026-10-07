"""Interpretable lexical cues collected alongside emotion predictions."""

from __future__ import annotations

import re


SENTIMENT_KEYWORDS: dict[str, tuple[str, ...]] = {
    "admiration": ("admire", "admirable", "inspiring", "impressive", "respect", "amazing work"),
    "amusement": ("funny", "hilarious", "lol", "laugh", "amusing", "made me laugh"),
    "anger": ("angry", "anger", "furious", "outraged", "rage", "hate", "ridiculous", "hypocrite"),
    "annoyance": ("annoyed", "annoying", "irritated", "frustrating", "frustrated", "bothered"),
    "approval": ("agree", "approved", "approval", "well done", "good idea", "support this"),
    "caring": ("care", "caring", "concerned for", "look after", "protect", "wishing you well"),
    "confusion": ("confused", "confusing", "don't understand", "unclear", "what does this mean"),
    "curiosity": ("curious", "wonder", "wondering", "how does", "why does", "want to know"),
    "desire": ("want", "wish", "hope to", "long for", "would love to", "need to see"),
    "disappointment": ("disappointed", "let down", "underwhelming", "expected better", "what a shame"),
    "disapproval": ("disagree", "unacceptable", "wrong", "oppose", "should not", "not okay"),
    "disgust": ("disgust", "disgusting", "appalling", "gross", "vile", "sickening", "revolting"),
    "embarrassment": ("embarrassed", "embarrassing", "awkward", "ashamed", "cringe", "mortified"),
    "excitement": ("excited", "thrilled", "can't wait", "cannot wait", "so pumped", "looking forward"),
    "fear": ("afraid", "fear", "scared", "worried", "threat", "danger", "terrifying", "risk", "anxious"),
    "gratitude": ("thank you", "thanks", "grateful", "thankful", "appreciate", "blessed"),
    "grief": ("grief", "mourning", "devastated", "heartbroken", "deep loss", "gone forever"),
    "joy": ("happy", "happiness", "joy", "delighted", "enjoy", "glad", "awesome", "beautiful", "wonderful", "fantastic"),
    "love": ("love", "loved", "loving", "adore", "affection", "heart"),
    "neutral": (),
    "nervousness": ("nervous", "anxious", "uneasy", "on edge", "apprehensive", "butterflies"),
    "optimism": ("optimistic", "hopeful", "bright future", "things will improve", "positive outlook", "can get better"),
    "pride": ("proud", "accomplished", "achievement", "we did it", "honored", "earned this"),
    "realization": ("realized", "realization", "it turns out", "now i see", "i understand now", "makes sense"),
    "relief": ("relieved", "what a relief", "finally safe", "glad it's over", "weight off", "no longer worried"),
    "remorse": ("sorry i", "i regret", "my fault", "shouldn't have", "feel guilty", "apologize"),
    "sadness": ("sad", "sadly", "sorry", "loss", "trauma", "suffering", "miss you", "heartbroken"),
    "surprise": ("wow", "surprised", "shocking", "unexpected", "astonished", "unbelievable", "mind blown"),
}

EMOJI_CUES: dict[str, tuple[str, ...]] = {
    "admiration": ("star_struck", "clapping_hands", "fire", "trophy"),
    "amusement": ("face_with_tears_of_joy", "rolling_on_the_floor_laughing", "grinning_squinting_face"),
    "anger": ("enraged_face", "angry_face", "face_with_symbols_on_mouth", "face_with_steam_from_nose"),
    "annoyance": ("unamused_face", "rolling_eyes", "face_with_raised_eyebrow"),
    "approval": ("thumbs_up", "check_mark_button", "white_heavy_check_mark"),
    "caring": ("hugging_face", "people_hugging", "heart_hands"),
    "confusion": ("confused_face", "face_with_raised_eyebrow", "thinking_face"),
    "curiosity": ("eyes", "thinking_face", "magnifying_glass_tilted_left"),
    "desire": ("heart_eyes", "smiling_face_with_heart_eyes", "pleading_face"),
    "disappointment": ("disappointed_face", "frowning_face", "downcast_face_with_sweat"),
    "disapproval": ("thumbs_down", "cross_mark", "face_with_rolling_eyes"),
    "disgust": ("nauseated_face", "vomiting_face", "face_vomiting"),
    "embarrassment": ("flushed_face", "face_with_hand_over_mouth", "see_no_evil_monkey"),
    "excitement": ("partying_face", "party_popper", "fireworks"),
    "fear": ("fearful_face", "face_screaming_in_fear", "worried_face", "anxious_face"),
    "gratitude": ("folded_hands", "heart_hands", "smiling_face_with_hearts"),
    "grief": ("broken_heart", "loudly_crying_face", "crying_face"),
    "joy": ("smiling_face", "grinning_face", "beaming_face_with_smiling_eyes", "party_popper", "sparkles"),
    "love": ("red_heart", "heart_suit", "two_hearts", "heart_hands", "sparkling_heart"),
    "neutral": (),
    "nervousness": ("anxious_face_with_sweat", "grimacing_face", "nauseated_face"),
    "optimism": ("sun_with_face", "rainbow", "four_leaf_clover", "seedling"),
    "pride": ("smiling_face_with_sunglasses", "flexed_biceps", "medal"),
    "realization": ("light_bulb", "exploding_head", "face_with_monocle"),
    "relief": ("relieved_face", "sigh", "smiling_face_with_tear"),
    "remorse": ("pleading_face", "pensive_face", "face_exhaling"),
    "sadness": ("loudly_crying_face", "crying_face", "sad_face", "broken_heart", "pensive_face"),
    "surprise": ("face_with_open_mouth", "astonished_face", "exploding_head", "flushed_face"),
}

_ALIASES = re.compile(r"\[([a-zA-Z0-9_]+)\]")


def matched_sentiment_keywords(text: str, emotion: str) -> list[str]:
    """Return distinct lexicon and emoji cues matching the predicted emotion."""
    normalized = text.casefold()
    matches = [
        keyword
        for keyword in SENTIMENT_KEYWORDS.get(emotion, ())
        if re.search(rf"(?<!\w){re.escape(keyword)}(?!\w)", normalized)
    ]
    aliases = {match.group(1).casefold() for match in _ALIASES.finditer(text)}
    matches.extend(
        f"[{alias}]"
        for alias in EMOJI_CUES.get(emotion, ())
        if alias in aliases
    )
    return list(dict.fromkeys(matches))
