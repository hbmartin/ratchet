---
description: Curate a wisdom-backed workflow from the local PCR store, install local skills, and optionally run the task.
argument-hint: "<problem description>"
allowed-tools: Bash, Read, Write, Glob, AskUserQuestion
---

# Wisdom Curate — Local PCR Network

Retrieve relevant wisdoms from the local knowledge store, curate them into a
step-by-step workflow, install recommended skills, and optionally
execute the task.

## Setup

```bash
MEGA_DIR="${CLAUDE_PLUGIN_ROOT:-$(cat ~/.local/share/mega-code/plugin-root 2>/dev/null)}"
set -a && . "$MEGA_DIR/.env" 2>/dev/null && set +a
uv run --directory "$MEGA_DIR" python -m mega_code.client.check_auth
```

If the auth check fails (non-zero exit), show the output to the user and stop.

### Data Directory

The mega-code data directory is returned by `mega_code.client.dirs.data_dir()`.
Use this function to resolve the path — never hardcode it.

Skills and curations are stored under this directory:

```
{data_dir()}/skills/{skill-name}/             ← installed skill directories
  SKILL.md                                     ← main skill file
  scripts/                                     ← optional
  references/                                  ← optional

{data_dir()}/curations/pending/               ← curated, not yet executed
  {session_id}.json
{data_dir()}/curations/running/               ← currently executing
  {session_id}.json
{data_dir()}/curations/completed/             ← finished
  {session_id}.json
```

Each curation JSON contains: session_id, query, curation (markdown workflow),
skills (list of local `{name, path, url}` references), wisdoms, token_count,
cost_usd, created_at, status.

Key Python functions for skill/curation access:
- `mega_code.client.dirs.data_dir()` → data root path
- `mega_code.client.skill_installer.skills_dir()` → skills directory
- `mega_code.client.skill_installer.install_skills(skills)` → download + extract
- `mega_code.client.curation_store.save_curation(result)` → save to pending/
- `mega_code.client.curation_store.get_curation(session_id)` → load by ID
- `mega_code.client.curation_store.list_curations(status)` → list by status
- `mega_code.client.curation_store.update_curation_status(id, status)` → transition

## Step 1: Validate Input

If `$ARGUMENTS` is empty or blank, use `AskUserQuestion` to ask the user
what task or skill they need help with. Do NOT proceed until the user
provides a non-empty task description. Store the answer as `TASK_QUERY`.

If `$ARGUMENTS` is provided, set `TASK_QUERY` to `$ARGUMENTS` and proceed.

## Step 2: Generate Session ID

```bash
SESSION_ID="${CLAUDE_SESSION_ID:-$(uuidgen 2>/dev/null || python3 -c 'import uuid;print(uuid.uuid4())')}"
echo "SESSION_ID=$SESSION_ID"
```

Remember this SESSION_ID — you will need it for feedback.

## Step 2b: Detect Project Context

Identify the project's tech stack using your own knowledge. Do NOT use a script.
Store the result in `TASK_CONTEXT` (separate from `TASK_QUERY`).

1. Use `Glob` to find manifest/config files in the project root:
   ```
   Glob("*") in the current working directory
   ```
   Look for any recognizable manifest — package.json, pyproject.toml, go.mod,
   Cargo.toml, pom.xml, build.gradle, Gemfile, composer.json, *.csproj, etc.
   This is not an exhaustive list — recognize any manifest you encounter.

2. `Read` the first manifest file found (limit to 50 lines). From its contents,
   determine the primary language, version (if visible), and key frameworks/libraries.

3. Compose `TASK_CONTEXT` as a descriptive sentence:
   - Examples:
     - `Python 3.12 project using FastAPI, SQLAlchemy, Celery`
     - `TypeScript project using Next.js 14, Prisma, TailwindCSS`
     - `Go 1.22 project using Gin, GORM`
     - `Java 21 Maven project using Spring Boot 3, JPA`
     - `Rust project using Axum, Tokio, SQLx`
     - `Ruby project using Rails 7, Sidekiq`
   - Include version numbers only when they are visible in the manifest.
   - If only the language is clear: `Python project`
   - If the project type is unrecognizable, leave `TASK_CONTEXT` empty.

## Step 3: Curate Skills

Show a brief acknowledgment to the user:

> Analyzing task... Curating skills...

**IMPORTANT**: Do NOT add any `echo` statements to this command.
The CLI prints JSON to stdout — any extra output will corrupt the JSON.

If `TASK_CONTEXT` is not empty, format the query as:
```
Task: <TASK_QUERY>, Task Context: <TASK_CONTEXT>
```

If `TASK_CONTEXT` is empty, use `TASK_QUERY` as-is.

```bash
uv run --directory "$MEGA_DIR" mega-code wisdom-curate \
  "$FORMATTED_QUERY" \
  --session-id "$SESSION_ID"
```

Where `FORMATTED_QUERY` is the value you composed above.

Parse the JSON output and store:
- `curation`: Markdown curation document (step-by-step workflow).
- `skills`: List of skill references, each with `name`, `path`, `url`.
- `wisdoms`: Underlying wisdom records.

## Step 4: Present Summary + Install Decision

Parse the `curation` field and present a structured summary:

```
Workflow: <title>
Overview: <1-2 sentence summary>
Steps:
1. <step title> — Skill: <skill-name>
2. <step title> — Skill: <skill-name>
3. <step title> — (no skill reference)

N skills recommended for this workflow.
```

Check which skills are already installed:

```bash
ls "$(uv run --directory "$MEGA_DIR" python -c "from mega_code.client.skill_installer import skills_dir; print(skills_dir())")" 2>/dev/null || echo "(no skills installed)"
```

