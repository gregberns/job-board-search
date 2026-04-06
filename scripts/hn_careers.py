#!/usr/bin/env python3
"""HN Careers Page Pipeline — discover and scrape job listings from HN companies.

Usage:
    python scripts/hn_careers.py harvest-ats   # Phase 1: extract ATS tokens from HN URLs
    python scripts/hn_careers.py discover      # Phase 2: find careers pages
    python scripts/hn_careers.py detect-ats    # Phase 3: detect ATS embeds in careers pages
    python scripts/hn_careers.py extract       # Phase 4: extract jobs from custom pages
    python scripts/hn_careers.py run-all       # All phases in sequence
    python scripts/hn_careers.py status        # Show pipeline status
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse, unquote

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "JobSpy"))

from jobspy.util import create_session, html_to_markdown

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "jobs.db"
TOKENS_DIR = Path(__file__).resolve().parent.parent / "tokens"

# --- ATS URL patterns ---

ATS_URL_PATTERNS = {
    "ashby": [
        (r'jobs\.ashbyhq\.com/([^/?#]+)', 1),
    ],
    "greenhouse": [
        (r'(?:boards|job-boards)(?:\.eu)?\.greenhouse\.io/(?:embed/job_board\?for=)?([^/?#&]+)', 1),
        (r'grnh\.se/', None),  # shortlink, needs redirect follow
    ],
    "lever": [
        (r'jobs(?:\.eu)?\.lever\.co/([^/?#]+)', 1),
    ],
}

# ATS indicators in HTML (for Phase 3)
ATS_HTML_PATTERNS = {
    "greenhouse": [
        (r'(?:boards|job-boards)(?:\.eu)?\.greenhouse\.io/(?:embed/job_board\?for=)?([^/?#&"\']+)', 1),
        (r'id=["\']grnhse_app["\']', None),
        (r'grnh\.se/([a-zA-Z0-9]+)', None),
    ],
    "lever": [
        (r'jobs(?:\.eu)?\.lever\.co/([^/?#"\']+)', 1),
        (r'lever\.co/embed', None),
    ],
    "ashby": [
        (r'jobs\.ashbyhq\.com/([^/?#"\']+)', 1),
    ],
}

CAREERS_PATH_KEYWORDS = [
    "/careers", "/jobs", "/join", "/about/careers", "/company/careers",
    "/work-with-us", "/hiring", "/open-positions", "/join-us", "/opportunities",
]

DEAD_END_DOMAINS = {
    "linkedin.com", "youtube.com", "twitter.com", "x.com", "github.com",
    "docs.google.com", "drive.google.com", "t.me", "telegram.me",
    "medium.com", "substack.com", "notion.so",
}

CAREERS_LINK_KEYWORDS = {"career", "job", "hiring", "join", "position", "opening", "work with"}


# --- Utility functions ---

def get_db(db_path: Path = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def load_existing_tokens(ats: str) -> set[str]:
    """Load all existing tokens for an ATS from token files."""
    tokens = set()
    for suffix in ["", "_raw"]:
        path = TOKENS_DIR / f"{ats}{suffix}.txt"
        if path.exists():
            for line in path.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    tokens.add(line.lower())
    return tokens


def append_tokens(ats: str, new_tokens: list[str]):
    """Append new tokens to the raw token file."""
    if not new_tokens:
        return
    path = TOKENS_DIR / f"{ats}_raw.txt"
    # For ashby, use the main file since there's no raw
    if ats == "ashby":
        path = TOKENS_DIR / "ashby.txt"
    existing = load_existing_tokens(ats)
    to_add = [t for t in new_tokens if t.lower() not in existing]
    if not to_add:
        return
    with open(path, "a") as f:
        for token in to_add:
            f.write(f"{token}\n")
    print(f"  Appended {len(to_add)} new tokens to {path}")


def extract_domain(url: str) -> str | None:
    """Extract the base domain from a URL."""
    try:
        parsed = urlparse(url)
        return parsed.netloc.lower().removeprefix("www.")
    except Exception:
        return None


def is_dead_end(url: str) -> bool:
    """Check if URL is a known non-scrapeable destination."""
    domain = extract_domain(url)
    if not domain:
        return True
    return any(domain.endswith(d) for d in DEAD_END_DOMAINS)


def is_careers_url(url: str) -> bool:
    """Check if URL path suggests it's a careers page."""
    try:
        path = urlparse(url).path.lower()
        return any(kw in path for kw in ["/career", "/jobs", "/hiring", "/join", "/work", "/position", "/opening"])
    except Exception:
        return False


