# Embedding Model Swap — Implementation Beads

Source spec: `SPEC.md` (this kerf work), updates to `specs/06-vector-search.md`

## Dependency Graph

```
L0 (Foundation — no deps between them)
├── 6a: Embedder backend swap (jbs/embeddings.py)
└── 6c: Dependency update (pyproject.toml)

L1 (Store — depends on L0)
└── 6b: Vec table migration (jbs/store.py)

L2 (Messages — depends on L0 + L1)
└── 6d: Spec + message updates (specs/, enrich.py, cli.py)
```

---

## Bead 6a: Embedder Backend Swap

**Modifies:** `jbs/embeddings.py`
**Spec:** SPEC.md §C1, `05-specs/c1-embedder-spec.md`

**What to build:**

1. Update constants:
   - `DESC_MODEL` = `"nomic-ai/nomic-embed-text-v1.5"`, `DESC_DIM` = 768
   - Add `SUMMARY_MLX_REGISTRY = "bge-small"`, `DESC_MLX_REGISTRY = "nomic-text-v1.5"`
   - Update `ALL_MODELS` dict: description model name, add `"backend"` key (`"mlx"` or `"fastembed"`)

2. Rewrite model loading (lazy properties):
   - `summary_model`: `EmbeddingModel.from_registry("bge-small")` via `mlx_embedding_models.embedding`
   - `desc_model`: Apply SEQ_LENS monkey-patch (extend with `[640, 768, 896, 1024, 1280, 1536, 2048]`), then `EmbeddingModel.from_registry("nomic-text-v1.5")`
   - `reranker`: unchanged (fastembed TextCrossEncoder)

3. Rewrite embedding methods:
   - `embed_summaries(texts)`: `model.encode(texts)` -> split ndarray rows into list. No prefix.
   - `embed_descriptions(texts)`: prepend `"search_document: "` to each text, encode, split rows
   - `query_summary(text)`: prepend `"query: "`, encode, return `result[0]`
   - `query_description(text)`: prepend `"search_query: "`, encode, return `result[0]`

4. Rewrite cache detection:
   - New `_is_mlx_model_cached(hf_name)`: check `~/.cache/huggingface/hub/models--{org}--{name}/snapshots/` for files
   - `is_model_cached(model_name)`: route to MLX check for embedding models, fastembed check for reranker
   - Remove `_get_cache_dir()` (fastembed-specific)
   - Keep `_resolve_hf_source()` scoped to reranker only

5. Rewrite `download_models()`:
   - MLX models: `huggingface_hub.snapshot_download(repo_id)`
   - Reranker: `TextCrossEncoder(model_name=...)` (fastembed, unchanged)

6. Keep unchanged: `build_composite_text()`, `build_description_text()`, `rrf_combine()`, `ModelNotCachedError`, `get_embedder()`, `_embedder`

**Tests:**
- `embed_summaries` returns list of ndarray(384,) — integration test, needs models
- `embed_descriptions` returns list of ndarray(768,) — integration test, needs models
- `query_summary` returns ndarray(384,) — integration test, needs models
- `query_description` returns ndarray(768,) — integration test, needs models
- Nomic handles >512 token input without error (SEQ_LENS patch)
- `build_composite_text` existing tests pass (unchanged function)
- `rrf_combine` existing tests pass (unchanged function)
- `is_model_cached` returns correct status
- `download_models` returns success dict
- `get_model_status` returns list of 3 dicts with correct structure

**Acceptance:**
1. `DESC_DIM` is 768, `SUMMARY_DIM` is 384
2. `embed_summaries(["test"])` returns `[ndarray(384,)]`
3. `embed_descriptions(["test"])` returns `[ndarray(768,)]`
4. `query_summary("test")` returns `ndarray(384,)`
5. `query_description("test")` returns `ndarray(768,)`
6. `rerank("q", ["d1", "d2"], 2)` returns `[(int, float), ...]`
7. All existing tests pass

---

## Bead 6b: Vec Table Migration

**Modifies:** `jbs/store.py`
**Spec:** SPEC.md §C2, `05-specs/c2-vec-migration-spec.md`
**Depends on:** 6a (needs `DESC_DIM` = 768)

**What to build:**

1. Add `vec_meta` table creation to `_ensure_schema()`:
   ```sql
   CREATE TABLE IF NOT EXISTS vec_meta (table_name TEXT PRIMARY KEY, dim INTEGER NOT NULL)
   ```

2. Add `_ensure_vec_table(conn, table_name, dim)` helper (module-level function):
   - Check `vec_meta` for stored dimension
   - If match: no action
   - If mismatch: DROP table, CREATE at new dim, update vec_meta
   - If no meta entry but table exists in sqlite_master: DROP (stale from pre-meta era), CREATE, insert meta
   - If no meta entry and no table: CREATE, insert meta

