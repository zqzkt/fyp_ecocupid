import os
import sys
import subprocess
from datetime import date, timedelta
from pathlib import Path


# ==========================================================
# SETTINGS
# ==========================================================

SCRIPT_DIR = Path(__file__).resolve().parent

NEWS_SCRAPERS = [
    "SG_news.py",
    "MY_news.py",
    "ID_news.py",
    "PH_news.py",
    "TH_news.py",
    "BN_news.py",
]


# ==========================================================
# DATE RANGE
# ==========================================================

TODAY = date.today()

START_DATE = TODAY - timedelta(days=7)
END_DATE = TODAY

START_DATE_STR = START_DATE.strftime("%Y-%m-%d")
END_DATE_STR = END_DATE.strftime("%Y-%m-%d")


# ==========================================================
# RUN ONE SCRAPER
# ==========================================================

def run_scraper(scraper_filename):

    scraper_path = SCRIPT_DIR / scraper_filename

    print()
    print("=" * 70)
    print(f"RUNNING: {scraper_filename}")
    print("=" * 70)

    if not scraper_path.exists():
        print(f"SKIPPED: File not found: {scraper_path}")

        return {
            "file": scraper_filename,
            "status": "FILE NOT FOUND"
        }

    env = os.environ.copy()

    env["NEWS_START_DATE"] = START_DATE_STR
    env["NEWS_END_DATE"] = END_DATE_STR

    try:
        result = subprocess.run(
            [
                sys.executable,
                str(scraper_path)
            ],
            cwd=str(SCRIPT_DIR),
            env=env,
            check=False
        )

        if result.returncode == 0:

            print()
            print(f"COMPLETED: {scraper_filename}")

            return {
                "file": scraper_filename,
                "status": "SUCCESS"
            }

        else:

            print()
            print(
                f"FAILED: {scraper_filename} "
                f"(exit code {result.returncode})"
            )

            return {
                "file": scraper_filename,
                "status": f"FAILED ({result.returncode})"
            }

    except Exception as e:

        print()
        print(
            f"ERROR running {scraper_filename}: {e}"
        )

        return {
            "file": scraper_filename,
            "status": f"ERROR: {e}"
        }


# ==========================================================
# MAIN
# ==========================================================

def main():

    print()
    print("=" * 70)
    print("NEWS DATA PIPELINE")
    print("=" * 70)

    print(
        f"Collection window: "
        f"{START_DATE_STR} to {END_DATE_STR}"
    )

    print(
        f"Number of scraper files configured: "
        f"{len(NEWS_SCRAPERS)}"
    )

    results = []

    for scraper_filename in NEWS_SCRAPERS:

        result = run_scraper(
            scraper_filename
        )

        results.append(
            result
        )

    print()
    print("=" * 70)
    print("PIPELINE SUMMARY")
    print("=" * 70)

    for result in results:

        print(
            f"{result['file']:<40} "
            f"{result['status']}"
        )

    successful = sum(
        1
        for result in results
        if result["status"] == "SUCCESS"
    )

    print()
    print(
        f"Successful: {successful}/{len(results)}"
    )

    print(
        f"Date range: {START_DATE_STR} "
        f"to {END_DATE_STR}"
    )

    print("=" * 70)


if __name__ == "__main__":
    main()
