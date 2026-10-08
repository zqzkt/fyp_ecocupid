import os
import sys
import subprocess
from datetime import date, timedelta
from pathlib import Path


# ==========================================================
# SETTINGS
# ==========================================================

SCRIPT_DIR = Path(__file__).resolve().parent
NEWS_RAW_DIR = SCRIPT_DIR / "News_raw"
NEWS_PROCESSED_DIR = SCRIPT_DIR / "News_processed"

NEWS_SCRAPERS = [
    "SG_news.py",
    "MY_news.py",
    "ID_news.py",
    "PH_news.py",
    "TH_news.py",
    "BN_news.py",
]

NEWS_CLEANED_SCRIPT = NEWS_PROCESSED_DIR / "News_cleaned.py"
NEWS_TOPIC_SCRIPT = NEWS_PROCESSED_DIR / "News_topic.py"


# ==========================================================
# PREVIOUS CALENDAR MONTH
# ==========================================================

TODAY = date.today()

FIRST_DAY_CURRENT_MONTH = TODAY.replace(day=1)
END_DATE = FIRST_DAY_CURRENT_MONTH - timedelta(days=1)
START_DATE = END_DATE.replace(day=1)

START_DATE_STR = START_DATE.strftime("%Y-%m-%d")
END_DATE_STR = END_DATE.strftime("%Y-%m-%d")


# ==========================================================
# RUN PYTHON SCRIPT
# ==========================================================

def run_python_script(script_path, display_name, extra_env=None):
    print()
    print("=" * 70)
    print(f"CURRENTLY RUNNING: {display_name}")
    print("=" * 70)
    print(f"File: {script_path}")
    print("-" * 70)

    if not script_path.exists():
        print(f"\nSKIPPED: File not found: {script_path}")
        return {
            "file": display_name,
            "status": "FILE NOT FOUND",
        }

    env = os.environ.copy()

    if extra_env:
        env.update(extra_env)

    try:
        # subprocess.run() waits until this script finishes.
        # Therefore the next scraper will NOT start until the
        # current scraper has completed.
        result = subprocess.run(
            [sys.executable, str(script_path)],
            cwd=str(script_path.parent),
            env=env,
            check=False,
        )

        if result.returncode == 0:
            print()
            print("-" * 70)
            print(f"COMPLETED: {display_name}")
            print("-" * 70)

            return {
                "file": display_name,
                "status": "SUCCESS",
            }

        print()
        print("-" * 70)
        print(
            f"FAILED: {display_name} "
            f"(exit code {result.returncode})"
        )
        print("-" * 70)

        return {
            "file": display_name,
            "status": f"FAILED ({result.returncode})",
        }

    except Exception as e:
        print()
        print("-" * 70)
        print(f"ERROR running {display_name}: {e}")
        print("-" * 70)

        return {
            "file": display_name,
            "status": f"ERROR: {e}",
        }


# ==========================================================
# RUN RAW NEWS SCRAPER
# ==========================================================

def run_scraper(scraper_filename):
    scraper_path = NEWS_RAW_DIR / scraper_filename

    scraper_env = {
        "NEWS_START_DATE": START_DATE_STR,
        "NEWS_END_DATE": END_DATE_STR,
    }

    return run_python_script(
        scraper_path,
        scraper_filename,
        extra_env=scraper_env,
    )


# ==========================================================
# PIPELINE INFORMATION
# ==========================================================

def print_pipeline_settings():
    print()
    print("=" * 70)
    print("NEWS DATA PIPELINE")
    print("=" * 70)

    print(f"Pipeline run date: {TODAY}")
    print(
        f"Collection period: "
        f"{START_DATE_STR} to {END_DATE_STR}"
    )
    print("Period: Previous complete calendar month")

    print(f"Raw scraper folder: {NEWS_RAW_DIR}")
    print(f"Processed folder: {NEWS_PROCESSED_DIR}")

    print()
    print("Pipeline order:")
    print("  1. Run 6 country news scrapers ONE BY ONE")
    print("  2. Run News_cleaned.py")
    print("  3. Run News_topic.py")

    print()
    print("News scraper order:")

    for index, scraper in enumerate(
        NEWS_SCRAPERS,
        start=1,
    ):
        print(
            f"  {index}. {scraper}"
        )


