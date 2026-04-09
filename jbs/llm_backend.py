"""LLM backend abstraction for enrichment classification."""

from __future__ import annotations

import json
import logging
import os
import time
from abc import ABC, abstractmethod

from jbs.enrich_prompts import (
    JOB_SYSTEM_PROMPT,
    COMPANY_SYSTEM_PROMPT,
    format_company_prompt,
    format_job_prompt,
)
from jbs.enrich_rules import normalize_tech_stack
from jbs.util import strip_boilerplate

log = logging.getLogger(__name__)

# Conditional imports — neither SDK may be installed
try:
    from claude_code_sdk import query as cc_query, ClaudeCodeOptions  # type: ignore[import-untyped]
    HAS_AGENT_SDK = True
except ImportError:
    HAS_AGENT_SDK = False

try:
    import anthropic  # type: ignore[import-untyped]
    HAS_ANTHROPIC = True
except ImportError:
    HAS_ANTHROPIC = False


def _parse_json_safe(text: str, custom_id: str) -> dict | None:
    """Parse JSON from LLM response, logging on failure."""
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        log.warning("Failed to parse JSON for %s: %s", custom_id, text[:200])
        return None


def _post_process_job(data: dict) -> dict:
    """Normalize tech_stack in a parsed job classification."""
    if "tech_stack" in data and isinstance(data["tech_stack"], list):
        data["tech_stack"] = normalize_tech_stack(data["tech_stack"])
    return data


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------

class LLMBackend(ABC):
    @abstractmethod
    def classify_jobs(self, jobs: list[dict], system_prompt: str) -> dict[str, dict]:
        """Classify jobs. Returns {job_id: classification_dict}."""

    @abstractmethod
    def classify_companies(self, companies: list[dict], system_prompt: str) -> dict[str, dict]:
        """Classify companies. Returns {name_normalized: classification_dict}."""


# ---------------------------------------------------------------------------
# Claude CLI backend (default — uses Claude subscription)
# ---------------------------------------------------------------------------

