#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
RATCHET_DIR="$REPO_ROOT"
EXPECTED_LOG="$SCRIPT_DIR/claude-acceptance-smoke.expected.log"

MODEL="sonnet"
DATA_DIR=""
FIXTURE_DIR=""
ARTIFACT_DIR=""
KEEP_TEMP=0
TEMP_DATA_DIR=0
TEMP_FIXTURE_DIR=0

usage() {
  cat <<'EOF'
Usage: scripts/claude-acceptance-smoke.sh [options]

Run a repo-local acceptance smoke test for the Ratchet plugin using real
Claude CLI invocations plus the local deterministic Ratchet runtime.

Options:
  --model <name>          Claude model alias for the prompt sessions.
  --data-dir <path>       Reuse an existing Ratchet data dir instead of mktemp.
  --fixture-dir <path>    Reuse an existing fixture project dir instead of mktemp.
  --artifacts-dir <path>  Write raw logs to this directory instead of mktemp.
  --keep-temp             Preserve mktemp-created fixture and data dirs.
  -h, --help              Show this help.
EOF
}

require_cmd() {
  local cmd=$1
  if ! command -v "$cmd" >/dev/null 2>&1; then
    printf 'Missing required command: %s\n' "$cmd" >&2
    exit 1
  fi
}

summary_log=""

summary() {
  printf '%s\n' "$1" | tee -a "$summary_log"
}

fail() {
  local message=$1
  summary "RESULT: FAIL"
  printf 'Failure: %s\n' "$message" >&2
  printf 'Artifacts dir: %s\n' "$ARTIFACT_DIR" >&2
  exit 1
}

run_claude() {
  local cwd=$1
  local output_path=$2
  shift 2

  (
    cd "$cwd"
    RATCHET_DATA_DIR="$DATA_DIR" \
    RATCHET_TEST_FAKE_LLM=1 \
    claude "$@" >"$output_path" 2>&1
  )
}

run_local() {
  local cwd=$1
  local output_path=$2
  shift 2

  (
    cd "$cwd"
    RATCHET_DATA_DIR="$DATA_DIR" \
    RATCHET_TEST_FAKE_LLM=1 \
    "$@" >"$output_path" 2>&1
  )
}

extract_latest_run_identifiers() {
  local db_path=$1

  python3 - "$db_path" <<'PY'
import sqlite3
import sys

db_path = sys.argv[1]
with sqlite3.connect(db_path) as conn:
    row = conn.execute(
        "SELECT run_id, project_id FROM pipeline_runs ORDER BY started_at DESC LIMIT 1"
    ).fetchone()

if row is None:
    raise SystemExit(1)

print(f"{row[0]}\t{row[1]}")
PY
}

cleanup() {
  if [[ "$KEEP_TEMP" -eq 1 ]]; then
    return
  fi

  if [[ "$TEMP_DATA_DIR" -eq 1 && -n "$DATA_DIR" && -d "$DATA_DIR" ]]; then
    rm -rf "$DATA_DIR"
  fi

  if [[ "$TEMP_FIXTURE_DIR" -eq 1 && -n "$FIXTURE_DIR" && -d "$FIXTURE_DIR" ]]; then
    rm -rf "$FIXTURE_DIR"
  fi
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --model)
      MODEL=${2:?missing value for --model}
      shift 2
      ;;
    --data-dir)
      DATA_DIR=${2:?missing value for --data-dir}
      shift 2
      ;;
    --fixture-dir)
      FIXTURE_DIR=${2:?missing value for --fixture-dir}
      shift 2
      ;;
    --artifacts-dir)
      ARTIFACT_DIR=${2:?missing value for --artifacts-dir}
      shift 2
      ;;
    --keep-temp)
      KEEP_TEMP=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      printf 'Unknown argument: %s\n' "$1" >&2
      usage
      exit 1
      ;;
  esac
done

require_cmd claude
require_cmd mktemp
require_cmd python3
require_cmd rg
require_cmd uv
require_cmd uuidgen

set -a
. "$RATCHET_DIR/.env" 2>/dev/null || true
set +a

if [[ -z "$DATA_DIR" ]]; then
  DATA_DIR="$(mktemp -d "${TMPDIR:-/tmp}/ratchet-acceptance-data.XXXXXX")"
  TEMP_DATA_DIR=1
fi

if [[ -z "$FIXTURE_DIR" ]]; then
  FIXTURE_DIR="$(mktemp -d "${TMPDIR:-/tmp}/ratchet-acceptance-fixture.XXXXXX")"
  TEMP_FIXTURE_DIR=1
