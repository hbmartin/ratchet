<div align="center">
  <img src="logo_ratchet.png" alt="Ratchet Logo" width="50%">
</div>

<div align="center">
  <h3>Self-Optimizing Infrastructure for AI Coding Agents</h3>
</div>

<div align="center">
  <a href="https://github.com/wisdomgraph/ratchetai"><img src="https://img.shields.io/badge/version-2.0.0b1-blue" alt="Version"></a>
  <a href="https://opensource.org/licenses/Apache-2.0"><img src="https://img.shields.io/badge/License-Apache_2.0-green.svg" alt="License"></a>
  <a href="https://github.com/wisdomgraph/ratchetai"><img src="https://img.shields.io/badge/hosts-Claude%20%2B%20Codex-blueviolet" alt="Claude and Codex Plugin"></a>
  <a href="https://ratchetai.ai"><img src="https://img.shields.io/badge/docs-ratchetai.ai-orange" alt="Docs"></a>
</div>

<br>

**Ratchet** turns your AI coding sessions into compounding knowledge. It extracts reusable **skills** and **strategies** from real execution traces, decomposes them into atomic **Primary-Context-Resultant (PCR)** units, and reinjects only the relevant knowledge back into future tasks.

The result: each session makes the next one better — not by accumulating more context, but by refining what gets used and when.

Knowledge is stored in the **Wisdom Graph DB**, a structured graph that maps relationships between procedures, contexts, constraints, and outcomes. Rather than loading entire skill blocks into the prompt, Ratchet retrieves only what matches the current task, along with workflow guidance and step-by-step cheatmaps. Skills are continuously evaluated and enhanced, so the system improves by refinement — not just accumulation.

---

## Quick Start

### Canonical 2.0 Identity

- Python distribution: `ratchet-agent`
- Import package: `ratchet`
- CLI: `ratchet`
- Environment prefix: `RATCHET_*`
- Data root: `~/.local/ratchet`
- Generated host packages: `dist/plugins/claude/ratchet` and `dist/plugins/codex/ratchet`

### Prerequisites

- Claude or Codex installed and working
- `uv` installed locally
- No Ratchet service account, OAuth login, or provider key is required

### 1. Install the plugin

Claude installs from the existing external marketplace URL:

```
/plugin marketplace add https://github.com/wisdomgraph/ratchetai
/plugin install ratchet@mind-ai-ratchet
```

Codex uses the generated local package and marketplace metadata:

```bash
codex plugin marketplace add dist/plugins/codex
```

Then install `ratchet` from the `ratchet-local` marketplace in Codex.

### 2. Configure local runtime

Settings live in `~/.local/ratchet/.env`; non-secret routing and source settings live in `~/.local/ratchet/config.yaml`.

The default mode is deterministic local embeddings and structured heuristic generation:

```bash
ratchet configure --llm-mode deterministic
```

Optional host-agent generation delegates through the local Claude or Codex CLI:

```bash
ratchet configure --llm-mode host-cli --host-agent codex
```

### 3. Use it in any project

Open Claude or Codex in any project directory and run:

| Command | What it does |
|---|---|
| `/ratchet:wisdom-gen` | Extract skills and strategies from your session traces |
| `/ratchet:wisdom-curate` | Retrieve relevant skills, workflows, and cheatmaps for your current task |
| `/ratchet:skill-enhance` | Evaluate existing skills, measure ROI, and generate improved versions |
| `/ratchet:status` | Check pipeline status and results |
| `/ratchet:debug` | Collect local pipeline evidence and write a debug bundle directory |

### Updating

```
/plugin marketplace update mind-ai-ratchet
```

---

## Why Ratchet

Most skill systems store skills as fixed blocks and inject them wholesale into context. As the library grows, the prompt grows — but reasoning quality does not. More skills often mean more noise, not more capability.

Ratchet is built around one principle: **Evaluated wisdom compounds. Unevaluated assets just add noise.**

What matters is not how many skills you store, but whether knowledge can be decomposed, retrieved, recomposed, and improved in a form that fits the task at hand.

---

## Benchmarks

Measured head-to-head against 5 leading systems on tasks developers actually ship.

<table>
<tr>
<td align="center"><h3>1/5</h3><b>Token Usage</b><br><sub>vs no-skill baseline</sub><br><sub>169K tokens vs 897K baseline</sub></td>
<td align="center"><h3>#1</h3><b>Highest Score</b><br><sub>against 5 competing systems</sub><br><sub>78% combined avg — 4 skills x 2 models</sub></td>
<td align="center"><h3>3x</h3><b>Structural Quality</b><br><sub>vs competitor average</sub><br><sub>16/16 score across 8 structural dimensions</sub></td>
</tr>
</table>

### Token Usage

```
Ratchet        ████░░░░░░░░░░░░░░░░  169K   ← 81% reduction
HF Upskill       ████████████████░░░░  763K
anthropic-skill  █████████████████░░░  826K
Baseline         ██████████████████░░  897K
skill-factory    ██████████████████████████████  1,448K
skill-builder    ██████████████████████████████████████████  2,024K
```