# ==========================================================
# PIPELINE SUMMARY
# ==========================================================

def print_summary(results):
    print()
    print("=" * 70)
    print("PIPELINE SUMMARY")
    print("=" * 70)

    for result in results:
        print(
            f"{result['file']:<30} "
            f"{result['status']}"
        )

    successful = sum(
        result["status"] == "SUCCESS"
        for result in results
    )

    print()
    print(
        f"Successful: "
        f"{successful}/{len(results)}"
    )

    print(
        f"Collection period: "
        f"{START_DATE_STR} to {END_DATE_STR}"
    )

    print("=" * 70)


# ==========================================================
# MAIN
# ==========================================================

def main():
    print_pipeline_settings()

    results = []

    # ------------------------------------------------------
    # STEP 1: RAW NEWS COLLECTION
    # ------------------------------------------------------

    print()
    print()
    print("#" * 70)
    print("STEP 1/3: RAW NEWS COLLECTION")
    print("#" * 70)

    scraper_results = []

    total_scrapers = len(NEWS_SCRAPERS)

    # Run each scraper ONE AT A TIME.
    #
    # The next scraper only starts after the current
    # scraper has completely finished.
    for index, scraper in enumerate(
        NEWS_SCRAPERS,
        start=1,
    ):
        print()
        print()
        print("#" * 70)
        print(
            f"NEWS SCRAPER {index}/{total_scrapers}"
        )
        print(f"CURRENT FILE: {scraper}")
        print("#" * 70)

        result = run_scraper(scraper)

        scraper_results.append(result)
        results.append(result)

        print()
        print(
            f"SCRAPER {index}/{total_scrapers} FINISHED: "
            f"{scraper}"
        )
        print(
            f"STATUS: {result['status']}"
        )

        # Show which scraper will run next.
        if index < total_scrapers:
            next_scraper = NEWS_SCRAPERS[index]

            print()
            print(
                f"NEXT SCRAPER: {next_scraper}"
            )

    # ------------------------------------------------------
    # SCRAPER FAILURE CHECK
    # ------------------------------------------------------

    scraper_failures = [
        result
        for result in scraper_results
        if result["status"] != "SUCCESS"
    ]

    if scraper_failures:
        print()
        print("=" * 70)
        print(
            f"WARNING: "
            f"{len(scraper_failures)} "
            f"news scraper(s) failed."
        )
        print("=" * 70)

        for failure in scraper_failures:
            print(
                f"  - {failure['file']}: "
                f"{failure['status']}"
            )

        print()
        print(
            "News_cleaned.py will still run using articles "
            "successfully collected by the other scrapers."
        )

    else:
        print()
        print("=" * 70)
        print("ALL 6 NEWS SCRAPERS COMPLETED SUCCESSFULLY")
        print("=" * 70)

    # ------------------------------------------------------
    # STEP 2: CLEAN AND CLASSIFY
    # ------------------------------------------------------

    print()
    print()
    print("#" * 70)
    print("STEP 2/3: NEWS CLEANING")
    print("#" * 70)

    cleaned_result = run_python_script(
        NEWS_CLEANED_SCRIPT,
        "News_cleaned.py",
    )

    results.append(cleaned_result)

    # Topic modelling depends on successful cleaning.
    if cleaned_result["status"] != "SUCCESS":
        print()
        print("=" * 70)
        print("PIPELINE STOPPED")
        print("=" * 70)

        print("News_cleaned.py failed.")
        print(
            "News_topic.py will not run because "
            "it depends on cleaned data."
        )

        print_summary(results)

        return

    # ------------------------------------------------------
    # STEP 3: TOPIC MODELLING
    # ------------------------------------------------------

    print()
    print()
    print("#" * 70)
    print("STEP 3/3: TOPIC MODELLING")
    print("#" * 70)

    topic_result = run_python_script(
        NEWS_TOPIC_SCRIPT,
        "News_topic.py",
    )

    results.append(topic_result)

    # ------------------------------------------------------
    # FINAL SUMMARY
    # ------------------------------------------------------

    print_summary(results)


# ==========================================================
# RUN
# ==========================================================

if __name__ == "__main__":
    main()
