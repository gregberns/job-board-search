"""Local embedding generation for vector search.

Models must be downloaded before use: `jbs models download`.
Loading will fail if models are not cached locally.

Embedding backends:
  - Summary + Description: mlx-embedding-models (Apple MLX, on-device)
  - Reranker: fastembed (ONNX cross-encoder)
"""

import json
import logging
import os
from pathlib import Path
from typing import Optional

import numpy as np

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SUMMARY_MODEL = "BAAI/bge-small-en-v1.5"
SUMMARY_DIM = 384
SUMMARY_MLX_REGISTRY = "bge-small"

DESC_MODEL = "nomic-ai/nomic-embed-text-v1.5"
DESC_DIM = 768
DESC_MLX_REGISTRY = "nomic-text-v1.5"

RERANK_MODEL = "Xenova/ms-marco-MiniLM-L-6-v2"

# Truncation limit for description texts. The nomic model has a 2048-token
# context window (~4 chars/token). 30k chars covers 99%+ of job descriptions
# without truncation while preventing OOM on outliers (some Greenhouse pages
# are 1M+ chars due to page-dump artifacts).
MAX_DESC_CHARS = 30_000

ALL_MODELS = {
    "summary": {"name": SUMMARY_MODEL, "type": "embedding", "backend": "mlx"},
    "description": {"name": DESC_MODEL, "type": "embedding", "backend": "mlx"},
    "reranker": {"name": RERANK_MODEL, "type": "cross_encoder", "backend": "fastembed"},
}


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------

def _is_mlx_model_cached(hf_name: str) -> bool:
    """Check if an MLX/HF Hub model is cached locally.

    MLX models are stored via huggingface_hub in the standard HF cache layout:
    ~/.cache/huggingface/hub/models--{org}--{name}/snapshots/{hash}/
    """
    cache_dir = Path.home() / ".cache" / "huggingface" / "hub"
    dir_name = "models--" + hf_name.replace("/", "--")
    model_dir = cache_dir / dir_name / "snapshots"
    if not model_dir.exists():
        return False
    # Check that at least one snapshot directory exists with files
    for snapshot in model_dir.iterdir():
        if snapshot.is_dir() and any(snapshot.iterdir()):
            return True
    return False


def _resolve_hf_source(model_name: str) -> str | None:
    """Look up the actual HF repo fastembed downloads from (reranker only)."""
    try:
        from fastembed.rerank.cross_encoder import TextCrossEncoder

        for m in TextCrossEncoder.list_supported_models():
            if m.get("model", "").lower() == model_name.lower():
                hf = m.get("sources", {}).get("hf")
                return hf
    except Exception:
        pass
    return None


def _is_fastembed_model_cached(model_name: str) -> bool:
    """Check if a fastembed model's ONNX file exists in the cache."""
    try:
        from fastembed.common.utils import define_cache_dir
        cache_dir = Path(str(define_cache_dir()))
    except Exception:
        return False

    hf_source = _resolve_hf_source(model_name)
    candidates = [
        "models--" + model_name.replace("/", "--"),
    ]
    if hf_source and hf_source != model_name:
        candidates.append("models--" + hf_source.replace("/", "--"))

    for dirname in candidates:
        model_dir = cache_dir / dirname
        if not model_dir.exists():
            continue
        for root, _dirs, files in os.walk(model_dir):
            if any(f.endswith(".onnx") for f in files):
                return True
    return False


def is_model_cached(model_name: str) -> bool:
    """Check if a model is cached locally.

    Routes to MLX cache detection for embedding models,
    fastembed cache detection for the reranker.
    """
    if model_name in (SUMMARY_MODEL, DESC_MODEL):
        return _is_mlx_model_cached(model_name)
    elif model_name == RERANK_MODEL:
        return _is_fastembed_model_cached(model_name)
    else:
        # Unknown model — try both
        return _is_mlx_model_cached(model_name) or _is_fastembed_model_cached(model_name)


