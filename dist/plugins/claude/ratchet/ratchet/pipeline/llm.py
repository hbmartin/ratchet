"""Local-only embedding and text generation helpers.

Ratchet does not call hosted model providers directly. The default provider is
deterministic and filesystem-safe. Optional host-agent generation delegates to
the existing ``ratchet.client.host_llm`` subprocess path.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from ratchet.client.config import load_config

_EMBED_DIMENSION = 128


class LocalLLMError(ValueError):
    """Raised when a local provider is unavailable or fails."""


@dataclass(frozen=True)
class RerankedDocument:
    """A document ranked for retrieval."""

    index: int
    text: str
    score: float


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

    def rerank_documents(
        self,
        query: str,
        documents: list[str],
        *,
        top_k: int | None = None,
    ) -> list[RerankedDocument]:
        query_vector = self.embed_query(query)
        document_vectors = self.embed_documents(documents)
        ranked = [
            RerankedDocument(
                index=index,
                text=document,
                score=sum(q * d for q, d in zip(query_vector, vector, strict=False)),
            )
            for index, (document, vector) in enumerate(zip(documents, document_vectors, strict=True))
        ]
        ranked.sort(key=lambda item: item.score, reverse=True)
        return ranked[:top_k] if top_k else ranked


class DeterministicLocalLLM(BaseLocalLLM):
    """Deterministic provider used by the local runtime."""

    provider = "deterministic"
    default_generation_model = "deterministic-local"

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
        prefix = f"RATCHET_JSON_PASS::{marker}"
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
                    "summary": (
                        f"Cluster {payload.get('cluster_id', 'cluster')} consolidates "
                        f"{len(payload.get('member_session_ids', []))} related sessions into "
                        "one reusable workflow."
                    ),
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


class FakeLocalLLM(DeterministicLocalLLM):
    """Backward-compatible test alias for deterministic local behavior."""

    provider = "fake"
    default_generation_model = "fake-local"


class LocalHashEmbeddingLLM(BaseLocalLLM):
    """Compatibility embedding provider backed by deterministic hashing."""

    provider = "local-hash"
    default_generation_model = ""

    def __init__(self) -> None:
        self._deterministic = DeterministicLocalLLM()

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._deterministic.embed_documents(texts)

    def generate_text(self, prompt: str, *, model: str | None = None) -> str:
        raise LocalLLMError("local-hash does not support generation")


class AgentCLILocalLLM(BaseLocalLLM):
    """Generation provider backed by an isolated local agent CLI."""

    provider = "agent-cli"
    default_generation_model = "host-agent"

    def __init__(self, agent: str | None = None) -> None:
        self.agent = agent

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        raise LocalLLMError("agent-cli does not provide embeddings")

    def generate_text(self, prompt: str, *, model: str | None = None) -> str:
        from ratchet.client.host_llm import complete

        _ = model
        try:
            result = asyncio.run(complete(prompt=prompt, agent=self.agent))
        except RuntimeError as exc:
            raise LocalLLMError(str(exc)) from exc
        if result.is_error or not result.text:
            raise LocalLLMError("agent CLI generation returned no text")
        return result.text


class CommandAdapterLLM(BaseLocalLLM):
    """Custom local command adapter.

    The generation command receives the prompt on stdin and returns text on
    stdout. The embedding command receives JSON ``{"texts": [...]}`` and
    returns ``[[...]]``.
    """

    provider = "command"
    default_generation_model = "command-adapter"

    def __init__(
        self,
        *,
        generation_command: str | None = None,
        embedding_command: str | None = None,
        timeout: float = 120.0,
    ) -> None:
        self.generation_command = generation_command
        self.embedding_command = embedding_command
        self.timeout = timeout

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not self.embedding_command:
            raise LocalLLMError("No command embedding adapter configured.")
        proc = subprocess.run(
            self.embedding_command,
            input=json.dumps({"texts": texts}),
            text=True,
            shell=True,
            capture_output=True,
            timeout=self.timeout,
            check=False,
        )
        if proc.returncode != 0:
            raise LocalLLMError(proc.stderr.strip() or "command embedder failed")
        vectors = json.loads(proc.stdout)
        if not isinstance(vectors, list):
            raise LocalLLMError("command embedder did not return a vector list")
        return [_normalize([float(v) for v in vector]) for vector in vectors]

    def generate_text(self, prompt: str, *, model: str | None = None) -> str:
        if not self.generation_command:
            raise LocalLLMError("No command generation adapter configured.")
        _ = model
        proc = subprocess.run(
            self.generation_command,
            input=prompt,
            text=True,
            shell=True,
            capture_output=True,
            timeout=self.timeout,
            check=False,
        )
        if proc.returncode != 0:
            raise LocalLLMError(proc.stderr.strip() or "command generator failed")
        text_output = proc.stdout.strip()
        if not text_output:
            raise LocalLLMError("command generator returned no text")
        return text_output


class RouterLLM(BaseLocalLLM):
    """Operation-aware local provider router."""

    provider = "router"
    default_generation_model = "router"

    def __init__(self, *, generation_providers: list[BaseLocalLLM], embedding_providers: list[BaseLocalLLM]) -> None:
        self.generation_providers = generation_providers
        self.embedding_providers = embedding_providers

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        errors: list[str] = []
        for provider in self.embedding_providers:
            try:
                return provider.embed_documents(texts)
            except Exception as exc:
                errors.append(f"{provider.provider}: {exc}")
        raise LocalLLMError("No embedding provider succeeded: " + "; ".join(errors))

    def generate_text(self, prompt: str, *, model: str | None = None) -> str:
        errors: list[str] = []
        for provider in self.generation_providers:
            try:
                return provider.generate_text(prompt, model=model)
            except Exception as exc:
                errors.append(f"{provider.provider}: {exc}")
        raise LocalLLMError("No generation provider succeeded: " + "; ".join(errors))

    def rerank_documents(
        self,
        query: str,
        documents: list[str],
        *,
        top_k: int | None = None,
    ) -> list[RerankedDocument]:
        try:
            return super().rerank_documents(query, documents, top_k=top_k)
        except Exception:
            return self._agent_rerank_documents(query, documents, top_k=top_k)

    def _agent_rerank_documents(
        self,
        query: str,
        documents: list[str],
        *,
        top_k: int | None = None,
    ) -> list[RerankedDocument]:
        numbered = "\n".join(f"{index}: {document}" for index, document in enumerate(documents))
        prompt = (
            "Rank the documents by relevance to the query. "
            "Return only JSON shaped as {\"ranked_indices\": [0, 1]}.\n\n"
            f"Query:\n{query}\n\nDocuments:\n{numbered}"
        )
        raw = self.generate_text(prompt)
        try:
            data = json.loads(raw)
            ranked_indices = data.get("ranked_indices", data)
            if not isinstance(ranked_indices, list):
                raise ValueError("ranked_indices is not a list")
            seen: set[int] = set()
            ranked: list[RerankedDocument] = []
            for rank, value in enumerate(ranked_indices):
                index = int(value)
                if index in seen or index < 0 or index >= len(documents):
                    continue
                seen.add(index)
                ranked.append(
                    RerankedDocument(
                        index=index,
                        text=documents[index],
                        score=float(len(documents) - rank),
                    )
                )
            for index, document in enumerate(documents):
                if index not in seen:
                    ranked.append(RerankedDocument(index=index, text=document, score=0.0))
            return ranked[:top_k] if top_k else ranked
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            raise LocalLLMError("Agent reranking did not return valid ranked indices") from exc


def _load_runtime_config() -> dict[str, Any]:
    return load_config()


def _running_agent_order() -> list[str]:
    configured = os.environ.get("RATCHETAI_HOST_AGENT") or os.environ.get("RATCHET_HOST_AGENT")
    if configured:
        return [configured]
    if any(os.environ.get(key) for key in ("CODEX_SHELL", "CODEX_THREAD_ID", "CODEX_HOME")):
        return ["codex", "claude"]
    if any(os.environ.get(key) for key in ("CLAUDE_SESSION_ID", "CLAUDE_PROJECT_DIR", "CLAUDE_PLUGIN_ROOT")):
        return ["claude", "codex"]
    return ["claude", "codex"]


def _provider_order(config: dict[str, Any], key: str, default: list[str]) -> list[str]:
    llm_config = config.get("llm", {})
    value = llm_config.get(key) if isinstance(llm_config, dict) else None
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return value
    return default


def _llm_mode(config: dict[str, Any]) -> str:
    llm_config = config.get("llm", {}) if isinstance(config.get("llm", {}), dict) else {}
    raw_mode = (
        os.environ.get("RATCHETAI_LLM_MODE")
        or os.environ.get("RATCHET_LLM_MODE")
        or llm_config.get("mode")
        or "deterministic"
    )
    mode = str(raw_mode).strip().lower()
    if mode in {"host", "host_cli", "agent", "agent-cli"}:
        return "host-cli"
    if mode in {"command", "deterministic", "host-cli"}:
        return mode
    return "deterministic"


def _build_provider(name: str, config: dict[str, Any]) -> BaseLocalLLM | None:
    llm_config = config.get("llm", {}) if isinstance(config.get("llm", {}), dict) else {}
    providers = llm_config.get("providers", {}) if isinstance(llm_config.get("providers", {}), dict) else {}
    provider_cfg = providers.get(name, {}) if isinstance(providers.get(name, {}), dict) else {}

    if name in {"deterministic", "fake"}:
        return DeterministicLocalLLM()
    if name == "local-hash":
        return LocalHashEmbeddingLLM()
    if name == "command":
        generation_command = provider_cfg.get("generation_command") or os.environ.get("RATCHET_GENERATION_COMMAND")
        embedding_command = provider_cfg.get("embedding_command") or os.environ.get("RATCHET_EMBEDDING_COMMAND")
        if generation_command or embedding_command:
            return CommandAdapterLLM(
                generation_command=str(generation_command) if generation_command else None,
                embedding_command=str(embedding_command) if embedding_command else None,
            )
    if name.startswith("agent:"):
        agent = name.split(":", 1)[1]
        if shutil.which(agent):
            return AgentCLILocalLLM(agent=agent)
    if name == "agent":
        for agent in _running_agent_order():
            if shutil.which(agent):
                return AgentCLILocalLLM(agent=agent)
    return None


def create_llm_client() -> BaseLocalLLM:
    """Resolve a local provider from configuration and environment."""
    if os.environ.get("RATCHET_TEST_FAKE_LLM") == "1":
        return FakeLocalLLM()

    config = _load_runtime_config()
    mode = _llm_mode(config)
    if mode == "host-cli":
        agent_order = [f"agent:{agent}" for agent in _running_agent_order()]
        generation_order = [*agent_order, "deterministic"]
        embedding_order = ["deterministic"]
    elif mode == "command":
        generation_order = _provider_order(config, "generation_order", ["command", "deterministic"])
        embedding_order = _provider_order(config, "embedding_order", ["command", "deterministic"])
    else:
        generation_order = ["deterministic"]
        embedding_order = ["deterministic"]

    generation_providers = [
        provider for name in generation_order if (provider := _build_provider(name, config))
    ]
    embedding_providers = [
        provider for name in embedding_order if (provider := _build_provider(name, config))
    ]
    if not generation_providers:
        generation_providers = [DeterministicLocalLLM()]
    if not embedding_providers:
        embedding_providers = [DeterministicLocalLLM()]
    return RouterLLM(
        generation_providers=generation_providers,
        embedding_providers=embedding_providers,
    )


def batch_embed_texts(texts: Iterable[str]) -> list[list[float]]:
    """Convenience wrapper used by the runtime and store tests."""
    client = create_llm_client()
    return client.embed_documents(list(texts))
