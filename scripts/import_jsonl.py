#!/usr/bin/env python3
"""Import a classified JSONL file into the SQLite jobs database.

Usage:
    python scripts/import_jsonl.py data/jobs_2026-04-05_210921_classified.jsonl
    python scripts/import_jsonl.py data/jobs_2026-04-05_210921_classified.jsonl --run-id 2026-04-05_210921
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "jobs.db"

# --- Location parsing ---

US_STATES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
    "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
    "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
    "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
    "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY", "DC",
}

US_STATE_NAMES = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR",
    "california": "CA", "colorado": "CO", "connecticut": "CT", "delaware": "DE",
    "florida": "FL", "georgia": "GA", "hawaii": "HI", "idaho": "ID",
    "illinois": "IL", "indiana": "IN", "iowa": "IA", "kansas": "KS",
    "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD",
    "massachusetts": "MA", "michigan": "MI", "minnesota": "MN",
    "mississippi": "MS", "missouri": "MO", "montana": "MT", "nebraska": "NE",
    "nevada": "NV", "new hampshire": "NH", "new jersey": "NJ",
    "new mexico": "NM", "new york": "NY", "north carolina": "NC",
    "north dakota": "ND", "ohio": "OH", "oklahoma": "OK", "oregon": "OR",
    "pennsylvania": "PA", "rhode island": "RI", "south carolina": "SC",
    "south dakota": "SD", "tennessee": "TN", "texas": "TX", "utah": "UT",
    "vermont": "VT", "virginia": "VA", "washington": "WA",
    "west virginia": "WV", "wisconsin": "WI", "wyoming": "WY",
    "district of columbia": "DC",
}

COUNTRY_MARKERS = {
    "united states": "US", "usa": "US", ", us": "US",
    "united kingdom": "GB", ", uk": "GB",
    "canada": "CA", ", ca ": "CA",
    "germany": "DE", "deutschland": "DE",
    "france": "FR", "ireland": "IE", "netherlands": "NL",
    "australia": "AU", "india": "IN", "japan": "JP",
    "singapore": "SG", "brazil": "BR", "israel": "IL",
    "spain": "ES", "italy": "IT", "sweden": "SE", "norway": "NO",
    "denmark": "DK", "finland": "FI", "poland": "PL",
    "switzerland": "CH", "austria": "AT", "belgium": "BE",
    "portugal": "PT", "czech": "CZ", "romania": "RO",
    "mexico": "MX", "colombia": "CO", "argentina": "AR",
    "south korea": "KR", "korea": "KR", "china": "CN",
    "taiwan": "TW", "hong kong": "HK", "philippines": "PH",
    "vietnam": "VN", "thailand": "TH", "indonesia": "ID",
    "malaysia": "MY", "new zealand": "NZ", "ukraine": "UA",
    "turkey": "TR",
}

REMOTE_KEYWORDS = {"remote", "anywhere", "worldwide", "distributed", "work from home", "wfh"}
HYBRID_KEYWORDS = {"hybrid"}
ONSITE_KEYWORDS = {"on-site", "onsite", "in-office", "in office"}


def parse_location(location_raw: str | None, is_remote: bool | None) -> dict:
    """Parse a raw location string into country, state, city, work_arrangement."""
    result = {"country": None, "state": None, "city": None, "work_arrangement": "unknown"}

    if is_remote:
        result["work_arrangement"] = "remote"

    if not location_raw:
        return result

    loc = location_raw.strip()
    loc_lower = loc.lower()

    # Detect work arrangement from location string
    if any(kw in loc_lower for kw in REMOTE_KEYWORDS):
        result["work_arrangement"] = "remote"
    elif any(kw in loc_lower for kw in HYBRID_KEYWORDS):
        result["work_arrangement"] = "hybrid"
    elif any(kw in loc_lower for kw in ONSITE_KEYWORDS):
        result["work_arrangement"] = "onsite"

    # Detect country
    for marker, code in COUNTRY_MARKERS.items():
        if marker in loc_lower:
            result["country"] = code
            break

    # Try "City, ST" pattern (US)
    m = re.search(r'([A-Za-z\s.]+),\s*([A-Z]{2})\b', loc)
    if m and m.group(2) in US_STATES:
        result["city"] = m.group(1).strip()
        result["state"] = m.group(2)
        result["country"] = "US"
        return result

    # Try full state names
    for state_name, abbr in US_STATE_NAMES.items():
        if state_name in loc_lower:
            result["state"] = abbr
            result["country"] = "US"
            # City is usually before the state name
            idx = loc_lower.index(state_name)
            city_part = loc[:idx].rstrip(", ").strip()
            if city_part and city_part.lower() not in REMOTE_KEYWORDS:
                result["city"] = city_part
            return result

    # If we found a country but no city yet, try to extract city
    if result["country"] and "," in loc:
        parts = [p.strip() for p in loc.split(",")]
        for part in parts:
            part_lower = part.lower()
            if (part_lower not in COUNTRY_MARKERS
                    and part_lower not in REMOTE_KEYWORDS
                    and part_lower not in HYBRID_KEYWORDS
                    and len(part) > 1
                    and part not in US_STATES):
                result["city"] = part
                break

    return result


def parse_date_posted(val) -> str | None:
    """Convert date_posted (epoch ms, ISO string, or date) to YYYY-MM-DD."""
    if val is None:
        return None
    if isinstance(val, (int, float)) and val > 1e9:
        # Epoch milliseconds
        try:
            return datetime.fromtimestamp(val / 1000, tz=None).strftime("%Y-%m-%d")
        except (OSError, ValueError):
            return None
    if isinstance(val, str):
        # Already a date string
        return val[:10] if len(val) >= 10 else val
    return str(val)


def import_jsonl(jsonl_path: Path, run_id: str, db_path: Path = DB_PATH):
    """Import a JSONL file into the database."""
    # Ensure DB exists
    from init_db import init_db
    if not db_path.exists():
        init_db(db_path)

    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    # Insert run record
    c.execute(
        "INSERT OR IGNORE INTO runs (run_id, started_at) VALUES (?, ?)",
        (run_id, datetime.now().isoformat()),
    )

    # Load and insert jobs
    inserted = 0
    skipped = 0

    with open(jsonl_path) as f:
        for line in f:
            job = json.loads(line)
            job_id = job.get("id")
            if not job_id:
                skipped += 1
                continue

            # Parse location
            loc = parse_location(job.get("location"), job.get("is_remote"))

            # Map ai_native bool -> confidence float
            ai_native_raw = job.get("ai_native")
            if ai_native_raw is True:
                ai_native = 0.8  # Haiku said yes, default high confidence
            elif ai_native_raw is False:
                ai_native = 0.0
            elif isinstance(ai_native_raw, (int, float)):
                ai_native = float(ai_native_raw)
            else:
                ai_native = None

            try:
                c.execute("""
                    INSERT OR REPLACE INTO jobs (
                        id, run_id, site, title, company, board_token,
                        location_raw, country, state, city, work_arrangement,
                        date_posted, job_url, job_url_direct, description,
                        job_type, job_function,
                        min_amount, max_amount, currency, salary_interval,
                        engineering_role, ai_native, seniority, domain, industry
                    ) VALUES (
                        ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?,
                        ?, ?, ?, ?,
                        ?, ?,
                        ?, ?, ?, ?,
                        ?, ?, ?, ?, ?
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
                    job.get("engineering_role"),
                    ai_native,
                    job.get("seniority"),
                    job.get("domain"),
                    job.get("industry"),
                ))
                inserted += 1
            except Exception as e:
                print(f"  Error inserting {job_id}: {e}", file=sys.stderr)
                skipped += 1

    # Update run total
    c.execute("UPDATE runs SET total_jobs = ? WHERE run_id = ?", (inserted, run_id))

    conn.commit()
    conn.close()
    print(f"Imported {inserted} jobs (skipped {skipped}) into {db_path}")


def main():
    parser = argparse.ArgumentParser(description="Import classified JSONL into jobs.db")
    parser.add_argument("jsonl_file", type=Path, help="Path to JSONL file")
    parser.add_argument(
        "--run-id",
        help="Run ID (default: extracted from filename, e.g. 2026-04-05_210921)",
    )
    parser.add_argument("--db", type=Path, default=DB_PATH, help="Database path")
    args = parser.parse_args()

    if not args.jsonl_file.exists():
        print(f"File not found: {args.jsonl_file}", file=sys.stderr)
        sys.exit(1)

    # Extract run_id from filename if not provided
    run_id = args.run_id
    if not run_id:
        m = re.search(r"jobs_(\d{4}-\d{2}-\d{2}_\d{6})", args.jsonl_file.name)
        if m:
            run_id = m.group(1)
        else:
            run_id = args.jsonl_file.stem

    import_jsonl(args.jsonl_file, run_id, args.db)


if __name__ == "__main__":
    main()
