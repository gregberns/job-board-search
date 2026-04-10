# Project Status — jbs

## What This Is

`jbs` — a local-first CLI tool for finding the right engineering job. Scrapes 5 job board sources, stores in SQLite, enriches with LLM classification + local embeddings, and provides keyword + semantic search/filter/annotation. Python 3.12, Click + Rich CLI, Claude Haiku for enrichment via subscription, MLX for local embeddings on Apple Silicon.

## Current State: Fully Operational (2026-04-10)

All features working end-to-end, including vector search. Specs in sync with code.

### Database (data/jobs.db)
- **4,801 jobs** (4,292 active, 509 inactive)
- **1,212 companies** (1,181 enriched with ai_native, industry, description)
- **1,253 engineering roles** identified by LLM
- **4,292 summary embeddings** (BGE-small 384d via MLX)
- **4,292 description embeddings** (nomic-v1.5 768d via MLX)
- Sources: Greenhouse (3,239), HN (624), Lever (557), Ashby (301), RemoteOK (80)

### What Works
- `jbs init` — create DB, import tokens from flat files
- `jbs scrape` — all 5 sources (Greenhouse, Lever, Ashby, RemoteOK, HN)
- `jbs enrich --stage rules` — free rule-based extraction (seniority, salary, visa, llm_filter)
- `jbs enrich --stage jobs` — LLM job classification via Claude CLI
- `jbs enrich --stage companies` — LLM company enrichment
- `jbs enrich --stage embeddings` — local embedding generation (MLX, ~15 min for 4,292 jobs, 1.7GB RSS)
- `jbs search` — FTS5 + structured filters
- `jbs search --vec "query"` — hybrid semantic search (FTS5 + KNN + RRF + cross-encoder re-rank)
- `jbs models list` — shows cached model status
- `jbs models download` — downloads embedding models
- `jbs show`, `jbs annotate`, `jbs apply`, `jbs stats`, `jbs tokens` — all working
- **527 tests passing**

---

## What Was Done This Session (2026-04-10)

### 1. Description Cleanup Bug Fix (kerf: `desc-cleanup`, SQUARE)
**Problem:** 2,025 Greenhouse descriptions were entity-encoded HTML (`&lt;div&gt;`); 18 had 1.8M chars of inline base64 images. Stage 0 cleanup missed them. Embedding generation OOM'd.

**Root cause:** Stage 0 only matched `LIKE '<%'`, missing entity-encoded `&lt;%`. The `html_to_markdown()` function didn't strip base64 data URIs.

**Fix:**
- `html_to_markdown()` now calls `html.unescape()` + strips `<img src="data:...">` tags
- Stage 0 matches both `'<%'` and `'&lt;%'` prefixes
- New `strip_data_uris()` for markdown-format base64 cleanup
- `MAX_DESC_CHARS = 30_000` truncation guard in embeddings.py
- DB impact: max description 1,832,407 → 19,611 chars; avg 10,330 → 5,709 chars

### 2. Embedding Model Swap (kerf: `embed-model`, SQUARE)
**Problem:** fastembed (ONNX Runtime) can't GPU-accelerate RoPE-based models on Apple Silicon. CoreML execution provider doesn't support rotary position embeddings. Long-context models (jina, nomic) fell back to CPU → OOM or unusably slow.

**Root cause:** Architectural mismatch between ONNX/CoreML and modern transformer position encodings.

**Fix:** Replaced fastembed with `mlx-embedding-models` (Apple MLX framework). Same models, native Metal GPU.
- Description model: jina 512d → nomic-v1.5 768d (original spec model)
- Backend: fastembed TextEmbedding → MLX EmbeddingModel (Metal GPU)
- SEQ_LENS monkey-patch for nomic's 2048-token context
- Cross-encoder reranker stays on fastembed (not available in MLX)
- `vec_meta` table tracks dimensions, auto-migrates on model change
- Benchmarks: BGE-small 13ms/doc, nomic 307ms/doc (vs minutes+ on ONNX CPU)

### 3. Spec Synchronization (kerf: `spec-sync`, SQUARE)
All 4 specs (00, 01, 05, 06) updated to match implemented code:
- Spec 01: Added missing modules, CLI commands, pipeline stages, util functions
- Spec 05: Claude CLI backend (was Agent SDK), batch params, llm_filter, dep names
- Spec 06: vec_meta migration, method defaults, MLX backend references
- Spec 00: Removed stale claude-agent-sdk reference

---

## Embedding Performance (M4 Mac Mini, 16GB)

| Model | Role | Dims | Backend | Per-doc | Batch 32 |
|-------|------|------|---------|---------|----------|
| BGE-small-en-v1.5 | Summary | 384 | MLX Metal | 13ms | 0.3s |
| nomic-embed-text-v1.5 | Description | 768 | MLX Metal | 307ms | 9.8s |
| ms-marco-MiniLM-L-6-v2 | Re-ranker | n/a | fastembed ONNX | per-query | per-query |

Full embedding run: 4,292 jobs in 15.6 minutes, steady 1,748MB RSS.

---

## Kerf Works

| Work | Jig | Status | Location |
|------|-----|--------|----------|
| `vector-search` | spec | ready | `~/.kerf/projects/job-board-search/vector-search/` |
| `desc-cleanup` | bug | ready | `~/.kerf/projects/job-board-search/desc-cleanup/` |
| `embed-model` | plan | ready | `~/.kerf/projects/job-board-search/embed-model/` |
| `spec-sync` | plan | ready | `~/.kerf/projects/job-board-search/spec-sync/` |

## Specs

All specs in `specs/`, **in sync with code** as of 2026-04-10:
- 00-overview, 01-architecture, 02-data-model, 03-cli-ux
- 04-search-ranking, 05-enrichment, 06-vector-search
- hn-careers-pipeline

## Known Issues (pre-existing)
- Salary regex overmatch on some Greenhouse postings
- Some company names are slug-derived
- `jbs tokens validate` not tested end-to-end
- `jbs tokens discover` not tested end-to-end
- mlx-embedding-models progress bars are noisy (tqdm output during search)

## Development Process

See `plans/PROCESS.md` and `CLAUDE.md`. Use kerf for non-trivial features. Delegate implementation via beads to worker agents. Don't implement directly — orchestrate.
