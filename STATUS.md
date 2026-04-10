# Project Status — jbs

## What This Is

`jbs` — a local-first CLI tool for finding the right engineering job. Scrapes 5 job board sources, stores in SQLite, enriches with LLM classification, and provides search/filter/annotation. Python 3.12, Click + Rich CLI, Claude Haiku for enrichment via subscription.

## Current State: Vector Search In Progress (Blocked)

The base `jbs` package is fully built and running. Vector search feature was specced via kerf and partially implemented, but is **blocked on model memory issues** and has **spec/code drift** that needs resolution.

### Database (data/jobs.db)
- **4,801 jobs** (4,292 active, 509 inactive)
- **1,212 companies** (1,181 enriched with ai_native, industry, description)
- **1,253 engineering roles** identified by LLM
- **0 embeddings** — vec tables exist but are empty (embedding generation OOM'd)
- Sources: Greenhouse (3,239), HN (624), Lever (557), Ashby (301), RemoteOK (80)

### What Works
- `jbs init` — create DB, import tokens from flat files
- `jbs scrape` — all 5 sources (Greenhouse, Lever, Ashby, RemoteOK, HN)
- `jbs enrich --stage rules` — free rule-based extraction
- `jbs enrich --stage jobs` — LLM job classification via Claude CLI
- `jbs enrich --stage companies` — LLM company enrichment
- `jbs enrich --stage embeddings` — **exists but OOMs** (see below)
- `jbs search` — FTS5 + structured filters (working)
- `jbs search --vec "query"` — **code exists but no embeddings to search**
- `jbs models list` — shows cached model status
- `jbs models download` — downloads embedding models
- `jbs show`, `jbs annotate`, `jbs apply`, `jbs stats`, `jbs tokens` — all working
- **518 tests passing**

---

## Vector Search Feature — Status

### kerf Work: `vector-search`
- **Status:** `ready` (all 8 passes complete, `kerf square` passes)
- **Location:** `~/.kerf/projects/job-board-search/vector-search/`
- **Beads:** `plans/jbs/beads-vector-search.md` — 7 beads (5a-5g), all implemented

### What Was Specced (specs/06-vector-search.md)
- Two embedding models: BGE-small (384d, composite) + nomic-Q (768d, descriptions)
- Cross-encoder re-ranking: ms-marco-MiniLM-L-6-v2
- Hybrid search: FTS5 keyword + vector KNN → RRF fusion → cross-encoder re-rank
- sqlite-vec for storage, fastembed (ONNX) for local embeddings
- Stage 4 enrichment for embedding generation

### What Was Implemented (code)
All beads (5a-5g) were implemented by worker agents and verified:
- `jbs/embeddings.py` — Embedder, RRF, re-ranking, model cache management
- `jbs/store.py` — sqlite-vec loading, vec tables, KNN, hybrid_search()
- `jbs/enrich.py` — Stage 4 embedding generation
- `jbs/models.py` — SearchQuery.vec_query field
- `jbs/cli.py` — `--vec` flag, `--stage embeddings`, `jbs models` commands
- `pyproject.toml` — `[vector]` optional deps
- All 4 spec files updated (01, 04, 05, 06)

### What's Broken / Blocked

**CRITICAL: Embedding models OOM on job descriptions**
- `nomic-ai/nomic-embed-text-v1.5-Q` (768d, 8192 tokens): OOM'd at 45GB+
- `jinaai/jina-embeddings-v2-small-en` (512d, 8192 tokens): OOM'd at 79GB
- Job descriptions average 9,482 chars (~2,400 tokens)
- Batch size was reduced from 100 → 32 but still OOMs
- **Root cause unknown**: Could be ONNX Runtime memory allocation for long sequences, or model architecture issue on this hardware
- The summary model (BGE-small, 512 token limit) works fine — it's the description model that explodes

**SPEC/CODE DRIFT — changes made outside process:**
1. **Description model changed**: Spec says `nomic-ai/nomic-embed-text-v1.5-Q` (768d), code says `jinaai/jina-embeddings-v2-small-en` (512d). Vec table was manually recreated with 512d. Neither model actually works.
2. **`jbs models` commands added**: `jbs models list` and `jbs models download` were added to cli.py without being specced. They work correctly but aren't in any spec.
3. **ModelNotCachedError guard added**: embeddings.py now refuses to load models that aren't cached locally (requires `jbs models download` first). Not in spec.
4. **`load_dotenv()` added**: cli.py now loads `.env` file at startup for HF_TOKEN. Not in spec.
5. **Batch strategy changed in enrich.py**: Stage 4 now fetches jobs page-by-page (batch_size=32) instead of loading all upfront. Not in spec.

### What Needs To Happen Next

1. **Investigate OOM**: Why do 8192-token ONNX models OOM on ~2400 token descriptions? Options:
   - Profile memory usage per-document to find the actual cause
   - Try batch_size=1 to isolate whether it's per-doc or cumulative
   - Try truncating descriptions to 512 tokens and using BGE-small for both
   - Try a different runtime (GPU vs CPU, different ONNX providers)
   - Consider API-based embeddings as fallback (OpenAI text-embedding-3-small)

2. **Resolve spec/code drift**: Either update specs to match code or revert code to match specs. The `jbs models` commands and cache guards are good ideas but need to be specced. The model choice needs a decision once OOM is resolved.

3. **Generate embeddings**: Once model issues are resolved, run `jbs enrich --stage embeddings` to populate vec tables.

4. **End-to-end test**: Verify `jbs search --vec "marketplace platform"` returns good results with real data.

---

## Prior State (Pre-Vector Search)

### LLM Pre-Filter
- 2,227 pass → sent to LLM
- 1,211 skip_mgmt, 920 skip_title, 296 skip_salary, 147 skip_seniority

### Known Issues (pre-existing)
- Salary regex overmatch on some Greenhouse postings
- Some company names are slug-derived
- `jbs tokens validate` not tested end-to-end
- `jbs tokens discover` not tested end-to-end

## Specs

All specs in `specs/`:
- 00-overview, 01-architecture, 02-data-model, 03-cli-ux
- 04-search-ranking (updated for vector search)
- 05-enrichment (updated for Stage 4)
- 06-vector-search (**new**, but has drift — see above)
- hn-careers-pipeline

## Development Process

See `plans/PROCESS.md` and `CLAUDE.md`. Use kerf for non-trivial features. Delegate implementation via beads to worker agents. Don't implement directly — orchestrate.
