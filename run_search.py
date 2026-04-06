#!/usr/bin/env python3
"""Run all new scrapers and save results to JSONL + SQLite."""

import sys
import os
import argparse
import json
import re
import sqlite3
import traceback
from datetime import date, datetime
from pathlib import Path

# Add JobSpy to path so `from jobspy import scrape_jobs` works
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "JobSpy"))

from jobspy import scrape_jobs
from scripts.import_jsonl import parse_location, parse_date_posted
from scripts.init_db import init_db

DB_PATH = Path("data/jobs.db")


def load_tokens(filepath: str) -> list[str]:
    """Load board tokens from a text file, one per line, skip comments/blanks."""
    tokens = []
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                tokens.append(line)
    return tokens


def load_404_tokens(source: str) -> set[str]:
    """Load previously logged 404 tokens for a source."""
    path = f"tokens/{source}_404.txt"
    if not os.path.exists(path):
        return set()
    return set(load_tokens(path))


def save_404_tokens(source: str, tokens: list[str]):
    """Append newly discovered 404 tokens to the log file."""
    if not tokens:
        return
    path = f"tokens/{source}_404.txt"
    existing = load_404_tokens(source)
    new_tokens = [t for t in tokens if t not in existing]
    if not new_tokens:
        return
    with open(path, "a") as f:
        for token in new_tokens:
            f.write(f"{token}\n")
    print(f"  Logged {len(new_tokens)} new 404 tokens to {path}")


