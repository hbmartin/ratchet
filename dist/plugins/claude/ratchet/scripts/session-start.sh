#!/bin/bash
# Ratchet SessionStart hook
#
# Runs on every Claude session start. Handles:
#   1. Bootstrap uv package manager if not installed
#   2. Write plugin-root breadcrumb file
#   3. Initialize profile.json with empty defaults
#   4. Ensure Python environment is ready (uv sync on first run)
#   5. Run the session collector
#
# Called from hooks/hooks.json with ${CLAUDE_PLUGIN_ROOT} set by Claude.

set -euo pipefail

RATCHET_DIR="${CLAUDE_PLUGIN_ROOT}"
# Allow tests and CI to override the data directory via RATCHET_DATA_DIR.
DATA_DIR="${RATCHET_DATA_DIR:-$HOME/.local/ratchet}"
HOOK_INPUT="$(cat || true)"

# ── 1. Bootstrap uv if not available ──────────────────────────────────
if ! command -v uv &>/dev/null; then
    # Check common install locations first
    for candidate in "$HOME/.local/bin/uv" "$HOME/.cargo/bin/uv"; do
        if [ -x "$candidate" ]; then
            export PATH="$(dirname "$candidate"):$PATH"
            break
        fi
    done
fi

if ! command -v uv &>/dev/null; then
    curl -LsSf https://astral.sh/uv/install.sh | sh || echo "WARNING: uv install failed — some features may be unavailable"
    export PATH="$HOME/.local/bin:$PATH"
fi

# ── 2. Plugin root breadcrumb ─────────────────────────────────────────
mkdir -p "$DATA_DIR"
echo "$RATCHET_DIR" > "$DATA_DIR/plugin-root"

# ── 3. Initialize profile.json if absent ──────────────────────────────
# Write an empty JSON object; UserProfile fields are populated by `ratchet profile`.
if [ ! -f "$DATA_DIR/profile.json" ]; then
    printf '{}' > "$DATA_DIR/profile.json"
fi

# ── 4. Ensure non-secret config store exists ──────────────────────────
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
  generation_order:
    - agent
    - ollama
    - lmstudio
    - command
    - gemini
    - openai
    - anthropic
  embedding_order:
    - ollama
    - lmstudio
    - command
    - openai
    - gemini
    - local-hash
  providers: {}
YAML
fi

# ── 5. Ensure stable credential store exists ──────────────────────────
# Credentials live in ~/.local/ratchet/.env. The versioned plugin .env is kept
# as a non-secret config overlay only.
if [ ! -f "$DATA_DIR/.env" ]; then
    touch "$DATA_DIR/.env"
    chmod 0600 "$DATA_DIR/.env"
fi
# Ensure the plugin dir still has a (possibly empty) .env so sourcing it is safe.
if [ ! -f "$RATCHET_DIR/.env" ]; then
    touch "$RATCHET_DIR/.env"
fi

# ── 6. Ensure Python environment is ready (first-run only) ────────────
# Check for the actual python binary, not just .venv directory — the dir
# may exist but be empty (e.g. only .gitignore and .lock from git).
if [ ! -x "$RATCHET_DIR/.venv/bin/python" ]; then
    uv sync --directory "$RATCHET_DIR" --quiet 2>/dev/null || true
fi

# ── 7. Run collector and approved-item auto-install ───────────────────
printf '%s' "$HOOK_INPUT" | uv run --directory "$RATCHET_DIR" python ratchet/client/collector.py --event SessionStart
PROJECT_DIR="$(printf '%s' "$HOOK_INPUT" | uv run --directory "$RATCHET_DIR" python -c 'import json, sys; data=json.load(sys.stdin) if not sys.stdin.closed else {}; print(data.get("cwd") or "")' 2>/dev/null || true)"
if [ -z "$PROJECT_DIR" ]; then
    PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$PWD}"
fi
uv run --directory "$RATCHET_DIR" python -m ratchet.client.auto_install --host claude --project-dir "$PROJECT_DIR" >/dev/null 2>&1 || true
