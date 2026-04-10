"""Local embedding generation for vector search.

Models must be downloaded before use: `jbs models download`.
Loading will fail if models are not cached locally.
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

DESC_MODEL = "jinaai/jina-embeddings-v2-small-en"
DESC_DIM = 512

RERANK_MODEL = "Xenova/ms-marco-MiniLM-L-6-v2"

# Truncation limit for description texts. The jina model has an 8192-token
# context window (~4 chars/token). 30k chars covers 99%+ of job descriptions
# without truncation while preventing OOM on outliers (some Greenhouse pages
# are 1M+ chars due to page-dump artifacts).
MAX_DESC_CHARS = 30_000

ALL_MODELS = {
    "summary": {"name": SUMMARY_MODEL, "type": "embedding"},
    "description": {"name": DESC_MODEL, "type": "embedding"},
    "reranker": {"name": RERANK_MODEL, "type": "cross_encoder"},
}


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------

def _get_cache_dir() -> Path:
    from fastembed.common.utils import define_cache_dir

    return Path(str(define_cache_dir()))


def is_model_cached(model_name: str) -> bool:
    """Check if a model's ONNX file exists in the cache.

    fastembed may store models under different names than the input
    (e.g., 'BAAI/bge-small-en-v1.5' → 'models--qdrant--bge-small-en-v1.5-onnx-q').
    We resolve the actual source repo from fastembed's model registry.
    """
    cache_dir = _get_cache_dir()

    # Get the HF source repo fastembed actually downloads from
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


def _resolve_hf_source(model_name: str) -> str | None:
    """Look up the actual HF repo fastembed downloads from."""
    try:
        from fastembed import TextEmbedding

        for m in TextEmbedding.list_supported_models():
            if m.get("model", "").lower() == model_name.lower():
                hf = m.get("sources", {}).get("hf")
                return hf
    except Exception:
        pass
    try:
        from fastembed.rerank.cross_encoder import TextCrossEncoder

        for m in TextCrossEncoder.list_supported_models():
            if m.get("model", "").lower() == model_name.lower():
                hf = m.get("sources", {}).get("hf")
                return hf
    except Exception:
        pass
    return None


def get_model_status() -> list[dict]:
    """Return status of all required models."""
    result = []
    for role, info in ALL_MODELS.items():
        cached = is_model_cached(info["name"])
        result.append({"role": role, "name": info["name"], "cached": cached})
    return result


def download_models() -> dict[str, bool]:
    """Download all models. Returns {model_name: success}."""
    from fastembed import TextEmbedding
    from fastembed.rerank.cross_encoder import TextCrossEncoder

    results = {}
    for role, info in ALL_MODELS.items():
        name = info["name"]
        log.info("Downloading %s model: %s", role, name)
        try:
            if info["type"] == "embedding":
                TextEmbedding(model_name=name)
            else:
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
            from fastembed import TextEmbedding

            self._require_cached(SUMMARY_MODEL)
            log.info("Loading summary model: %s", SUMMARY_MODEL)
            self._summary_model = TextEmbedding(model_name=SUMMARY_MODEL)
        return self._summary_model

    @property
    def desc_model(self):
        if self._desc_model is None:
            from fastembed import TextEmbedding

            self._require_cached(DESC_MODEL)
            log.info("Loading description model: %s", DESC_MODEL)
            self._desc_model = TextEmbedding(model_name=DESC_MODEL)
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
        """Embed a batch of composite summary texts."""
        return list(self.summary_model.passage_embed(texts))

    def embed_descriptions(self, texts: list[str]) -> list[np.ndarray]:
        """Embed a batch of full description texts."""
        return list(self.desc_model.passage_embed(texts))

    def query_summary(self, text: str) -> np.ndarray:
        """Embed a single query for summary search."""
        return list(self.summary_model.query_embed([text]))[0]

    def query_description(self, text: str) -> np.ndarray:
        """Embed a single query for description search."""
        return list(self.desc_model.query_embed([text]))[0]

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
