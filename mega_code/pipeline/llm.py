"""Local provider access for embeddings and optional text generation.

The local runtime is always filesystem-first, but still relies on the user's
own Gemini or OpenAI key for semantic embeddings and optional summarization.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
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
                for i in range(0, len(digest), 2):
                    idx = digest[i] % _EMBED_DIMENSION
                    sign = 1.0 if digest[(i + 1) % len(digest)] % 2 == 0 else -1.0
                    weight = (digest[(i + 2) % len(digest)] / 255.0) + 0.1
                    vec[idx] += sign * weight
            vectors.append(_normalize(vec))
        return vectors

    def _structured_payload(self, prompt: str, marker: str) -> dict | None:
        prefix = f"MEGA_CODE_JSON_PASS::{marker}"
        if not prompt.startswith(prefix):
            return None
        match = re.search(r"PAYLOAD_JSON_START\n(.*)\nPAYLOAD_JSON_END", prompt, re.DOTALL)
        if not match:
            return None
        return json.loads(match.group(1))

    def generate_text(self, prompt: str, *, model: str | None = None) -> str:
        if payload := self._structured_payload(prompt, "SUCCESS_ANALYST"):
            return json.dumps({"proposals": payload.get("candidates", [])})
        if payload := self._structured_payload(prompt, "ERROR_ANALYST"):
            return json.dumps({"proposals": payload.get("candidates", [])})
        if payload := self._structured_payload(prompt, "CONSOLIDATOR"):
            grouped_proposals = payload.get("grouped_proposals", [])
            workflow = []
            verification_loop: list[str] = []
            failure_guards: list[str] = []
            strategy = {
                "delta_rules": [],
                "correction_patterns": [],
                "when_to_retry": [],
                "when_to_stop": [],
                "support_signals": [],
            }
            memory_fragments = []
            for proposal in grouped_proposals:
                item = {
                    "title": proposal["title"],
                    "rule": proposal["rule"],
                    "evidence_session_ids": proposal.get("evidence_session_ids", []),
                    "support_count": proposal.get("support_count", 1),
                    "examples": proposal.get("examples", []),
                }
                target = proposal.get("target", "")
                if target == "canonical_workflow":
                    workflow.append(item)
                elif target == "verification_loop":
                    verification_loop.append(proposal["rule"])
                elif target == "failure_guards":
                    failure_guards.append(proposal["rule"])
                elif target == "correction_patterns":
                    strategy["correction_patterns"].append(proposal["rule"])
                    strategy["delta_rules"].append(proposal["rule"])
                elif target == "when_to_retry":
                    strategy["when_to_retry"].append(proposal["rule"])
                    strategy["delta_rules"].append(proposal["rule"])
                elif target == "when_to_stop":
                    strategy["when_to_stop"].append(proposal["rule"])
                elif target == "support_signals":
                    strategy["support_signals"].append(proposal["rule"])
                else:
                    strategy["delta_rules"].append(proposal["rule"])
                memory_fragments.append(
                    {
                        "name": proposal["title"],
                        "procedure": proposal["rule"],
                        "context": proposal.get("applicability", ""),
                        "resultant": "Advance the clustered workflow reliably."
                        if target in {"canonical_workflow", "verification_loop"}
                        else "Avoid repeating the same failure pattern.",
                        "constraints": "Ground the action in repeated session evidence.",
                        "evidence_session_ids": proposal.get("evidence_session_ids", []),
                        "support_count": proposal.get("support_count", 1),
                        "kind": "success" if target in {"canonical_workflow", "verification_loop"} else "error",
                    }
                )
            if not strategy["support_signals"]:
                strategy["support_signals"] = verification_loop[:2] or [
                    "Use the project verification command as the readiness signal."
                ]
            return json.dumps(
                {
                    "summary": f"Cluster {payload.get('cluster_id', 'cluster')} consolidates {len(payload.get('member_session_ids', []))} related sessions into one reusable workflow.",
                    "applicability": payload.get("applicability_hints", []),
                    "canonical_workflow": workflow[:6],
                    "verification_loop": verification_loop[:4],
                    "failure_guards": failure_guards[:4],
                    "strategy": strategy,
                    "memory_fragments": memory_fragments[:8],
                    "keywords": payload.get("keywords", []),
                }
            )
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