def get_model_status() -> list[dict]:
    """Return status of all required models."""
    result = []
    for role, info in ALL_MODELS.items():
        cached = is_model_cached(info["name"])
        result.append({"role": role, "name": info["name"], "cached": cached})
    return result


def download_models() -> dict[str, bool]:
    """Download all models. Returns {model_name: success}.

    MLX embedding models are downloaded via huggingface_hub.snapshot_download().
    The reranker is downloaded via fastembed TextCrossEncoder instantiation.
    """
    results = {}
    for role, info in ALL_MODELS.items():
        name = info["name"]
        backend = info["backend"]
        log.info("Downloading %s model: %s (backend: %s)", role, name, backend)
        try:
            if backend == "mlx":
                from huggingface_hub import snapshot_download
                snapshot_download(repo_id=name)
            else:
                from fastembed.rerank.cross_encoder import TextCrossEncoder
                TextCrossEncoder(model_name=name)
            results[name] = True
            log.info("  %s: OK", name)
        except Exception as exc:
            results[name] = False
            log.error("  %s: FAILED — %s", name, exc)
    return results


# ---------------------------------------------------------------------------
# Embedder
# ---------------------------------------------------------------------------


class ModelNotCachedError(RuntimeError):
    """Raised when trying to load a model that hasn't been downloaded."""


