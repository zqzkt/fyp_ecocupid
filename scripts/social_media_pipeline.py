"""Run social-media collectors, cleaning, environmental filtering, and sentiment."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCES_DIR = REPO_ROOT / "scripts" / "sources"

SOCIAL_MEDIA_COLLECTORS = (
    "facebook.py",
    "instagram_apify.py",
    "reddit_apify.py",
    "twitter.py",
    "youtube_videos.py",
)
COLLECTOR_BY_PLATFORM = {
    "facebook": "facebook.py",
    "instagram": "instagram_apify.py",
    "reddit": "reddit_apify.py",
    "x": "twitter.py",
    "youtube": "youtube_videos.py",
}
CLEANER = REPO_ROOT / "scripts" / "cleaning" / "clean_social.py"
SENTIMENT_ANALYSIS = (
    REPO_ROOT / "scripts" / "sentiment" / "sentiment_analysis.py"
)
ENVIRONMENTAL_FILTER = (
    REPO_ROOT / "scripts" / "cleaning" / "filter_environmental.py"
)


def run_cleaner() -> None:
    """Refresh the shared clean tables after a successful raw-data upload."""
    print("Raw data uploaded; cleaning all available platform tables...")
    try:
        subprocess.run(
            [sys.executable, str(CLEANER)],
            cwd=REPO_ROOT,
            check=True,
        )
    except subprocess.CalledProcessError as error:
        raise SystemExit(
            f"Cleaning failed with exit code {error.returncode}; "
            "raw rows remain stored, but the clean tables may be incomplete."
        ) from error


def run_environmental_filter() -> None:
    """Classify clean social posts as environmentally related."""
    print("Clean tables refreshed; classifying environmental posts...")
    try:
        subprocess.run(
            [sys.executable, str(ENVIRONMENTAL_FILTER)],
            cwd=REPO_ROOT,
            check=True,
        )
    except subprocess.CalledProcessError as error:
        raise SystemExit(
            f"Environmental filtering failed with exit code {error.returncode}; "
            "environmental labels may be incomplete."
        ) from error


def run_sentiment(*, platform: str | None = None, dry_run: bool = False) -> None:
    """Rebuild environment sentiment after raw data has been cleaned."""
    print("Clean tables refreshed; deriving environment sentiment...")
    command = [sys.executable, str(SENTIMENT_ANALYSIS), "--all"]
    if platform:
        command.extend(("--platform", platform))
    if dry_run:
        command.append("--dry-run")
    try:
        subprocess.run(command, cwd=REPO_ROOT, check=True)
    except subprocess.CalledProcessError as error:
        raise SystemExit(
            f"Sentiment derivation failed with exit code {error.returncode}; "
            "raw and clean rows remain stored, but sentiment_analysis may be stale."
        ) from error


def run_script(
    script_path: Path,
    display_name: str,
    args: tuple[str, ...] = (),
) -> tuple[str, bool]:
    """Run one pipeline step and return its display name and success state."""
    print()
    print("=" * 70)
    print(f"RUNNING: {display_name}")
    print("=" * 70)

    if not script_path.is_file():
        print(f"FAILED: File not found: {script_path}")
        return display_name, False

    try:
        result = subprocess.run(
            [sys.executable, str(script_path), *args],
            cwd=REPO_ROOT,
            check=False,
        )
    except OSError as error:
        print(f"FAILED: Could not start {display_name}: {error}")
        return display_name, False

    if result.returncode == 0:
        print(f"COMPLETED: {display_name}")
        return display_name, True

    print(f"FAILED: {display_name} (exit code {result.returncode})")
    return display_name, False


def print_summary(results: list[tuple[str, bool]]) -> None:
    print()
    print("=" * 70)
    print("SOCIAL MEDIA PIPELINE SUMMARY")
    print("=" * 70)
    for name, succeeded in results:
        print(f"{name:<30} {'SUCCESS' if succeeded else 'FAILED'}")

    successes = sum(succeeded for _, succeeded in results)
    print()
    print(f"Successful: {successes}/{len(results)}")
    print("=" * 70)


def main(platform: str | None = None) -> int:
    results: list[tuple[str, bool]] = []

    print("SOCIAL MEDIA PIPELINE")
    print(
        "Collectors run sequentially before shared cleaning, environmental "
        "filtering, and sentiment analysis."
    )

    collectors = (
        (COLLECTOR_BY_PLATFORM[platform],)
        if platform is not None
        else SOCIAL_MEDIA_COLLECTORS
    )
    collector_results = [
        run_script(SOURCES_DIR / collector, collector)
        for collector in collectors
    ]
    results.extend(collector_results)

    cleaner_name, cleaner_succeeded = run_script(CLEANER, "clean_social.py")
    results.append((cleaner_name, cleaner_succeeded))

    if cleaner_succeeded:
        environmental_name, environmental_succeeded = run_script(
            ENVIRONMENTAL_FILTER,
            "filter_environmental.py",
        )
        results.append((environmental_name, environmental_succeeded))
        if environmental_succeeded:
            results.append(
                run_script(
                    SENTIMENT_ANALYSIS,
                    "sentiment_analysis.py",
                    ("--run-now",),
                )
            )
        else:
            print()
            print("Skipping sentiment_analysis.py because environmental filtering failed.")
    else:
        print()
        print("Skipping environmental filtering and sentiment because social cleaning failed.")

    print_summary(results)
    return 0 if all(succeeded for _, succeeded in results) else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Collect social-media data and run shared processing."
    )
    parser.add_argument(
        "--platform",
        choices=tuple(COLLECTOR_BY_PLATFORM),
        help="Collect one platform, then run shared cleaning, filtering, and sentiment.",
    )
    args = parser.parse_args()
    raise SystemExit(main(platform=args.platform))
