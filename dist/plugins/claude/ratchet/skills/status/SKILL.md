---
name: ratchet-status
description: Show Ratchet status including pending skills, strategies, and recent pipeline runs.
argument-hint: ""
allowed-tools: Bash, Read
---

# Ratchet Status

Show current Ratchet status and pending items.

## Setup

```bash
RATCHET_DIR="${RATCHET_PLUGIN_ROOT:-${CLAUDE_PLUGIN_ROOT:-${CODEX_PLUGIN_ROOT:-$(cat ~/.local/ratchet/plugin-root 2>/dev/null)}}}"
set -a && . "$RATCHET_DIR/.env" 2>/dev/null && set +a
uv run --directory "$RATCHET_DIR" python -m ratchet.client.check_auth
```

If the auth check fails (non-zero exit), show the output to the user and stop.

## Local Pipeline Status

```bash
uv run --directory "$RATCHET_DIR" ratchet pipeline-status --all --recent 10 2>/dev/null || true
```

For a run that is failed, stale, or otherwise unclear, inspect it before
guessing:

```bash
uv run --directory "$RATCHET_DIR" ratchet pipeline-inspect --run-id <RUN_ID>
uv run --directory "$RATCHET_DIR" ratchet pipeline-logs --run-id <RUN_ID> --tail 120
```

If the user needs to hand off raw evidence, create a bundle directory:

```bash
uv run --directory "$RATCHET_DIR" ratchet debug-bundle --run-id <RUN_ID>
```

## Quick Status

```bash
DATA_DIR="$(uv run --directory "$RATCHET_DIR" python -c "from ratchet.client.dirs import data_dir; print(data_dir())")"
ls -la "$DATA_DIR/data/pending-skills/" "$DATA_DIR/data/pending-strategies/" 2>/dev/null || echo "No pending items"
```

## Detailed Pending Items

Uses `ls` checks to avoid zsh glob errors on empty directories.

```bash
DATA_DIR="$(uv run --directory "$RATCHET_DIR" python -c "from ratchet.client.dirs import data_dir; print(data_dir())")"
SKILLS_DIR="$DATA_DIR/data/pending-skills"
STRATS_DIR="$DATA_DIR/data/pending-strategies"

echo "=== Pending Skills ==="
if [ -d "$SKILLS_DIR" ] && [ "$(ls -A "$SKILLS_DIR" 2>/dev/null)" ]; then
  for dir in "$SKILLS_DIR"/*/; do
    name=$(basename "$dir")
    desc=$(grep -m1 "description:" "$dir/SKILL.md" 2>/dev/null | cut -d: -f2- | head -c 60)
    echo "  $name:$desc"
  done
else
  echo "  (none)"
fi

echo "=== Pending Strategies ==="
if [ -d "$STRATS_DIR" ] && [ "$(ls -A "$STRATS_DIR" 2>/dev/null)" ]; then
  for file in "$STRATS_DIR"/*.md; do
    name=$(basename "$file" .md)
    desc=$(grep -m1 "^# " "$file" | cut -c3- | head -c 60)
    echo "  $name: $desc"
  done
else
  echo "  (none)"
fi
```

## Output Locations

| Type | Pending Location | Installed Location |
|------|------------------|-------------------|
| Skills | `~/.local/ratchet/data/pending-skills/{name}/` | `{data_dir}/skills/{name}/SKILL.md` |
| Strategies | `~/.local/ratchet/data/pending-strategies/{name}.md` | `.claude/rules/ratchet/{name}.md` |
