---
name: ratchet-login
description: Show local Ratchet setup status and optional host-agent configuration.
argument-hint: ""
allowed-tools: Bash, Read
---

# Local Setup Status

Ratchet runs locally by default. OAuth login and provider keys are no longer
required for normal use.

## Usage

```bash
RATCHET_DIR="${RATCHET_PLUGIN_ROOT:-${CLAUDE_PLUGIN_ROOT:-${CODEX_PLUGIN_ROOT:-$(cat ~/.local/ratchet/plugin-root 2>/dev/null)}}}"
set -a && . "$RATCHET_DIR/.env" 2>/dev/null && set +a

# Show status
uv run --directory "$RATCHET_DIR" ratchet login

# Optional: enable host-agent generation
# uv run --directory "$RATCHET_DIR" ratchet configure --llm-mode host-cli --host-agent codex

# Verify configuration
uv run --directory "$RATCHET_DIR" ratchet status
```

If no host-agent mode is configured, `/ratchet:wisdom-gen` and
`/ratchet:wisdom-curate` use deterministic local generation.
