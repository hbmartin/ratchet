"""Local provider access for embeddings and optional text generation.

The local runtime is always filesystem-first, but still relies on the user's
own Gemini or OpenAI key for semantic embeddings and optional summarization.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from collections.abc import Iterable

import httpx

_EMBED_DIMENSION = 128


class LocalLLMError(ValueError):
    """Raised when no local provider is configured or a provider call fails."""


def _normalize(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(v * v for v in vec))
    if norm <= 0:
        return vec
    return [v / norm for v in vec]


class BaseLocalLLM:
    """Minimal provider surface required by the local runtime."""

    provider = "base"
    default_generation_model = ""

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]

    def generate_text(self, prompt: str, *, model: str | None = None) -> str:
        raise NotImplementedError


class FakeLocalLLM(BaseLocalLLM):
    """Deterministic provider used only in tests."""

    provider = "fake"
    default_generation_model = "fake-local"

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in texts:
            vec = [0.0] * _EMBED_DIMENSION
            for token in text.lower().split():
                digest = hashlib.sha256(token.encode("utf-8")).digest()
                for i in range(0, min(len(digest), _EMBED_DIMENSION)):
                    vec[i] += digest[i] / 255.0
            vectors.append(_normalize(vec))
        return vectors

    def generate_text(self, prompt: str, *, model: str | None = None) -> str:
        return json.dumps(
            {
                "summary": "deterministic local summary",
                "prompt_preview": prompt[:120],
                "model": model or self.default_generation_model,
            }
        )


class GeminiLocalLLM(BaseLocalLLM):
    """Gemini REST wrapper using the user's own API key."""

    provider = "gemini"
    default_generation_model = "gemini-2.5-flash"
    embedding_model = "gemini-embedding-001"

    def __init__(self, api_key: str, timeout: float = 60.0) -> None:
        self.api_key = api_key
        self.timeout = timeout
        self._client = httpx.Client(timeout=timeout)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in texts:
            response = self._client.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{self.embedding_model}:embedContent",
                headers={
                    "Content-Type": "application/json",
                    "x-goog-api-key": self.api_key,
                },
                json={
                    "model": f"models/{self.embedding_model}",
                    "taskType": "SEMANTIC_SIMILARITY",
                    "outputDimensionality": _EMBED_DIMENSION,
                    "content": {"parts": [{"text": text}]},
                },
            )
            response.raise_for_status()
            data = response.json()
            embedding = data.get("embedding", {}).get("values", [])
            if not embedding:
                raise LocalLLMError("Gemini embeddings response was empty.")
            vectors.append(_normalize([float(v) for v in embedding]))
        return vectors

    def generate_text(self, prompt: str, *, model: str | None = None) -> str:
        response = self._client.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model or self.default_generation_model}:generateContent",
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": self.api_key,
            },
            json={
                "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0.2},
            },
        )
        response.raise_for_status()
        data = response.json()
        candidates = data.get("candidates", [])
        if not candidates:
            raise LocalLLMError("Gemini generation response was empty.")
        parts = candidates[0].get("content", {}).get("parts", [])
        return "".join(str(part.get("text", "")) for part in parts).strip()


class OpenAILocalLLM(BaseLocalLLM):
    """OpenAI REST wrapper using the user's own API key."""

    provider = "openai"
    default_generation_model = "gpt-5-mini"
    embedding_model = "text-embedding-3-small"

    def __init__(self, api_key: str, timeout: float = 60.0) -> None:
        self.api_key = api_key
        self.timeout = timeout
        self._client = httpx.Client(timeout=timeout)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        response = self._client.post(
            "https://api.openai.com/v1/embeddings",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.embedding_model,
                "input": texts,
                "dimensions": _EMBED_DIMENSION,
            },
        )
        response.raise_for_status()
        data = response.json()
        items = data.get("data", [])
        if not items:
            raise LocalLLMError("OpenAI embeddings response was empty.")
        return [_normalize([float(v) for v in item.get("embedding", [])]) for item in items]

    def generate_text(self, prompt: str, *, model: str | None = None) -> str:
        response = self._client.post(
            "https://api.openai.com/v1/responses",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model or self.default_generation_model,
                "input": prompt,
            },
        )
        response.raise_for_status()
        data = response.json()
        output = data.get("output", [])
        chunks: list[str] = []
        for item in output:
            for content in item.get("content", []):
                text = content.get("text")
                if isinstance(text, str):
                    chunks.append(text)
        text_output = "".join(chunks).strip()
        if not text_output:
            raise LocalLLMError("OpenAI responses output was empty.")
        return text_output


def create_llm_client() -> BaseLocalLLM:
    """Resolve the local provider from environment variables."""
    if os.environ.get("MEGA_CODE_TEST_FAKE_LLM") == "1":
        return FakeLocalLLM()
    if gemini_api_key := os.environ.get("GEMINI_API_KEY"):
        return GeminiLocalLLM(gemini_api_key)
    if openai_api_key := os.environ.get("OPENAI_API_KEY"):
        return OpenAILocalLLM(openai_api_key)
    raise LocalLLMError(
        "No local model provider configured. Set GEMINI_API_KEY or OPENAI_API_KEY."
    )


def batch_embed_texts(texts: Iterable[str]) -> list[list[float]]:
    """Convenience wrapper used by the runtime and store tests."""
    client = create_llm_client()
    return client.embed_documents(list(texts))
