---
name: ratchet-wisdom-gen
description: Run the Ratchet skill extraction pipeline to analyze project sessions and generate reusable skills and strategies.
argument-hint: "[--project [@<name>]] [--model <model>] [--poll-timeout <seconds>] [--include-claude] [--include-codex] [--include-all]"
allowed-tools: Bash, Read, Write, Edit, AskUserQuestion
disable-model-invocation: true
---

# Run Local Skill Extraction Pipeline

Extract reusable skills and coding strategies from your project sessions.

## ⚠️ Important: Pipeline Is Asynchronous

The command schedules a local background worker, then polls the local runtime
until it reaches a terminal status.

The default poll timeout is **20 minutes**. For longer runs, use `--poll-timeout`:
- `--poll-timeout 3600` — wait up to 1 hour
- `--poll-timeout 0` — wait indefinitely (no timeout)

## Setup

```bash
RATCHET_DIR="${RATCHET_PLUGIN_ROOT:-${CLAUDE_PLUGIN_ROOT:-${CODEX_PLUGIN_ROOT:-$(cat ~/.local/ratchet/plugin-root 2>/dev/null)}}}"
set -a && . "$RATCHET_DIR/.env" 2>/dev/null && set +a
uv run --directory "$RATCHET_DIR" python -m ratchet.client.check_auth
```

If the auth check fails (non-zero exit), show the output to the user and stop.

All commands below assume `RATCHET_DIR` is set.

## Flags

| Flag | Behavior |
|------|----------|
| *(none)* | Process current session only |
| `--project` | All sessions in current project |
| `--project @name` | Specific project by name prefix |
| `--session-id <uuid>` | Specific session |
| `--model <alias>` | Optional local provider model override |
| `--poll-timeout <seconds>` | Max seconds to poll for completion (default: 1200 = 20 min; 0 = indefinite) |
| `--include-claude` | Include related Claude Code sessions from the project |
| `--include-codex` | Include related Codex CLI sessions from the project |
| `--include-all` | Include all related session sources |

**Project argument formats** (all equivalent):
`@ratchet` · `ratchet` · `ratchet_b39e0992` · `/path/to/project`

When this command runs inside Codex, `--project` includes related Codex sessions by default unless you explicitly choose sources with `--include-*`.

## Running the Pipeline

All variables must be in **one single Bash call** so `$LOG` and `$RATCHET_DIR` stay in scope:

```bash
LOG="/tmp/ratchet-run-$(date +%Y%m%d-%H%M%S).log" && \
  echo "Pipeline log: $LOG" && \
  export CLAUDE_PROJECT_DIR="$PWD" && \
  uv run --directory "$RATCHET_DIR" python -m ratchet.client.run_pipeline [FLAGS] 2>&1 | tee "$LOG"
```

Replace `[FLAGS]` with desired combination from the table above.
Tell the user the log path so they can monitor with `tail -f` or check after completion.
The background worker also writes a durable run log under the run directory:
`~/.local/ratchet/runs/{project_id}/{run_id}/worker.log`.

## Model Options

| Alias | Provider |
|-------|----------|
| `gemini-2.5-flash` | Google |
| `gpt-5-mini` | OpenAI |

When omitted, the local runtime prefers Gemini when `GEMINI_API_KEY` is set,
otherwise OpenAI when `OPENAI_API_KEY` is set.

## Pipeline Outputs

1. **Skills & Strategies** — saved to pending dirs for review/install
2. **Lesson Learned documents** — saved to `~/.local/ratchet/data/feedback/{project_id}/{run_id}/lessons/` (from sessions tagged `lesson_learn`)

## Handling Active Pipeline (Exit Code 2)

If the pipeline command exits with code **2**, a pipeline is already running.
Parse the JSON output to get `conflict.run_id` and `conflict.project_id`.

Use the `AskUserQuestion` tool to present these options:

**Question:** "A pipeline is already running for this project (run_id: {run_id}). What would you like to do?"

**Options:**
1. "Stop it and start a new one"
2. "Wait for the existing run to finish"
3. "Leave it running — exit without action"

**Option 1 — Stop and restart:**
```bash
uv run --directory "$RATCHET_DIR" python -m ratchet.client.cli pipeline-stop --run-id <RUN_ID>
```
Then re-run the pipeline command from "Running the Pipeline" section.

**Option 2 — Wait for existing run:**
```bash
uv run --directory "$RATCHET_DIR" python -m ratchet.client.run_pipeline \
  --poll-existing <RUN_ID> --project <PROJECT_ID> [--poll-timeout <seconds>] 2>&1 | tee "$LOG"
```
Then follow the Post-Pipeline Workflow as normal.

**Option 3 — Leave it running:**
Return immediately. Do not print anything or ask further questions.

## Handling Local Timeout (Exit Code 3)

If the pipeline command exits with code **3**, the local poll timeout was hit
before the worker reached a terminal status. Parse the JSON output for
`timeout.error` details.

Use the `AskUserQuestion` tool to present these options:

**Question:** "The local pipeline timed out ({error message}). What would you like to do?"

**Options:**
1. "Run again — start a fresh pipeline run"
2. "Do nothing — exit without action"

**Option 1 — Run again:**
Re-execute the pipeline command from "Running the Pipeline" section.

**Option 2 — Do nothing:**
Return immediately. Do not print anything or ask further questions.

## Post-Pipeline Workflow (MANDATORY)

The pipeline prints a JSON object with `additionalContext` on completion.
You MUST parse and follow the embedded workflow immediately — do NOT just report "pipeline complete".

### Steps:

1. Parse `run_id` and `project_id` from the pipeline output JSON (`additionalContext`).

2. Run this command to get the detailed review workflow instructions:

```bash
uv run --directory "$RATCHET_DIR" python -m ratchet.client.pending review \
  --run-id <RUN_ID> --project-id <PROJECT_ID>
```

3. Follow the printed instructions **exactly** — they contain the full review, install, and archive workflow.

## Debugging Runs

Every run has local debug artifacts: `worker.log`, `events.jsonl`, and raw LLM
prompt/response files under `llm/`.

Use these commands before making assumptions about a stuck or failed run:

```bash
uv run --directory "$RATCHET_DIR" ratchet pipeline-status --all --recent 10
uv run --directory "$RATCHET_DIR" ratchet pipeline-inspect --run-id <RUN_ID>
uv run --directory "$RATCHET_DIR" ratchet pipeline-logs --run-id <RUN_ID> --tail 160
```

For handoff or deep debugging, create a raw bundle directory:

```bash
uv run --directory "$RATCHET_DIR" ratchet debug-bundle --run-id <RUN_ID>
```
