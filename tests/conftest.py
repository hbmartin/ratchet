"""Shared test fixtures for mega-code-oss tests."""

from __future__ import annotations

import os
from pathlib import Path

import pytest


@pytest.fixture
def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


@pytest.fixture
def fake_uv(tmp_path: Path) -> dict[str, Path]:
    """Create a lightweight fake ``uv`` binary for deterministic hook/skill tests."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log_path = tmp_path / "uv.log"
    uv_path = bin_dir / "uv"
    uv_path.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
PYTHON_BIN="${PYTHON_BIN:-$(command -v python3 || command -v python || true)}"
if [ -z "$PYTHON_BIN" ]; then
  echo "fake uv: no python interpreter found" >&2
  exit 2
fi
if [ -n "${MEGA_CODE_TEST_UV_LOG:-}" ]; then
  printf '%s\\n' "$*" >> "$MEGA_CODE_TEST_UV_LOG"
fi
cmd="${1:-}"
if [ -z "$cmd" ]; then
  echo "fake uv: missing command" >&2
  exit 2
fi
shift || true
case "$cmd" in
  sync)
    dir=""
    while [ $# -gt 0 ]; do
      case "$1" in
        --directory)
          dir="$2"
          shift 2
          ;;
        *)
          shift
          ;;
      esac
    done
    if [ -n "$dir" ]; then
      mkdir -p "$dir/.venv/bin"
      cat > "$dir/.venv/bin/python" <<'PYEOF'
#!/usr/bin/env bash
PYTHON_BIN="${PYTHON_BIN:-$(command -v python3 || command -v python || true)}"
exec "$PYTHON_BIN" "$@"
PYEOF
      chmod +x "$dir/.venv/bin/python"
    fi
    exit 0
    ;;
  run)
    dir=""
    while [ $# -gt 0 ]; do
      case "$1" in
        --directory)
          dir="$2"
          shift 2
          ;;
        *)
          break
          ;;
      esac
    done
    if [ -n "$dir" ]; then
      cd "$dir"
    fi
    if [ "${1:-}" = "mega-code" ]; then
      shift
      exec "$PYTHON_BIN" -m mega_code.client.cli "$@"
    fi
    if [ "${1:-}" = "python" ]; then
      shift
      exec "$PYTHON_BIN" "$@"
    fi
    exec "$@"
    ;;
  *)
    echo "Unsupported fake uv command: $cmd" >&2
    exit 2
    ;;
esac
""",
        encoding="utf-8",
    )
    uv_path.chmod(0o755)
    return {"bin_dir": bin_dir, "log_path": log_path, "uv_path": uv_path}


@pytest.fixture
def test_env(repo_root: Path, tmp_path: Path, fake_uv: dict[str, Path]) -> dict[str, str]:
    """Environment shared by subprocess-based contract and wrapper tests."""
    home = tmp_path / "home"
    home.mkdir()
    data_dir = tmp_path / "data"
    pythonpath = os.pathsep.join(filter(None, [str(repo_root), os.environ.get("PYTHONPATH", "")]))
    path = os.pathsep.join([str(fake_uv["bin_dir"]), os.environ.get("PATH", "")])
    env = os.environ.copy()
    env.update(
        {
            "CLAUDE_PLUGIN_ROOT": str(repo_root),
            "HOME": str(home),
            "MEGA_CODE_DATA_DIR": str(data_dir),
            "MEGA_CODE_TEST_FAKE_LLM": "1",
            "MEGA_CODE_TEST_UV_LOG": str(fake_uv["log_path"]),
            "OPENAI_API_KEY": "sk-test-local",
            "PATH": path,
            "PYTHON_BIN": str(repo_root / ".venv" / "bin" / "python"),
            "PYTHONPATH": pythonpath,
        }
    )
    return env
