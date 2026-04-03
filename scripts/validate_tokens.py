#!/usr/bin/env python3
"""Validate raw ATS board tokens against live APIs.

Usage:
    python scripts/validate_tokens.py
    python scripts/validate_tokens.py --token-dir tokens --workers-gh 20 --workers-lever 2
"""

from __future__ import annotations

import argparse
import http.client
import random
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
DEFAULT_TOKEN_DIR = Path("tokens")
GH_WORKERS = 20
LEVER_WORKERS = 2        # Lever rate-limits at ~10 req / 10 s / IP
MAX_RETRIES = 5
INITIAL_BACKOFF = 1.0    # seconds
PROGRESS_EVERY = 50      # print progress every N tokens

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def read_tokens(path: Path) -> list[str]:
    """Read a token file, skipping blanks and comment lines."""
    tokens: list[str] = []
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            tokens.append(line)
    return tokens


def write_token_file(path: Path, tokens: list[str], header: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as fh:
        fh.write(f"{header}\n")
        for token in tokens:
            fh.write(f"{token}\n")


def _get_status(url: str, timeout: int = 15) -> int:
    """Return the HTTP status code for *url*, or -1 on network error."""
    req = Request(url, headers={"User-Agent": "validate_tokens/1.0"})
    try:
        with urlopen(req, timeout=timeout) as resp:
            return resp.status
    except HTTPError as exc:
        return exc.code
    except (URLError, http.client.RemoteDisconnected, TimeoutError, OSError):
        return -1


# ---------------------------------------------------------------------------
# Greenhouse validation
# ---------------------------------------------------------------------------

def validate_greenhouse_token(token: str) -> tuple[str, bool]:
    """Return (token, is_valid).  Retries on 429 with exponential backoff."""
    url = f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs"
    backoff = INITIAL_BACKOFF
    for attempt in range(MAX_RETRIES):
        status = _get_status(url)
        if status == 200:
            return token, True
        if status == 404:
            return token, False
        if status == 429:
            jitter = random.uniform(0, backoff * 0.5)
            time.sleep(backoff + jitter)
            backoff *= 2
            continue
        # Transient network error -- retry once more
        if status == -1 and attempt < MAX_RETRIES - 1:
            time.sleep(backoff)
            backoff *= 2
            continue
        break
    return token, False


# ---------------------------------------------------------------------------
# Lever validation
# ---------------------------------------------------------------------------

def validate_lever_token(token: str) -> tuple[str, bool]:
    """Return (token, is_valid).  Retries on 429 with exponential backoff."""
    url = f"https://api.lever.co/v0/postings/{token}?mode=json"
    backoff = INITIAL_BACKOFF
    for attempt in range(MAX_RETRIES):
        status = _get_status(url)
        if status == 200:
            return token, True
        if status == 404:
            return token, False
        if status == 429:
            jitter = random.uniform(0, backoff * 0.5)
            time.sleep(backoff + jitter)
            backoff *= 2
            continue
        if status == -1 and attempt < MAX_RETRIES - 1:
            time.sleep(backoff)
            backoff *= 2
            continue
        break
    return token, False


# ---------------------------------------------------------------------------
# Concurrent runner
# ---------------------------------------------------------------------------

def validate_batch(
    tokens: list[str],
    validate_fn,
    max_workers: int,
    label: str,
) -> list[str]:
    """Validate *tokens* concurrently and return the list of valid ones."""
    total = len(tokens)
    valid: list[str] = []
    done = 0

    print(f"\n[{label}] Validating {total} tokens ({max_workers} workers) ...")

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(validate_fn, t): t for t in tokens}
        for future in as_completed(futures):
            token, is_valid = future.result()
            if is_valid:
                valid.append(token)
            done += 1
            if done % PROGRESS_EVERY == 0 or done == total:
                pct = done / total * 100
                print(
                    f"  [{label}] {done}/{total} checked "
                    f"({pct:.0f}%) -- {len(valid)} valid so far"
                )

    valid.sort()
    return valid


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Validate raw ATS board tokens against live APIs."
    )
    parser.add_argument(
        "--token-dir",
        type=Path,
        default=DEFAULT_TOKEN_DIR,
        help="Directory containing raw token files (default: tokens/)",
    )
    parser.add_argument(
        "--workers-gh",
        type=int,
        default=GH_WORKERS,
        help=f"Concurrent workers for Greenhouse (default: {GH_WORKERS})",
    )
    parser.add_argument(
        "--workers-lever",
        type=int,
        default=LEVER_WORKERS,
        help=f"Concurrent workers for Lever (default: {LEVER_WORKERS})",
    )
    parser.add_argument(
        "--skip-greenhouse",
        action="store_true",
        help="Skip Greenhouse validation",
    )
    parser.add_argument(
        "--skip-lever",
        action="store_true",
        help="Skip Lever validation",
    )
    args = parser.parse_args(argv)

    today = date.today().isoformat()
    summaries: list[str] = []

    # --- Greenhouse ---
    if not args.skip_greenhouse:
        gh_raw_path = args.token_dir / "greenhouse_raw.txt"
        if not gh_raw_path.exists():
            print(
                f"[WARN] {gh_raw_path} not found -- run bootstrap_tokens.py first.",
                file=sys.stderr,
            )
        else:
            gh_tokens = read_tokens(gh_raw_path)
            gh_valid = validate_batch(
                gh_tokens,
                validate_greenhouse_token,
                max_workers=args.workers_gh,
                label="Greenhouse",
            )
            gh_out = args.token_dir / "greenhouse.txt"
            write_token_file(
                gh_out,
                gh_valid,
                f"# Greenhouse board tokens (validated {today})",
            )
            pct = len(gh_valid) / len(gh_tokens) * 100 if gh_tokens else 0
            summary = (
                f"Greenhouse: {len(gh_valid)}/{len(gh_tokens)} valid ({pct:.0f}%)"
            )
            summaries.append(summary)
            print(f"\n  {summary}  ->  {gh_out}")

    # --- Lever ---
    if not args.skip_lever:
        lever_raw_path = args.token_dir / "lever_raw.txt"
        if not lever_raw_path.exists():
            print(
                f"[WARN] {lever_raw_path} not found -- run bootstrap_tokens.py first.",
                file=sys.stderr,
            )
        else:
            lever_tokens = read_tokens(lever_raw_path)
            lever_valid = validate_batch(
                lever_tokens,
                validate_lever_token,
                max_workers=args.workers_lever,
                label="Lever",
            )
            lever_out = args.token_dir / "lever.txt"
            write_token_file(
                lever_out,
                lever_valid,
                f"# Lever board tokens (validated {today})",
            )
            pct = (
                len(lever_valid) / len(lever_tokens) * 100
                if lever_tokens
                else 0
            )
            summary = (
                f"Lever: {len(lever_valid)}/{len(lever_tokens)} valid ({pct:.0f}%)"
            )
            summaries.append(summary)
            print(f"\n  {summary}  ->  {lever_out}")

    # --- Final summary ---
    print("\n========== Validation Summary ==========")
    for s in summaries:
        print(f"  {s}")
    print("========================================\n")


if __name__ == "__main__":
    main()
