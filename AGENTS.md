# ratchet plugin agent guide

This repo contains the Ratchet plugin surfaces:

- shared Claude/Codex skills in `skills/`
- host hook sources in `hooks/claude/` and `hooks/codex/`
- generated host packages in `dist/plugins/claude/ratchet` and `dist/plugins/codex/ratchet`
- helper scripts in `scripts/`
- client/runtime code in `ratchet/`

Keep changes scoped to those areas. If a task requires core extraction logic,
prefer editing `ratchet/` rather than duplicating logic in skill docs or shell
scripts.

## Repo map

```text
skills/wisdom-gen/ -> /ratchet:wisdom-gen
skills/status/     -> /ratchet:status
skills/debug/      -> /ratchet:debug
skills/profile/    -> /ratchet:profile
skills/login/      -> /ratchet:login
skills/help/       -> /ratchet:help

hooks/claude/hooks.json -> SessionStart / SessionEnd / UserPromptSubmit / Stop
hooks/codex/hooks.json  -> SessionStart / UserPromptSubmit / Stop
scripts/           -> session-start.sh, check_pending_skills.py,
                      codex-bootstrap.sh, generate_plugin_packages.py
```

## Non-negotiable runtime rules

### Resolve `RATCHET_DIR` in host-facing skills

Every shared skill that runs `uv` must set:

```bash
RATCHET_DIR="${RATCHET_PLUGIN_ROOT:-${CLAUDE_PLUGIN_ROOT:-${CODEX_PLUGIN_ROOT:-$(cat ~/.local/ratchet/plugin-root 2>/dev/null)}}}"
```

Every `uv run` command must include:

```bash
--directory "$RATCHET_DIR"
```

### Load environment before Python commands in skills/scripts

Before Python commands that depend on credentials or server config, load `.env`:

```bash
set -a && . "$RATCHET_DIR/.env" 2>/dev/null && set +a
```

If a command talks to the Ratchet server, check `RATCHET_API_KEY` first and
fail with a clear message when it is missing.

### Keep related shell steps in one Bash block

If a skill depends on variables such as `RATCHET_DIR`, `LOG`, or exported project
context, keep the commands in one Bash block so state is preserved.

## Shared skill conventions

Shared host skills live in `skills/*/SKILL.md`.

Required frontmatter:

- `name:` with a `ratchet-*` value
- `description:`
- `allowed-tools:`

Optional but expected when relevant:

- `argument-hint:`
- `disable-model-invocation: true` for skills that only orchestrate Bash

Authoring rules:

- Prefer the smallest `allowed-tools:` set that still works.
- Use `Bash, Read` by default; add `Write`, `Edit`, or `AskUserQuestion` only when needed.
- Keep command examples copy-pastable.
- Do not hardcode plugin install paths; use host hook roots and `RATCHET_DIR` in skills.
- If a skill invokes Python entry points, prefer existing modules in `ratchet.client` or scripts in `scripts/`.
- Keep `agents/openai.yaml` present for every shared skill so Codex can display it.

## Hook conventions

Hook source config lives in `hooks/claude/hooks.json` and `hooks/codex/hooks.json`.
Generated packages expose the selected host config as `hooks/hooks.json`.

Required rules:

- Claude hook commands reference `${CLAUDE_PLUGIN_ROOT}`.
- Codex hook commands resolve `${RATCHET_PLUGIN_ROOT}` or `${CODEX_PLUGIN_ROOT}`.
- Every hook entry must include a `timeout`.
- Use at most `30` seconds for collection/data hooks and at most `5` seconds for quick checks.
- Claude supports `SessionStart`, `SessionEnd`, `UserPromptSubmit`, and `Stop`.
- Codex supports `SessionStart`, `UserPromptSubmit`, and `Stop`; there is no Codex `SessionEnd` dependency.

When editing hooks:

- Keep commands non-interactive.
- Prefer existing scripts/modules over inline shell.
- Preserve fast-path behavior for prompt-time hooks.

## Preferred implementation pattern

When adding or updating behavior:

1. Put reusable logic in `ratchet/` or `scripts/`.
2. Keep `SKILL.md` files focused on invocation workflow and operator guidance.
3. Reuse existing commands and paths where possible.
4. Run `uv run python scripts/generate_plugin_packages.py` after changing shared package inputs.

## Consistency checks

Before finishing a change, verify:

- referenced files and commands actually exist in this repo
- skills use the `RATCHET_DIR` pattern when calling `uv`
- generated Claude and Codex packages are current
- hook commands use the correct host root
- new server-facing commands document the required auth/env assumptions
- instructions do not mention commands or skills that are absent from this repo

## What to avoid

- Duplicating Python business logic in `SKILL.md`
- hardcoded absolute paths in hooks or skills
- leaving stale references in docs after renaming files or commands
