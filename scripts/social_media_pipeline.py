"""Run all social-media collectors, cleaning, and sentiment analysis."""

from __future__ import annotations

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
CLEANER = REPO_ROOT / "scripts" / "cleaning" / "clean_social.py"
SENTIMENT_ANALYSIS = (
    REPO_ROOT / "scripts" / "sentiment" / "sentiment_analysis.py"
)


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


def main() -> int:
    results: list[tuple[str, bool]] = []

    print("SOCIAL MEDIA PIPELINE")
    print("Collectors run sequentially before cleaning and sentiment analysis.")

    for collector in SOCIAL_MEDIA_COLLECTORS:
        results.append(
            run_script(
                SOURCES_DIR / collector,
                collector,
            )
        )

    # Clean any data collected successfully, even if another collector failed.
    cleaner_name, cleaner_succeeded = run_script(CLEANER, "clean_social.py")
    results.append((cleaner_name, cleaner_succeeded))

    if cleaner_succeeded:
        results.append(
            run_script(
                SENTIMENT_ANALYSIS,
                "sentiment_analysis.py",
                ("--run-now",),
            )
        )
    else:
        print()
        print("Skipping sentiment_analysis.py because social cleaning failed.")

    print_summary(results)
    return 0 if all(succeeded for _, succeeded in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
