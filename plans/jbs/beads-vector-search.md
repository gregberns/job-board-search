# Vector Search Implementation Beads

Source spec: `specs/06-vector-search.md` (new), updates to 04, 05

## Dependency Graph

```
L0 (Foundation — no deps on existing code beyond what exists)
├── 5a: Embeddings Module (jbs/embeddings.py)
└── 5b: pyproject.toml vector deps

L1 (Store — depends on L0)
└── 5c: Store vec integration (sqlite-vec loading, vec tables, storage, KNN)

L2 (Features — depends on L1)
├── 5d: Hybrid search (Store.hybrid_search, search dispatch)
└── 5e: Enrichment Stage 4 (enrich.py embedding generation)

L3 (CLI — depends on L2)
└── 5f: CLI + models (--vec flag, --stage embeddings, SearchQuery.vec_query)

L4 (Specs — parallel with everything)
└── 5g: Update spec files
```

---

## Bead 5a: Embeddings Module

**Creates:** `jbs/embeddings.py`
**Spec:** 06-vector-search §Module Layout, §Text Preparation, §Embedding Models

**What to build:**

1. `Embedder` class:
   - Lazy properties: `summary_model` (BGE-small, 384d), `desc_model` (nomic-Q, 768d), `reranker` (ms-marco-MiniLM)
   - `build_composite_text(job: dict) -> str` — Title + Company (+ desc) + Summary + Domain + Tech. Omit lines for NULL fields.
   - `build_description_text(job: dict) -> str` — "{title} at {company}\n\n{description}"
   - `embed_summaries(texts: list[str]) -> list[np.ndarray]` — via summary_model.passage_embed()
   - `embed_descriptions(texts: list[str]) -> list[np.ndarray]` — via desc_model.passage_embed()
   - `query_summary(text: str) -> np.ndarray` — via summary_model.query_embed()
   - `query_description(text: str) -> np.ndarray` — via desc_model.query_embed()
   - `rerank(query: str, documents: list[str], top_n: int) -> list[tuple[int, float]]` — via TextCrossEncoder from fastembed.rerank.cross_encoder

2. `get_embedder() -> Embedder` — module singleton

3. `rrf_combine(*ranked_lists, k=60) -> list[tuple[str, float]]` — Reciprocal Rank Fusion

**Tests:**
- `build_composite_text` with partial fields
- `rrf_combine` ranking correctness
- Model loading and embedding shapes (integration test, can be slow)

**Acceptance:** rrf_combine unit tests pass; embedding dimensions match spec (384, 768)

---

## Bead 5b: pyproject.toml vector deps

**Modifies:** `pyproject.toml`
**Spec:** 06-vector-search §Dependencies

Add:
```toml
[project.optional-dependencies]
vector = ["sqlite-vec>=0.1.6", "fastembed>=0.8"]
```

Keep existing `enrich` group unchanged.

**Acceptance:** `pip install -e ".[vector]"` succeeds

---

## Bead 5c: Store vec integration

**Modifies:** `jbs/store.py`
**Spec:** 06-vector-search §Storage, §Store Methods, §Graceful Degradation

**What to build:**

1. `_load_vec(conn) -> bool` — module-level helper: import sqlite_vec, enable_load_extension, sqlite_vec.load(conn). Return False on ImportError or any exception.

2. In `_conn()`: call `_load_vec`, set `self._vec_loaded`.

3. In `_ensure_schema()`: if `_vec_loaded`, create vec0 virtual tables:
   ```sql
   CREATE VIRTUAL TABLE IF NOT EXISTS vec_summaries USING vec0(embedding float[384] distance_metric=cosine);
   CREATE VIRTUAL TABLE IF NOT EXISTS vec_descriptions USING vec0(embedding float[768] distance_metric=cosine);
   ```

4. Methods:
   - `has_vec() -> bool`
   - `get_vec_counts() -> dict[str, int]`
   - `get_unembedded_jobs(limit=500) -> list[dict]` — active jobs WHERE rowid NOT IN vec_summaries, with company join
   - `store_embeddings(rows: list[tuple[int, np.ndarray|None, np.ndarray|None]]) -> int` — INSERT OR REPLACE, commit
   - `_vec_knn(table, query_vec, k=200) -> list[tuple[str, float]]` — MATCH + join to jobs for ID
   - `_fts_rank(text, limit=200) -> list[tuple[str, float]]` — standalone FTS5 ranking

**Import:** `import numpy as np` at top; `from jbs.embeddings import SUMMARY_DIM, DESC_DIM` in _ensure_schema only (lazy).

