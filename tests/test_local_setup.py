"""Tests for local setup behavior."""

from __future__ import annotations

from ratchet.client.check_auth import check_auth
from ratchet.client.cli import get_env_path, load_env_file
from ratchet.client.login import run_login


def test_check_auth_requires_no_remote_or_provider_keys(tmp_path, monkeypatch):
    monkeypatch.setenv("RATCHET_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("RATCHET_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("PATH", str(tmp_path / "empty-bin"))

    assert check_auth() is True


def test_login_shim_writes_no_remote_mode_or_keys(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("RATCHET_DATA_DIR", str(tmp_path / "data"))

    assert run_login() == 0

    output = capsys.readouterr().out
    loaded = load_env_file(get_env_path())
    assert "runs locally" in output
    assert "RATCHET_API_KEY" not in loaded
    assert "RATCHET_CLIENT_MODE" not in loaded
    assert "RATCHET_SERVER_URL" not in loaded


def test_login_shim_removes_stale_remote_and_provider_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("RATCHET_DATA_DIR", str(tmp_path / "data"))
    env_path = get_env_path()
    env_path.parent.mkdir(parents=True, exist_ok=True)
    env_path.write_text(
        "\n".join(
            [
                "RATCHET_API_KEY=mg-old",
                "RATCHET_CLIENT_MODE=remote",
                "RATCHET_SERVER_URL=old",
                "OPENAI_API_KEY=sk-old",
                "RATCHET_LLM_MODE=host-cli",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    assert run_login() == 0

    loaded = load_env_file(env_path)
    assert "RATCHET_API_KEY" not in loaded
    assert "RATCHET_CLIENT_MODE" not in loaded
    assert "RATCHET_SERVER_URL" not in loaded
    assert "OPENAI_API_KEY" not in loaded
    assert loaded["RATCHET_LLM_MODE"] == "host-cli"