**IMPORTANT — BINARY INSTALL DECISION**: There are EXACTLY two outcomes.
- "Yes" → install ALL not-yet-installed skills (proceed to Step 5)
- "Skip" → install NOTHING (skip to Step 6)

Do NOT offer partial, selective, or subset installation in any form.

Show all skills with their status, then use `AskUserQuestion` to ask:

```
The following skills are recommended for this workflow:

1. python-pro — [Already installed]
2. fastapi — [Not installed]
3. d3-visualization — [Not installed]

Would you like to install the 2 new skills? (Yes / Skip)
```

- If **Yes**: install all not-yet-installed skills (proceed to Step 5).
- If **Skip**: skip to Step 6 (no installation).
- If the user responds with anything other than Yes: treat as Skip.
- If all skills are already installed: inform the user and skip to Step 6.

## Step 5: Install Skills

For each not-yet-installed skill, install from the local source path returned
by `wisdom-curate`:

Write the JSON array of not-yet-installed skills from Step 3 to a temp file,
then pass the file path to the installer:

```bash
SKILLS_JSON_FILE="$(mktemp)"
cat > "$SKILLS_JSON_FILE" << 'SKILLS_EOF'
<JSON array of not-yet-installed skills from Step 3>
SKILLS_EOF

uv run --directory "$MEGA_DIR" python -c "
from mega_code.client.skill_installer import install_skills
from mega_code.client.api.protocol import SkillRefItem
import json, sys, os

skills = [SkillRefItem(**s) for s in json.loads(open(sys.argv[1]).read())]
os.unlink(sys.argv[1])
results = install_skills(skills)
for name, status in results.items():
    print(f'{name}: {status}')
" "$SKILLS_JSON_FILE"
```

Skills are copied to `{data_dir()}/skills/{skill-name}/`.

Report per-skill status:
```
Installed: fastapi ✓
Installed: d3-visualization ✓
Skipped: python-pro (already installed)
```

## Step 6: Save Curation + Run Decision

Save the curate result for potential later resumption:

Write the full curate result JSON from Step 3 to a temp file,
then pass the file path:

```bash
CURATE_JSON_FILE="$(mktemp)"
cat > "$CURATE_JSON_FILE" << 'CURATE_EOF'
<full curate result JSON from Step 3>
CURATE_EOF

uv run --directory "$MEGA_DIR" python -c "
from mega_code.client.curation_store import save_curation
from mega_code.client.api.protocol import WisdomCurateResult
import json, sys, os

result = WisdomCurateResult(**json.loads(open(sys.argv[1]).read()))
os.unlink(sys.argv[1])
path = save_curation(result)
print(f'Saved: {path}')
" "$CURATE_JSON_FILE"
```

Use `AskUserQuestion` to present the run decision:

- If the query is specific (actionable task), offer both options:
  ```
  Your task is ready to run. Would you like to:
  - Run now — execute the workflow with the installed skills
  - Later — end here, you can use the skills manually later
  ```
- If the query is vague, explain why and offer only **Later**.

## Step 7: Run Now

If the user chooses **Run now**:

Update curation status:

```bash
uv run --directory "$MEGA_DIR" python -c "
import sys
from mega_code.client.curation_store import update_curation_status
update_curation_status(sys.argv[1], 'running')
" "$SESSION_ID"
```

Follow the curation workflow. For each step:

1. Read the installed skill to get domain knowledge.
2. Adapt the step to the user's specific context.
3. Execute the step.

### Reading installed skills

When a step references a skill, read it from the installed skills directory:

```
Read("{data_dir()}/skills/{skill-name}/SKILL.md")
```

For specific sections referenced in the curation:
```
Reference: `python-pro/SKILL.md#Type Hints L42-78`
→ Read("{data_dir()}/skills/python-pro/SKILL.md", offset=42, limit=37)
```

After the workflow completes, mark as completed:

```bash
uv run --directory "$MEGA_DIR" python -c "
import sys
from mega_code.client.curation_store import update_curation_status
update_curation_status(sys.argv[1], 'completed')
" "$SESSION_ID"
```

Proceed to Feedback.

## Step 8: Later

If the user chooses **Later**:

Show a brief summary:
```
Skills installed: python-pro, fastapi
Curation saved to: {data_dir()}/curations/pending/{SESSION_ID}.json
You can resume this workflow later by asking me to continue it.
```

Proceed to Feedback with abbreviated feedback.

## Feedback (MANDATORY)

**You MUST complete this step.** Do NOT skip it.

Use the same `SESSION_ID` from Step 2.

### After Run Now (full feedback)

Evaluate how useful the curation was by writing natural language
feedback covering these 6 required fields:

1. **Overall**: rating (1-5) + estimated accuracy/efficiency impact
2. **Per-step**: each step's rating + which wisdoms were applied/partial/unused
3. **Missing**: skills or strategies that would have been useful but weren't provided
4. **Unexpected**: items that were surprisingly useful or harmful
5. **Recommendations**: per-item improvement suggestions for future routing
6. **[UPDATE]**: any outdated information, wrong model names, deprecated APIs found

### After Later (abbreviated feedback)

Provide curation-quality feedback only:

1. **Overall**: rating (1-5) of the curated skill selection relevance
2. **Missing**: skills or knowledge that should have been included
3. **Unexpected**: surprising inclusions (good or bad)

### Submit feedback

```bash
uv run --directory "$MEGA_DIR" mega-code wisdom-feedback \
  --session-id "$SESSION_ID" \
  --feedback-text "
Overall: <rating>/5. <impact estimates>

Step 1 (<step name>): <rating>/5
- <wisdom/item>: <applied|partial|not used>. <effect estimate>.

Missing: <what knowledge was needed but not provided>

Unexpected: <any surprises>

Recommendations:
- <per-item improvement suggestions>
"
```
