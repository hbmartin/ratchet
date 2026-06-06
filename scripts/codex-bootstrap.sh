#!/bin/bash
# Ratchet Codex SessionStart hook.

set -euo pipefail

RATCHET_DIR="${1:-${RATCHET_PLUGIN_ROOT:-${CODEX_PLUGIN_ROOT:-$(pwd)}}}"
DATA_DIR="${RATCHET_DATA_DIR:-$HOME/.local/ratchet}"
HOOK_INPUT="$(cat || true)"

if ! command -v uv &>/dev/null; then
    for candidate in "$HOME/.local/bin/uv" "$HOME/.cargo/bin/uv"; do
        if [ -x "$candidate" ]; then
            export PATH="$(dirname "$candidate"):$PATH"
            break
        fi
    done
fi

if ! command -v uv &>/dev/null; then
    echo "WARNING: uv is required for Ratchet hooks. Install uv locally; skipping Ratchet session bootstrap." >&2
    exit 0
fi

mkdir -p "$DATA_DIR"
echo "$RATCHET_DIR" > "$DATA_DIR/plugin-root"

if [ ! -f "$DATA_DIR/profile.json" ]; then
    printf '{}' > "$DATA_DIR/profile.json"
fi

if [ ! -f "$DATA_DIR/config.yaml" ]; then
    cat > "$DATA_DIR/config.yaml" <<'YAML'
sources:
  ratchet:
    enabled: true
  claude:
    enabled: true
  codex:
    enabled: true
  cursor:
    enabled: false
  gemini:
    enabled: false
  opencode:
    enabled: false
  parquet:
    enabled: false
    datasets: {}
llm:
  mode: deterministic
  generation_order:
    - deterministic
  embedding_order:
    - deterministic
  providers: {}
YAML
fi

if [ ! -f "$DATA_DIR/.env" ]; then
    touch "$DATA_DIR/.env"
    chmod 0600 "$DATA_DIR/.env"
fi

if [ ! -f "$RATCHET_DIR/.env" ]; then
    touch "$RATCHET_DIR/.env"
fi
set -a && . "$RATCHET_DIR/.env" 2>/dev/null && set +a

if [ ! -x "$RATCHET_DIR/.venv/bin/python" ]; then
    uv sync --directory "$RATCHET_DIR" --quiet 2>/dev/null || true
fi

export RATCHET_PLUGIN_ROOT="$RATCHET_DIR"
printf '%s' "$HOOK_INPUT" | uv run --directory "$RATCHET_DIR" python ratchet/client/codex_collector.py --event SessionStart

PROJECT_DIR="$(printf '%s' "$HOOK_INPUT" | uv run --directory "$RATCHET_DIR" python -c 'import json, sys; data=json.load(sys.stdin) if not sys.stdin.closed else {}; print(data.get("cwd") or "")' 2>/dev/null || true)"
if [ -z "$PROJECT_DIR" ]; then
    PROJECT_DIR="$PWD"
fi
uv run --directory "$RATCHET_DIR" python -m ratchet.client.auto_install --host codex --project-dir "$PROJECT_DIR" >/dev/null 2>&1 || true
