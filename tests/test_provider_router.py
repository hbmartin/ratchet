"""Provider-router tests for Ratchet local runtime."""

from __future__ import annotations

import json
from pathlib import Path

from ratchet.pipeline import llm as llm_module
from ratchet.pipeline.llm import BaseLocalLLM, LocalLLMError, RouterLLM, create_llm_client


def _write_config(path: Path, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    return path


def test_generation_order_prefers_configured_command(tmp_path, monkeypatch):
    command = "python3 -c 'import sys; print(\"command:\" + sys.stdin.read()[:5])'"
    config_path = _write_config(
        tmp_path / "config.yaml",
        "llm:\n"
        "  generation_order: [command]\n"
        "  embedding_order: [local-hash]\n"
        "  providers:\n"
        "    command:\n"
        f"      generation_command: {json.dumps(command)}\n",
    )
    monkeypatch.setenv("RATCHET_CONFIG", str(config_path))
    monkeypatch.delenv("RATCHET_TEST_FAKE_LLM", raising=False)

    client = create_llm_client()

    assert isinstance(client, RouterLLM)
    assert client.generation_providers[0].provider == "command"
    assert client.generate_text("hello world") == "command:hello"


def test_local_adapter_selection_from_config(tmp_path, monkeypatch):
    config_path = _write_config(
        tmp_path / "config.yaml",
        "llm:\n"
        "  generation_order: [ollama]\n"
        "  embedding_order: [local-hash]\n"
        "  providers:\n"
        "    ollama:\n"
        "      enabled: true\n"
        "      generation_model: llama3.2\n",
    )
    monkeypatch.setenv("RATCHET_CONFIG", str(config_path))
    monkeypatch.delenv("RATCHET_TEST_FAKE_LLM", raising=False)

    client = create_llm_client()

    assert isinstance(client, RouterLLM)
    assert client.generation_providers[0].provider == "ollama"
    assert client.generation_providers[0].default_generation_model == "llama3.2"


def test_api_generation_preference_respects_config(tmp_path, monkeypatch):
    config_path = _write_config(
        tmp_path / "config.yaml",
        "llm:\n"
        "  generation_order: [openai, gemini]\n"
        "  embedding_order: [local-hash]\n",
    )
    monkeypatch.setenv("RATCHET_CONFIG", str(config_path))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-test")
    monkeypatch.delenv("RATCHET_TEST_FAKE_LLM", raising=False)

    client = create_llm_client()

    assert isinstance(client, RouterLLM)
    assert [provider.provider for provider in client.generation_providers[:2]] == [
        "openai",
        "gemini",
    ]


def test_current_agent_first_generation_default(tmp_path, monkeypatch):
    monkeypatch.setenv("RATCHET_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("CODEX_THREAD_ID", "thread-1")
    monkeypatch.delenv("RATCHET_TEST_FAKE_LLM", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(llm_module.shutil, "which", lambda name: f"/bin/{name}" if name == "codex" else None)

    client = create_llm_client()

    assert isinstance(client, RouterLLM)
    first = client.generation_providers[0]
    assert first.provider == "agent-cli"
    assert getattr(first, "agent") == "codex"


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