**Tests:**
- `has_vec()` returns True when sqlite-vec installed
- Vec tables created alongside existing schema
- Round-trip: store_embeddings then _vec_knn returns stored vectors
- Existing tests still pass

**Acceptance:** All existing store tests pass; new vec round-trip test passes

---

## Bead 5d: Hybrid search

**Modifies:** `jbs/store.py`
**Spec:** 06-vector-search §Hybrid Search Pipeline, 04-search-ranking §Search Dispatch

**What to build:**

1. `hybrid_search(query: SearchQuery) -> list[dict]`:
   - Step 1: Build structured WHERE clause (reuse existing filter logic), get candidate IDs
   - Step 2: If query.text, run `_fts_rank(text)`, filter to candidates → ranked list
   - Step 3: Embed vec_query with `embedder.query_summary()`, run `_vec_knn("vec_summaries")`, filter → ranked list
   - Step 4: Embed vec_query with `embedder.query_description()`, run `_vec_knn("vec_descriptions")`, filter → ranked list
   - Step 5: `rrf_combine(*ranked_lists)` 
   - Step 6: Take top 50, build rerank documents (title + company + summary or first 500 chars of desc), `embedder.rerank(vec_query, docs, top_n=50)`
   - Step 7: Apply offset/limit, fetch full details via IN clause, preserve order, attach scores

2. Modify `search()`: if `query.vec_query and self._vec_loaded`, dispatch to `hybrid_search()`

**Tests:**
- search() without vec_query unchanged (regression test)
- hybrid_search with structured filters narrows results
- hybrid_search with text + vec_query uses all 3 signals
- Empty vec tables returns empty results gracefully

**Acceptance:** Existing search tests pass; hybrid search returns results ordered by relevance

---

## Bead 5e: Enrichment Stage 4

**Modifies:** `jbs/enrich.py`
**Spec:** 05-enrichment additions §Stage 4

**What to build:**

1. `_run_stage4_embeddings(force: bool)`:
   - If not `store.has_vec()`: log warning, return
   - If force: delete all from vec_summaries and vec_descriptions
   - Get unembedded jobs via `store.get_unembedded_jobs(limit=5000)`
   - Import and get embedder
   - Batch loop (batches of 100):
     - Build composite texts and description texts
     - Embed both batches
     - Store via `store.store_embeddings()`
     - Log progress
   - Record in enrichment_runs (stage='embeddings')

2. Update `run()`: add `if stage is None or stage == "embeddings": self._run_stage4_embeddings(force)`

3. Update `_dry_run()`: add Stage 4 count (active jobs not in vec_summaries)

**Handle errors:** If fastembed not installed, catch ImportError with clear message. If a batch fails, log and continue with next batch.

**Tests:**
- Stage 4 embeds jobs that lack embeddings
- Stage 4 skips already-embedded jobs
- Stage 4 with force re-embeds everything
- dry_run includes Stage 4 count

**Acceptance:** `jbs enrich --stage embeddings` completes successfully on real DB

---

## Bead 5f: CLI + models

**Modifies:** `jbs/models.py`, `jbs/cli.py`
**Spec:** 04-search-ranking §SearchQuery, CLI changes

**What to build:**

1. `models.py`: Add `vec_query: str | None = None` to SearchQuery dataclass

2. `cli.py` search command:
   - Add `@click.option("--vec", default=None, help="Semantic search query")` 
   - Pass `vec_query=vec` to SearchQuery construction
   - If vec is set and not store.has_vec(): click.echo warning

3. `cli.py` enrich command:
   - Update stage type/choices to include 'embeddings'

**Tests:**
- CLI accepts --vec flag
- CLI accepts --stage embeddings
- SearchQuery.vec_query field exists

**Acceptance:** End-to-end: `jbs search --vec "marketplace platform" --engineering` returns results

---

## Bead 5g: Update spec files

**Creates/Modifies:** `specs/06-vector-search.md`, `specs/04-search-ranking.md`, `specs/05-enrichment.md`, `specs/01-architecture.md`

Copy from kerf artifacts:
- `05-spec-drafts/vector-search.md` → `specs/06-vector-search.md`
- `05-spec-drafts/search-ranking.md` → `specs/04-search-ranking.md`
- Apply `05-spec-drafts/enrichment.md` additions to `specs/05-enrichment.md`
- Apply `05-spec-drafts/architecture.md` additions to `specs/01-architecture.md`

**Acceptance:** All spec files internally consistent, cross-references valid
