"""Local setup/status shim for legacy Ratchet login entry points."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from ratchet.client.cli import get_env_path, load_env_file, save_env_file

logger = logging.getLogger(__name__)

_DEFAULT_PROVIDER = "local"
_LEGACY_CREDENTIAL_KEYS = {
    "ANTHROPIC_API_KEY",
    "GEMINI_API_KEY",
    "OPENAI_API_KEY",
    "RATCHET_API_KEY",
    "RATCHET_OPENAI_COMPAT_API_KEY",
}


def _save_local_setup(
    *,
    llm_mode: str | None = None,
    host_agent: str | None = None,
) -> tuple[Path, dict[str, str]]:
    """Persist optional local runtime settings without credential fields."""
    env_path = get_env_path()
    env_vars = load_env_file(env_path)
    env_vars.pop("RATCHET_CLIENT_MODE", None)
    env_vars.pop("RATCHET_SERVER_URL", None)
    for key in _LEGACY_CREDENTIAL_KEYS:
        env_vars.pop(key, None)

    resolved_llm_mode = llm_mode or env_vars.get("RATCHET_LLM_MODE")
    if host_agent and resolved_llm_mode != "host-cli":
        raise ValueError("--host-agent requires --llm-mode host-cli")
    if llm_mode:
        env_vars["RATCHET_LLM_MODE"] = llm_mode
    if resolved_llm_mode != "host-cli":
        env_vars.pop("RATCHET_HOST_AGENT", None)
    if host_agent:
        env_vars["RATCHET_HOST_AGENT"] = host_agent
    env_path.parent.mkdir(parents=True, exist_ok=True)
    save_env_file(env_path, env_vars, remove_absent=True)
    return env_path, env_vars


def create_cli_session(base_url: str | None = None, provider: str = _DEFAULT_PROVIDER) -> dict:
    """Return local setup metadata for compatibility with old two-step login."""
    _ = base_url
    return {
        "status": "local",
        "provider": provider,
        "message": "Login is not required; Ratchet runs locally.",
    }


def poll_cli_session(
    base_url: str | None = None,
    client_id: str | None = None,
    *,
    timeout: int = 0,
    interval: int = 0,
) -> str:
    """Compatibility no-op for old login polling callers."""
    _ = (base_url, client_id, timeout, interval)
    return "local"


def run_create(
    provider: str = _DEFAULT_PROVIDER,
    base_url: str | None = None,
) -> int:
    """Step 1 compatibility: print local status JSON."""
    print(json.dumps(create_cli_session(base_url=base_url, provider=provider)))
    return 0


def run_poll(client_id: str, base_url: str | None = None) -> int:
    """Step 2 compatibility: persist local setup and report status."""
    _ = poll_cli_session(base_url=base_url, client_id=client_id)
    env_path, _env_vars = _save_local_setup()
    print("Login is not required; Ratchet runs locally.")
    print(f"Local settings checked at: {env_path}")
    return 0


def run_login(
    provider: str = _DEFAULT_PROVIDER,
    base_url: str | None = None,
) -> int:
    """Run local setup/status in place of the removed OAuth flow."""
    _ = (provider, base_url)
    env_path, _env_vars = _save_local_setup()
    print("Login is not required; Ratchet runs locally.")
    print(f"Local settings checked at: {env_path}")
    print("Client mode: local")
    return 0


def main() -> int:
    """CLI entry point for legacy login invocations."""
    parser = argparse.ArgumentParser(
        prog="ratchet-login",
        description="Show Ratchet local setup status",
    )
    parser.add_argument(
        "--step",
        choices=["create", "poll"],
        default=None,
        help="Compatibility step: 'create' prints status, 'poll' checks local setup",
    )
    parser.add_argument(
        "--provider",
        default=_DEFAULT_PROVIDER,
        help="Deprecated compatibility option; ignored.",
    )
    parser.add_argument(
        "--url",
        type=str,
        default=None,
        help="Deprecated compatibility option; ignored.",
    )
    parser.add_argument(
        "--client-id",
        type=str,
        default=None,
        help="Deprecated compatibility option; accepted for --step poll.",
    )
    parser.add_argument(
        "--llm-mode",
        choices=["deterministic", "host-cli"],
        default=None,
        help="Optional local generation mode to persist.",
    )
    parser.add_argument(
        "--host-agent",
        choices=["claude", "codex"],
        default=None,
        help="Host-agent CLI to use when --llm-mode host-cli is selected.",
    )

    args = parser.parse_args()
    if args.llm_mode or args.host_agent:
        try:
            env_path, _env_vars = _save_local_setup(
                llm_mode=args.llm_mode,
                host_agent=args.host_agent,
            )
        except ValueError as exc:
            parser.error(str(exc))
        print(f"Local settings saved to: {env_path}")

    if args.step == "create":
        return run_create(provider=args.provider, base_url=args.url)
    if args.step == "poll":
        return run_poll(client_id=args.client_id or "local", base_url=args.url)
    return run_login(provider=args.provider, base_url=args.url)


if __name__ == "__main__":
    sys.exit(main())
