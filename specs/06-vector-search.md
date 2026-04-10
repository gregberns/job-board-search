# Spec 06: Vector Search & Hybrid Retrieval

## Problem

FTS5 keyword search matches literal terms but cannot handle semantic queries like "marketplace platform where software is the core product" or "AI-native startup solving real-time coordination." The user's most important search criterion — business model alignment — is subjective and doesn't reduce to structured filter categories. Keyword search will miss companies that "connect buyers and sellers" when searching for "marketplace."

## Goal

Add local embedding-based vector search that combines with the existing FTS5 keyword search and structured filters via hybrid retrieval with re-ranking. All embeddings run locally — no API key needed.

## Embedding Models

Two MLX models via `mlx-embedding-models` (Metal GPU), one ONNX model via `fastembed` (re-ranking). Lazy-loaded, embedding models cached in `~/.cache/huggingface/hub/`, reranker in fastembed cache:

| Role | Model | Dims | Max Tokens | Size | Backend |
|------|-------|------|------------|------|---------|
| Summary | `BAAI/bge-small-en-v1.5` | 384 | 512 | 67 MB | MLX (Metal GPU) |
| Description | `nomic-ai/nomic-embed-text-v1.5` | 768 | 2048 | ~300 MB | MLX (Metal GPU) |
| Re-ranker | `Xenova/ms-marco-MiniLM-L-6-v2` | n/a | n/a | 80 MB | ONNX (fastembed) |

Total: ~447 MB downloaded on first use.

## Text Preparation

### Composite Text (for summary model)

```
Title: {title}
Company: {company_name} — {company_description}
Summary: {job_summary}
Domain: {domain}
Tech: {tech_stack, comma-joined}
```

Lines are omitted when the field is NULL. Typical length: 200-400 tokens. This captures the job's identity in a compact form — what role, at what kind of company, doing what, with what tech.

### Description Text (for description model)

```
{title} at {company_name}

{full job description}
```

Title and company prepended for context. Typical length: 2,000-3,000 tokens. The description model's 8,192 token limit covers all jobs in the corpus (avg 9,482 chars ≈ 2,400 tokens).

## Storage

Two sqlite-vec virtual tables, created in `Store._ensure_schema()` when sqlite-vec is available:

```sql
CREATE VIRTUAL TABLE IF NOT EXISTS vec_summaries
    USING vec0(embedding float[384] distance_metric=cosine);

CREATE VIRTUAL TABLE IF NOT EXISTS vec_descriptions
    USING vec0(embedding float[768] distance_metric=cosine);
```

**Rowid mapping:** Vec table rowids match the implicit SQLite `rowid` of the `jobs` table. This allows zero-cost joins: `JOIN jobs j ON j.rowid = v.rowid`. No separate mapping table is needed.

**Insert:**
```python
blob = embedding.astype(np.float32).tobytes()
conn.execute("INSERT OR REPLACE INTO vec_summaries(rowid, embedding) VALUES (?, ?)", (job_rowid, blob))
```

**KNN query:**
```sql
SELECT v.rowid, v.distance, j.id
FROM vec_summaries v
JOIN jobs j ON j.rowid = v.rowid
WHERE v.embedding MATCH :query_blob AND k = :k
ORDER BY v.distance
```

## Hybrid Search Pipeline

When `SearchQuery.vec_query` is set and sqlite-vec is loaded, `Store.search()` dispatches to `Store.hybrid_search()`:

### Step 1: Structured Filtering

Build WHERE clause from all structured fields (seniority, salary, domain, engineering_only, ai_native, etc.) — same logic as the existing search query builder. Execute to get the candidate job ID set. This narrows the universe before any ranking.

### Step 2: FTS5 Keyword Ranking (optional)

If `SearchQuery.text` is also set, run the FTS5 MATCH query. Score by `1.0 / (1.0 + ABS(rank))`. Filter results to the candidate set. This produces **ranked list 1**.

### Step 3: Summary Vector KNN