def normalize_company(name: str) -> str:
    return re.sub(r'[^a-z0-9]', '', name.lower())


# --- Phase 1: Harvest ATS Tokens ---

def harvest_ats(db_path: Path = DB_PATH):
    """Extract ATS tokens from HN job URLs and append to token files."""
    print("Phase 1: Harvesting ATS tokens from HN URLs")
    conn = get_db(db_path)

    rows = conn.execute(
        "SELECT id, company, job_url FROM jobs WHERE site = 'hn' AND job_url IS NOT NULL"
    ).fetchall()
    print(f"  Found {len(rows)} HN jobs with URLs")

    new_tokens: dict[str, list[str]] = {"ashby": [], "greenhouse": [], "lever": []}
    ats_entries = []

    for row in rows:
        job_id, company, url = row["id"], row["company"], row["job_url"]
        if not url:
            continue

        for ats, patterns in ATS_URL_PATTERNS.items():
            for pattern, group_idx in patterns:
                m = re.search(pattern, url)
                if m:
                    token = unquote(m.group(group_idx)) if group_idx and m.lastindex else None
                    if token:
                        new_tokens[ats].append(token)
                    ats_entries.append((job_id, company, url, ats, token))
                    break
            else:
                continue
            break

    # Append new tokens to files
    for ats, tokens in new_tokens.items():
        if tokens:
            append_tokens(ats, tokens)

    # Populate hn_career_pages table
    now = datetime.now().isoformat()
    for job_id, company, url, ats, token in ats_entries:
        conn.execute("""
            INSERT OR REPLACE INTO hn_career_pages
                (hn_job_id, company_name, company_url, ats_platform, ats_token, page_type, status, last_checked)
            VALUES (?, ?, ?, ?, ?, 'ats', 'discovered', ?)
        """, (job_id, company, url, ats, token, now))

    # Insert all non-ATS HN jobs as pending
    ats_job_ids = {e[0] for e in ats_entries}
    for row in rows:
        if row["id"] not in ats_job_ids:
            conn.execute("""
                INSERT OR IGNORE INTO hn_career_pages
                    (hn_job_id, company_name, company_url, status)
                VALUES (?, ?, ?, 'pending')
            """, (row["id"], row["company"], row["job_url"]))

    # Backfill companies.url
    updated_urls = 0
    for row in rows:
        url = row["job_url"]
        company = (row["company"] or "").strip()
        if not company or not url or "news.ycombinator.com" in url:
            continue
        norm = normalize_company(company)
        result = conn.execute(
            "UPDATE companies SET url = ? WHERE name_normalized = ? AND url IS NULL",
            (url, norm)
        )
        updated_urls += result.rowcount

    conn.commit()
    conn.close()

    total_new = sum(len(t) for t in new_tokens.values())
    print(f"  ATS tokens found: {len(ats_entries)} ({total_new} new)")
    print(f"  Company URLs backfilled: {updated_urls}")
    print(f"  Next: run 'python run_search.py' to scrape new tokens")


# --- Phase 2: Careers Page Discovery ---

