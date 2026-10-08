
"""Train a multilabel GoEmotions classifier with a held-out test evaluation."""

from __future__ import annotations

import csv
from pathlib import Path
import sys

import emoji
import joblib
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import classification_report, f1_score
from sklearn.multiclass import OneVsRestClassifier
from sklearn.preprocessing import MultiLabelBinarizer
from sklearn.pipeline import Pipeline

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.sentiment.emotion_labels import EMOTIONS
from scripts.sentiment.emotion_inference import decode_emotion_probabilities
from scripts.sentiment.text_preprocessing import prepare_text

DATASET_DIR = Path(__file__).resolve().parent / "dataset" / "goemotions"
MODEL_PATH = Path(__file__).resolve().parent / "emotion_model.joblib"
THRESHOLD_GRID = np.arange(0.05, 0.96, 0.025)


def load_split(name: str, label_binarizer: MultiLabelBinarizer) -> tuple[list[str], np.ndarray]:
    texts: list[str] = []
    labels: list[list[str]] = []
    label_names = tuple((DATASET_DIR / "emotions.txt").read_text(encoding="utf-8").splitlines())
    if label_names != EMOTIONS:
        raise ValueError("The checked-in GoEmotions label order does not match emotion_labels.py")

    with (DATASET_DIR / f"{name}.tsv").open(encoding="utf-8", newline="") as handle:
        for row in csv.reader(handle, delimiter="\t"):
            if len(row) < 2:
                continue
            text, raw_ids = row[0], row[1]
            if not text.strip() or not raw_ids.strip():
                continue
            ids = [int(value) for value in raw_ids.split(",")]
            if any(value < 0 or value >= len(EMOTIONS) for value in ids):
                raise ValueError(f"Invalid GoEmotions label id in {name}.tsv: {raw_ids}")
            texts.append(text)
            labels.append([EMOTIONS[value] for value in ids])

    return texts, label_binarizer.transform(labels)


def tune_thresholds(y_true: np.ndarray, probabilities: np.ndarray) -> np.ndarray:
    """Choose a per-label F1 threshold using only the validation split."""
    thresholds = np.full(len(EMOTIONS), 0.5, dtype=float)
    for label_index in range(len(EMOTIONS)):
        best_f1, best_threshold = -1.0, 0.5
        for threshold in THRESHOLD_GRID:
            prediction = probabilities[:, label_index] >= threshold
            score = f1_score(
                y_true[:, label_index], prediction, zero_division=0
            )
            if score > best_f1:
                best_f1, best_threshold = score, float(threshold)
        thresholds[label_index] = best_threshold
    return thresholds


def evaluate(name: str, y_true: np.ndarray, probabilities: np.ndarray, thresholds: np.ndarray) -> None:
    encoder = MultiLabelBinarizer(classes=EMOTIONS)
    encoder.fit([list(EMOTIONS)])
    predictions = encoder.transform(decode_emotion_probabilities(probabilities, thresholds))
    print(f"{name}: micro-F1={f1_score(y_true, predictions, average='micro', zero_division=0):.4f}; "
          f"macro-F1={f1_score(y_true, predictions, average='macro', zero_division=0):.4f}; "
          f"samples-F1={f1_score(y_true, predictions, average='samples', zero_division=0):.4f}")
    print(classification_report(y_true, predictions, target_names=EMOTIONS, zero_division=0))


def train() -> None:
    label_binarizer = MultiLabelBinarizer(classes=EMOTIONS)
    label_binarizer.fit([list(EMOTIONS)])
    train_texts, train_labels = load_split("train", label_binarizer)
    dev_texts, dev_labels = load_split("dev", label_binarizer)
    test_texts, test_labels = load_split("test", label_binarizer)

    pipeline = Pipeline(
        [
            (
                "tfidf",
                TfidfVectorizer(
                    ngram_range=(1, 2),
                    min_df=2,
                    max_features=250_000,
                    sublinear_tf=True,
                    strip_accents="unicode",
                    preprocessor=prepare_text,
                ),
            ),
            (
                "classifier",
                OneVsRestClassifier(
                    LogisticRegression(
                        C=4.0,
                        class_weight="balanced",
                        solver="liblinear",
                        max_iter=1000,
                        random_state=42,
                    ),
                    # Avoid joblib memmapping the shared sparse matrix read-only
                    # on macOS; this classifier is small enough to run serially.
                    n_jobs=1,
                ),
            ),
        ]
    )
    print(f"Training multilabel model on {len(train_texts):,} GoEmotions examples...", flush=True)
    pipeline.fit(train_texts, train_labels)

    dev_probabilities = pipeline.predict_proba(dev_texts)
    thresholds = tune_thresholds(dev_labels, dev_probabilities)
    evaluate("Validation", dev_labels, dev_probabilities, thresholds)

    test_probabilities = pipeline.predict_proba(test_texts)
    evaluate("Test", test_labels, test_probabilities, thresholds)

    joblib.dump(
        {
            "model": pipeline,
            "labels": list(EMOTIONS),
            "thresholds": thresholds,
            "dataset": "google-research/goemotions",
        },
        MODEL_PATH,
        compress=3,
    )
    print(f"Saved multilabel GoEmotions model to {MODEL_PATH}")


if __name__ == "__main__":
    train()