fi

ARTIFACT_DIR=${ARTIFACT_DIR:-$(mktemp -d "${TMPDIR:-/tmp}/ratchet-acceptance-artifacts.XXXXXX")}
mkdir -p "$ARTIFACT_DIR"

trap cleanup EXIT

summary_log="$ARTIFACT_DIR/06-summary.log"
: >"$summary_log"

AUTH_STATUS_LOG="$ARTIFACT_DIR/00-claude-auth-status.json"
STATUS_LOG="$ARTIFACT_DIR/01-status.stream.jsonl"
PROMPT1_LOG="$ARTIFACT_DIR/02-prompt-coverage.txt"
PROMPT2_LOG="$ARTIFACT_DIR/03-prompt-improvement.txt"
PIPELINE_LOG="$ARTIFACT_DIR/04-pipeline.log"
REVIEW_LOG="$ARTIFACT_DIR/05-pending-review.log"

claude auth status >"$AUTH_STATUS_LOG" 2>&1 || fail "Claude auth status failed."

rg -q '"loggedIn": true' "$AUTH_STATUS_LOG" || fail "Claude is not authenticated."

mkdir -p "$FIXTURE_DIR/src/auth" "$FIXTURE_DIR/tests"
cat >"$FIXTURE_DIR/src/auth/refresh.py" <<'EOF'
def refresh_token(existing_token: str) -> str:
    return existing_token + "-refreshed"
EOF

cat >"$FIXTURE_DIR/tests/test_auth.py" <<'EOF'
from src.auth.refresh import refresh_token


def test_refresh_token() -> None:
    assert refresh_token("abc") == "abc-refreshed"
EOF

cat >"$FIXTURE_DIR/pyproject.toml" <<'EOF'
[project]
name = "ratchet-acceptance-fixture"
version = "0.1.0"
EOF

printf 'version = 1\n' >"$FIXTURE_DIR/uv.lock"

STATUS_SESSION_ID="$(uuidgen | tr '[:upper:]' '[:lower:]')"
PROMPT1_SESSION_ID="$(uuidgen | tr '[:upper:]' '[:lower:]')"
PROMPT2_SESSION_ID="$(uuidgen | tr '[:upper:]' '[:lower:]')"

PROMPT1=$'Inspect `src/auth/refresh.py` and `tests/test_auth.py`. Use `rg` first.\nRespond with plain text only and exactly two bullets:\n- Covered: <what the current test covers>\n- Missing: <one important gap>\nDo not edit files.'
PROMPT2=$'Inspect the same files. Use `rg` first.\nRespond with plain text only and exactly one sentence that begins with `Next improvement:`.\nDo not edit files.'

run_claude \
  "$REPO_ROOT" \
  "$STATUS_LOG" \
  -p \
  --verbose \
  --session-id "$STATUS_SESSION_ID" \
  --plugin-dir "$REPO_ROOT" \
  --permission-mode bypassPermissions \
  --output-format stream-json \
  --include-hook-events \
  '/ratchet:status'

rg -q '"hook_event":"SessionStart"' "$STATUS_LOG" || fail "SessionStart hook event missing from status smoke."
rg -q '"hook_event":"UserPromptSubmit"' "$STATUS_LOG" || fail "UserPromptSubmit hook event missing from status smoke."
rg -q '"hook_event":"Stop"' "$STATUS_LOG" || fail "Stop hook event missing from status smoke."
rg -q 'Ratchet Status' "$STATUS_LOG" || fail "Status smoke did not return the status summary."
rg -q 'No active pipeline runs' "$STATUS_LOG" || fail "Status smoke did not report an idle pipeline."

find "$DATA_DIR/projects" -name metadata.json -print -quit | rg -q '.' || fail "No session metadata written to the data dir."
find "$DATA_DIR/projects" -name stats.json -print -quit | rg -q '.' || fail "No session stats written to the data dir."
find "$DATA_DIR/projects" -name events.jsonl -print -quit | rg -q '.' || fail "No session event log written to the data dir."
find "$DATA_DIR/projects" -name turns.jsonl -print -quit | rg -q '.' || fail "No session turns log written to the data dir."

run_claude \
  "$FIXTURE_DIR" \
  "$PROMPT1_LOG" \
  -p \
  --model "$MODEL" \
  --session-id "$PROMPT1_SESSION_ID" \
  --plugin-dir "$REPO_ROOT" \
  --permission-mode bypassPermissions \
  "$PROMPT1"