Embed `vec_query` using the summary model's `query_embed()` method (applies appropriate query prefix). Run KNN against `vec_summaries` with k=500. Filter results to the candidate set. This produces **ranked list 2**.

### Step 4: Description Vector KNN

Embed `vec_query` using the description model's `query_embed()` method. Run KNN against `vec_descriptions` with k=500. Filter results to the candidate set. This produces **ranked list 3**.

### Step 5: RRF Fusion

Combine all available ranked lists (2 or 3, depending on whether a text query was provided) using Reciprocal Rank Fusion:

```
score(job) = Σ 1/(k + rank_i)   for each ranked list i where the job appears
```

k = 60 (standard constant, empirically validated). RRF is rank-based, not score-based, so it is immune to scale differences between FTS5 scores and vector distances.

### Step 6: Cross-Encoder Re-ranking

Take the top 50 results from RRF. For each, build a (query, document) pair:
- Query: `vec_query`
- Document: job title + company name + job_summary (or first 500 chars of description if no summary)

Score each pair with the cross-encoder model. Re-sort by cross-encoder score descending.

### Step 7: Return

Apply `SearchQuery.offset` and `SearchQuery.limit`. Fetch full job details for the final result set. Return in re-ranked order with scores.

## Module Layout

`jbs/embeddings.py`:

```python
class Embedder:
    """Lazy-loading local embedding models."""

    # Properties: summary_model, desc_model, reranker (lazy-loaded)

    # Text preparation
    @staticmethod
    def build_composite_text(job: dict) -> str: ...
    @staticmethod
    def build_description_text(job: dict) -> str: ...

    # Batch embedding (for enrichment)
    def embed_summaries(self, texts: list[str]) -> list[np.ndarray]: ...
    def embed_descriptions(self, texts: list[str]) -> list[np.ndarray]: ...

    # Query embedding (for search)
    def query_summary(self, text: str) -> np.ndarray: ...
    def query_description(self, text: str) -> np.ndarray: ...

    # Re-ranking
    def rerank(self, query: str, documents: list[str], top_n: int) -> list[tuple[int, float]]: ...

def get_embedder() -> Embedder: ...  # Module-level singleton

def rrf_combine(*ranked_lists, k=60) -> list[tuple[str, float]]: ...
```

## Store Methods

Added to `Store`:

| Method | Purpose |
|--------|---------|
| `has_vec()` | Check if sqlite-vec is loaded |
| `get_vec_counts()` | Count embeddings in each vec table |
| `get_unembedded_jobs(limit)` | Active jobs not yet in vec_summaries |
| `store_embeddings(rows)` | Insert/replace embeddings in both vec tables |
| `hybrid_search(query)` | Full hybrid pipeline (steps 1-7) |

Private helpers:
| Method | Purpose |
|--------|---------|
| `_vec_knn(table, query_vec, k)` | KNN on a single vec table |
| `_fts_rank(text, limit)` | FTS5 ranking without structured filters |

## Graceful Degradation

| Condition | Behavior |
|-----------|----------|
| `sqlite-vec` not installed | `has_vec()` returns False. `search()` ignores `vec_query` with a warning. `enrich --stage embeddings` fails with install instructions. |
| `mlx-embedding-models` not installed | `enrich --stage embeddings` fails with install instructions. Search with `--vec` fails with install instructions. |
| Vec tables exist but are empty | `--vec` search returns empty results with message: "No embeddings found. Run: jbs enrich --stage embeddings" |
| Some jobs lack embeddings | KNN returns whatever matches. New jobs need `jbs enrich --stage embeddings` to be searchable via vector. |
| `vec_query` absent | Existing search behavior, unchanged. |

## Dependencies

```toml
[project.optional-dependencies]
vector = [
    "sqlite-vec>=0.1.6",
    "fastembed>=0.8",
    "mlx-embedding-models>=0.0.11",
    "einops",
]
```

`numpy` is a transitive dependency of mlx-embedding-models.
