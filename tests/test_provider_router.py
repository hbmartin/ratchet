"""Provider-router tests for Ratchet local runtime."""

from __future__ import annotations

import json
from pathlib import Path

from ratchet.pipeline import llm as llm_module
from ratchet.pipeline.llm import (
    BaseLocalLLM,
    DeterministicLocalLLM,
    LocalLLMError,
    RouterLLM,
    create_llm_client,
)


def _write_config(path: Path, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    return path


def test_default_generation_is_deterministic_even_when_agent_cli_exists(tmp_path, monkeypatch):
    monkeypatch.setenv("RATCHET_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("CODEX_THREAD_ID", "thread-1")
    monkeypatch.delenv("RATCHET_TEST_FAKE_LLM", raising=False)
    monkeypatch.delenv("RATCHET_LLM_MODE", raising=False)
    monkeypatch.delenv("RATCHETAI_LLM_MODE", raising=False)
    monkeypatch.setattr(llm_module.shutil, "which", lambda name: f"/bin/{name}")

    client = create_llm_client()

    assert isinstance(client, RouterLLM)
    assert client.generation_providers[0].provider == "deterministic"
    assert client.embedding_providers[0].provider == "deterministic"


def test_host_cli_mode_prefers_current_agent(tmp_path, monkeypatch):
    monkeypatch.setenv("RATCHET_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("RATCHET_LLM_MODE", "host-cli")
    monkeypatch.setenv("CODEX_THREAD_ID", "thread-1")
    monkeypatch.delenv("RATCHET_TEST_FAKE_LLM", raising=False)
    monkeypatch.setattr(llm_module.shutil, "which", lambda name: f"/bin/{name}" if name == "codex" else None)

    client = create_llm_client()

    assert isinstance(client, RouterLLM)
    first = client.generation_providers[0]
    assert first.provider == "agent-cli"
    assert getattr(first, "agent") == "codex"
    assert client.generation_providers[-1].provider == "deterministic"
    assert client.embedding_providers[0].provider == "deterministic"


def test_command_mode_prefers_configured_command(tmp_path, monkeypatch):
    command = "python3 -c 'import sys; print(\"command:\" + sys.stdin.read()[:5])'"
    config_path = _write_config(
        tmp_path / "config.yaml",
        "llm:\n"
        "  mode: command\n"
        "  generation_order: [command]\n"
        "  embedding_order: [deterministic]\n"
        "  providers:\n"
        "    command:\n"
        f"      generation_command: {json.dumps(command)}\n",
    )
    monkeypatch.setenv("RATCHET_CONFIG", str(config_path))
    monkeypatch.delenv("RATCHET_TEST_FAKE_LLM", raising=False)
    monkeypatch.delenv("RATCHET_LLM_MODE", raising=False)
    monkeypatch.delenv("RATCHETAI_LLM_MODE", raising=False)

    client = create_llm_client()

    assert isinstance(client, RouterLLM)
    assert client.generation_providers[0].provider == "command"
    assert client.generate_text("hello world") == "command:hello"


def test_api_provider_names_in_config_are_ignored(tmp_path, monkeypatch):
    config_path = _write_config(
        tmp_path / "config.yaml",
        "llm:\n"
        "  mode: deterministic\n"
        "  generation_order: [openai, gemini]\n"
        "  embedding_order: [openai, gemini]\n",
    )
    monkeypatch.setenv("RATCHET_CONFIG", str(config_path))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-test")
    monkeypatch.delenv("RATCHET_TEST_FAKE_LLM", raising=False)

    client = create_llm_client()

    assert isinstance(client, RouterLLM)
    assert all(isinstance(provider, DeterministicLocalLLM) for provider in client.generation_providers)
    assert all(isinstance(provider, DeterministicLocalLLM) for provider in client.embedding_providers)


class _NoEmbeddingLLM(BaseLocalLLM):
    provider = "no-embedding"

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        raise LocalLLMError("no embeddings")

    def generate_text(self, prompt: str, *, model: str | None = None) -> str:
        return '{"ranked_indices": [2, 0, 1]}'


def test_agent_rerank_fallback_when_no_embedder():
    router = RouterLLM(generation_providers=[_NoEmbeddingLLM()], embedding_providers=[])

    ranked = router.rerank_documents("auth refresh", ["a", "b", "c"], top_k=2)

    assert [item.index for item in ranked] == [2, 0]
