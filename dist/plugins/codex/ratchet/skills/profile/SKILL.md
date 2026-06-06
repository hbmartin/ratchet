---
name: ratchet-profile
description: View or update your Ratchet developer profile (language, level, style) to personalise skill extraction.
argument-hint: "[--language <lang>] [--level Beginner|Intermediate|Expert] [--style Mentor|Formal|Concise] [--reset]"
allowed-tools: Bash, AskUserQuestion
---

# Developer Profile

Set up your developer profile to personalise skill extraction. Profile determines
which skills are too basic for your experience level.

## Setup

```bash
RATCHET_DIR="${RATCHET_PLUGIN_ROOT:-${CLAUDE_PLUGIN_ROOT:-${CODEX_PLUGIN_ROOT:-$(cat ~/.local/ratchet/plugin-root 2>/dev/null)}}}"
set -a && . "$RATCHET_DIR/.env" 2>/dev/null && set +a
uv run --directory "$RATCHET_DIR" python -m ratchet.client.check_auth
```

If the auth check fails (non-zero exit), show the output to the user and stop.

## Interactive Setup (Recommended)

Ask the user for their profile using `AskUserQuestion` with these fields:

- **language**: Preferred communication language — options: `English`, `Korean`, `Thai`
  (user can also type a custom language via "Other")
- **level**: `Beginner`, `Intermediate`, or `Expert`
- **style**: `Mentor`, `Formal`, or `Concise` (reserved for future use)

Save with:

```bash
uv run --directory "$RATCHET_DIR" ratchet profile --language "<language>" --level <level> --style <style>
```

## Show Current Profile

```bash
uv run --directory "$RATCHET_DIR" ratchet profile
```

## Reset Profile

```bash
uv run --directory "$RATCHET_DIR" ratchet profile --reset
```

## Profile Storage

Profile is saved in two places:

- **Remote server** — authoritative source, persists across machines.
  Requires a valid API key (run `/ratchet:login` first).
- **Local mirror** `~/.local/ratchet/profile.json` — written only after a successful remote save.
