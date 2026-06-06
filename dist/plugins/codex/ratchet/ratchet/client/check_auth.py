"""Local setup gate for ratchet skills.

Usage:
    python -m ratchet.client.check_auth

Exit 0 = local generation path configured, Exit 1 = missing provider.
"""

from __future__ import annotations

import os
import shutil
import sys
from typing import Any

from ratchet.client.cli import get_env_path, load_env_file
from ratchet.client.config import load_config

_NOT_CONFIGURED = (
    "No Ratchet generation provider configured. Install/authenticate the Claude or Codex CLI, "
    "configure a local adapter in ~/.local/ratchet/config.yaml, or set OPENAI_API_KEY, "
    "GEMINI_API_KEY, or ANTHROPIC_API_KEY in ~/.local/ratchet/.env."
)


def _provider_config(name: str, config: dict[str, Any]) -> dict[str, Any]:
    llm_config = config.get("llm", {})
    providers = llm_config.get("providers", {}) if isinstance(llm_config, dict) else {}
    provider = providers.get(name, {}) if isinstance(providers, dict) else {}
    return provider if isinstance(provider, dict) else {}


def _has_configured_local_adapter(config: dict[str, Any]) -> bool:
    ollama_cfg = _provider_config("ollama", config)
    if ollama_cfg.get("enabled") or os.environ.get("OLLAMA_HOST"):
        return True

    for name in ("lmstudio", "openai-compatible"):
        endpoint_cfg = _provider_config(name, config)
        if endpoint_cfg.get("base_url") or os.environ.get("RATCHET_OPENAI_COMPAT_BASE_URL"):
            return True

    command_cfg = _provider_config("command", config)
    if (
        command_cfg.get("generation_command")
        or command_cfg.get("embedding_command")
        or os.environ.get("RATCHET_GENERATION_COMMAND")
        or os.environ.get("RATCHET_EMBEDDING_COMMAND")
    ):
        return True

    return False


def check_auth() -> bool:
    """Check that Ratchet can reach at least one generation provider.

    Local mode does not require a Ratchet API key or server reachability.
    """
    for key, value in load_env_file(get_env_path()).items():
        os.environ.setdefault(key, value)

    if os.environ.get("RATCHET_TEST_FAKE_LLM") == "1":
        return True

    if any(os.environ.get(key) for key in ("GEMINI_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY")):
        return True

    config = load_config()
    if _has_configured_local_adapter(config):
        return True

    if shutil.which("codex") or shutil.which("claude"):
        return True

    print(_NOT_CONFIGURED)
    return False


def main() -> int:
    return 0 if check_auth() else 1


if __name__ == "__main__":
    sys.exit(main())
