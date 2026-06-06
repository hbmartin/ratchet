# Ratchet Architecture

Ratchet is a local plugin runtime for Claude and Codex. It collects session
events, stores trajectories in SQLite/filesystem state, runs local background
pipeline workers, and writes generated skills, strategies, lessons, wisdom
curations, and feedback under `~/.local/ratchet`.

There is no hosted Ratchet service dependency. Legacy remote constructor
arguments and mode values are accepted only for compatibility and resolve to the
local runtime.

## Runtime Surfaces

- `ratchet.client.api.create_client(...)` returns local behavior.
- `ratchet.pipeline.local_client.RatchetLocal` is the canonical client.
- `ratchet.client.api.remote.RatchetRemote` is a no-network shim around
  `RatchetLocal`.
- `ratchet.pipeline.store.LocalStore` owns SQLite state, run directories,
  artifacts, feedback, and curation records.
- `ratchet.pipeline.worker` runs a background local pipeline for queued runs.

## Storage

Default data root:

```text
~/.local/ratchet/
├── .env
├── config.yaml
├── local-runtime.sqlite3
├── projects/
├── runs/{project_id}/{run_id}/
├── data/pending-skills/
├── data/pending-strategies/
├── data/feedback/
├── knowledge/
└── curations/
```

`.env` stores local runtime settings only. `config.yaml` stores non-secret source
and generation settings.

## Generation

The default generation path is deterministic:

- deterministic local embeddings,
- structured heuristic generation for analyst/consolidator prompts,
- deterministic reranking from local embeddings.

Optional host-agent mode delegates generation to the existing local host-agent
subprocess path:

```bash
ratchet configure --llm-mode host-cli --host-agent codex
```

Ratchet itself does not call model provider REST endpoints.

## Pipeline Conflict Handling

The local store allows only one active pipeline per project. When a second run
is requested without `force=True`, `RatchetLocal.trigger_pipeline_run` raises
`PipelineConflictError`. The CLI preserves the old exit-code behavior:

- `0`: success,
- `1`: failure,
- `2`: active pipeline conflict,
- `3`: local poll timeout.

## Skill Installation

Curated skill installation is local-only. `SkillRefItem.path` must point to a
local skill source with `SKILL.md`. URL-only skill references are skipped with a
clear message because remote downloads are disabled.

## Review UI

`ratchet.client.enhancement_viewer` starts a localhost-only review UI for
skill-enhancement feedback. This is the only HTTP traffic intentionally kept in
the runtime.

## Generated Packages

Shared source lives in:

- `ratchet/`
- `skills/`
- `hooks/`
- `scripts/`

After changing those inputs, run:

```bash
uv run python scripts/generate_plugin_packages.py
```

This refreshes `dist/plugins/claude/ratchet` and
`dist/plugins/codex/ratchet`.
