"""Local worker runtime for distillation and curation."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import tomllib
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mega_code.client.api.protocol import (
    OperatorPlanItem,
    OutputsResult,
    PendingSkillData,
    PendingStrategyData,
    SkillRefItem,
    WisdomCurateResult,
    WisdomResultItem,
)
from mega_code.client.api.sync import _session_to_turnset
from mega_code.client.history.loader import DataLoader, load_sessions_from_project
from mega_code.client.history.sources.mega_code import MegaCodeSource
from mega_code.client.models import Turn, TurnSet
from mega_code.client.skill_utils import DEFAULT_VERSION, get_author, sanitize_name
from mega_code.pipeline.llm import BaseLocalLLM, create_llm_client
from mega_code.pipeline.store import LocalStore, cosine_similarity, normalize_scores, utcnow_iso

_STOP_WORDS = {
    "the",
    "and",
    "for",
    "with",
    "that",
    "this",
    "from",
    "into",
    "then",
    "when",
    "your",
    "their",
    "have",
    "user",
    "assistant",
    "using",
    "project",
    "code",
}


@dataclass
class SessionArtifacts:
    pending_skill: PendingSkillData
    pending_strategy: PendingStrategyData
    artifact_payloads: list[dict[str, Any]]
    operator_payloads: list[dict[str, Any]]


def _tokenize(text: str) -> list[str]:
    return [token for token in re.findall(r"[a-z0-9_/-]+", text.lower()) if token and token not in _STOP_WORDS]


def _first_sentence(text: str, fallback: str) -> str:
    match = re.search(r"(.+?[.!?])(?:\s|$)", text.strip())
    return (match.group(1).strip() if match else fallback).strip()


def _snippet(text: str, limit: int = 180) -> str:
    flat = " ".join(text.split())
    return flat[:limit].rstrip() + ("..." if len(flat) > limit else "")


def _top_keywords(turns: list[Turn]) -> list[str]:
    counter: Counter[str] = Counter()
    for turn in turns:
        counter.update(_tokenize(turn.command or ""))
        counter.update(_tokenize(turn.tool_name or ""))
        counter.update(_tokenize(turn.content))
    return [token for token, _count in counter.most_common(6)]


def _derive_skill_name(turn_set: TurnSet) -> str:
    keywords = _top_keywords(turn_set.turns)
    project_part = sanitize_name(Path(turn_set.metadata.project_path or "project").name)[:16]
    stem = "-".join(keywords[:3]) if keywords else f"{project_part}-workflow"
    return sanitize_name(stem or f"{project_part}-workflow")


def _collect_steps(turns: list[Turn]) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = []
    for turn in turns:
        if turn.command:
            steps.append(
                {
                    "kind": "command",
                    "label": f"Run `{turn.command.strip()}`",
                    "turn_id": turn.turn_id,
                    "evidence": _snippet(turn.content or turn.command),
                    "error": turn.is_error,
                }
            )
        elif turn.tool_name:
            target = f" on `{turn.tool_target}`" if turn.tool_target else ""
            steps.append(
                {
                    "kind": "tool",
                    "label": f"Use `{turn.tool_name}`{target}",
                    "turn_id": turn.turn_id,
                    "evidence": _snippet(turn.content or turn.tool_name),
                    "error": turn.is_error,
                }
            )
        elif turn.role == "assistant" and turn.content.strip():
            steps.append(
                {
                    "kind": "analysis",
                    "label": _first_sentence(turn.content, "Review the current state."),
                    "turn_id": turn.turn_id,
                    "evidence": _snippet(turn.content),
                    "error": turn.is_error,
                }
            )
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for step in steps:
        key = step["label"].lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(step)
        if len(deduped) >= 6:
            break
    if not deduped:
        deduped.append(
            {
                "kind": "analysis",
                "label": "Review the task and implement the requested change.",
                "turn_id": 0,
                "evidence": "Derived from the session transcript.",
                "error": False,
            }
        )
    return deduped


def _build_skill_markdown(turn_set: TurnSet, skill_name: str, steps: list[dict[str, Any]], keywords: list[str]) -> str:
    project_name = Path(turn_set.metadata.project_path or "project").name
    description = (
        f"Reusable workflow distilled from session {turn_set.session_id} for {project_name}, "
        f"covering {' ,'.join(keywords[:3]) if keywords else 'local task execution'}."
    )
    body_lines = [
        "---",
        f"name: {skill_name}",
        f"description: \"{description}\"",
        "metadata:",
        f"  tags: [{', '.join(keywords[:4])}]",
        f"  author: \"{get_author()}\"",
        f"  version: \"{DEFAULT_VERSION}\"",
        f"  generated_at: \"{datetime.now(UTC).strftime('%Y-%m-%dT%H:%M:%SZ')}\"",
        "---",
        "",
        "# Summary",
        f"This local skill was distilled from project context `{project_name}`.",
        "",
        "## Workflow",
    ]
    for idx, step in enumerate(steps, 1):
        body_lines.append(f"{idx}. {step['label']}")
        body_lines.append(f"   Evidence: {step['evidence']}")
    body_lines.extend(
        [
            "",
            "## Guardrails",
            "- Preserve local project context and verify before finalizing.",
            "- Prefer the commands and tools that already succeeded in the captured session.",
            "- If a step fails, inspect the related evidence snippet before retrying.",
        ]
    )
    return "\n".join(body_lines) + "\n"


def _build_strategy_markdown(skill_name: str, turn_set: TurnSet, steps: list[dict[str, Any]]) -> str:
    error_steps = [step for step in steps if step["error"]]
    heading = f"# {skill_name.replace('-', ' ').title()} Strategy"
    lines = [heading, "", "## Decision Rules"]
    if error_steps:
        lines.append("- Re-check the failing command or tool output before moving to the next step.")
        for step in error_steps[:3]:
            lines.append(f"- When `{step['label']}` fails, use its evidence to tighten the next attempt.")
    else:
        lines.append("- Preserve the step order that produced the successful outcome in the source session.")
        lines.append("- Use small verification loops after each material command or tool action.")
    lines.extend(
        [
            "",
            "## Context",
            f"- Session: `{turn_set.session_id}`",
            f"- Model: `{turn_set.metadata.model_id or 'unknown'}`",
        ]
    )
    return "\n".join(lines) + "\n"


def _artifact_id(run_id: str, session_id: str, artifact_type: str, name: str) -> str:
    base = f"{run_id}:{session_id}:{artifact_type}:{name}"
    return str(uuid.uuid5(uuid.NAMESPACE_URL, base))


def _stable_id(*parts: object) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, ":".join(str(part) for part in parts)))


def _extract_paths(text: str) -> list[str]:
    paths = re.findall(
        r"(?:[A-Za-z0-9._-]+/)+[A-Za-z0-9._-]+|[A-Za-z0-9._-]+\.(?:py|ts|tsx|js|jsx|json|toml|yaml|yml|md|go|rs|java|rb|sh)",
        text,
    )
    deduped: list[str] = []
    for path in paths:
        if path not in deduped:
            deduped.append(path)
    return deduped[:4]


def _extract_env_vars(text: str) -> list[str]:
    vars_found = re.findall(r"\b[A-Z][A-Z0-9_]{2,}\b", text)
    deduped: list[str] = []
    for value in vars_found:
        if value not in deduped:
            deduped.append(value)
    return deduped[:4]


def _command_tool_name(command: str | None, tool_name: str | None = None) -> str:
    if command:
        return command.strip().split()[0]
    return tool_name or ""


def _normalize_intent(text: str) -> str:
    tokens = _tokenize(text)
    return " ".join(tokens[:8]) or "operator"


def _slot_signature(slots: list[dict[str, Any]]) -> str:
    if not slots:
        return "no-slots"
    parts = [
        f"{slot['slot_type']}:{slot['slot_name']}:{slot.get('slot_value', '')}"
        for slot in sorted(slots, key=lambda item: (item["slot_type"], item["slot_name"], item.get("slot_value", "")))
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:16]


def _safe_read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def _frameworks_from_text(text: str, candidates: list[str]) -> list[str]:
    lowered = text.lower()
    return [name for name in candidates if name in lowered]


def _inspect_project_fingerprint(project_path: str | None) -> dict[str, Any]:
    fingerprint: dict[str, Any] = {
        "project_path": project_path or "",
        "language": "",
        "frameworks": [],
        "package_manager": "",
    }
    if not project_path:
        return fingerprint
    root = Path(project_path)
    if not root.exists():
        return fingerprint
    package_json = root / "package.json"
    pyproject = root / "pyproject.toml"
    go_mod = root / "go.mod"
    cargo_toml = root / "Cargo.toml"
    gemfile = root / "Gemfile"
    if package_json.exists():
        payload = json.loads(_safe_read_text(package_json) or "{}")
        deps = {
            *payload.get("dependencies", {}).keys(),
            *payload.get("devDependencies", {}).keys(),
        }
        fingerprint["language"] = "typescript" if "typescript" in deps else "javascript"
        fingerprint["frameworks"] = [
            name
            for name in ("next", "react", "vite", "express", "nestjs", "astro", "svelte")
            if name in deps
        ]
        if (root / "pnpm-lock.yaml").exists():
            fingerprint["package_manager"] = "pnpm"
        elif (root / "yarn.lock").exists():
            fingerprint["package_manager"] = "yarn"
        elif (root / "bun.lockb").exists() or (root / "bun.lock").exists():
            fingerprint["package_manager"] = "bun"
        else:
            fingerprint["package_manager"] = "npm"
    elif pyproject.exists():
        try:
            payload = tomllib.loads(_safe_read_text(pyproject) or "")
        except tomllib.TOMLDecodeError:
            payload = {}
        project_data = payload.get("project", {})
        deps = project_data.get("dependencies", [])
        deps_text = " ".join(deps)
        fingerprint["language"] = "python"
        fingerprint["frameworks"] = _frameworks_from_text(
            deps_text,
            ["fastapi", "django", "flask", "sqlalchemy", "pytest", "celery"],
        )
        if (root / "uv.lock").exists():
            fingerprint["package_manager"] = "uv"
        elif (root / "poetry.lock").exists():
            fingerprint["package_manager"] = "poetry"
        elif (root / "requirements.txt").exists():
            fingerprint["package_manager"] = "pip"
    elif go_mod.exists():
        fingerprint["language"] = "go"
        fingerprint["package_manager"] = "go"
        fingerprint["frameworks"] = _frameworks_from_text(_safe_read_text(go_mod), ["gin", "gorm", "cobra"])
    elif cargo_toml.exists():
        fingerprint["language"] = "rust"
        fingerprint["package_manager"] = "cargo"
        fingerprint["frameworks"] = _frameworks_from_text(
            _safe_read_text(cargo_toml),
            ["axum", "tokio", "sqlx", "actix"],
        )
    elif gemfile.exists():
        fingerprint["language"] = "ruby"
        fingerprint["package_manager"] = "bundler"
        fingerprint["frameworks"] = _frameworks_from_text(_safe_read_text(gemfile), ["rails", "sinatra", "sidekiq"])
    return fingerprint


def _current_runtime_fingerprint(query: str) -> dict[str, Any]:
    fingerprint = _inspect_project_fingerprint(os.getcwd())
    fingerprint["branch"] = os.environ.get("GIT_BRANCH", "")
    fingerprint["model"] = os.environ.get("MODEL", "")
    fingerprint["required_tools"] = []
    env_vars = _extract_env_vars(query)
    fingerprint["env_var_presence"] = {item: bool(os.environ.get(item)) for item in env_vars}
    return fingerprint


def _fingerprint_lexical_text(fingerprint: dict[str, Any]) -> str:
    env_presence = " ".join(
        f"{key}:{'present' if value else 'missing'}"
        for key, value in sorted(fingerprint.get("env_var_presence", {}).items())
    )
    return " ".join(
        filter(
            None,
            [
                fingerprint.get("language", ""),
                " ".join(fingerprint.get("frameworks", [])),
                fingerprint.get("package_manager", ""),
                fingerprint.get("branch", ""),
                fingerprint.get("model", ""),
                " ".join(fingerprint.get("required_tools", [])),
                env_presence,
                fingerprint.get("project_path", ""),
            ],
        )
    )


def _step_procedure_text(step: dict[str, Any]) -> str:
    tool = _command_tool_name(step.get("command"), step.get("tool_name"))
    if step.get("command"):
        return f"{step['label']} Use `{tool}` to execute the captured command intent."
    if step.get("tool_name"):
        return f"{step['label']} Use `{step['tool_name']}` with the same target and sequencing."
    return f"{step['label']} Preserve the same analysis framing before changing code."


def _step_outcome_text(step: dict[str, Any]) -> str:
    if step["error"]:
        return (
            f"Use the evidence to recover from failure before retrying. "
            f"Observed evidence: {step['evidence']}"
        )
    if step.get("command"):
        return f"Expected outcome: {step['evidence']} Verify the result against `{step['command']}`."
    return f"Expected outcome: {step['evidence']}"


def _build_context_text(turn_set: TurnSet, env_fingerprint: dict[str, Any]) -> str:
    frameworks = ",".join(env_fingerprint.get("frameworks", [])) or "none"
    return (
        f"project={turn_set.metadata.project_path or 'unknown'} "
        f"language={env_fingerprint.get('language') or 'unknown'} "
        f"frameworks={frameworks} "
        f"package_manager={env_fingerprint.get('package_manager') or 'unknown'} "
        f"branch={turn_set.metadata.git_branch or 'unknown'} "
        f"model={turn_set.metadata.model_id or 'unknown'}"
    )


def _step_context_text(step: dict[str, Any], context_text: str, env_fingerprint: dict[str, Any]) -> str:
    focus = []
    if tool := _command_tool_name(step.get("command"), step.get("tool_name")):
        focus.append(f"tool={tool}")
    paths = _extract_paths(" ".join(filter(None, [step.get("command"), step.get("evidence"), step.get("label")])))
    if paths:
        focus.append(f"paths={','.join(paths)}")
    frameworks = ",".join(env_fingerprint.get("frameworks", []))
    if frameworks:
        focus.append(f"frameworks={frameworks}")
    return " ".join([context_text, *focus]).strip()


def _derive_preconditions(
    *,
    artifact_id: str,
    operator_index: int,
    step: dict[str, Any],
    env_fingerprint: dict[str, Any],
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    tool = _command_tool_name(step.get("command"), step.get("tool_name"))
    if tool:
        items.append(
            {
                "precondition_id": _stable_id(artifact_id, operator_index, "pre", "tool", tool),
                "precondition_type": "tool",
                "key_name": "tool",
                "value": tool,
                "description": f"`{tool}` must be available in the execution environment.",
            }
        )
    for path in _extract_paths(" ".join(filter(None, [step.get("command"), step.get("label")]))):
        items.append(
            {
                "precondition_id": _stable_id(artifact_id, operator_index, "pre", "file", path),
                "precondition_type": "file",
                "key_name": "path",
                "value": path,
                "description": f"Expected project file or path `{path}` to exist.",
            }
        )
    for env_var in _extract_env_vars(" ".join(filter(None, [step.get("command"), step.get("evidence")]))):
        items.append(
            {
                "precondition_id": _stable_id(artifact_id, operator_index, "pre", "env", env_var),
                "precondition_type": "env_var",
                "key_name": "env_var",
                "value": env_var,
                "description": f"Environment variable `{env_var}` must be configured.",
            }
        )
    package_manager = env_fingerprint.get("package_manager")
    if package_manager and tool in {"npm", "pnpm", "yarn", "bun", "uv", "poetry", "pip", "cargo"}:
        items.append(
            {
                "precondition_id": _stable_id(artifact_id, operator_index, "pre", "pkg", package_manager),
                "precondition_type": "package_manager",
                "key_name": "package_manager",
                "value": package_manager,
                "description": f"Expected package manager `{package_manager}` for this workflow.",
            }
        )
    return items


def _derive_postconditions(
    *,
    artifact_id: str,
    operator_index: int,
    step: dict[str, Any],
) -> list[dict[str, Any]]:
    items = [
        {
            "postcondition_id": _stable_id(artifact_id, operator_index, "post", "evidence"),
            "postcondition_type": "evidence",
            "key_name": "snippet",
            "value": step["evidence"],
            "description": "Preserve the observed evidence snippet as the operator outcome anchor.",
        }
    ]
    if step.get("command"):
        items.append(
            {
                "postcondition_id": _stable_id(artifact_id, operator_index, "post", "verify"),
                "postcondition_type": "verification",
                "key_name": "command",
                "value": step["command"],
                "description": "Re-run or validate against the captured command outcome.",
            }
        )
    for path in _extract_paths(" ".join(filter(None, [step.get("command"), step.get("evidence")]))):
        items.append(
            {
                "postcondition_id": _stable_id(artifact_id, operator_index, "post", "artifact", path),
                "postcondition_type": "artifact",
                "key_name": "path",
                "value": path,
                "description": f"Result should affect or verify `{path}`.",
            }
        )
    return items


def _derive_slots(
    *,
    artifact_id: str,
    operator_index: int,
    step: dict[str, Any],
    turn_set: TurnSet,
) -> list[dict[str, Any]]:
    slots: list[dict[str, Any]] = []
    for idx, path in enumerate(_extract_paths(" ".join(filter(None, [step.get("command"), step.get("label")]))), 1):
        slots.append(
            {
                "slot_id": _stable_id(artifact_id, operator_index, "slot", "path", idx),
                "slot_name": f"path_{idx}",
                "slot_type": "path",
                "slot_value": path,
                "required": True,
                "description": f"File or path target `{path}`.",
            }
        )
    for idx, env_var in enumerate(_extract_env_vars(" ".join(filter(None, [step.get("command"), step.get("evidence")]))), 1):
        slots.append(
            {
                "slot_id": _stable_id(artifact_id, operator_index, "slot", "env", idx),
                "slot_name": f"env_{idx}",
                "slot_type": "env_var",
                "slot_value": env_var,
                "required": True,
                "description": f"Environment variable slot `{env_var}`.",
            }
        )
    if turn_set.metadata.git_branch:
        slots.append(
            {
                "slot_id": _stable_id(artifact_id, operator_index, "slot", "branch"),
                "slot_name": "git_branch",
                "slot_type": "branch",
                "slot_value": turn_set.metadata.git_branch,
                "required": False,
                "description": "Captured source branch for the original workflow.",
            }
        )
    return slots


def _operator_payloads(
    *,
    run_id: str,
    project_id: str,
    session_id: str,
    artifact_id: str,
    skill_name: str,
    turn_set: TurnSet,
    steps: list[dict[str, Any]],
    llm: BaseLocalLLM,
    context_text: str,
    env_fingerprint: dict[str, Any],
) -> list[dict[str, Any]]:
    procedure_texts = [_step_procedure_text(step) for step in steps]
    context_texts = [_step_context_text(step, context_text, env_fingerprint) for step in steps]
    outcome_texts = [_step_outcome_text(step) for step in steps]
    embeddings = llm.embed_documents([*procedure_texts, *context_texts, *outcome_texts])
    procedure_embeddings = embeddings[: len(steps)]
    context_embeddings = embeddings[len(steps) : len(steps) * 2]
    outcome_embeddings = embeddings[len(steps) * 2 :]
    payloads: list[dict[str, Any]] = []
    previous_operator_id: str | None = None
    last_analysis_operator_id: str | None = None
    fingerprint_hash = hashlib.sha256(
        json.dumps(env_fingerprint, sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]
    for idx, step in enumerate(steps, 1):
        operator_id = _stable_id(artifact_id, "operator", idx)
        slots = _derive_slots(artifact_id=artifact_id, operator_index=idx, step=step, turn_set=turn_set)
        edges: list[dict[str, Any]] = []
        if previous_operator_id:
            edges.append(
                {
                    "edge_type": "depends_on",
                    "target_operator_id": previous_operator_id,
                    "metadata": {"reason": "preserve successful step order"},
                }
            )
        if step["kind"] != "analysis" and last_analysis_operator_id and last_analysis_operator_id != previous_operator_id:
            edges.append(
                {
                    "edge_type": "requires_context",
                    "target_operator_id": last_analysis_operator_id,
                    "metadata": {"reason": "analysis step established the execution context"},
                }
            )
        payload = {
            "operator_id": operator_id,
            "artifact_id": artifact_id,
            "run_id": run_id,
            "project_id": project_id,
            "session_id": session_id,
            "name": f"{skill_name}-operator-{idx}",
            "title": step["label"],
            "procedure": procedure_texts[idx - 1],
            "context": context_texts[idx - 1],
            "outcome": outcome_texts[idx - 1],
            "source_artifact": skill_name,
            "normalized_intent": _normalize_intent(step["label"]),
            "slot_signature": _slot_signature(slots),
            "feedback_score": 0.0,
            "created_at": utcnow_iso(),
            "indexes": {
                "procedure": {
                    "facet_text": procedure_texts[idx - 1],
                    "embedding": procedure_embeddings[idx - 1],
                    "lexical_text": " ".join([step["label"], step.get("command") or "", skill_name]),
                },
                "context": {
                    "facet_text": context_texts[idx - 1],
                    "embedding": context_embeddings[idx - 1],
                    "lexical_text": " ".join(
                        [
                            context_text,
                            " ".join(env_fingerprint.get("frameworks", [])),
                            env_fingerprint.get("package_manager", ""),
                            env_fingerprint.get("language", ""),
                        ]
                    ),
                },
                "outcome": {
                    "facet_text": outcome_texts[idx - 1],
                    "embedding": outcome_embeddings[idx - 1],
                    "lexical_text": " ".join([step["evidence"], step.get("command") or "", skill_name]),
                },
            },
            "edges": edges,
            "preconditions": _derive_preconditions(
                artifact_id=artifact_id,
                operator_index=idx,
                step=step,
                env_fingerprint=env_fingerprint,
            ),
            "postconditions": _derive_postconditions(
                artifact_id=artifact_id,
                operator_index=idx,
                step=step,
            ),
            "slots": slots,
            "env_fingerprint": {
                "fingerprint": env_fingerprint,
                "lexical_text": _fingerprint_lexical_text(env_fingerprint),
                "fingerprint_hash": fingerprint_hash,
            },
        }
        payloads.append(payload)
        previous_operator_id = operator_id
        if step["kind"] == "analysis":
            last_analysis_operator_id = operator_id
    return payloads


def distill_session(
    *,
    run_id: str,
    project_id: str,
    turn_set: TurnSet,
    llm: BaseLocalLLM,
    store: LocalStore,
) -> SessionArtifacts:
    skill_name = _derive_skill_name(turn_set)
    keywords = _top_keywords(turn_set.turns)
    steps = _collect_steps(turn_set.turns)
    env_fingerprint = _inspect_project_fingerprint(turn_set.metadata.project_path)
    env_fingerprint["branch"] = turn_set.metadata.git_branch or ""
    env_fingerprint["model"] = turn_set.metadata.model_id or ""
    required_tools = sorted(
        {
            tool
            for tool in (
                _command_tool_name(step.get("command"), step.get("tool_name")) for step in steps
            )
            if tool
        }
    )
    env_fingerprint["required_tools"] = required_tools
    referenced_env_vars = sorted(
        {
            env_var
            for step in steps
            for env_var in _extract_env_vars(
                " ".join(filter(None, [step.get("command"), step.get("evidence"), step.get("label")]))
            )
        }
    )
    env_fingerprint["env_var_presence"] = {
        env_var: bool(os.environ.get(env_var)) for env_var in referenced_env_vars
    }
    skill_md = _build_skill_markdown(turn_set, skill_name, steps, keywords)
    strategy_name = f"{skill_name}-strategy"
    strategy_md = _build_strategy_markdown(skill_name, turn_set, steps)
    evidence_items = [
        {
            "turn_id": turn.turn_id,
            "role": turn.role,
            "tool_name": turn.tool_name,
            "command": turn.command,
            "snippet": _snippet(turn.content),
            "is_error": turn.is_error,
        }
        for turn in turn_set.turns[:12]
    ]
    metadata = {
        "generated_at": utcnow_iso(),
        "workflow": {
            "domains": keywords[:4],
            "session_id": turn_set.session_id,
        },
        "pcr_model": "procedure-context-resultant",
    }
    injection_rules = {
        "mode": "local",
        "trigger_keywords": keywords[:6],
        "project_path": turn_set.metadata.project_path or "",
    }
    context_text = _build_context_text(turn_set, env_fingerprint)
    artifact_embedding = llm.embed_documents([skill_md + "\n" + strategy_md])[0]
    skill_artifact_id = _artifact_id(run_id, turn_set.session_id, "skill", skill_name)
    skill_source_path = store.write_source_tree(
        artifact_type="skill", name=skill_name, content=skill_md
    )
    strategy_artifact_id = _artifact_id(run_id, turn_set.session_id, "strategy", strategy_name)
    strategy_source_path = store.write_source_tree(
        artifact_type="strategy", name=strategy_name, content=strategy_md
    )
    pending_skill = PendingSkillData(
        skill_name=skill_name,
        skill_md=skill_md,
        injection_rules=json.dumps(injection_rules, indent=2),
        evidence=json.dumps(evidence_items, indent=2),
        metadata=json.dumps(metadata, indent=2),
        author=get_author(),
        version=DEFAULT_VERSION,
        tags=keywords[:4],
    )
    pending_strategy = PendingStrategyData(
        strategy_name=strategy_name,
        content=strategy_md,
        category="local-runtime",
        author=get_author(),
        version=DEFAULT_VERSION,
        tags=keywords[:4],
    )
    artifact_payloads = [
        {
            "artifact_id": skill_artifact_id,
            "artifact_type": "skill",
            "name": skill_name,
            "version": DEFAULT_VERSION,
            "content": skill_md,
            "metadata": metadata,
            "source_path": skill_source_path,
            "created_at": utcnow_iso(),
            "embedding": artifact_embedding,
        },
        {
            "artifact_id": strategy_artifact_id,
            "artifact_type": "strategy",
            "name": strategy_name,
            "version": DEFAULT_VERSION,
            "content": strategy_md,
            "metadata": metadata,
            "source_path": strategy_source_path,
            "created_at": utcnow_iso(),
            "embedding": artifact_embedding,
        },
    ]
    operator_payloads = _operator_payloads(
        run_id=run_id,
        project_id=project_id,
        session_id=turn_set.session_id,
        artifact_id=skill_artifact_id,
        skill_name=skill_name,
        turn_set=turn_set,
        steps=steps,
        llm=llm,
        context_text=context_text,
        env_fingerprint=env_fingerprint,
    )
    return SessionArtifacts(
        pending_skill=pending_skill,
        pending_strategy=pending_strategy,
        artifact_payloads=artifact_payloads,
        operator_payloads=operator_payloads,
    )


def _load_turnset_from_session_id(session_id: str, store: LocalStore) -> TurnSet:
    saved = store.load_saved_turnset(session_id)
    if saved is not None:
        return saved
    source = MegaCodeSource()
    loader = DataLoader()
    loader.register_source(source)
    session = loader.load_from("mega_code", session_id)
    turn_set = _session_to_turnset(session)
    if turn_set is None:
        raise ValueError(f"Session {session_id} did not produce any turns.")
    return turn_set


def load_turnsets_for_run(config: dict[str, Any], *, store: LocalStore) -> list[TurnSet]:
    project_path = config.get("project_path")
    session_id = config.get("session_id")
    include_claude = bool(config.get("include_claude"))
    include_codex = bool(config.get("include_codex"))
    limit = config.get("limit_value")
    if session_id:
        return [_load_turnset_from_session_id(session_id, store)]
    if not project_path:
        raise ValueError("Local pipeline requires a project path or session id.")
    sessions = load_sessions_from_project(
        Path(project_path),
        include_claude=include_claude,
        include_codex=include_codex,
        limit=limit,
    )
    turnsets: list[TurnSet] = []
    for session in sessions:
        turn_set = _session_to_turnset(session)
        if turn_set is not None:
            turnsets.append(turn_set)
    return turnsets


def run_local_pipeline(run_id: str, *, store: LocalStore | None = None) -> OutputsResult:
    store = store or LocalStore()
    llm = create_llm_client()
    config = store.get_run_config(run_id)
    turnsets = load_turnsets_for_run(config, store=store)
    store.update_progress(run_id, phase="distilling", processed=0, total=len(turnsets))
    pending_skills: list[PendingSkillData] = []
    pending_strategies: list[PendingStrategyData] = []
    artifact_payloads: list[dict[str, Any]] = []
    operator_payloads: list[dict[str, Any]] = []
    for idx, turn_set in enumerate(turnsets, 1):
        if store.is_stop_requested(run_id):
            raise RuntimeError("Pipeline stop requested.")
        artifacts = distill_session(
            run_id=run_id,
            project_id=config["project_id"],
            turn_set=turn_set,
            llm=llm,
            store=store,
        )
        pending_skills.append(artifacts.pending_skill)
        pending_strategies.append(artifacts.pending_strategy)
        artifact_payloads.extend(artifacts.artifact_payloads)
        operator_payloads.extend(artifacts.operator_payloads)
        store.update_progress(run_id, phase="distilling", processed=idx, total=len(turnsets))
    store.save_artifacts(
        run_id=run_id,
        project_id=config["project_id"],
        session_id=config.get("session_id") or "",
        artifact_payloads=artifact_payloads,
        operator_payloads=operator_payloads,
    )
    outputs = OutputsResult(
        pending_skills=pending_skills,
        pending_strategies=pending_strategies,
        pending_lessons=[],
    )
    return outputs


def _bm25_scores(query_tokens: list[str], docs: list[list[str]]) -> list[float]:
    if not docs:
        return []
    doc_freq: defaultdict[str, int] = defaultdict(int)
    for doc in docs:
        for token in set(doc):
            doc_freq[token] += 1
    avgdl = sum(len(doc) for doc in docs) / len(docs)
    k1 = 1.5
    b = 0.75
    scores: list[float] = []
    for doc in docs:
        counts = Counter(doc)
        score = 0.0
        for token in query_tokens:
            if token not in counts:
                continue
            idf = math.log(1 + (len(docs) - doc_freq[token] + 0.5) / (doc_freq[token] + 0.5))
            denom = counts[token] + k1 * (1 - b + b * (len(doc) / avgdl if avgdl else 0))
            score += idf * (counts[token] * (k1 + 1)) / denom
        scores.append(score)
    return scores


def _days_since(timestamp: str) -> float:
    try:
        created = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError:
        return 365.0
    return max((datetime.now(UTC) - created).total_seconds() / 86400.0, 0.0)


def _facet_candidate_scores(
    *,
    query_embedding: list[float],
    query_tokens: list[str],
    operators: list[dict[str, Any]],
    facet_name: str,
) -> dict[str, float]:
    lexical_docs = [_tokenize(item["indexes"][facet_name].get("lexical_text", "")) for item in operators]
    lexical_scores = _bm25_scores(query_tokens, lexical_docs)
    semantic_scores = [
        cosine_similarity(
            query_embedding,
            json.loads(item["indexes"][facet_name].get("embedding_json", "[]")),
        )
        for item in operators
    ]
    normalized_lexical = normalize_scores(lexical_scores)
    normalized_semantic = normalize_scores(semantic_scores)
    return {
        item["operator_id"]: round(0.65 * normalized_semantic[idx] + 0.35 * normalized_lexical[idx], 6)
        for idx, item in enumerate(operators)
    }


def _env_match_score(current: dict[str, Any], candidate: dict[str, Any]) -> float:
    checks = 0.0
    score = 0.0
    current_language = current.get("language") or ""
    if language := candidate.get("language"):
        checks += 1
        score += 1.0 if current_language == language else (0.6 if not current_language else 0.0)
    current_pm = current.get("package_manager") or ""
    if package_manager := candidate.get("package_manager"):
        checks += 1
        score += 1.0 if current_pm == package_manager else (0.6 if not current_pm else 0.0)
    current_branch = current.get("branch") or ""
    if branch := candidate.get("branch"):
        checks += 1
        score += 1.0 if current_branch == branch else (0.6 if not current_branch else 0.0)
    frameworks = candidate.get("frameworks", [])
    if frameworks:
        checks += 1
        current_frameworks = set(current.get("frameworks", []))
        if not current_frameworks:
            score += 0.6
        else:
            score += max(len(current_frameworks.intersection(frameworks)) / len(frameworks), 0.0)
    required_tools = candidate.get("required_tools", [])
    if required_tools:
        checks += 1
        available = sum(1 for item in required_tools if shutil.which(item))
        score += available / len(required_tools)
    env_presence = candidate.get("env_var_presence", {})
    if env_presence:
        checks += 1
        env_matches = sum(1 for key, value in env_presence.items() if bool(os.environ.get(key)) == bool(value))
        score += env_matches / max(len(env_presence), 1)
    return round(score / checks, 6) if checks else 0.6


def _operator_conflict_ids(operator: dict[str, Any]) -> set[str]:
    ids = {
        edge["target_operator_id"]
        for edge in operator.get("edges", [])
        if edge.get("edge_type") == "conflicts_with"
    }
    ids.update(
        edge["source_operator_id"]
        for edge in operator.get("incoming_edges", [])
        if edge.get("edge_type") == "conflicts_with"
    )
    return ids


def _path_exists(path_value: str) -> bool:
    if not path_value:
        return False
    path = Path(path_value)
    if path.exists():
        return True
    return (Path(os.getcwd()) / path_value).exists()


def _evaluate_preconditions(
    operator: dict[str, Any],
    current_env: dict[str, Any],
) -> list[str]:
    missing: list[str] = []
    for item in operator.get("preconditions", []):
        kind = item.get("precondition_type")
        value = item.get("value", "")
        description = item.get("description", value)
        if kind == "tool":
            if not shutil.which(value):
                missing.append(description)
        elif kind == "file":
            if not _path_exists(value):
                missing.append(description)
        elif kind == "env_var":
            if not os.environ.get(value):
                missing.append(description)
        elif kind == "package_manager":
            current_pm = current_env.get("package_manager") or ""
            if current_pm and current_pm != value:
                missing.append(description)
        elif kind == "branch":
            current_branch = current_env.get("branch") or ""
            if current_branch and current_branch != value:
                missing.append(description)
    return missing


def _evaluate_slots(operator: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    for item in operator.get("slots", []):
        if not item.get("required", True):
            continue
        if not str(item.get("slot_value", "")).strip():
            missing.append(item.get("slot_name", "slot"))
    return missing


def curate_local_wisdom(
    *,
    query: str,
    session_id: str = "",
    top_k: int = 20,
    store: LocalStore | None = None,
) -> WisdomCurateResult:
    store = store or LocalStore()
    llm = create_llm_client()
    query_embedding = llm.embed_query(query)
    operators = store.fetch_operators()
    if not operators:
        curation = (
            "Wisdom Curation\n\n"
            f"Problem: {query}\n\n"
            "Workflow: Local Operator Graph\n"
            "Overview: No operator graph data is available yet. Run the local pipeline to distill operators first.\n"
        )
        result = WisdomCurateResult(
            session_id=session_id or str(uuid.uuid4()),
            query=query,
            curation=curation,
            skills=[],
            wisdoms=[],
            operator_plan=[],
            readiness_summary={"ready": 0, "blocked": 0},
            token_count=0,
            cost_usd=0.0,
        )
        store.save_curation(result)
        return result
    query_tokens = _tokenize(query)
    procedure_scores = _facet_candidate_scores(
        query_embedding=query_embedding,
        query_tokens=query_tokens,
        operators=operators,
        facet_name="procedure",
    )
    context_scores = _facet_candidate_scores(
        query_embedding=query_embedding,
        query_tokens=query_tokens,
        operators=operators,
        facet_name="context",
    )
    outcome_scores = _facet_candidate_scores(
        query_embedding=query_embedding,
        query_tokens=query_tokens,
        operators=operators,
        facet_name="outcome",
    )
    facet_limit = max(top_k, 5)
    candidate_ids: set[str] = set()
    for facet_scores in (procedure_scores, context_scores, outcome_scores):
        top_ids = sorted(facet_scores, key=facet_scores.get, reverse=True)[:facet_limit]
        candidate_ids.update(top_ids)
    current_env = _current_runtime_fingerprint(query)
    scored: list[dict[str, Any]] = []
    operator_map = {item["operator_id"]: item for item in operators}
    superseded_ids = {
        edge["target_operator_id"]
        for item in operators
        for edge in item.get("edges", [])
        if edge.get("edge_type") == "supersedes"
    }
    for operator_id in candidate_ids:
        operator = operator_map[operator_id]
        if operator_id in superseded_ids:
            continue
        candidate_fingerprint = json.loads(operator["env_fingerprint"].get("fingerprint_json", "{}"))
        env_match_score = _env_match_score(current_env, candidate_fingerprint)
        feedback_boost = float(operator["feedback_score"]) * 0.15
        recency_boost = max(0.0, 0.1 - min(_days_since(operator["created_at"]) / 365.0, 0.1))
        provenance_boost = 0.05 if operator.get("source_path") else 0.0
        retrieval_score = (
            0.45 * procedure_scores.get(operator_id, 0.0)
            + 0.25 * context_scores.get(operator_id, 0.0)
            + 0.30 * outcome_scores.get(operator_id, 0.0)
        )
        final_score = retrieval_score * (0.35 + 0.65 * env_match_score) + feedback_boost + recency_boost + provenance_boost
        scored.append(
            {
                **operator,
                "env_match_score": round(env_match_score, 6),
                "score": round(final_score, 6),
            }
        )
    scored.sort(key=lambda item: item["score"], reverse=True)
    seeds = scored[:top_k]
    seed_ids = {item["operator_id"] for item in seeds}
    selected_ids = set(seed_ids)

    def expand_neighbors(operator_id: str) -> None:
        operator = operator_map[operator_id]
        for edge in operator.get("edges", []):
            if edge.get("edge_type") not in {"depends_on", "requires_context"}:
                continue
            target_id = edge["target_operator_id"]
            if target_id in superseded_ids or target_id in selected_ids or target_id not in operator_map:
                continue
            selected_ids.add(target_id)
            expand_neighbors(target_id)

    for item in list(seed_ids):
        expand_neighbors(item)
    selected = [operator_map[item_id] for item_id in selected_ids if item_id in operator_map and item_id not in superseded_ids]
    score_lookup = {item["operator_id"]: item for item in scored}
    kept_ids: list[str] = []
    dropped_by_conflict: set[str] = set()
    for item in sorted(
        selected,
        key=lambda current: score_lookup.get(current["operator_id"], {"score": 0.0})["score"],
        reverse=True,
    ):
        operator_id = item["operator_id"]
        if operator_id in dropped_by_conflict:
            continue
        kept_ids.append(operator_id)
        dropped_by_conflict.update(_operator_conflict_ids(item))
        dropped_by_conflict.discard(operator_id)
    selected_map = {item_id: operator_map[item_id] for item_id in kept_ids}
    ordered: list[dict[str, Any]] = []
    visited: set[str] = set()

    def visit(operator_id: str) -> None:
        if operator_id in visited or operator_id not in selected_map:
            return
        visited.add(operator_id)
        operator = selected_map[operator_id]
        for edge in operator.get("edges", []):
            if edge.get("edge_type") in {"depends_on", "requires_context"}:
                visit(edge["target_operator_id"])
        ordered.append(
            {
                **operator,
                "score": score_lookup.get(operator_id, {"score": 0.0})["score"],
                "env_match_score": score_lookup.get(operator_id, {"env_match_score": 0.0})["env_match_score"],
            }
        )

    for item in sorted(
        kept_ids,
        key=lambda operator_id: score_lookup.get(operator_id, {"score": 0.0})["score"],
        reverse=True,
    ):
        visit(item)
    plan_items: list[OperatorPlanItem] = []
    title_lookup = {item["operator_id"]: item["title"] for item in ordered}
    status_lookup: dict[str, str] = {}
    for item in ordered:
        depends_on = [
            edge["target_operator_id"]
            for edge in item.get("edges", [])
            if edge.get("edge_type") == "depends_on" and edge["target_operator_id"] in selected_map
        ]
        requires_context = [
            edge["target_operator_id"]
            for edge in item.get("edges", [])
            if edge.get("edge_type") == "requires_context" and edge["target_operator_id"] in selected_map
        ]
        missing_preconditions = _evaluate_preconditions(item, current_env)
        missing_slots = _evaluate_slots(item)
        dependency_blockers = [
            f"Dependency `{title_lookup[dep_id]}` is not ready."
            for dep_id in [*depends_on, *requires_context]
            if status_lookup.get(dep_id) not in (None, "ready")
        ]
        missing_preconditions.extend(dependency_blockers)
        status = "ready" if not missing_preconditions and not missing_slots else "blocked"
        status_lookup[item["operator_id"]] = status
        plan_items.append(
            OperatorPlanItem(
                operator_id=item["operator_id"],
                title=item["title"],
                source_artifact=item["source_artifact"],
                score=float(item["score"]),
                status=status,
                depends_on=depends_on,
                requires_context=requires_context,
                conflicts_with=sorted(_operator_conflict_ids(item).intersection(selected_map)),
                missing_preconditions=missing_preconditions,
                missing_slots=missing_slots,
                env_match_score=float(item["env_match_score"]),
            )
        )
    readiness_summary = dict(Counter(item.status for item in plan_items))
    skills: list[SkillRefItem] = []
    seen_skill_names: set[str] = set()
    for item in ordered:
        skill_name = item["source_artifact"]
        if skill_name in seen_skill_names:
            continue
        seen_skill_names.add(skill_name)
        skills.append(
            SkillRefItem(
                name=skill_name,
                path=item.get("source_path") or "",
                url="",
            )
        )
    title = _first_sentence(query.strip().title(), "Local Wisdom Curation")
    lines = [
        "Wisdom Curation",
        "",
        f"Problem: {query}",
        "",
        f"Workflow: {title}",
        "Overview: Local graph-aware retrieval over operator procedure, context, and outcome indexes.",
        f"Readiness: {readiness_summary.get('ready', 0)} ready, {readiness_summary.get('blocked', 0)} blocked.",
        "",
        "Operator Plan:",
    ]
    for idx, item in enumerate(plan_items, 1):
        source = title_lookup.get(item.operator_id, item.title)
        operator = selected_map[item.operator_id]
        lines.append(f"{idx}. {source} — Skill: {item.source_artifact} [{item.status}]")
        lines.append(f"   Context: {operator['context']}")
        lines.append(f"   Outcome: {operator['outcome']}")
        if item.depends_on:
            lines.append(f"   Depends On: {', '.join(title_lookup[dep] for dep in item.depends_on)}")
        if item.requires_context:
            lines.append(f"   Requires Context: {', '.join(title_lookup[dep] for dep in item.requires_context)}")
        if item.missing_preconditions:
            lines.append(f"   Missing Preconditions: {'; '.join(item.missing_preconditions)}")
        if item.missing_slots:
            lines.append(f"   Missing Slots: {', '.join(item.missing_slots)}")
        if item.conflicts_with:
            lines.append(f"   Conflicts: {', '.join(title_lookup.get(dep, dep) for dep in item.conflicts_with)}")
        lines.append(f"   Score: {item.score:.3f} | Env Match: {item.env_match_score:.3f}")
    curation = "\n".join(lines) + "\n"
    result = WisdomCurateResult(
        session_id=session_id or str(uuid.uuid4()),
        query=query,
        curation=curation,
        skills=skills,
        wisdoms=[
            WisdomResultItem(
                wisdom_id=item.operator_id,
                score=float(item.score),
                is_seed=item.operator_id in seed_ids,
            )
            for item in plan_items
        ],
        operator_plan=plan_items,
        readiness_summary=readiness_summary,
        token_count=0,
        cost_usd=0.0,
    )
    store.save_curation(result)
    return result