### Combined Score

```
Ratchet        ████████████████  78%   ← #1
HF Upskill       ██████████████░░  70%
anthropic-skill  █████████████░░░  65%
Baseline         █████████████░░░  65%
skill-builder    ██████████░░░░░░  50%
skill-factory    █████████░░░░░░░  43%
```

Two of the four competing systems perform **worse than using no skills at all**. Ratchet is the only system that beats the no-skill baseline on both token efficiency and task quality simultaneously.

> [See the full benchmark →](https://www.ratchetai.ai/performance)

---

## How It Works

Ratchet installs as a Claude or Codex plugin and runs inside your existing workflow — no new tools or editors required. It operates through three core flows:

### 1. wisdom-gen — Extract knowledge from sessions

Reads your coding session traces and extracts reusable wisdom from what actually happened:

- **Skills** — reusable procedures that worked
- **Strategies** — decision rules and correction patterns from repeated choices
- **PCR units** — atomic Primary-Context-Resultant structures distilled from validated knowledge

These are written to structured local files for review and reuse.

### 2. wisdom-curate — Retrieve the right knowledge

Instead of injecting an entire skill library into context, Ratchet decomposes curated skills into atomic PCR-level wisdom, stores them in the Wisdom Graph DB, and retrieves only what is relevant to your current task.

For a given task, it provides:
- The most relevant Skills and Strategies
- A recommended workflow for solving the problem
- A **Cheatmap** — which skills to apply at each step and why

> **Note:** All Skills referenced in a curation must be installed locally. Missing skills will cause the curation to reference procedures the agent cannot access.

### 3. skill-enhance — Improve what you have

Evaluates generated skills, measures their ROI, and produces enhanced versions. The system improves quality, efficiency, and transferability of existing skills rather than merely accumulating more.

### What gets generated locally

```
~/.local/ratchet/data/
├── pending-skills/{skill-name}/SKILL.md    # Reusable procedures from session traces
├── pending-strategies/{strategy-name}.md   # Decision rules from corrections and repeated choices
└── enhanced-skills/{skill-name}/SKILL.md   # Evaluated and enhanced versions with ROI insights
```

<details>
<summary><b>Example: SKILL.md</b></summary>

```markdown
---
name: ui-consistency-and-discovery
description: ‘Guidelines for maintaining UI legibility and clean aesthetics while
  using ripgrep for efficient project exploration and global string replacement.’
metadata:
  tags: [ui-ux, ripgrep, accessibility, project-navigation]
  author: co-authored by http://www.ratchetai.ai
  version: "1.0.0"
  generated_at: "2026-03-26T05:22:58Z"
  roi:
    model: deterministic-local
    performance_increase: "75%"
    token_savings: "83%"
---

## Handle authentication token refresh

When an API call returns 401, check token expiry before retrying.
Refresh using POST /auth/refresh with the stored refresh_token.
Only retry the original request once — if it fails again, surface the error.

Applies to: src/api/client.py, any authenticated endpoint
Validated: 4 sessions
```
</details>

<details>
<summary><b>Example: Strategy</b></summary>

```markdown
## Database migration approach

In this project, always run migrations against a local test DB first.
Schema changes that touch the users table require a backup step before applying.
Learned from: 2 rollback incidents in sessions 3 and 7.
```
</details>

The agent reads these files at the start of every session. It does not repeat the mistake that generated the strategy. It does not re-derive the procedure that generated the skill.

<details>
<summary><b>Example: Cheatmap output</b></summary>

```markdown
Wisdom Curation

Problem
Situation: The user is in the late stages of a web development project and wants
to refine the visual aesthetics and UI components.
Goals: Acquire advanced front-end design techniques and UI/UX principles to
elevate visual quality and improve user retention.

IMPORTANT: How to use this curation
Each step may have a Reference: entry pointing to domain-specific knowledge.
Before executing each step, you MUST read the referenced section.

step-1: Visual Hierarchy and Aesthetic Audit

Portfolio: 1 core + 0 supporting skills selected for complementary coverage.

1. [H] Visual and Accessibility Audit (score=0.508)
   P: Assess visual polish against an 8px spacing scale, typography hierarchy,
      and semantic color usage. Verify WCAG 2.1 AA compliance.
   R: UI components are fully keyboard-accessible and screen-reader friendly.
   Reference: design-review/SKILL.md#Phase 3: Visual Polish L136-150

step-2: Advanced UI Component Design Systems

Portfolio: 1 core + 1 supporting skills selected for complementary coverage.

1. [H] micro-interaction-and-animation-implementation (score=0.501)
   P: Apply subtle CSS transitions and spring physics to buttons, toggles,
      and form elements.
   R: Interface elements provide immediate, satisfying visual feedback.
   Reference: delight/SKILL.md#Micro-interactions & Animation L84-122
```
</details>

---

## wisdom-gen Reference

### Session resolution

The pipeline operates on a **project** — a set of sessions grouped by working directory.

| Invocation | What gets processed |
|---|---|
| `/ratchet:wisdom-gen` | All sessions for the **current working directory** |
| `/ratchet:wisdom-gen --project` | Same as above (explicit) |
| `/ratchet:wisdom-gen --project @name` | All sessions for the named project (prefix-matched against `mapping.json`; also accepts `name`, `name_hash`, or `/absolute/path`) |
| `/ratchet:wisdom-gen --session-id <uuid>` | A single session by ID |

When no project or session is specified, the current working directory is hashed to locate its data folder under `~/.local/ratchet/projects/`.

### Local ingest

Before triggering the pipeline, Ratchet persists normalized `TurnSet` trajectories locally. The local worker reads stored turns or falls back to the collected session history under `~/.local/ratchet/projects/{project_id}/`.

Sync behavior:
- **New sessions** (not in the ledger) are uploaded.
- **Known sessions** are skipped, **unless** the source file’s `mtime` has changed — in which case they are re-uploaded. This handles sessions whose files grow after the initial upload (e.g., long-running sessions that gain new turns).
- The ledger records `uploaded_at`, `turn_count`, and (where applicable) `file_mtime` for each synced session.

#### Sync invariants

1. **No data loss on first run.** When no ledger exists, every locally stored session for the project is uploaded — not just the current terminal session.
2. **Idempotency.** Re-running `/ratchet:wisdom-gen` with an up-to-date ledger produces no duplicate uploads.
3. **Modified-session re-sync.** If a session file’s `mtime` has changed since the last recorded upload, it is re-uploaded.
4. **Filter-before-upload.** All turns pass through `SecretMasker` and `PathAnonymizer` before transmission. No raw absolute paths or secrets leave the client.

### Pipeline lifecycle

1. **Trigger** — the client records the project ID (and optionally a session ID) and starts a local worker.
2. **Poll** — the client polls the local runtime DB until the worker reports completion, failure, or timeout. Default poll timeout is 20 minutes (`--poll-timeout` to override; `0` = wait indefinitely).
3. **Save** — on success, extracted Skills and Strategies are written to local pending folders for review.

Every run gets a durable debug directory:

```text
~/.local/ratchet/runs/{project_id}/{run_id}/
├── worker.log
├── events.jsonl
└── llm/
```

Use the CLI first when debugging:

```bash
ratchet debug
ratchet debug --run-id <RUN_ID>
ratchet debug-bundle --run-id <RUN_ID>
```

`debug-bundle` writes a raw evidence directory at
`~/.local/ratchet/runs/{project_id}/{run_id}/debug-bundle/` by default.

External telemetry is optional. Local logs, events, and LLM artifacts are enough
for day-to-day debugging. To enable OTLP export for client spans, install the
`telemetry` extra and set `OTEL_EXPORTER_OTLP_ENDPOINT`.

| Exit code | Meaning |
|---|---|
| `0` | Success — outputs saved, post-pipeline review begins |
| `1` | Fatal error (auth, network, unexpected failure) |
| `2` | Conflict — a pipeline is already running for this project |
| `3` | Local timeout — polling exceeded the configured timeout |

---

## Project Structure

```
ratchet/
├── .claude-plugin/
│   └── plugin.json              # Plugin metadata
├── hooks/
│   └── hooks.json               # Lifecycle hooks (SessionStart, etc.)
├── skills/
│   ├── wisdom-gen/SKILL.md      # /ratchet:wisdom-gen
│   ├── wisdom-curate/SKILL.md   # /ratchet:wisdom-curate
│   ├── skill-enhance/SKILL.md   # /ratchet:skill-enhance
│   ├── status/SKILL.md          # /ratchet:status
│   ├── debug/SKILL.md           # /ratchet:debug
│   ├── login/SKILL.md           # /ratchet:login
│   ├── stop/SKILL.md            # /ratchet:stop
│   ├── profile/SKILL.md         # /ratchet:profile
│   └── help/SKILL.md            # /ratchet:help
├── ratchet/
│   └── client/                  # Python client modules
├── scripts/
│   ├── session-start.sh         # Bootstrap script
│   └── check_pending_skills.py  # Pending skills checker
└── pyproject.toml
```

---

## Configuration

Configuration is stored in `~/.local/ratchet/` and persists across sessions. Default enabled sources are Ratchet-collected sessions, Claude native sessions, and Codex native sessions. Other implemented sources stay disabled unless enabled in `config.yaml`.

## Development Setup

To develop and test changes locally from this repository:

```bash
# Install dependencies
uv sync

# Regenerate committed Claude and Codex plugin packages
uv run python scripts/generate_plugin_packages.py
```

## Terms of Service

By using this plugin, you agree to the [Terms of Service](https://ratchetai.ai/terms).

## License

Apache-2.0