def discover(db_path: Path = DB_PATH):
    """Find careers pages for non-ATS HN companies."""
    print("Phase 2: Discovering careers pages")
    conn = get_db(db_path)
    session = create_session(is_tls=False, has_retry=True)

    # Get pending entries that aren't ATS
    rows = conn.execute("""
        SELECT hn_job_id, company_name, company_url
        FROM hn_career_pages
        WHERE status = 'pending' AND company_url IS NOT NULL
    """).fetchall()
    print(f"  {len(rows)} companies to check")

    now = datetime.now().isoformat()
    found = 0
    dead = 0
    checked = 0

    for row in rows:
        job_id = row["hn_job_id"]
        company = row["company_name"]
        url = row["company_url"]

        # Skip dead ends
        if is_dead_end(url):
            conn.execute(
                "UPDATE hn_career_pages SET page_type = 'dead_end', status = 'skipped', last_checked = ? WHERE hn_job_id = ?",
                (now, job_id)
            )
            dead += 1
            continue

        # If URL is already a careers page
        if is_careers_url(url):
            conn.execute(
                "UPDATE hn_career_pages SET careers_url = ?, page_type = 'unknown', status = 'discovered', last_checked = ? WHERE hn_job_id = ?",
                (url, now, job_id)
            )
            found += 1
            checked += 1
            continue

        # If URL is an HN comment link, skip
        if "news.ycombinator.com" in url:
            conn.execute(
                "UPDATE hn_career_pages SET page_type = 'dead_end', status = 'skipped', last_checked = ? WHERE hn_job_id = ?",
                (now, job_id)
            )
            dead += 1
            continue

        # Probe common careers paths
        parsed = urlparse(url)
        base = f"{parsed.scheme}://{parsed.netloc}"
        careers_url = None

        for path in CAREERS_PATH_KEYWORDS:
            probe_url = base + path
            try:
                time.sleep(0.3)
                resp = session.head(probe_url, timeout=10, allow_redirects=True)
                if resp.status_code == 200:
                    careers_url = probe_url
                    break
            except Exception:
                continue

        # If no common path, try scanning homepage for links
        if not careers_url:
            try:
                time.sleep(0.3)
                resp = session.get(base, timeout=10)
                if resp.status_code == 200:
                    html = resp.text.lower()
                    # Look for <a> tags with careers-related text
                    links = re.findall(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>([^<]*)</a>', html)
                    for href, text in links:
                        combined = (href + " " + text).lower()
                        if any(kw in combined for kw in CAREERS_LINK_KEYWORDS):
                            if href.startswith("http"):
                                careers_url = href
                            elif href.startswith("/"):
                                careers_url = base + href
                            break
            except Exception:
                pass

        checked += 1
        if careers_url:
            conn.execute(
                "UPDATE hn_career_pages SET careers_url = ?, page_type = 'unknown', status = 'discovered', last_checked = ? WHERE hn_job_id = ?",
                (careers_url, now, job_id)
            )
            found += 1
        else:
            conn.execute(
                "UPDATE hn_career_pages SET page_type = 'dead_end', status = 'skipped', last_checked = ?, error = 'no careers page found' WHERE hn_job_id = ?",
                (now, job_id)
            )

        if checked % 20 == 0:
            conn.commit()
            print(f"  Checked {checked}/{len(rows)} — found {found} careers pages")

    conn.commit()
    conn.close()
    print(f"  Done: {found} careers pages found, {dead} dead ends, {len(rows) - found - dead} not found")


# --- Phase 3: ATS Detection on Careers Pages ---

def detect_ats(db_path: Path = DB_PATH):
    """Detect ATS embeds in discovered careers pages."""
    print("Phase 3: Detecting ATS embeds in careers pages")
    conn = get_db(db_path)
    session = create_session(is_tls=False, has_retry=True)

    rows = conn.execute("""
        SELECT hn_job_id, company_name, careers_url
        FROM hn_career_pages
        WHERE status = 'discovered' AND careers_url IS NOT NULL AND ats_platform IS NULL
    """).fetchall()
    print(f"  {len(rows)} careers pages to check")

    now = datetime.now().isoformat()
    ats_found = 0
    new_tokens: dict[str, list[str]] = {"ashby": [], "greenhouse": [], "lever": []}

    for row in rows:
        job_id = row["hn_job_id"]
        url = row["careers_url"]

        try:
            time.sleep(0.3)
            resp = session.get(url, timeout=15)
            if resp.status_code != 200:
                conn.execute(
                    "UPDATE hn_career_pages SET last_checked = ?, error = ? WHERE hn_job_id = ?",
                    (now, f"HTTP {resp.status_code}", job_id)
                )
                continue

            html = resp.text

            # Check for ATS patterns in HTML
            detected_ats = None
            detected_token = None

            for ats, patterns in ATS_HTML_PATTERNS.items():
                for pattern, group_idx in patterns:
                    m = re.search(pattern, html)
                    if m:
                        detected_ats = ats
                        if group_idx and m.lastindex:
                            detected_token = m.group(group_idx)
                        break
                if detected_ats:
                    break

            if detected_ats:
                conn.execute("""
                    UPDATE hn_career_pages
                    SET ats_platform = ?, ats_token = ?, page_type = 'ats', status = 'discovered', last_checked = ?
                    WHERE hn_job_id = ?
                """, (detected_ats, detected_token, now, job_id))
                if detected_token:
                    new_tokens[detected_ats].append(detected_token)
                ats_found += 1
            else:
                # Classify as static_html or spa
                body_content = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
                body_content = re.sub(r'<style[^>]*>.*?</style>', '', body_content, flags=re.DOTALL | re.IGNORECASE)
                body_text = re.sub(r'<[^>]+>', ' ', body_content).strip()

                if len(body_text) > 500:
                    page_type = "static_html"
                else:
                    page_type = "spa"

                conn.execute(
                    "UPDATE hn_career_pages SET page_type = ?, last_checked = ? WHERE hn_job_id = ?",
                    (page_type, now, job_id)
                )

        except Exception as e:
            conn.execute(
                "UPDATE hn_career_pages SET last_checked = ?, error = ? WHERE hn_job_id = ?",
                (now, str(e)[:200], job_id)
            )

    # Append new tokens
    for ats, tokens in new_tokens.items():
        if tokens:
            append_tokens(ats, tokens)

    conn.commit()
    conn.close()
    print(f"  ATS detected: {ats_found}")
    for ats, tokens in new_tokens.items():
        if tokens:
            print(f"    {ats}: {tokens}")


# --- Phase 4: Extract Jobs from Custom Careers Pages ---

def extract(db_path: Path = DB_PATH):
    """Extract job listings from non-ATS careers pages using HTML parsing."""
    print("Phase 4: Extracting jobs from custom careers pages")
    conn = get_db(db_path)
    session = create_session(is_tls=False, has_retry=True)

    rows = conn.execute("""
        SELECT hn_job_id, company_name, careers_url
        FROM hn_career_pages
        WHERE status = 'discovered' AND page_type = 'static_html' AND careers_url IS NOT NULL
    """).fetchall()
    print(f"  {len(rows)} static pages to extract")

    if not rows:
        print("  Nothing to extract")
        conn.close()
        return

    # Fetch pages and convert to markdown
    pages = []
    now = datetime.now().isoformat()
    for row in rows:
        try:
            time.sleep(0.3)
            resp = session.get(row["careers_url"], timeout=15)
            if resp.status_code == 200:
                md = html_to_markdown(resp.text)
                if md and len(md) > 100:
                    pages.append({
                        "hn_job_id": row["hn_job_id"],
                        "company": row["company_name"],
                        "careers_url": row["careers_url"],
                        "markdown": md[:3000],  # truncate for LLM context
                    })
        except Exception as e:
            conn.execute(
                "UPDATE hn_career_pages SET error = ?, last_checked = ? WHERE hn_job_id = ?",
                (str(e)[:200], now, row["hn_job_id"])
            )

    conn.commit()

    if not pages:
        print("  No extractable content found")
        conn.close()
        return

    # Write batch files for Haiku processing
    batch_size = 10
    batch_dir = Path("data")
    for i in range(0, len(pages), batch_size):
        batch = pages[i:i+batch_size]
        batch_file = batch_dir / f"hn_extract_batch_{i//batch_size:03d}.json"
        with open(batch_file, "w") as f:
            json.dump(batch, f, indent=1, ensure_ascii=False)

    num_batches = (len(pages) + batch_size - 1) // batch_size
    print(f"  Created {num_batches} batch files in data/hn_extract_batch_*.json")
    print(f"  Run Haiku agents to extract jobs, then use 'python scripts/hn_careers.py import-extracted' to load results")

    conn.close()


def import_extracted(db_path: Path = DB_PATH):
    """Import Haiku-extracted job listings from batch result files."""
    print("Importing extracted jobs")
    conn = get_db(db_path)

    result_files = sorted(Path("data").glob("hn_extracted_*.jsonl"))
    if not result_files:
        print("  No result files found (data/hn_extracted_*.jsonl)")
        conn.close()
        return

    now = datetime.now().isoformat()
    run_id = datetime.now().strftime("%Y-%m-%d_%H%M%S") + "_hn_careers"
    conn.execute(
        "INSERT OR IGNORE INTO runs (run_id, started_at, sources) VALUES (?, ?, 'hn_careers')",
        (run_id, now)
    )

    inserted = 0
    for f in result_files:
        with open(f) as fh:
            for line in fh:
                try:
                    data = json.loads(line)
                    company = data.get("company", "")
                    hn_job_id = data.get("hn_job_id", "")
                    jobs_list = data.get("jobs", [])

                    for job in jobs_list:
                        title = job.get("title", "").strip()
                        job_url = job.get("url", "").strip()
                        if not title:
                            continue

                        slug = normalize_company(company)
                        job_hash = hashlib.md5(f"{title}{job_url}".encode()).hexdigest()[:8]
                        job_id = f"hn-careers-{slug}-{job_hash}"

                        cur = conn.execute("""
                            INSERT OR IGNORE INTO jobs
                                (id, run_id, site, title, company, job_url, board_token, location_raw)
                            VALUES (?, ?, 'hn', ?, ?, ?, ?, ?)
                        """, (
                            job_id, run_id, title, company, job_url,
                            f"hn-{hn_job_id}", job.get("location"),
                        ))
                        inserted += cur.rowcount

                    # Update hn_career_pages status
                    conn.execute(
                        "UPDATE hn_career_pages SET status = 'scraped', last_checked = ? WHERE hn_job_id = ?",
                        (now, hn_job_id)
                    )
                except Exception as e:
                    print(f"  Error processing line: {e}")

    conn.execute("UPDATE runs SET total_jobs = ? WHERE run_id = ?", (inserted, run_id))
    conn.commit()
    conn.close()
    print(f"  Inserted {inserted} jobs from {len(result_files)} files")


# --- Status ---

def status(db_path: Path = DB_PATH):
    """Show pipeline status."""
    conn = get_db(db_path)

    total = conn.execute("SELECT COUNT(*) FROM hn_career_pages").fetchone()[0]
    if total == 0:
        print("No HN career pages tracked yet. Run 'harvest-ats' first.")
        conn.close()
        return

    print(f"HN Careers Pipeline Status ({total} companies tracked)")
    print()

    # By status
    print("  By status:")
    for row in conn.execute("SELECT status, COUNT(*) FROM hn_career_pages GROUP BY status ORDER BY COUNT(*) DESC"):
        print(f"    {row[0]:12s} {row[1]:4d}")

    # By page_type
    print("\n  By page type:")
    for row in conn.execute("SELECT COALESCE(page_type, 'unknown'), COUNT(*) FROM hn_career_pages GROUP BY page_type ORDER BY COUNT(*) DESC"):
        print(f"    {row[0]:12s} {row[1]:4d}")

    # ATS breakdown
    print("\n  ATS platforms detected:")
    for row in conn.execute("SELECT ats_platform, COUNT(*) FROM hn_career_pages WHERE ats_platform IS NOT NULL GROUP BY ats_platform ORDER BY COUNT(*) DESC"):
        print(f"    {row[0]:12s} {row[1]:4d}")

    # Token summary
    print("\n  New tokens by ATS:")
    for row in conn.execute("SELECT ats_platform, GROUP_CONCAT(ats_token, ', ') FROM hn_career_pages WHERE ats_token IS NOT NULL GROUP BY ats_platform"):
        tokens = row[1].split(", ")
        print(f"    {row[0]:12s} {len(tokens)} tokens")

    conn.close()


# --- CLI ---

def main():
    parser = argparse.ArgumentParser(description="HN Careers Page Pipeline")
    parser.add_argument("command", choices=[
        "harvest-ats", "discover", "detect-ats", "extract",
        "import-extracted", "run-all", "status",
    ])
    parser.add_argument("--db", type=Path, default=DB_PATH)
    args = parser.parse_args()

    commands = {
        "harvest-ats": harvest_ats,
        "discover": discover,
        "detect-ats": detect_ats,
        "extract": extract,
        "import-extracted": import_extracted,
        "status": status,
    }

    if args.command == "run-all":
        for cmd in ["harvest-ats", "discover", "detect-ats", "extract"]:
            print(f"\n{'=' * 60}")
            commands[cmd](args.db)
    else:
        commands[args.command](args.db)


if __name__ == "__main__":
    main()
