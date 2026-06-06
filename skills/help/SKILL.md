---
description: Show MEGA-Code help — available commands, output locations, skill and strategy structure, and usage tips.
argument-hint: ""
allowed-tools: Read
---

# MEGA-Code Help

## Available Commands

| Command | Description |
|---------|-------------|
| `/mega-code:login` | Show local provider-key setup help |
| `/mega-code:wisdom-gen` | Run skill extraction pipeline |
| `/mega-code:skill-enhance` | Evaluate and enhance a skill with A/B testing |
| `/mega-code:wisdom-curate` | Curate a wisdom-backed workflow with skill installation |
| `/mega-code:status` | Show pending items and status |
| `/mega-code:stop` | Stop a running pipeline |
| `/mega-code:profile` | View or update your developer profile |
| `/mega-code:help` | Show this help |

## Output Locations

| Type | Pending Location | Installed Location |
|------|------------------|-------------------|
| Skills | `~/.local/ratchetai/data/pending-skills/{name}/` | `.claude/skills/{name}/SKILL.md` |
| Strategies | `~/.local/ratchetai/data/pending-strategies/{name}.md` | `.claude/rules/mega-code/{name}.md` |
| Curated Skills | — | `{data_dir}/skills/{name}/SKILL.md` |
| Curations | `{data_dir}/curations/pending/{session_id}.json` | `{data_dir}/curations/completed/{session_id}.json` |

## Skill Structure

Generated skills follow this structure:

```
~/.local/ratchetai/data/pending-skills/{skill-name}/
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

## Model Options

The `--model` flag for `/mega-code:wisdom-gen` accepts any model alias supported by the LLM module:

| Alias | Provider |
|-------|----------|
| `gemini-3-flash` | Google |
| `gpt-5-mini` | OpenAI |

When no model is specified, the local runtime prefers Gemini when configured,
otherwise OpenAI.


## Tips

  - Run /mega-code:wisdom-gen after significant coding sessions
  - Run /mega-code:skill-enhance <skill> to improve an existing skill and review ROI
  - Use --project to analyze multiple sessions for stronger patterns
  - Skills with more evidence (from multiple sessions) are higher quality
  - Review and edit skills before installing for best results
  - Run /mega-code:wisdom-curate <task description> to get a curated workflow with relevant skills
  - Curated workflows can be executed immediately or saved for later resumption
  - For plugin updates, use `/plugin marketplace update mind-ai-mega-code`
