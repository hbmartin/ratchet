"""Tests for local setup/auth behavior."""

from __future__ import annotations

from mega_code.client.check_auth import check_auth


def test_check_auth_accepts_openai_key_without_mega_api_key(tmp_path, monkeypatch):
    monkeypatch.setenv("MEGA_CODE_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("MEGA_CODE_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-local")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert check_auth() is True


def test_check_auth_rejects_missing_provider_keys(tmp_path, monkeypatch):
    monkeypatch.setenv("MEGA_CODE_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("MEGA_CODE_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert check_auth() is False
