---
description: Show the local MEGA-Code setup steps for configuring Gemini or OpenAI keys.
argument-hint: ""
allowed-tools: Bash, Read
---

# Configure Local Provider Keys

MEGA-Code now runs in local mode by default. OAuth login is no longer required
for normal use.

## Setup

```bash
MEGA_DIR="${CLAUDE_PLUGIN_ROOT:-$(cat ~/.local/share/mega-code/plugin-root 2>/dev/null)}"
set -a && . "$MEGA_DIR/.env" 2>/dev/null && set +a
```

## Configure Gemini

```bash
uv run --directory "$MEGA_DIR" mega-code configure --gemini-api-key <your_key>
```

## Configure OpenAI

```bash
uv run --directory "$MEGA_DIR" mega-code configure --openai-api-key <your_key>
```

## Verify

```bash
grep -E "^(GEMINI_API_KEY|OPENAI_API_KEY)=" "$HOME/.local/share/mega-code/.env" \
  | sed -E 's/(=.*).*/=***/'
```

If neither key is configured, `/mega-code:wisdom-gen`, `/mega-code:wisdom-curate`,
and `/mega-code:status` will stop and ask for local setup first.
