"""Embedding providers.

``HashingEmbedder`` is a deterministic lexical embedder (feature hashing of normalised unigrams
and bigrams with sub-linear term frequency). It needs no model download or network, so retrieval
works offline and in CI. Switch to provider embeddings for semantic recall in production.
"""

from __future__ import annotations

import hashlib
import itertools
import math
from collections import Counter
from collections.abc import Sequence
from typing import Protocol

import httpx

from src.agent.textmatch import tokens
from src.config import Settings

STOPWORDS = frozenset(
    {
        "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "has", "have", "in", "is",
        "it", "its", "of", "on", "or", "that", "the", "this", "to", "was", "were", "will", "with",
        "our", "we", "you", "your", "i", "me", "my", "can", "could", "would", "should", "please",
        "there", "their", "them", "they", "what", "when", "where", "which", "who", "how", "about",
        "into", "than", "then", "also", "any", "all", "not", "no", "do", "does", "did",
    }
)
_SUFFIXES = ("ing", "ed", "es", "s", "ly")


def _stem(word: str) -> str:
    for suffix in _SUFFIXES:
        if len(word) > len(suffix) + 3 and word.endswith(suffix):
            return word[: -len(suffix)]
    return word


def features(text: str) -> Counter[str]:
    words = [_stem(word) for word in tokens(text) if word not in STOPWORDS]
    grams: Counter[str] = Counter(words)
    grams.update(f"{left} {right}" for left, right in itertools.pairwise(words))
    return grams


class Embedder(Protocol):
    name: str
    dim: int

    async def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


class HashingEmbedder:
    name = "hashing"

    def __init__(self, dim: int = 512) -> None:
        self.dim = dim

    def embed_one(self, text: str) -> list[float]:
        vector = [0.0] * self.dim
        for gram, count in features(text).items():
            digest = hashlib.blake2b(gram.encode(), digest_size=8).digest()
            bucket = int.from_bytes(digest[:4], "little") % self.dim
            sign = 1.0 if digest[4] & 1 else -1.0
            weight = (1.0 + math.log(count)) * (1.5 if " " in gram else 1.0)
            vector[bucket] += sign * weight
        norm = math.sqrt(sum(value * value for value in vector))
        return [value / norm for value in vector] if norm else vector

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [self.embed_one(text) for text in texts]


class OpenAICompatibleEmbedder:
    """OpenAI ``/v1/embeddings`` (also served by Ollama, vLLM and most gateways)."""

    def __init__(self, *, base_url: str, model: str, api_key: str | None, dim: int, timeout: float = 60):
        self.name = model
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.dim = dim
        self.timeout = timeout

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        vectors: list[list[float]] = []
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            for start in range(0, len(texts), 64):
                batch = list(texts[start : start + 64])
                response = await client.post(
                    f"{self.base_url}/embeddings",
                    headers=headers,
                    json={"model": self.model, "input": batch},
                )
                response.raise_for_status()
                data = sorted(response.json()["data"], key=lambda item: item["index"])
                vectors.extend(item["embedding"] for item in data)
        return vectors


def build_embedder(settings: Settings) -> Embedder:
    if settings.embeddings == "openai":
        key = settings.openai_api_key.get_secret_value() if settings.openai_api_key else None
        if not key:
            raise ValueError("OPENAI_API_KEY is required for EMBEDDINGS=openai")
        return OpenAICompatibleEmbedder(
            base_url=settings.embedding_base_url or "https://api.openai.com/v1",
            model=settings.embedding_model or "text-embedding-3-small",
            api_key=key,
            dim=settings.embedding_dim or 1536,
        )
    if settings.embeddings == "ollama":
        return OpenAICompatibleEmbedder(
            base_url=settings.embedding_base_url or "http://localhost:11434/v1",
            model=settings.embedding_model or "nomic-embed-text",
            api_key=None,
            dim=settings.embedding_dim or 768,
        )
    return HashingEmbedder(dim=settings.embedding_dim or 512)