3. Replace current vec table creation block in `_ensure_schema()`:
   ```python
   # Before (lines 372-382):
   if self._vec_loaded:
       from jbs.embeddings import SUMMARY_DIM, DESC_DIM
       conn.execute(f"CREATE VIRTUAL TABLE IF NOT EXISTS vec_summaries ...")
       conn.execute(f"CREATE VIRTUAL TABLE IF NOT EXISTS vec_descriptions ...")

   # After:
   if self._vec_loaded:
       from jbs.embeddings import SUMMARY_DIM, DESC_DIM
       conn.execute("CREATE TABLE IF NOT EXISTS vec_meta (table_name TEXT PRIMARY KEY, dim INTEGER NOT NULL)")
       _ensure_vec_table(conn, "vec_summaries", SUMMARY_DIM)
       _ensure_vec_table(conn, "vec_descriptions", DESC_DIM)
   ```

**Tests:**
- Fresh database: both vec tables created at correct dimensions (384d, 768d)
- Fresh database: vec_meta has entries for both tables with correct dims
- Migration: existing 512d vec_descriptions dropped and recreated at 768d
- Migration: existing vec_summaries (384d) preserved, embeddings intact
- Idempotent: running _ensure_schema() twice produces same result
- store_embeddings() with 768d vectors succeeds after migration
- _vec_knn("vec_descriptions", ...) works with 768d query after migration
- All existing store tests pass

**Acceptance:**
1. Fresh DB: `vec_meta` shows `vec_summaries=384, vec_descriptions=768`
2. Migrated DB: `vec_descriptions` recreated at 768d, `vec_summaries` preserved
3. `store_embeddings()` accepts 768d description vectors
4. Idempotent: repeated `_ensure_schema()` calls are no-ops after first run
5. All existing tests pass

---

## Bead 6c: Dependency Update

**Modifies:** `pyproject.toml`
**Spec:** SPEC.md §C3, `05-specs/c3-dependencies-spec.md`

**What to build:**

Update `[project.optional-dependencies]`:

```toml
# Before:
vector = ["sqlite-vec>=0.1.6", "fastembed>=0.8"]

# After:
vector = [
    "sqlite-vec>=0.1.6",
    "fastembed>=0.8",
    "mlx-embedding-models>=0.0.11",
    "einops",
]
```

Then: `pip install -e ".[vector]"` in the project venv.

**Tests:**
- `pip install -e ".[vector]"` completes without error
- `python -c "import mlx_embedding_models"` succeeds
- `python -c "import einops"` succeeds
- `python -c "import fastembed"` still succeeds
- `python -c "import sqlite_vec"` still succeeds

**Acceptance:**
1. `pip install -e ".[vector]"` succeeds
2. All required imports work
3. No dependency conflicts

---

## Bead 6d: Spec + Message Updates

**Modifies:** `specs/06-vector-search.md`, `jbs/enrich.py`, `jbs/cli.py`
**Spec:** SPEC.md §C4, `05-specs/c4-spec-updates-spec.md`
**Depends on:** 6a + 6c (final model and package names)

**What to build:**

1. `specs/06-vector-search.md`:
   - Model table header: "Three ONNX models via `fastembed`" -> "Two MLX models via `mlx-embedding-models` (Metal GPU), one ONNX model via `fastembed` (re-ranking). Lazy-loaded, embedding models cached in `~/.cache/huggingface/hub/`, reranker in fastembed cache:"
   - Dependencies section: update vector deps to match pyproject.toml
   - Dependencies note: update numpy note
   - Graceful degradation: "`fastembed` not installed" -> "`mlx-embedding-models` not installed"

2. `jbs/enrich.py`:
   - Line 394-395: `"Install: pip install sqlite-vec fastembed"` -> `"Install: pip install -e '.[vector]'"`
   - Lines 402-404: `"Stage 4: fastembed not available. Install: pip install fastembed"` -> `"Stage 4: mlx-embedding-models not available. Install: pip install -e '.[vector]'"`
   - Line 470: `'local-onnx'` -> `'local-mlx'`

3. `jbs/cli.py`:
   - Line 308: `"Warning: --vec requires sqlite-vec and fastembed. Install: pip install sqlite-vec fastembed"` -> `"Warning: --vec requires sqlite-vec and mlx-embedding-models. Install: pip install -e '.[vector]'"`

**Tests:**
- `grep "local-onnx" jbs/enrich.py` returns nothing
- `grep "fastembed" jbs/enrich.py` only finds import statements (not user messages)
- `grep "fastembed" jbs/cli.py` returns nothing (or only non-user-facing references)
- All existing tests pass

**Acceptance:**
1. No stale "fastembed" references in user-facing messages
2. enrichment_runs model is `'local-mlx'`
3. spec file internally consistent with new runtime
4. All existing tests pass
