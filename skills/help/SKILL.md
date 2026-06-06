---
name: ratchet-help
description: Show Ratchet help — available commands, output locations, skill and strategy structure, and usage tips.
argument-hint: ""
allowed-tools: Read
---

# Ratchet Help

## Available Commands

| Command | Description |
|---------|-------------|
| `/ratchet:login` | Show local setup status |
| `/ratchet:wisdom-gen` | Run skill extraction pipeline |
| `/ratchet:skill-enhance` | Evaluate and enhance a skill with A/B testing |
| `/ratchet:wisdom-curate` | Curate a wisdom-backed workflow with skill installation |
| `/ratchet:status` | Show pending items and status |
| `/ratchet:debug` | Collect local pipeline evidence and write a debug bundle directory |
| `/ratchet:stop` | Stop a running pipeline |
| `/ratchet:profile` | View or update your developer profile |
| `/ratchet:help` | Show this help |

## Output Locations

| Type | Pending Location | Installed Location |
|------|------------------|-------------------|
| Skills | `~/.local/ratchet/data/pending-skills/{name}/` | `.claude/skills/{name}/SKILL.md` |
| Strategies | `~/.local/ratchet/data/pending-strategies/{name}.md` | `.claude/rules/ratchet/{name}.md` |
| Curated Skills | — | `{data_dir}/skills/{name}/SKILL.md` |
| Curations | `{data_dir}/curations/pending/{session_id}.json` | `{data_dir}/curations/completed/{session_id}.json` |

## Skill Structure

Generated skills follow this structure:

```
~/.local/ratchet/data/pending-skills/{skill-name}/
├── SKILL.md        # Main skill content
├── injection.json  # Auto-trigger rules
├── evidence.json   # Source evidence
└── metadata.json   # Generation info
```

## Strategy Structure

Strategies are modular rules saved as:

```markdown
---
paths: **/*.py
---

# Strategy Title

Clear statement of the preference or convention.
```

## Generation Mode

Ratchet defaults to deterministic local embeddings and structured heuristic
generation. Optional host-agent generation can be enabled with:

```bash
ratchet configure --llm-mode host-cli --host-agent codex
```


## Tips

  - Run /ratchet:wisdom-gen after significant coding sessions
  - Run /ratchet:skill-enhance <skill> to improve an existing skill and review ROI
  - Use --project to analyze multiple sessions for stronger patterns
  - Skills with more evidence (from multiple sessions) are higher quality
  - Review and edit skills before installing for best results
  - Run /ratchet:wisdom-curate <task description> to get a curated workflow with relevant skills
  - Curated workflows can be executed immediately or saved for later resumption
  - For plugin updates, use `/plugin marketplace update mind-ai-ratchet`