class ClaudeCLIBackend(LLMBackend):
    """Calls `claude` CLI with --output-format json. Uses subscription auth.
    Batches 20 jobs per call with 2KB description truncation."""

    BATCH_SIZE = 20
    DESC_LIMIT = 2000

    def _call_claude(self, prompt: str) -> str:
        """Call claude CLI and return the model's text response."""
        import subprocess
        result = subprocess.run(
            ["claude", "-p", prompt,
             "--model", "claude-haiku-4-5-20251001",
             "--output-format", "json",
             "--max-turns", "1"],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode != 0:
            raise RuntimeError(f"claude CLI failed: {result.stderr[:200]}")

        # Parse the wrapper JSON to extract the model's response
        wrapper = json.loads(result.stdout)
        text = wrapper.get("result", "")

        # Strip markdown code fences if present
        if text.startswith("```"):
            lines = text.split("\n")
            # Remove first line (```json) and last line (```)
            lines = [l for l in lines if not l.strip().startswith("```")]
            text = "\n".join(lines)

        return text.strip()

    def classify_jobs(self, jobs: list[dict], system_prompt: str) -> dict[str, dict]:
        batches = [jobs[i:i + self.BATCH_SIZE] for i in range(0, len(jobs), self.BATCH_SIZE)]
        results: dict[str, dict] = {}

        for i, batch in enumerate(batches):
            jobs_json = json.dumps([{
                "id": j["id"],
                "title": j.get("title", ""),
                "company": j.get("company_raw", ""),
                "description": strip_boilerplate(j.get("description", ""))[:self.DESC_LIMIT],
                "location": j.get("location_raw", ""),
                "seniority": j.get("seniority") or "unknown",
                "is_management": j.get("is_management"),
                "salary_usd_min": j.get("salary_usd_min"),
                "salary_usd_max": j.get("salary_usd_max"),
            } for j in batch], indent=2)

            prompt = (
                f"{system_prompt}\n\nClassify each job and return a JSON array "
                f"where each element includes the job's \"id\" plus the classification fields.\n\n"
                f"Jobs:\n{jobs_json}"
            )

            try:
                response_text = self._call_claude(prompt)
                parsed = json.loads(response_text)
                if isinstance(parsed, list):
                    for item in parsed:
                        if "id" in item:
                            results[item["id"]] = _post_process_job(item)
                elif isinstance(parsed, dict) and "id" in parsed:
                    results[parsed["id"]] = _post_process_job(parsed)
                log.info("  batch %d/%d: %d classified", i + 1, len(batches), len(batch))
            except Exception:
                log.exception("CLI batch %d/%d failed, skipping %d jobs", i + 1, len(batches), len(batch))

        return results

    def classify_companies(self, companies: list[dict], system_prompt: str) -> dict[str, dict]:
        batches = [companies[i:i + self.BATCH_SIZE] for i in range(0, len(companies), self.BATCH_SIZE)]
        results: dict[str, dict] = {}

        for i, batch in enumerate(batches):
            items_json = json.dumps([{
                "name_normalized": c.get("name_normalized", ""),
                "name": c.get("name", ""),
                "website": c.get("website"),
                "ats_platform": c.get("ats_platform"),
                "sample_titles": c.get("sample_titles", ""),
                "tech_stacks": c.get("tech_stacks", ""),
            } for c in batch], indent=2)

            prompt = (
                f"{system_prompt}\n\nClassify each company and return a JSON array "
                f"where each element includes the company's \"name_normalized\" plus "
                f"the classification fields.\n\nCompanies:\n{items_json}"
            )

            try:
                response_text = self._call_claude(prompt)
                parsed = json.loads(response_text)
                if isinstance(parsed, list):
                    for item in parsed:
                        if "name_normalized" in item:
                            results[item["name_normalized"]] = item
                log.info("  batch %d/%d: %d classified", i + 1, len(batches), len(batch))
            except Exception:
                log.exception("CLI company batch %d/%d failed, skipping %d", i + 1, len(batches), len(batch))

        return results


# ---------------------------------------------------------------------------
# Batch API backend (fast path — requires ANTHROPIC_API_KEY)
# ---------------------------------------------------------------------------

class BatchAPIBackend(LLMBackend):
    """Individual calls via Anthropic Message Batches API. Full descriptions."""

    POLL_INTERVAL = 30
    TIMEOUT = 3600

    def classify_jobs(self, jobs: list[dict], system_prompt: str) -> dict[str, dict]:
        client = anthropic.Anthropic()

        requests = []
        for job in jobs:
            clean_desc = strip_boilerplate(job.get("description", ""))
            job_with_clean = {**job, "description": clean_desc}
            requests.append({
                "custom_id": job["id"],
                "params": {
                    "model": "claude-haiku-4-5-20251001",
                    "max_tokens": 300,
                    "system": system_prompt,
                    "messages": [{"role": "user", "content": format_job_prompt(job_with_clean)}],
                },
            })

        return self._run_batch(client, requests, _post_process_job)

    def classify_companies(self, companies: list[dict], system_prompt: str) -> dict[str, dict]:
        client = anthropic.Anthropic()

        requests = []
        for company in companies:
            requests.append({
                "custom_id": company.get("name_normalized", ""),
                "params": {
                    "model": "claude-haiku-4-5-20251001",
                    "max_tokens": 300,
                    "system": system_prompt,
                    "messages": [{"role": "user", "content": format_company_prompt(company)}],
                },
            })

        return self._run_batch(client, requests)

    def _run_batch(
        self,
        client: anthropic.Anthropic,
        requests: list[dict],
        post_fn=None,
    ) -> dict[str, dict]:
        batch = client.messages.batches.create(requests=requests)

        deadline = time.time() + self.TIMEOUT
        while batch.processing_status != "ended":
            if time.time() > deadline:
                raise TimeoutError(f"Batch {batch.id} not completed after 1h")
            time.sleep(self.POLL_INTERVAL)
            batch = client.messages.batches.retrieve(batch.id)

        results: dict[str, dict] = {}
        for entry in client.messages.batches.results(batch.id):
            if entry.result.type == "succeeded":
                data = _parse_json_safe(entry.result.message.content[0].text, entry.custom_id)
                if data is not None:
                    results[entry.custom_id] = post_fn(data) if post_fn else data

        return results


# ---------------------------------------------------------------------------
# Auto-selection
# ---------------------------------------------------------------------------

def get_llm_backend() -> LLMBackend | None:
    """Auto-select LLM backend.

    Priority:
    1. Batch API (if ANTHROPIC_API_KEY set + anthropic installed) — fastest
    2. Claude CLI (if `claude` in PATH) — uses subscription, no API key
    3. None
    """
    if os.environ.get("ANTHROPIC_API_KEY") and HAS_ANTHROPIC:
        return BatchAPIBackend()
    # Check if claude CLI is available
    import shutil
    if shutil.which("claude"):
        return ClaudeCLIBackend()
    return None
