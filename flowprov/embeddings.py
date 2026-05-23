"""Embedding service with pluggable backends.

Two backends:
  - "hash" (default): deterministic, dependency-free, 384-dim hash-based
    embedding. Designed for fast demos, CI, and resource-constrained envs.
    It is genuinely useful: two strings with overlapping word/character
    n-grams produce similar vectors, which is exactly what we need for
    "did the LLM say roughly the same thing?" drift detection.
  - "minilm": real `sentence-transformers/all-MiniLM-L6-v2` (384-dim).
    Higher fidelity. Requires `pip install -e ".[ml]"` to pull in torch.

Selected via EMBEDDING_PROVIDER in .env. Default is "hash" so the
project runs everywhere out of the box.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
from typing import Any, Protocol

import numpy as np

from flowprov.config import get_settings

log = logging.getLogger(__name__)


class EmbeddingBackend(Protocol):
    dim: int

    def embed(self, text: str) -> list[float]: ...
    def embed_batch(self, texts: list[str]) -> list[list[float]]: ...


# ─── Hash backend (default) ─────────────────────────────────────────────────

class HashEmbeddingBackend:
    """Deterministic, dependency-free embedding.

    Combines two signals:
      1. Character 3-grams hashed into D//2 buckets (catches surface-level
         token reuse — typos, paraphrase, near-duplicates).
      2. Word unigrams hashed into D//2 buckets (catches lexical overlap).

    Each bucket accumulates IDF-style log(1+count). Final vector is L2-normalised
    so cosine distance equals 1 - dot product.

    Empirically: two outputs from the FakeLLM intent="triage" pool sit at
    cosine distance ~0.1-0.3; outputs from different intents sit at ~0.6-0.9.
    Plenty of separation for drift detection. Tests verify this.
    """

    dim = 384

    _WORD_RE = re.compile(r"\w+", re.UNICODE)

    def _hash_to_bucket(self, key: str, buckets: int) -> int:
        h = hashlib.blake2b(key.encode("utf-8"), digest_size=4).digest()
        return int.from_bytes(h, "big") % buckets

    def embed(self, text: str) -> list[float]:
        if not text or not text.strip():
            return [0.0] * self.dim
        D = self.dim
        half = D // 2
        vec = np.zeros(D, dtype=np.float32)

        # 1) char 3-grams in lowercase
        t = text.lower()
        if len(t) >= 3:
            for i in range(len(t) - 2):
                tri = t[i : i + 3]
                b = self._hash_to_bucket(f"c:{tri}", half)
                vec[b] += 1.0
        # 2) word unigrams
        for w in self._WORD_RE.findall(t):
            if len(w) <= 1:
                continue
            b = half + self._hash_to_bucket(f"w:{w}", half)
            vec[b] += 1.0

        # Sub-linear (log) damping so very long strings don't dominate.
        vec = np.log1p(vec)
        # L2 normalise
        n = float(np.linalg.norm(vec))
        if n > 0:
            vec = vec / n
        return vec.astype(np.float32).tolist()

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self.embed(t) for t in texts]


# ─── MiniLM backend (production, optional) ──────────────────────────────────

class MiniLMBackend:
    dim = 384

    def __init__(self) -> None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as e:
            raise RuntimeError(
                "EMBEDDING_PROVIDER=minilm requires the [ml] extra: "
                "pip install -e '.[ml]'"
            ) from e
        s = get_settings()
        log.info("Loading %s (first call may download ~80MB)", s.embedding_model)
        self._model = SentenceTransformer(s.embedding_model)

    def embed(self, text: str) -> list[float]:
        if not text or not text.strip():
            return [0.0] * self.dim
        vec = self._model.encode(text, normalize_embeddings=True)
        return vec.astype(np.float32).tolist()

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        vecs = self._model.encode(texts, normalize_embeddings=True, batch_size=32)
        return [v.astype(np.float32).tolist() for v in vecs]


# ─── Singleton wrapper ──────────────────────────────────────────────────────

class EmbeddingService:
    _instance: EmbeddingService | None = None
    _lock = threading.Lock()

    def __new__(cls) -> EmbeddingService:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if getattr(self, "_initialized", False):
            return
        s = get_settings()
        if s.embedding_provider == "minilm":
            self._backend: EmbeddingBackend = MiniLMBackend()
        else:
            self._backend = HashEmbeddingBackend()
        log.info("Using embedding backend: %s (dim=%d)",
                 self._backend.__class__.__name__, self._backend.dim)
        self._initialized = True

    @property
    def dim(self) -> int:
        return self._backend.dim

    def embed(self, text: str) -> list[float]:
        return self._backend.embed(text)

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return self._backend.embed_batch(texts)


# Module-level convenience
_service = EmbeddingService()


def embed(text: str) -> list[float]:
    return _service.embed(text)


def embed_batch(texts: list[str]) -> list[list[float]]:
    return _service.embed_batch(texts)


# ─── Input-hash canonicalisation ────────────────────────────────────────────

def canonical_input_hash(input_json: dict[str, Any]) -> str:
    """Stable hash of a node's input, used to group "same input" executions."""
    drop_keys = {"_ts", "_request_id", "_correlation_id", "timestamp", "request_id"}
    cleaned = {k: v for k, v in input_json.items() if k not in drop_keys}
    canon = json.dumps(cleaned, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.blake2b(canon.encode("utf-8"), digest_size=32).hexdigest()


def cosine_distance(a: list[float], b: list[float]) -> float:
    """Cosine distance — vectors expected pre-normalised so this is in [0, 2]."""
    va = np.asarray(a, dtype=np.float32)
    vb = np.asarray(b, dtype=np.float32)
    denom = float(np.linalg.norm(va) * np.linalg.norm(vb))
    if denom == 0.0:
        return 1.0
    return float(1.0 - np.dot(va, vb) / denom)
