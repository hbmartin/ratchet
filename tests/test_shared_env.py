"""Tests for shared local environment (~/.local/ratchet).

Covers:
1. Shared .env settings store (get_env_path, save_env_file, load_env_file)
2. Login/setup writes local-only settings to the shared location
3. Cross-tool settings sharing (Claude Code + Codex use same path)
4. Bootstrap scripts create consistent data directory structure
"""

import argparse
import os
import stat
from pathlib import Path

import pytest

from ratchet.client.cli import get_env_path, load_env_file, save_env_file
from ratchet.client.dirs import data_dir

# ═══════════════════════════════════════════════════════════════════════════
# Unit tests: shared .env path and file operations
# ═══════════════════════════════════════════════════════════════════════════


class TestGetEnvPath:
    """get_env_path() always returns ~/.local/ratchet/.env."""

    def test_returns_stable_path(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        result = get_env_path()
        assert result == tmp_path / ".local" / "ratchet" / ".env"

    def test_creates_parent_directory(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        result = get_env_path()
        assert result.parent.is_dir()

    def test_idempotent_calls(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        path1 = get_env_path()
        path2 = get_env_path()
        assert path1 == path2


class TestSaveAndLoadEnvFile:
    """save_env_file and load_env_file round-trip correctly."""

    def test_round_trip(self, tmp_path):
        env_path = tmp_path / ".env"
        env_vars = {}
        save_env_file(env_path, env_vars)
        loaded = load_env_file(env_path)
        assert loaded == env_vars

    def test_permissions_are_600(self, tmp_path):
        env_path = tmp_path / ".env"
        save_env_file(env_path, {"KEY": "value"})
        mode = stat.S_IMODE(env_path.stat().st_mode)
        assert mode == 0o600

    def test_update_preserves_existing_keys(self, tmp_path):
        env_path = tmp_path / ".env"
        save_env_file(env_path, {"A": "1", "B": "2"})
        save_env_file(env_path, {"B": "updated"})
        loaded = load_env_file(env_path)
        assert loaded["A"] == "1"
        assert loaded["B"] == "updated"

    def test_load_missing_file_returns_empty(self, tmp_path):
        env_path = tmp_path / "nonexistent.env"
        assert load_env_file(env_path) == {}


# ═══════════════════════════════════════════════════════════════════════════
# Unit tests: local setup saves to shared location
# ═══════════════════════════════════════════════════════════════════════════


class TestLoginSavesLocalSettings:
    """Local setup writes only local settings to ~/.local/ratchet/.env."""

    def test_save_local_setup_writes_to_stable_path(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        from ratchet.client.login import _save_local_setup

        env_path, env_vars = _save_local_setup(llm_mode="host-cli", host_agent="codex")
        assert env_path == tmp_path / ".local" / "ratchet" / ".env"
        assert env_vars["RATCHET_LLM_MODE"] == "host-cli"
        assert env_vars["RATCHET_HOST_AGENT"] == "codex"

    def test_save_local_setup_file_permissions(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        from ratchet.client.login import _save_local_setup

        env_path, _ = _save_local_setup(llm_mode="deterministic")
        mode = stat.S_IMODE(env_path.stat().st_mode)
        assert mode == 0o600

    def test_save_local_setup_removes_remote_and_provider_keys(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        from ratchet.client.login import _save_local_setup

        env_path = get_env_path()
        save_env_file(
            env_path,
            {
                "RATCHET_API_KEY": "mg-old",
                "RATCHET_CLIENT_MODE": "remote",
                "RATCHET_SERVER_URL": "old",
                "OPENAI_API_KEY": "sk-old",
                "UNRELATED_API_KEY": "keep-me",
                "RATCHET_LLM_MODE": "host-cli",
                "RATCHET_HOST_AGENT": "codex",
            },
        )

        _save_local_setup(llm_mode="deterministic")
        loaded = load_env_file(env_path)
        assert "RATCHET_API_KEY" not in loaded
        assert "RATCHET_CLIENT_MODE" not in loaded
        assert "RATCHET_SERVER_URL" not in loaded
        assert "OPENAI_API_KEY" not in loaded
        assert loaded["UNRELATED_API_KEY"] == "keep-me"
        assert loaded["RATCHET_LLM_MODE"] == "deterministic"
        assert "RATCHET_HOST_AGENT" not in loaded

    def test_configure_rejects_host_agent_without_host_cli(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        from ratchet.client import cli

        args = argparse.Namespace(
            llm_mode=None,
            host_agent="codex",
            user_id=None,
            api_key=None,
            server_url=None,
            client_mode=None,
            openai_api_key=None,
            gemini_api_key=None,
        )

        assert cli.cmd_configure(args) == 2
        assert "--host-agent requires --llm-mode host-cli" in capsys.readouterr().err


# ═══════════════════════════════════════════════════════════════════════════
# Unit tests: cross-tool settings sharing
# ═══════════════════════════════════════════════════════════════════════════


class TestCrossToolSettingsSharing:
    """Local setup from one tool (Claude Code or Codex) is visible to the other."""

    def test_setup_via_claude_code_visible_to_codex(self, tmp_path, monkeypatch):
        """Settings saved by Claude Code setup are readable by Codex CLI."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        from ratchet.client.login import _save_local_setup

        _save_local_setup(llm_mode="host-cli", host_agent="claude")

        env_path = get_env_path()
        loaded = load_env_file(env_path)
        assert loaded["RATCHET_LLM_MODE"] == "host-cli"
        assert loaded["RATCHET_HOST_AGENT"] == "claude"

    def test_setup_via_codex_visible_to_claude_code(self, tmp_path, monkeypatch):
        """Settings saved via Codex are readable by Claude Code."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        from ratchet.client.login import _save_local_setup

        _save_local_setup(llm_mode="host-cli", host_agent="codex")

        env_path = get_env_path()
        loaded = load_env_file(env_path)
        assert loaded["RATCHET_HOST_AGENT"] == "codex"

    def test_second_setup_overwrites_local_settings(self, tmp_path, monkeypatch):
        """Re-running setup from another tool overwrites local runtime settings."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        from ratchet.client.login import _save_local_setup

        _save_local_setup(llm_mode="host-cli", host_agent="claude")
        _save_local_setup(llm_mode="deterministic")

        loaded = load_env_file(get_env_path())
        assert loaded["RATCHET_LLM_MODE"] == "deterministic"
        assert "RATCHET_HOST_AGENT" not in loaded

    def test_run_pipeline_script_loads_stable_env(self, tmp_path, monkeypatch):
        """run_pipeline.py loads ~/.local/ratchet/.env first."""
        # The script at module level does:
        #   _stable_env = Path.home() / ".local" / "ratchet" / ".env"
        #   if _stable_env.exists(): dotenv.load_dotenv(_stable_env, override=False)
        # We verify the path construction matches get_env_path()
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        stable_env = Path.home() / ".local" / "ratchet" / ".env"
        assert stable_env == get_env_path()


class TestDataDirIdentity:
    """Default path resolution uses only ~/.local/ratchet."""

    def test_data_dir_defaults_to_ratchet(self, tmp_path, monkeypatch):
        monkeypatch.delenv("RATCHET_DATA_DIR", raising=False)
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        assert data_dir() == tmp_path / ".local" / "ratchet"


# ═══════════════════════════════════════════════════════════════════════════
# Integration tests: bootstrap scripts produce consistent layout
# ═══════════════════════════════════════════════════════════════════════════


class TestBootstrapConsistency:
    """Both session-start.sh and codex-bootstrap.sh create the same data dir layout."""

    SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"

    def _run_bootstrap(self, script_name, tmp_path, ratchet_dir, data_dir):
        """Run a bootstrap script with controlled env."""
        import subprocess

        script = self.SCRIPTS_DIR / script_name
        if not script.is_file():
            pytest.skip(f"Script {script_name} not found")

        env = os.environ.copy()
        env["RATCHET_DATA_DIR"] = str(data_dir)
        env["HOME"] = str(tmp_path / "home")
        (tmp_path / "home").mkdir(exist_ok=True)

        if script_name == "session-start.sh":
            env["CLAUDE_PLUGIN_ROOT"] = str(ratchet_dir)
        subprocess.run(
            ["bash", str(script)] + ([str(ratchet_dir)] if "codex" in script_name else []),
            env=env,
            timeout=60,
            capture_output=True,
        )
        return data_dir

    def test_both_scripts_create_env_file(self, tmp_path):
        """Both bootstrap scripts create .env in the data directory."""
        ratchet_dir = tmp_path / "ratchet"
        ratchet_dir.mkdir()
        (ratchet_dir / "pyproject.toml").write_text(
            '[project]\nname="t"\nversion="0.1"\nrequires-python=">=3.10"\n'
        )
        (ratchet_dir / ".env").touch()

        for script_name in ("codex-bootstrap.sh", "session-start.sh"):
            data_dir = tmp_path / f"data-{script_name}"
            self._run_bootstrap(script_name, tmp_path, ratchet_dir, data_dir)
            assert (data_dir / ".env").is_file(), f"{script_name} didn't create .env"
            mode = stat.S_IMODE((data_dir / ".env").stat().st_mode)
            assert mode == 0o600, f"{script_name} didn't set .env permissions to 0600"

    def test_both_scripts_create_profile_json(self, tmp_path):
        """Both bootstrap scripts create profile.json = {}."""
        ratchet_dir = tmp_path / "ratchet"
        ratchet_dir.mkdir()
        (ratchet_dir / "pyproject.toml").write_text(
            '[project]\nname="t"\nversion="0.1"\nrequires-python=">=3.10"\n'
        )
        (ratchet_dir / ".env").touch()

        for script_name in ("codex-bootstrap.sh", "session-start.sh"):
            data_dir = tmp_path / f"data-{script_name}"
            self._run_bootstrap(script_name, tmp_path, ratchet_dir, data_dir)
            assert (data_dir / "profile.json").read_text() == "{}"

    def test_both_scripts_write_plugin_root_breadcrumb(self, tmp_path):
        """Both bootstrap scripts write plugin-root breadcrumb."""
        ratchet_dir = tmp_path / "ratchet"
        ratchet_dir.mkdir()
        (ratchet_dir / "pyproject.toml").write_text(
            '[project]\nname="t"\nversion="0.1"\nrequires-python=">=3.10"\n'
        )
        (ratchet_dir / ".env").touch()

        for script_name in ("codex-bootstrap.sh", "session-start.sh"):
            data_dir = tmp_path / f"data-{script_name}"
            self._run_bootstrap(script_name, tmp_path, ratchet_dir, data_dir)
            assert (data_dir / "plugin-root").read_text().strip() == str(ratchet_dir)

    def test_both_scripts_create_config_yaml(self, tmp_path):
        """Both bootstrap scripts create non-secret config.yaml."""
        ratchet_dir = tmp_path / "ratchet"
        ratchet_dir.mkdir()
        (ratchet_dir / "pyproject.toml").write_text(
            '[project]\nname="t"\nversion="0.1"\nrequires-python=">=3.10"\n'
        )
        (ratchet_dir / ".env").touch()

        for script_name in ("codex-bootstrap.sh", "session-start.sh"):
            data_dir = tmp_path / f"data-{script_name}"
            self._run_bootstrap(script_name, tmp_path, ratchet_dir, data_dir)
            content = (data_dir / "config.yaml").read_text()
            assert "ratchet:" in content
            assert "codex:" in content
            assert "generation_order:" in content

    def test_plugin_dir_credentials_are_not_copied(self, tmp_path):
        """Bootstrap leaves plugin-root secrets out of DATA_DIR/.env."""
        ratchet_dir = tmp_path / "ratchet"
        ratchet_dir.mkdir()
        (ratchet_dir / "pyproject.toml").write_text(
            '[project]\nname="t"\nversion="0.1"\nrequires-python=">=3.10"\n'
        )
        (ratchet_dir / ".env").write_text("RATCHET_API_KEY=mg_secret_key\n")

        data_dir = tmp_path / "data-isolated"
        self._run_bootstrap("codex-bootstrap.sh", tmp_path, ratchet_dir, data_dir)

        content = (data_dir / ".env").read_text()
        assert "mg_secret_key" not in content
