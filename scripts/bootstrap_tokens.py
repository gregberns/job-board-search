#!/usr/bin/env python3
"""Fetch the awesome-easy-apply README and extract ATS board tokens.

Usage:
    python scripts/bootstrap_tokens.py
    python scripts/bootstrap_tokens.py --output-dir tokens
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import date
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

README_URL = (
    "https://raw.githubusercontent.com/sample-resume/"
    "awesome-easy-apply/main/README.md"
)

# Patterns -------------------------------------------------------------------
# boards.greenhouse.io/{token}  (token = path segment, no further slash)
GREENHOUSE_RE = re.compile(r"boards\.greenhouse\.io/([A-Za-z0-9_-]+)")
# jobs.lever.co/{slug}          (slug = path segment, no further slash)
LEVER_RE = re.compile(r"jobs\.lever\.co/([A-Za-z0-9_.-]+)")


def fetch_readme(url: str, timeout: int = 30) -> str:
    """Download the README text, with basic error handling."""
    req = Request(url, headers={"User-Agent": "bootstrap_tokens/1.0"})
    try:
        with urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8")
    except URLError as exc:
        print(f"[ERROR] Failed to fetch {url}: {exc}", file=sys.stderr)
        sys.exit(1)


def extract_tokens(text: str, pattern: re.Pattern[str]) -> list[str]:
    """Return deduplicated tokens preserving first-seen order."""
    seen: set[str] = set()
    tokens: list[str] = []
    for match in pattern.finditer(text):
        token = match.group(1).lower()
        if token not in seen:
            seen.add(token)
            tokens.append(token)
    return tokens


def write_token_file(path: Path, tokens: list[str], header: str) -> None:
    """Write tokens to *path*, one per line, with a leading comment."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as fh:
        fh.write(f"{header}\n")
        for token in tokens:
            fh.write(f"{token}\n")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Extract ATS board tokens from the awesome-easy-apply README."
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("tokens"),
        help="Directory to write raw token files (default: tokens/)",
    )
    parser.add_argument(
        "--url",
        default=README_URL,
        help="URL to fetch the README from (default: awesome-easy-apply main)",
    )
    args = parser.parse_args(argv)

    print(f"Fetching README from {args.url} ...")
    text = fetch_readme(args.url)
    print(f"  Downloaded {len(text):,} bytes.")

    # --- Greenhouse ---
    gh_tokens = extract_tokens(text, GREENHOUSE_RE)
    gh_path = args.output_dir / "greenhouse_raw.txt"
    today = date.today().isoformat()
    write_token_file(
        gh_path,
        gh_tokens,
        f"# Greenhouse board tokens (raw, extracted {today})",
    )
    print(f"Greenhouse: {len(gh_tokens)} tokens -> {gh_path}")

    # --- Lever ---
    lever_tokens = extract_tokens(text, LEVER_RE)
    lever_path = args.output_dir / "lever_raw.txt"
    write_token_file(
        lever_path,
        lever_tokens,
        f"# Lever board tokens (raw, extracted {today})",
    )
    print(f"Lever:      {len(lever_tokens)} tokens -> {lever_path}")

    # --- Summary ---
    print()
    print("Done.  Summary:")
    print(f"  Greenhouse : {len(gh_tokens):>5} raw tokens")
    print(f"  Lever      : {len(lever_tokens):>5} raw tokens")


if __name__ == "__main__":
    main()
