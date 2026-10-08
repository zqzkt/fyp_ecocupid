"""Decode multilabel emotion probabilities into emotion assignments."""

from __future__ import annotations

from typing import Sequence

import numpy as np

from scripts.sentiment.emotion_labels import EMOTIONS


def decode_emotion_probabilities(
    probabilities: np.ndarray,
    thresholds: Sequence[float],
) -> list[list[str]]:
    """Select thresholded emotions; emit neutral only when no emotion passes."""
    thresholds_array = np.asarray(thresholds, dtype=float)
    binary = probabilities >= thresholds_array
    neutral_index = EMOTIONS.index("neutral")
    decoded: list[list[str]] = []
    for index, row in enumerate(probabilities):
        selected = np.flatnonzero(binary[index])
        non_neutral = [i for i in selected if i != neutral_index]
        if non_neutral:
            decoded.append([EMOTIONS[i] for i in non_neutral])
        elif neutral_index in selected:
            decoded.append(["neutral"])
        else:
            # Ensure every item receives at least one label if all thresholds miss.
            best_index = int(np.argmax(row))
            decoded.append([EMOTIONS[best_index]])
    return decoded