def insert_df_to_db(df, run_id: str, db_path: Path = DB_PATH):
    """Insert a DataFrame of scraped jobs into the SQLite database."""
    if len(df) == 0:
        return 0

    if not db_path.exists():
        init_db(db_path)

    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    # Ensure run exists
    c.execute(
        "INSERT OR IGNORE INTO runs (run_id, started_at) VALUES (?, ?)",
        (run_id, datetime.now().isoformat()),
    )

    def _clean(val):
        """Convert NaN/None to None, everything else to str."""
        if val is None:
            return None
        if isinstance(val, float) and val != val:  # NaN check
            return None
        return val

    inserted = 0
    for _, row in df.iterrows():
        job = {k: _clean(v) for k, v in row.to_dict().items()}
        job_id = job.get("id")
        if not job_id:
            continue

        loc = parse_location(job.get("location"), job.get("is_remote"))

        try:
            c.execute("""
                INSERT OR IGNORE INTO jobs (
                    id, run_id, site, title, company, board_token,
                    location_raw, country, state, city, work_arrangement,
                    date_posted, job_url, job_url_direct, description,
                    job_type, job_function,
                    min_amount, max_amount, currency, salary_interval
                ) VALUES (
                    ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?,
                    ?, ?, ?, ?,
                    ?, ?,
                    ?, ?, ?, ?
                )
            """, (
                job_id,
                run_id,
                job.get("site"),
                job.get("title"),
                job.get("company"),
                job.get("board_token"),
                job.get("location"),
                loc["country"],
                loc["state"],
                loc["city"],
                loc["work_arrangement"],
                parse_date_posted(job.get("date_posted")),
                job.get("job_url"),
                job.get("job_url_direct"),
                job.get("description"),
                job.get("job_type"),
                job.get("job_function"),
                job.get("min_amount"),
                job.get("max_amount"),
                job.get("currency"),
                job.get("interval"),
            ))
            inserted += c.rowcount
        except Exception as e:
            print(f"  DB insert error for {job_id}: {e}", file=sys.stderr)

    # Upsert companies from this batch
    companies_seen = set()
    for _, row in df.iterrows():
        raw = row.get("company")
        company = str(raw).strip() if raw is not None and raw == raw else ""
        if not company:
            continue
        norm = re.sub(r'[^a-z0-9]', '', company.lower())
        if norm in companies_seen:
            continue
        companies_seen.add(norm)
        c.execute("""
            INSERT OR IGNORE INTO companies (name, name_normalized, board_token, site)
            VALUES (?, ?, ?, ?)
        """, (company, norm, row.get("board_token"), row.get("site")))

    conn.commit()
    conn.close()
    return inserted


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
    parser.add_argument("--search-term", default=None)
    parser.add_argument("--results-wanted", type=int, default=99999)
    parser.add_argument("--hours-old", type=int, default=168)
    parser.add_argument(
        "--sources",
        default="remoteok,greenhouse,lever,ashby,hn",
        help="Comma-separated list of sources to scrape",
    )
    args = parser.parse_args()

    sources = [s.strip() for s in args.sources.split(",")]

    os.makedirs("data", exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    run_id = timestamp
    output_path = f"data/jobs_{timestamp}.jsonl"

    # Ensure DB exists
    if not DB_PATH.exists():
        init_db(DB_PATH)

    total_jobs = 0
    total_db = 0

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

            # Load tokens for ATS sources (skip known 404s)
            if source == "greenhouse":
                token_path = resolve_token_path(
                    "tokens/greenhouse.txt", "tokens/greenhouse_raw.txt"
                )
                if token_path is None:
                    print(
                        f"  WARNING: tokens/greenhouse.txt not found, skipping {source}"
                    )
                    continue
                bad = load_404_tokens("greenhouse")
                all_tokens = load_tokens(token_path)
                good_tokens = [t for t in all_tokens if t not in bad]
                if bad:
                    print(f"  Skipping {len(all_tokens) - len(good_tokens)} known-404 tokens")
                kwargs["greenhouse_board_tokens"] = good_tokens

            elif source == "lever":
                token_path = resolve_token_path(
                    "tokens/lever.txt", "tokens/lever_raw.txt"
                )
                if token_path is None:
                    print(f"  WARNING: tokens/lever.txt not found, skipping {source}")
                    continue
                bad = load_404_tokens("lever")
                all_tokens = load_tokens(token_path)
                good_tokens = [t for t in all_tokens if t not in bad]
                if bad:
                    print(f"  Skipping {len(all_tokens) - len(good_tokens)} known-404 tokens")
                kwargs["lever_company_slugs"] = good_tokens

            elif source == "ashby":
                token_path = "tokens/ashby.txt"
                if not os.path.exists(token_path):
                    print(
                        f"  WARNING: {token_path} not found, skipping {source}"
                    )
                    continue
                bad = load_404_tokens("ashby")
                all_tokens = load_tokens(token_path)
                good_tokens = [t for t in all_tokens if t not in bad]
                if bad:
                    print(f"  Skipping {len(all_tokens) - len(good_tokens)} known-404 tokens")
                kwargs["ashby_board_names"] = good_tokens

            df = scrape_jobs(**kwargs)

            # Save any newly discovered 404 tokens
            failed = df.attrs.get("failed_tokens", {})
            if source in failed:
                save_404_tokens(source, failed[source])

            count = len(df)
            total_jobs += count
            print(f"  {source}: {count} jobs")

            if count > 0:
                df.to_json(output_path, orient="records", lines=True, mode="a")
                db_count = insert_df_to_db(df, run_id)
                total_db += db_count
                print(f"  Written to {output_path} + {db_count} to jobs.db")
            else:
                print(f"  0 jobs from {source}, nothing written")

        except Exception as e:
            print(f"  ERROR scraping {source}: {e}")
            traceback.print_exc()

    print(f"\n{'=' * 60}")
    print(f"Total: {total_jobs} jobs saved to {output_path}")
    print(f"       {total_db} new jobs inserted into {DB_PATH}")
    print(f"{'=' * 60}")

    # Update run record with final stats
    if total_db > 0:
        conn = sqlite3.connect(DB_PATH)
        conn.execute(
            "UPDATE runs SET total_jobs = ?, sources = ?, search_term = ? WHERE run_id = ?",
            (total_db, ",".join(sources), args.search_term, run_id),
        )
        conn.commit()
        conn.close()

    # Dedup step
    if total_jobs > 0 and os.path.exists(output_path):
        from scripts.dedup import dedup_jsonl

        deduped_path = output_path.replace(".jsonl", "_deduped.jsonl")
        orig, deduped = dedup_jsonl(output_path, deduped_path)
        print(f"Deduped: {orig} -> {deduped} jobs ({orig - deduped} duplicates removed)")


if __name__ == "__main__":
    main()