class Embedder:
    """Lazy-loaded embedding models for job vector search.

    Embedding models use mlx-embedding-models (Apple MLX, on-device).
    Reranker uses fastembed (ONNX cross-encoder).

    Models must be pre-downloaded via `jbs models download`.
    Raises ModelNotCachedError if a model is missing.
    """

    def __init__(self) -> None:
        self._summary_model = None
        self._desc_model = None
        self._reranker = None

    @staticmethod
    def _require_cached(model_name: str) -> None:
        if not is_model_cached(model_name):
            raise ModelNotCachedError(
                f"Model '{model_name}' not found in cache. "
                f"Run: jbs models download"
            )

    # -- lazy model properties ----------------------------------------------

    @property
    def summary_model(self):
        if self._summary_model is None:
            from mlx_embedding_models.embedding import EmbeddingModel

            self._require_cached(SUMMARY_MODEL)
            log.info("Loading summary model: %s", SUMMARY_MODEL)
            self._summary_model = EmbeddingModel.from_registry(SUMMARY_MLX_REGISTRY)
        return self._summary_model

    @property
    def desc_model(self):
        if self._desc_model is None:
            import mlx_embedding_models.embedding as mlx_emb
            from mlx_embedding_models.embedding import EmbeddingModel

            # Monkey-patch SEQ_LENS for 2048-token support (nomic-v1.5 needs it)
            if 2048 not in mlx_emb.SEQ_LENS:
                mlx_emb.SEQ_LENS.extend([640, 768, 896, 1024, 1280, 1536, 2048])

            self._require_cached(DESC_MODEL)
            log.info("Loading description model: %s", DESC_MODEL)
            self._desc_model = EmbeddingModel.from_registry(DESC_MLX_REGISTRY)
        return self._desc_model

    @property
    def reranker(self):
        if self._reranker is None:
            from fastembed.rerank.cross_encoder import TextCrossEncoder

            self._require_cached(RERANK_MODEL)
            log.info("Loading reranker: %s", RERANK_MODEL)
            self._reranker = TextCrossEncoder(model_name=RERANK_MODEL)
        return self._reranker

    # -- static helpers -----------------------------------------------------

    @staticmethod
    def build_composite_text(job: dict) -> str:
        """Build short text from job metadata for summary embedding."""
        lines: list[str] = []

        title = job.get("title")
        if title:
            lines.append(f"Title: {title}")

        company_name = job.get("company_name") or job.get("company_raw")
        company_desc = job.get("company_description")
        if company_name and company_desc:
            lines.append(f"Company: {company_name} — {company_desc}")
        elif company_name:
            lines.append(f"Company: {company_name}")

        summary = job.get("job_summary")
        if summary:
            lines.append(f"Summary: {summary}")

        domain = job.get("domain")
        if domain:
            lines.append(f"Domain: {domain}")

        tech_stack = job.get("tech_stack")
        if tech_stack:
            if isinstance(tech_stack, str):
                try:
                    tech_stack = json.loads(tech_stack)
                except (json.JSONDecodeError, TypeError):
                    tech_stack = [tech_stack]
            if isinstance(tech_stack, list) and tech_stack:
                lines.append(f"Tech: {', '.join(str(t) for t in tech_stack)}")

        return "\n".join(lines)

    @staticmethod
    def build_description_text(job: dict) -> str:
        """Build full description text for description embedding."""
        title = job.get("title") or ""
        company_name = job.get("company_name") or job.get("company_raw") or ""
        description = job.get("description") or ""

        if not description:
            return ""

        # Truncate to avoid OOM on outlier descriptions (some are 1M+ chars)
        if len(description) > MAX_DESC_CHARS:
            description = description[:MAX_DESC_CHARS]

        header = f"{title} at {company_name}" if company_name else title
        return f"{header}\n\n{description}"

    # -- embedding methods --------------------------------------------------

    def embed_summaries(self, texts: list[str]) -> list[np.ndarray]:
        """Embed a batch of composite summary texts.

        BGE-small does not require a prefix for passage/document embedding.
        Returns list of ndarray(384,).
        """
        result = self.summary_model.encode(texts)
        return [row for row in result]

    def embed_descriptions(self, texts: list[str]) -> list[np.ndarray]:
        """Embed a batch of full description texts.

        Nomic requires "search_document: " prefix for document embedding.
        Returns list of ndarray(768,).
        """
        prefixed = ["search_document: " + t for t in texts]
        result = self.desc_model.encode(prefixed)
        return [row for row in result]

    def query_summary(self, text: str) -> np.ndarray:
        """Embed a single query for summary search.

        BGE-small uses "query: " prefix for query embedding.
        Returns ndarray(384,).
        """
        result = self.summary_model.encode(["query: " + text])
        return result[0]

    def query_description(self, text: str) -> np.ndarray:
        """Embed a single query for description search.

        Nomic uses "search_query: " prefix for query embedding.
        Returns ndarray(768,).
        """
        result = self.desc_model.encode(["search_query: " + text])
        return result[0]

    def rerank(
        self, query: str, documents: list[str], top_n: int = 50
    ) -> list[tuple[int, float]]:
        """Rerank documents against a query using cross-encoder.

        Returns list of (original_index, score) tuples sorted by score desc.
        """
        scores = list(self.reranker.rerank(query, documents, top_k=top_n))
        indexed = [(i, s) for i, s in enumerate(scores)]
        indexed.sort(key=lambda x: x[1], reverse=True)
        return indexed[:top_n]


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_embedder: Optional[Embedder] = None


def get_embedder() -> Embedder:
    """Return the module-level Embedder singleton."""
    global _embedder
    if _embedder is None:
        _embedder = Embedder()
    return _embedder


# ---------------------------------------------------------------------------
# Reciprocal Rank Fusion
# ---------------------------------------------------------------------------


def rrf_combine(
    *ranked_lists: list[tuple[str, float]], k: int = 60
) -> list[tuple[str, float]]:
    """Reciprocal Rank Fusion over multiple ranked result lists.

    Each input is a list of (job_id, raw_score) tuples ordered best-first.
    Returns combined list of (job_id, rrf_score) sorted by score descending.
    """
    scores: dict[str, float] = {}
    for ranked in ranked_lists:
        for rank, (job_id, _raw) in enumerate(ranked, start=1):
            scores[job_id] = scores.get(job_id, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda x: x[1], reverse=True)