run_claude \
  "$FIXTURE_DIR" \
  "$PROMPT2_LOG" \
  -p \
  --model "$MODEL" \
  --session-id "$PROMPT2_SESSION_ID" \
  --plugin-dir "$REPO_ROOT" \
  --permission-mode bypassPermissions \
  "$PROMPT2"

rg -q 'Covered:' "$PROMPT1_LOG" || fail "Prompt session 1 did not return the Covered bullet."
rg -q 'Missing:' "$PROMPT1_LOG" || fail "Prompt session 1 did not return the Missing bullet."
rg -q '^Next improvement:' "$PROMPT2_LOG" || fail "Prompt session 2 did not return the expected sentence."

SESSION_DIR_COUNT="$(find "$DATA_DIR/projects" -mindepth 2 -maxdepth 2 -type d 2>/dev/null | wc -l | tr -d ' ')"
[[ "$SESSION_DIR_COUNT" -ge 3 ]] || fail "Expected at least 3 captured session directories."

run_local \
  "$FIXTURE_DIR" \
  "$PIPELINE_LOG" \
  uv run --directory "$REPO_ROOT" python -m ratchet.client.run_pipeline --project --poll-timeout 60

IFS=$'\t' read -r RUN_ID PROJECT_ID < <(
  extract_latest_run_identifiers "$DATA_DIR/local-runtime.sqlite3"
) || fail "Unable to read the latest run identifiers from the local runtime store."

[[ -n "$RUN_ID" ]] || fail "Pipeline run_id was empty."
[[ -n "$PROJECT_ID" ]] || fail "Pipeline project_id was empty."

PENDING_SKILL_COUNT="$(find "$DATA_DIR/data/pending-skills" -name SKILL.md 2>/dev/null | wc -l | tr -d ' ')"
PENDING_STRATEGY_COUNT="$(find "$DATA_DIR/data/pending-strategies" -name '*.md' 2>/dev/null | wc -l | tr -d ' ')"

[[ "$PENDING_SKILL_COUNT" -ge 1 ]] || fail "Expected at least one pending skill."
[[ "$PENDING_STRATEGY_COUNT" -ge 1 ]] || fail "Expected at least one pending strategy."

run_local \
  "$FIXTURE_DIR" \
  "$REVIEW_LOG" \
  uv run --directory "$REPO_ROOT" python -m ratchet.client.pending review --run-id "$RUN_ID" --project-id "$PROJECT_ID"

rg -q 'MANDATORY WORKFLOW FOR CLAUDE' "$REVIEW_LOG" || fail "Pending review output was not rendered."

summary "Ratchet Claude acceptance smoke test"
summary "Repo root: <repo-root>"
summary "Claude auth mode: detected and usable"
summary "Ratchet local model mode: fake via RATCHET_TEST_FAKE_LLM=1"
summary "Fixture project: auth refresh sample"
summary "Status smoke:"
summary "PASS - slash command /ratchet:status loaded from --plugin-dir"
summary "PASS - SessionStart hook event observed"
summary "PASS - UserPromptSubmit hook event observed"
summary "PASS - Stop hook event observed"
summary "PASS - session files written under <data-dir>/projects/"
summary "Prompt sessions:"
summary "PASS - prompt session 1 returned Covered/Missing bullets"
summary "PASS - prompt session 2 returned a Next improvement sentence"
summary "PASS - at least 3 session directories captured"
summary "Pipeline:"
summary "PASS - local run_pipeline completed for the fixture project"
summary "PASS - pending skill count >= 1"
summary "PASS - pending strategy count >= 1"
summary "Review:"
summary "PASS - pending review rendered the mandatory install workflow"
summary "Artifacts:"
summary "Raw logs: <artifacts-dir>/"
summary "Expected summary reference: scripts/claude-acceptance-smoke.expected.log"
summary "RESULT: PASS"

if ! diff -u "$EXPECTED_LOG" "$summary_log" >/dev/null; then
  diff -u "$EXPECTED_LOG" "$summary_log" >&2 || true
  fail "The normalized summary did not match the checked-in expected log."
fi

printf 'Artifacts dir: %s\n' "$ARTIFACT_DIR" >&2
if [[ "$KEEP_TEMP" -eq 1 ]]; then
  printf 'Fixture dir: %s\n' "$FIXTURE_DIR" >&2
  printf 'Data dir: %s\n' "$DATA_DIR" >&2
fi
