#!/usr/bin/env python3
"""Deduplicate a JSONL jobs file by (company, title)."""

from __future__ import annotations

import argparse
import json
import re
import sys
from typing import Optional


def normalize_company(name: str | None) -> str:
    if not name:
        return ""
    name = name.lower().strip()
    # Strip common suffixes
    for suffix in [
        "inc.", "inc", "llc", "ltd.", "ltd", "corp.", "corp", "co.", "co",
        "corporation", "incorporated", "limited", "company", "gmbh", "ag", "sa",
    ]:
        name = re.sub(rf'\b{re.escape(suffix)}\b\.?', '', name, flags=re.IGNORECASE)
    return re.sub(r'\s+', ' ', name).strip()


def normalize_title(title: str | None) -> str:
    if not title:
        return ""
    return re.sub(r'\s+', ' ', title.lower().strip())


def _richness(record: dict) -> tuple[int, int]:
    """Return (non-empty field count, description length) for conflict resolution."""
    non_empty = sum(
        1 for v in record.values()
        if v is not None and v != "" and v != []
    )
    desc_len = len(record.get("description") or "")
    return (non_empty, desc_len)


def dedup_jsonl(input_path: str, output_path: str | None = None) -> tuple[int, int]:
    """
    Deduplicate a JSONL file.
    Returns (original_count, deduped_count).
    """
    if output_path is None:
        output_path = input_path.replace(".jsonl", "_deduped.jsonl")

    # Read and group by dedup key
    groups: dict[tuple[str, str], dict] = {}
    original_count = 0

    with open(input_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            original_count += 1

            key = (
                normalize_company(record.get("company_name") or record.get("company")),
                normalize_title(record.get("title")),
            )

            if key in groups:
                # Keep the richer record
                if _richness(record) > _richness(groups[key]):
                    groups[key] = record
            else:
                groups[key] = record

    # Write deduplicated results
    deduped_count = len(groups)
    with open(output_path, "w", encoding="utf-8") as f:
        for record in groups.values():
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    return original_count, deduped_count


def main():
    parser = argparse.ArgumentParser(description="Deduplicate a JSONL jobs file")
    parser.add_argument("input", help="Path to input JSONL file")
    parser.add_argument(
        "--output", "-o",
        default=None,
        help="Output path (default: <input>_deduped.jsonl)",
    )
    args = parser.parse_args()

    orig, deduped = dedup_jsonl(args.input, args.output)
    print(f"Deduped: {orig} -> {deduped} jobs ({orig - deduped} duplicates removed)")


if __name__ == "__main__":
    main()
