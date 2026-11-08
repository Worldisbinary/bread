"""Embeddings and vector search.

Default: BAAI/bge-small-en-v1.5 through fastembed (ONNX, runs locally on CPU, free,
384 dimensions). Vectors are L2-normalised, so cosine similarity is a dot product.
HashEmbedder is a deterministic offline fallback for tests and CI.
"""

import hashlib
import re

import numpy as np

QUERY_PREFIX = "Represent this sentence for searching relevant passages: "  # bge retrieval convention


class FastEmbedder:
    name = "bge-small-en-v1.5"

    def __init__(self, model: str = "BAAI/bge-small-en-v1.5") -> None:
        import os

        from fastembed import TextEmbedding

        self.model = TextEmbedding(model, cache_dir=os.environ.get("FASTEMBED_CACHE_PATH"))
        self._cache: dict[str, np.ndarray] = {}

    def embed(self, texts: list[str]) -> np.ndarray:
        missing = [t for t in dict.fromkeys(texts) if t not in self._cache]
        if missing:
            for text, vec in zip(missing, self.model.embed(missing), strict=True):
                self._cache[text] = _normalise(np.asarray(vec, dtype=np.float32))
        return np.stack([self._cache[t] for t in texts]) if texts else np.zeros((0, 384), np.float32)

    def embed_query(self, text: str) -> np.ndarray:
        return self.embed([QUERY_PREFIX + text])[0]


class HashEmbedder:
    """Feature-hashed unigrams and bigrams. Captures word overlap only; good enough for tests."""

    name = "hash-256"

    def __init__(self, dim: int = 256) -> None:
        self.dim = dim

    def embed(self, texts: list[str]) -> np.ndarray:
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for row, text in enumerate(texts):
            words = re.findall(r"[a-z0-9]+", text.lower())
            for token in words + [f"{a} {b}" for a, b in zip(words, words[1:], strict=False)]:
                h = int(hashlib.md5(token.encode()).hexdigest(), 16)
                out[row, h % self.dim] += 1.0 if (h >> 64) & 1 else -1.0
            out[row] = _normalise(out[row])
        return out

    def embed_query(self, text: str) -> np.ndarray:
        return self.embed([text])[0]


def _normalise(v: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(v)
    return v / n if n else v


def default_embedder():
    try:
        return FastEmbedder()
    except ImportError:
        return HashEmbedder()


class VectorIndex:
    """A small in-memory index: exact cosine search over normalised vectors (fine at this scale)."""

    def __init__(self, dim: int) -> None:
        self.vectors = np.zeros((0, dim), dtype=np.float32)
        self.payloads: list = []

    def add(self, vectors: np.ndarray, payloads: list) -> None:
        if len(payloads):
            self.vectors = np.vstack([self.vectors, vectors.astype(np.float32)])
            self.payloads.extend(payloads)

    def search(self, query: np.ndarray, k: int = 3, min_score: float = -1.0) -> list[tuple[float, object]]:
        if not self.payloads:
            return []
        scores = self.vectors @ query
        top = np.argsort(-scores)[:k]
        return [(float(scores[i]), self.payloads[i]) for i in top if scores[i] >= min_score]

    def __len__(self) -> int:
        return len(self.payloads)
