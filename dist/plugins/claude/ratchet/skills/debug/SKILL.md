---
name: ratchet-debug
description: Collect Ratchet local pipeline debug evidence. Use when a run is failed, stuck, stale, stopped, missing outputs, has confusing LLM behavior, or needs local evidence from pipeline traces, events.jsonl, worker.log, raw LLM artifacts, and a debug bundle directory.
argument-hint: "[run-id]"
allowed-tools: Bash, Read
---

# Ratchet Debug

Collect local evidence before inferring pipeline behavior. This skill is not a
repair workflow; use its output and bundle path as evidence for the invoking
agent to decide the next action.

Keep setup and execution in one Bash block so `RATCHET_DIR`, env vars, and an
optional run id stay in scope.

```bash
RATCHET_DIR="${RATCHET_PLUGIN_ROOT:-${CLAUDE_PLUGIN_ROOT:-${CODEX_PLUGIN_ROOT:-$(cat ~/.local/ratchet/plugin-root 2>/dev/null)}}}"
set -a && . "$RATCHET_DIR/.env" 2>/dev/null && set +a
RUN_ID="${RUN_ID:-}"

if [ -n "$RUN_ID" ]; then
  uv run --directory "$RATCHET_DIR" ratchet debug --run-id "$RUN_ID"
else
  uv run --directory "$RATCHET_DIR" ratchet debug
fi
```

`ratchet debug` auto-selects a run when no run id is supplied. It first selects
the newest failed run or an active run that has exceeded the staleness threshold;
if neither exists, it selects the newest recent run. Local debug evidence does
not require provider auth.

The command prints run evidence and writes a raw local bundle directory. Use the
reported `Bundle dir` path when handing off evidence.

Bundle contents include `snapshot.json`, `status.json`, `manifest.json`,
`worker.log`, `events.jsonl`, `llm/`, and related session files when present.
If the bundle directory already exists, Ratchet leaves it unchanged and reports
that it skipped creation.

For exact log contents, use the path reported by `ratchet debug` or run:

```bash
uv run --directory "$RATCHET_DIR" ratchet pipeline-logs --run-id <RUN_ID> --tail 160
```

For machine-readable evidence:

```bash
uv run --directory "$RATCHET_DIR" ratchet debug --run-id <RUN_ID> --json
```
