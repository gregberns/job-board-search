"""Enrichment pipeline: 4-stage processing of scraped jobs."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from jbs.enrich_prompts import JOB_SYSTEM_PROMPT, COMPANY_SYSTEM_PROMPT
from jbs.enrich_rules import (
    classify_llm_filter,
    extract_is_management,
    extract_seniority,
    extract_visa,
    extract_years_experience,
    normalize_salary_to_usd,
    normalize_tech_stack,
)
from jbs.llm_backend import LLMBackend, get_llm_backend
from jbs.store import Store
from jbs.util import fix_mojibake, html_to_markdown, strip_boilerplate, strip_data_uris

log = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class EnrichmentPipeline:
    def __init__(self, store: Store):
        self.store = store

    def run(
        self,
        stage: str | None = None,
        force: bool = False,
        source: str | None = None,
        dry_run: bool = False,
    ):
        """Run enrichment. stage: 'rules', 'jobs', 'companies', or None (all)."""
        if dry_run:
            return self._dry_run(source)

        if stage is None or stage == "rules":
            self._run_stage0_cleanup(source)
            self._run_stage1_rules(force, source)
        if stage is None or stage == "jobs":
            self._run_stage2_jobs(force, source)
        if stage is None or stage == "companies":
            self._run_stage3_companies(force)
        if stage is None or stage == "embeddings":
            self._run_stage4_embeddings(force)

    # ------------------------------------------------------------------
    # Stage 0: Description cleanup (persisted)
    # ------------------------------------------------------------------

    def _run_stage0_cleanup(self, source: str | None = None):
        conn = self.store._conn()
        counts = {"html_to_md": 0, "data_uri": 0, "encoding": 0}

        # 0a: Greenhouse HTML -> markdown (raw HTML and entity-encoded HTML)
        if source is None or source == "greenhouse":
            rows = conn.execute("""
                SELECT id, description FROM jobs
                WHERE site = 'greenhouse'
                  AND (description LIKE '<%' OR description LIKE '&lt;%')
            """).fetchall()
            for row in rows:
                md = html_to_markdown(row["description"])
                conn.execute(
                    "UPDATE jobs SET description = ? WHERE id = ?",
                    (md, row["id"]),
                )
            counts["html_to_md"] = len(rows)

        # 0b: Strip base64 data: URIs from any description (catches previously
        # converted markdown that still contains ![](data:image/...;base64,...))
        rows = conn.execute("""
            SELECT id, description FROM jobs
            WHERE description LIKE '%data:image/%'
              OR description LIKE '%data:application/%'
        """).fetchall()
        for row in rows:
            cleaned = strip_data_uris(row["description"])
            if cleaned != row["description"]:
                conn.execute(
                    "UPDATE jobs SET description = ? WHERE id = ?",
                    (cleaned, row["id"]),
                )
                counts["data_uri"] += 1

        # 0c: RemoteOK encoding fix
        if source is None or source == "remoteok":
            rows = conn.execute("""
                SELECT id, description FROM jobs
                WHERE site = 'remoteok'
                  AND description LIKE '%\u00e2%'
            """).fetchall()
            for row in rows:
                fixed = fix_mojibake(row["description"])
                conn.execute(
                    "UPDATE jobs SET description = ? WHERE id = ?",
                    (fixed, row["id"]),
                )
            counts["encoding"] = len(rows)

        conn.commit()
        log.info(
            "Stage 0: html_to_md=%d  data_uri=%d  encoding=%d",
            counts["html_to_md"], counts["data_uri"], counts["encoding"],
        )
        return counts

    # ------------------------------------------------------------------
    # Stage 1: Rule-based extraction
    # ------------------------------------------------------------------

    def _run_stage1_rules(self, force: bool = False, source: str | None = None):
        conn = self.store._conn()

        where_parts = []
        params: list = []
        if not force:
            where_parts.append("enriched_at IS NULL")
        if source:
            where_parts.append("site = ?")
            params.append(source)

        where_clause = " AND ".join(where_parts) if where_parts else "1=1"

        rows = conn.execute(
            f"""SELECT id, title, description, min_amount, max_amount, currency,
                       salary_interval, salary_usd_max, seniority, is_management
                FROM jobs WHERE {where_clause}""",
            params,
        ).fetchall()

        counts = {"seniority": 0, "visa": 0, "salary": 0, "years_exp": 0, "management": 0, "llm_send": 0}
        now = _now_iso()

        for row in rows:
            updates: dict = {}

            # Seniority
            if row["title"]:
                seniority = extract_seniority(row["title"])
                if seniority:
                    updates["seniority"] = seniority
                    counts["seniority"] += 1

                # Management
                is_mgmt = extract_is_management(row["title"])
                updates["is_management"] = is_mgmt
                if is_mgmt:
                    counts["management"] += 1

            # Salary normalization
            usd_min, usd_max = normalize_salary_to_usd(
                row["min_amount"], row["max_amount"],
                row["currency"], row["salary_interval"],
            )
            if usd_min is not None or usd_max is not None:
                updates["salary_usd_min"] = usd_min
                updates["salary_usd_max"] = usd_max
                counts["salary"] += 1

            # Visa + years (description-based)
            if row["description"]:
                visa = extract_visa(row["description"])
                updates["visa_sponsorship"] = visa
                if visa != "unknown":
                    counts["visa"] += 1

                yrs = extract_years_experience(row["description"])
                if yrs is not None:
                    updates["years_experience"] = yrs
                    counts["years_exp"] += 1

            # LLM pre-filter (always recomputed, not gated on prior value)
            if row["title"]:
                llm_f = classify_llm_filter(
                    title=row["title"],
                    is_management=updates.get("is_management", row["is_management"]),
                    seniority=updates.get("seniority", row["seniority"]),
                    salary_usd_max=updates.get("salary_usd_max", row["salary_usd_max"]),
                    max_amount=row["max_amount"],
                )
                updates["llm_filter"] = llm_f
                if llm_f == "send":
                    counts["llm_send"] += 1

            # Always set enriched_at
            updates["enriched_at"] = now

            if updates:
                set_clause = ", ".join(f"{k} = ?" for k in updates)
                conn.execute(
                    f"UPDATE jobs SET {set_clause} WHERE id = ?",
                    list(updates.values()) + [row["id"]],
                )

        conn.commit()
        log.info(
            "Stage 1: %d jobs — seniority=%d visa=%d salary=%d years_exp=%d management=%d llm_send=%d",
            len(rows), counts["seniority"], counts["visa"],
            counts["salary"], counts["years_exp"], counts["management"], counts["llm_send"],
        )
        return len(rows), counts

    # ------------------------------------------------------------------
    # Stage 2: LLM job classification
    # ------------------------------------------------------------------

    def _run_stage2_jobs(self, force: bool = False, source: str | None = None):
        backend = get_llm_backend()
        if backend is None:
            log.warning(
                "Stage 2: No LLM backend available. "
                "Set ANTHROPIC_API_KEY or install claude-agent-sdk."
            )
            return 0, {}

        return self._run_stage2_with_backend(backend, force, source)

    def _run_stage2_with_backend(
        self, backend: LLMBackend, force: bool = False, source: str | None = None
    ):
        conn = self.store._conn()

        where_parts = [
            "description IS NOT NULL",
            "length(description) > 50",
        ]
        params: list = []
        if not force:
            where_parts.append("engineering_role IS NULL")
            # Respect pre-filter: only send jobs marked 'send' or not yet filtered
            where_parts.append("(llm_filter = 'send' OR llm_filter IS NULL)")
        if source:
            where_parts.append("site = ?")
            params.append(source)

        where_clause = " AND ".join(where_parts)

        rows = conn.execute(
            f"""SELECT id, title, company_raw, description, location_raw,
                       work_arrangement, seniority, is_management,
                       salary_usd_min, salary_usd_max
                FROM jobs WHERE {where_clause}
                ORDER BY date_posted DESC""",
            params,
        ).fetchall()

        if not rows:
            log.info("Stage 2: no jobs to classify")
            return 0, {}

        jobs = [dict(r) for r in rows]
        run_id = f"enrich_{datetime.now(timezone.utc).strftime('%Y-%m-%d_%H%M%S')}"

        log.info("Stage 2: classifying %d jobs...", len(jobs))
        results = backend.classify_jobs(jobs, JOB_SYSTEM_PROMPT)

        # Apply results (commit incrementally for crash resilience)
        written = 0
        for job_id, data in results.items():
            updates = {}
            if "engineering_role" in data:
                updates["engineering_role"] = 1 if data["engineering_role"] else 0
            if "seniority" in data:
                updates["seniority"] = data["seniority"]
            if "is_management" in data:
                updates["is_management"] = 1 if data["is_management"] else 0
            if "domain" in data:
                updates["domain"] = data["domain"]
            if "tech_stack" in data and isinstance(data["tech_stack"], list):
                updates["tech_stack"] = json.dumps(normalize_tech_stack(data["tech_stack"]))
            if "job_summary" in data:
                updates["job_summary"] = data["job_summary"]

            if updates:
                set_clause = ", ".join(f"{k} = ?" for k in updates)
                conn.execute(
                    f"UPDATE jobs SET {set_clause} WHERE id = ?",
                    list(updates.values()) + [job_id],
                )
                written += 1
                # Commit every 20 jobs so partial results survive crashes
                if written % 20 == 0:
                    conn.commit()

        conn.commit()

        # Track enrichment run
        conn.execute(
            """INSERT INTO enrichment_runs (run_id, started_at, stage, items, model)
               VALUES (?, ?, 'jobs', ?, 'claude-haiku')""",
            (run_id, _now_iso(), len(results)),
        )
        conn.commit()

        log.info("Stage 2: classified %d/%d jobs", len(results), len(jobs))
        return len(jobs), results

    # ------------------------------------------------------------------
    # Stage 3: LLM company enrichment
    # ------------------------------------------------------------------

    def _run_stage3_companies(self, force: bool = False):
        backend = get_llm_backend()
        if backend is None:
            log.warning(
                "Stage 3: No LLM backend available. "
                "Set ANTHROPIC_API_KEY or install claude-agent-sdk."
            )
            return 0, {}

        return self._run_stage3_with_backend(backend, force)

    def _run_stage3_with_backend(self, backend: LLMBackend, force: bool = False):
        conn = self.store._conn()

        where = "1=1" if force else "c.enriched_at IS NULL"

        rows = conn.execute(
            f"""SELECT c.name, c.name_normalized, c.ats_platform, c.ats_token, c.website,
                       GROUP_CONCAT(DISTINCT j.title) as sample_titles,
                       GROUP_CONCAT(DISTINCT j.tech_stack) as tech_stacks
                FROM companies c
                LEFT JOIN jobs j ON j.company_id = c.id AND j.engineering_role = 1
                WHERE {where}
                GROUP BY c.id""",
        ).fetchall()

        if not rows:
            log.info("Stage 3: no companies to classify")
            return 0, {}

        companies = [dict(r) for r in rows]
        run_id = f"enrich_co_{datetime.now(timezone.utc).strftime('%Y-%m-%d_%H%M%S')}"

        log.info("Stage 3: classifying %d companies...", len(companies))
        results = backend.classify_companies(companies, COMPANY_SYSTEM_PROMPT)

        # Apply results
        now = _now_iso()
        for name_norm, data in results.items():
            updates: dict = {}
            for field in ("description", "industry", "funding_stage", "size_estimate"):
                if field in data:
                    updates[field] = data[field]
            if "ai_native" in data:
                updates["ai_native"] = float(data["ai_native"])
            updates["enriched_at"] = now

            if updates:
                set_clause = ", ".join(f"{k} = ?" for k in updates)
                conn.execute(
                    f"UPDATE companies SET {set_clause} WHERE name_normalized = ?",
                    list(updates.values()) + [name_norm],
                )

        # Aggregate tech stacks from jobs to companies
        conn.execute("""
            UPDATE companies SET tech_stack = (
                SELECT json_group_array(DISTINCT value)
                FROM jobs, json_each(jobs.tech_stack)
                WHERE jobs.company_id = companies.id
            ) WHERE tech_stack IS NULL OR tech_stack = '[]'
        """)

        conn.commit()

        # Track enrichment run
        conn.execute(
            """INSERT INTO enrichment_runs (run_id, started_at, stage, items, model)
               VALUES (?, ?, 'companies', ?, 'claude-haiku')""",
            (run_id, _now_iso(), len(results)),
        )
        conn.commit()

        log.info("Stage 3: classified %d/%d companies", len(results), len(companies))
        return len(companies), results

    # ------------------------------------------------------------------
    # Stage 4: Embedding generation (local, no LLM needed)
    # ------------------------------------------------------------------

    def _run_stage4_embeddings(self, force: bool = False):
        if not self.store.has_vec():
            log.warning(
                "Stage 4: sqlite-vec not available. "
                "Install: pip install -e '.[vector]'"
            )
            return 0

        try:
            from jbs.embeddings import get_embedder
        except ImportError:
            log.warning(
                "Stage 4: mlx-embedding-models not available. "
                "Install: pip install -e '.[vector]'"
            )
            return 0

        conn = self.store._conn()

        # Force: clear existing embeddings
        if force:
            conn.execute("DELETE FROM vec_summaries")
            conn.execute("DELETE FROM vec_descriptions")
            conn.commit()

        embedder = get_embedder()
        run_id = f"enrich_emb_{datetime.now(timezone.utc).strftime('%Y-%m-%d_%H%M%S')}"
        total_embedded = 0
        batch_size = 32  # Small batches to limit memory (description model uses ~1GB per batch)

        # Fetch and process in pages to avoid loading all descriptions into memory
        page = 0
        while True:
            jobs = self.store.get_unembedded_jobs(limit=batch_size)
            if not jobs:
                if page == 0:
                    log.info("Stage 4: no jobs to embed")
                break

            if page == 0:
                # Count total on first page for logging
                total_pending = conn.execute(
                    """SELECT COUNT(*) as cnt FROM jobs
                       WHERE is_active = 1 AND description IS NOT NULL
                         AND rowid NOT IN (SELECT rowid FROM vec_summaries)"""
                ).fetchone()["cnt"]
                log.info("Stage 4: embedding %d jobs...", total_pending)

            # Build texts
            summary_texts = [embedder.build_composite_text(j) for j in jobs]
            desc_texts = [embedder.build_description_text(j) for j in jobs]

            # Embed summaries (small model, fast)
            summary_vecs = embedder.embed_summaries(summary_texts)

            # Embed descriptions (large model, memory-intensive)
            non_empty_descs = [t for t in desc_texts if t]
            desc_vecs = embedder.embed_descriptions(non_empty_descs) if non_empty_descs else []

            # Map desc_vecs back accounting for skipped empty texts
            desc_vec_iter = iter(desc_vecs)
            rows_to_store = []
            for j_idx, job in enumerate(jobs):
                s_vec = summary_vecs[j_idx]
                d_vec = next(desc_vec_iter) if desc_texts[j_idx] else None
                rows_to_store.append((job["rowid"], s_vec, d_vec))

            stored = self.store.store_embeddings(rows_to_store)
            total_embedded += stored
            page += 1

            log.info(
                "Stage 4: batch %d — %d embedded (%d total)",
                page, stored, total_embedded,
            )

        # Record enrichment run
        conn.execute(
            """INSERT INTO enrichment_runs (run_id, started_at, stage, items, model)
               VALUES (?, ?, 'embeddings', ?, 'local-mlx')""",
            (run_id, _now_iso(), total_embedded),
        )
        conn.commit()

        log.info("Stage 4: embedded %d jobs total", total_embedded)
        return total_embedded

    # ------------------------------------------------------------------
    # Dry run
    # ------------------------------------------------------------------

    def _dry_run(self, source: str | None = None) -> dict:
        conn = self.store._conn()
        source_filter = "AND site = ?" if source else ""
        params: list = [source] if source else []

        # Stage 0 counts
        gh_html = conn.execute(
            f"SELECT COUNT(*) as cnt FROM jobs WHERE site = 'greenhouse' AND description LIKE '<%' {source_filter}",
            params if source == "greenhouse" else [],
        ).fetchone()["cnt"] if source is None or source == "greenhouse" else 0

        rok_enc = conn.execute(
            f"SELECT COUNT(*) as cnt FROM jobs WHERE site = 'remoteok' AND description LIKE '%\u00e2%' {source_filter}",
            params if source == "remoteok" else [],
        ).fetchone()["cnt"] if source is None or source == "remoteok" else 0

        # Stage 1 count
        stage1 = conn.execute(
            f"SELECT COUNT(*) as cnt FROM jobs WHERE enriched_at IS NULL {source_filter}",
            params,
        ).fetchone()["cnt"]

        # Stage 2 count
        stage2 = conn.execute(
            f"""SELECT COUNT(*) as cnt FROM jobs
                WHERE engineering_role IS NULL
                  AND description IS NOT NULL
                  AND length(description) > 50
                  {source_filter}""",
            params,
        ).fetchone()["cnt"]

        # Stage 3 count
        stage3 = conn.execute(
            "SELECT COUNT(*) as cnt FROM companies WHERE enriched_at IS NULL"
        ).fetchone()["cnt"]

        # Stage 4 count
        stage4 = 0
        if self.store.has_vec():
            stage4 = conn.execute(
                """SELECT COUNT(*) as cnt FROM jobs
                   WHERE is_active = 1 AND description IS NOT NULL
                     AND rowid NOT IN (SELECT rowid FROM vec_summaries)"""
            ).fetchone()["cnt"]

        info = {
            "stage0_html": gh_html,
            "stage0_encoding": rok_enc,
            "stage1": stage1,
            "stage2": stage2,
            "stage3": stage3,
            "stage4": stage4,
        }

        log.info(
            "Dry run:\n"
            "  Stage 0: %d HTML, %d encoding\n"
            "  Stage 1: %d jobs (free)\n"
            "  Stage 2: %d jobs for LLM\n"
            "  Stage 3: %d companies for LLM\n"
            "  Stage 4: %d jobs for embedding (free, local)",
            gh_html, rok_enc, stage1, stage2, stage3, stage4,
        )
        return info
