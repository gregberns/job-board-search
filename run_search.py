#!/usr/bin/env python3
"""Run all new scrapers and save results as incremental JSONL."""

import sys
import os
import argparse
import traceback
from datetime import date

# Add JobSpy to path so `from jobspy import scrape_jobs` works
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "JobSpy"))

from jobspy import scrape_jobs


def load_tokens(filepath: str) -> list[str]:
    """Load board tokens from a text file, one per line, skip comments/blanks."""
    tokens = []
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                tokens.append(line)
    return tokens


def resolve_token_path(preferred: str, fallback: str) -> str | None:
    """Return the first existing token path, or None if neither exists."""
    if os.path.exists(preferred):
        return preferred
    if os.path.exists(fallback):
        print(f"  NOTE: {preferred} not found, using {fallback}")
        return fallback
    return None


def main():
    parser = argparse.ArgumentParser(
        description="Run job scrapers and save JSONL output"
    )
    parser.add_argument("--search-term", default="software engineer")
    parser.add_argument("--results-wanted", type=int, default=1000)
    parser.add_argument("--hours-old", type=int, default=168)
    parser.add_argument(
        "--sources",
        default="remoteok,greenhouse,lever,ashby,hn",
        help="Comma-separated list of sources to scrape",
    )
    args = parser.parse_args()

    sources = [s.strip() for s in args.sources.split(",")]

    os.makedirs("data", exist_ok=True)
    output_path = f"data/jobs_{date.today().isoformat()}.jsonl"

    total_jobs = 0

    for source in sources:
        print(f"\n{'=' * 60}")
        print(f"Scraping: {source}")
        print(f"{'=' * 60}")

        try:
            kwargs: dict = {
                "site_name": source,
                "search_term": args.search_term,
                "results_wanted": args.results_wanted,
                "hours_old": args.hours_old,
            }

            # Load tokens for ATS sources
            if source == "greenhouse":
                token_path = resolve_token_path(
                    "tokens/greenhouse.txt", "tokens/greenhouse_raw.txt"
                )
                if token_path is None:
                    print(
                        f"  WARNING: tokens/greenhouse.txt not found, skipping {source}"
                    )
                    continue
                kwargs["greenhouse_board_tokens"] = load_tokens(token_path)

            elif source == "lever":
                token_path = resolve_token_path(
                    "tokens/lever.txt", "tokens/lever_raw.txt"
                )
                if token_path is None:
                    print(f"  WARNING: tokens/lever.txt not found, skipping {source}")
                    continue
                kwargs["lever_company_slugs"] = load_tokens(token_path)

            elif source == "ashby":
                token_path = "tokens/ashby.txt"
                if not os.path.exists(token_path):
                    print(
                        f"  WARNING: {token_path} not found, skipping {source}"
                    )
                    continue
                kwargs["ashby_board_names"] = load_tokens(token_path)

            df = scrape_jobs(**kwargs)

            count = len(df)
            total_jobs += count
            print(f"  {source}: {count} jobs")

            if count > 0:
                df.to_json(output_path, orient="records", lines=True, mode="a")
                print(f"  Written to {output_path}")
            else:
                print(f"  0 jobs from {source}, nothing written")

        except Exception as e:
            print(f"  ERROR scraping {source}: {e}")
            traceback.print_exc()

    print(f"\n{'=' * 60}")
    print(f"Total: {total_jobs} jobs saved to {output_path}")
    print(f"{'=' * 60}")

    # Dedup step
    if total_jobs > 0 and os.path.exists(output_path):
        from scripts.dedup import dedup_jsonl

        deduped_path = output_path.replace(".jsonl", "_deduped.jsonl")
        orig, deduped = dedup_jsonl(output_path, deduped_path)
        print(f"Deduped: {orig} -> {deduped} jobs ({orig - deduped} duplicates removed)")


if __name__ == "__main__":
    main()
