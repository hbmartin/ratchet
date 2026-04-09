---
description: Show MEGA-Code status including pending skills, strategies, and recent pipeline runs.
argument-hint: ""
allowed-tools: Bash, Read
---

# MEGA-Code Status

Show current MEGA-Code status and pending items.

## Setup

```bash
MEGA_DIR="${CLAUDE_PLUGIN_ROOT:-$(cat ~/.local/share/mega-code/plugin-root 2>/dev/null)}"
set -a && . "$MEGA_DIR/.env" 2>/dev/null && set +a
uv run --directory "$MEGA_DIR" python -m mega_code.client.check_auth
```

If the auth check fails (non-zero exit), show the output to the user and stop.

## Local Pipeline Status

```bash
uv run --directory "$MEGA_DIR" mega-code pipeline-status 2>/dev/null || true
```

## Quick Status

```bash
DATA_DIR="$(uv run --directory "$MEGA_DIR" python -c "from mega_code.client.dirs import data_dir; print(data_dir())")"
ls -la "$DATA_DIR/data/pending-skills/" "$DATA_DIR/data/pending-strategies/" 2>/dev/null || echo "No pending items"
```

## Detailed Pending Items

Uses `ls` checks to avoid zsh glob errors on empty directories.

```bash
DATA_DIR="$(uv run --directory "$MEGA_DIR" python -c "from mega_code.client.dirs import data_dir; print(data_dir())")"
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
| Skills | `~/.local/share/mega-code/data/pending-skills/{name}/` | `{data_dir}/skills/{name}/SKILL.md` |
| Strategies | `~/.local/share/mega-code/data/pending-strategies/{name}.md` | `.claude/rules/mega-code/{name}.md` |
