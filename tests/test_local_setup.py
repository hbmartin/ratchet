"""Tests for local setup/auth behavior."""

from __future__ import annotations

from ratchet.client.check_auth import check_auth


def test_check_auth_accepts_openai_key_without_ratchet_api_key(tmp_path, monkeypatch):
    monkeypatch.setenv("RATCHET_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("RATCHET_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-local")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert check_auth() is True


def test_check_auth_rejects_missing_provider_keys(tmp_path, monkeypatch):
    monkeypatch.setenv("RATCHET_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("RATCHET_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("RATCHET_TEST_FAKE_LLM", raising=False)
    monkeypatch.delenv("RATCHET_OPENAI_COMPAT_BASE_URL", raising=False)
    monkeypatch.delenv("RATCHET_GENERATION_COMMAND", raising=False)
    monkeypatch.delenv("RATCHET_EMBEDDING_COMMAND", raising=False)
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    monkeypatch.setenv("PATH", str(tmp_path / "empty-bin"))
    assert check_auth() is False


def test_check_auth_accepts_local_adapter_config(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "config.yaml").write_text(
        "llm:\n"
        "  providers:\n"
        "    openai-compatible:\n"
        "      base_url: http://localhost:1234\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("RATCHET_DATA_DIR", str(data_dir))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("PATH", str(tmp_path / "empty-bin"))

    assert check_auth() is True


def test_check_auth_accepts_agent_cli(tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    codex = bin_dir / "codex"
    codex.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    codex.chmod(0o755)
    monkeypatch.setenv("RATCHET_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("PATH", str(bin_dir))

    assert check_auth() is True
