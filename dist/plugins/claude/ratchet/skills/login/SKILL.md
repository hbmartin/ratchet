---
name: ratchet-login
description: Show the local Ratchet setup steps for configuring Gemini or OpenAI keys.
argument-hint: ""
allowed-tools: Bash, Read
---

# Configure Local Provider Keys

Ratchet now runs in local mode by default. OAuth login is no longer required
for normal use.

## Setup

```bash
RATCHET_DIR="${RATCHET_PLUGIN_ROOT:-${CLAUDE_PLUGIN_ROOT:-${CODEX_PLUGIN_ROOT:-$(cat ~/.local/ratchet/plugin-root 2>/dev/null)}}}"
set -a && . "$RATCHET_DIR/.env" 2>/dev/null && set +a
```

## Configure Gemini

```bash
uv run --directory "$RATCHET_DIR" ratchet configure --gemini-api-key <your_key>
```

## Configure OpenAI

```bash
uv run --directory "$RATCHET_DIR" ratchet configure --openai-api-key <your_key>
```

## Verify

```bash
grep -E "^(GEMINI_API_KEY|OPENAI_API_KEY)=" "$HOME/.local/ratchet/.env" \
  | sed -E 's/(=.*).*/=***/'
```

If neither key is configured, `/ratchet:wisdom-gen`, `/ratchet:wisdom-curate`,
and `/ratchet:status` will stop and ask for local setup first.
