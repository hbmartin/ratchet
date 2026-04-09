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

from pydantic import BaseModel, Field, ValidationError

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
    pcr_payloads: list[dict[str, Any]]
    operator_payloads: list[dict[str, Any]]


@dataclass
class SessionTrace:
    turn_set: TurnSet
    keywords: list[str]
    dominant_tools: list[str]
    referenced_paths: list[str]
    referenced_env_vars: list[str]
    env_fingerprint: dict[str, Any]
    descriptor_text: str
    descriptor_embedding: list[float]
    steps: list[dict[str, Any]]
    success_steps: list[dict[str, Any]]
    error_windows: list[dict[str, Any]]
    correction_windows: list[dict[str, Any]]


@dataclass
class TraceCluster:
    cluster_id: str
    skill_name: str
    strategy_name: str
    traces: list[SessionTrace]


class _AnalystProposal(BaseModel):
    target: str
    title: str
    rule: str
    applicability: str
    evidence_session_ids: list[str] = Field(default_factory=list)
    support_count: int = 1
    examples: list[str] = Field(default_factory=list)


class _AnalystPass(BaseModel):
    proposals: list[_AnalystProposal] = Field(default_factory=list)


class _WorkflowItem(BaseModel):
    title: str
    rule: str
    evidence_session_ids: list[str] = Field(default_factory=list)
    support_count: int = 1
    examples: list[str] = Field(default_factory=list)


class _StrategySections(BaseModel):
    delta_rules: list[str] = Field(default_factory=list)
    correction_patterns: list[str] = Field(default_factory=list)
    when_to_retry: list[str] = Field(default_factory=list)
    when_to_stop: list[str] = Field(default_factory=list)
    support_signals: list[str] = Field(default_factory=list)


class _MemoryFragment(BaseModel):
    name: str
    procedure: str
    context: str
    resultant: str
    constraints: str
    evidence_session_ids: list[str] = Field(default_factory=list)
    support_count: int = 1
    kind: str = "success"


class _ConsolidatedCluster(BaseModel):
    summary: str
    applicability: list[str] = Field(default_factory=list)
    canonical_workflow: list[_WorkflowItem] = Field(default_factory=list)
    verification_loop: list[str] = Field(default_factory=list)
    failure_guards: list[str] = Field(default_factory=list)
    strategy: _StrategySections = Field(default_factory=_StrategySections)
    memory_fragments: list[_MemoryFragment] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)


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


def _collect_steps(
    turns: list[Turn],
    *,
    dedupe: bool = True,
    limit: int | None = 6,
) -> list[dict[str, Any]]:
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
                    "command": turn.command,
                    "tool_name": turn.tool_name,
                    "tool_target": turn.tool_target,
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
                    "command": turn.command,
                    "tool_name": turn.tool_name,
                    "tool_target": turn.tool_target,
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
                    "command": turn.command,
                    "tool_name": turn.tool_name,
                    "tool_target": turn.tool_target,
                }
            )
    selected = steps
    if dedupe:
        deduped: list[dict[str, Any]] = []
        seen: set[str] = set()
        for step in steps:
            key = step["label"].lower()
            if key in seen:
                continue
            seen.add(key)
            deduped.append(step)
            if limit is not None and len(deduped) >= limit:
                break
        selected = deduped
    elif limit is not None:
        selected = steps[:limit]
    if not selected:
        selected = [
            {
                "kind": "analysis",
                "label": "Review the task and implement the requested change.",
                "turn_id": 0,
                "evidence": "Derived from the session transcript.",
                "error": False,
                "command": None,
                "tool_name": None,
                "tool_target": None,
            }
        ]
    return selected


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


def _distinct_strings(values: list[str], *, limit: int | None = None) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = value.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
        if limit is not None and len(result) >= limit:
            break
    return result


def _first_user_prompt(turn_set: TurnSet) -> str:
    for turn in turn_set.turns:
        if turn.role == "user" and turn.content.strip():
            return _first_sentence(turn.content, turn.content.strip())
    return "General coding workflow."


def _session_descriptor_text(
    turn_set: TurnSet,
    *,
    keywords: list[str],
    dominant_tools: list[str],
    referenced_paths: list[str],
    steps: list[dict[str, Any]],
) -> str:
    step_labels = [step["label"] for step in steps[:6]]
    return " ".join(
        filter(
            None,
            [
                _first_user_prompt(turn_set),
                "keywords " + " ".join(keywords[:6]),
                "tools " + " ".join(dominant_tools[:4]),
                "paths " + " ".join(referenced_paths[:4]),
                "steps " + " ".join(step_labels),
            ],
        )
    )


def _build_session_trace(turn_set: TurnSet) -> SessionTrace:
    steps = _collect_steps(turn_set.turns, dedupe=False, limit=None)
    keywords = _top_keywords(turn_set.turns)
    tool_counter: Counter[str] = Counter()
    paths: list[str] = []
    env_vars: list[str] = []
    for step in steps:
        if tool := _command_tool_name(step.get("command"), step.get("tool_name")):
            tool_counter[tool] += 1
        paths.extend(_extract_paths(" ".join(filter(None, [step.get("command"), step["label"], step["evidence"]]))))
        env_vars.extend(_extract_env_vars(" ".join(filter(None, [step.get("command"), step["evidence"], step["label"]]))))
    dominant_tools = [tool for tool, _count in tool_counter.most_common(6)]
    referenced_paths = _distinct_strings(paths, limit=8)
    referenced_env_vars = _distinct_strings(env_vars, limit=8)
    env_fingerprint = _inspect_project_fingerprint(turn_set.metadata.project_path)
    env_fingerprint["branch"] = turn_set.metadata.git_branch or ""
    env_fingerprint["model"] = turn_set.metadata.model_id or ""
    env_fingerprint["required_tools"] = dominant_tools[:6]
    env_fingerprint["env_var_presence"] = {
        env_var: bool(os.environ.get(env_var)) for env_var in referenced_env_vars
    }
    error_windows: list[dict[str, Any]] = []
    correction_windows: list[dict[str, Any]] = []
    for idx, step in enumerate(steps):
        if not step["error"]:
            continue
        recovery_steps = [item for item in steps[idx + 1 : idx + 4] if not item["error"]]
        error_windows.append(
            {
                "error_step": step,
                "previous_step": steps[idx - 1] if idx > 0 else None,
                "recovery_steps": recovery_steps,
                "session_id": turn_set.session_id,
            }
        )
        if recovery_steps:
            correction_windows.append(
                {
                    "error_step": step,
                    "recovery_steps": recovery_steps,
                    "session_id": turn_set.session_id,
                }
            )
    descriptor_text = _session_descriptor_text(
        turn_set,
        keywords=keywords,
        dominant_tools=dominant_tools,
        referenced_paths=referenced_paths,
        steps=steps,
    )
    return SessionTrace(
        turn_set=turn_set,
        keywords=keywords,
        dominant_tools=dominant_tools,
        referenced_paths=referenced_paths,
        referenced_env_vars=referenced_env_vars,
        env_fingerprint=env_fingerprint,
        descriptor_text=descriptor_text,
        descriptor_embedding=[],
        steps=steps,
        success_steps=[step for step in steps if not step["error"]],
        error_windows=error_windows,
        correction_windows=correction_windows,
    )


def _build_session_traces(turnsets: list[TurnSet], llm: BaseLocalLLM) -> list[SessionTrace]:
    traces = [_build_session_trace(turn_set) for turn_set in turnsets]
    if not traces:
        return []
    embeddings = llm.embed_documents([trace.descriptor_text for trace in traces])
    for trace, embedding in zip(traces, embeddings, strict=False):
        trace.descriptor_embedding = embedding
    return traces


def _jaccard_score(left: list[str], right: list[str]) -> float:
    left_set = {item for item in left if item}
    right_set = {item for item in right if item}
    if not left_set and not right_set:
        return 0.0
    return len(left_set.intersection(right_set)) / max(len(left_set.union(right_set)), 1)


def _cluster_pair_allowed(left: SessionTrace, right: SessionTrace) -> bool:
    for key in ("language", "package_manager"):
        left_value = str(left.env_fingerprint.get(key, "")).strip()
        right_value = str(right.env_fingerprint.get(key, "")).strip()
        if left_value and right_value and left_value != right_value:
            return False
    return True


def _trace_similarity(left: SessionTrace, right: SessionTrace) -> float:
    if not _cluster_pair_allowed(left, right):
        return 0.0
    return round(
        0.6 * cosine_similarity(left.descriptor_embedding, right.descriptor_embedding)
        + 0.25 * _jaccard_score(left.dominant_tools, right.dominant_tools)
        + 0.15 * _jaccard_score(left.referenced_paths, right.referenced_paths),
        6,
    )


def _cluster_id(session_ids: list[str]) -> str:
    digest = hashlib.sha256("|".join(sorted(session_ids)).encode("utf-8")).hexdigest()
    return digest[:12]


def _cluster_keywords(traces: list[SessionTrace]) -> list[str]:
    counter: Counter[str] = Counter()
    for trace in traces:
        counter.update(trace.keywords)
    return [token for token, _count in counter.most_common(8)]


def _cluster_skill_name(traces: list[SessionTrace], cluster_id: str) -> str:
    keywords = _cluster_keywords(traces)
    project_name = Path(traces[0].turn_set.metadata.project_path or "project").name
    stem = "-".join(keywords[:3]) if keywords else sanitize_name(project_name) or "workflow"
    return sanitize_name(f"{stem}-{cluster_id[:8]}")


def _connected_components(
    traces: list[SessionTrace],
    *,
    anchor_session_id: str = "",
) -> list[list[SessionTrace]]:
    if not traces:
        return []
    trace_map = {trace.turn_set.session_id: trace for trace in traces}
    adjacency: dict[str, set[str]] = {session_id: set() for session_id in trace_map}
    similarity_cache: dict[tuple[str, str], float] = {}
    for idx, left in enumerate(traces):
        for right in traces[idx + 1 :]:
            similarity = _trace_similarity(left, right)
            similarity_cache[(left.turn_set.session_id, right.turn_set.session_id)] = similarity
            threshold = 0.72
            if anchor_session_id and anchor_session_id in {left.turn_set.session_id, right.turn_set.session_id}:
                threshold = 0.68
            if similarity < threshold:
                continue
            adjacency[left.turn_set.session_id].add(right.turn_set.session_id)
            adjacency[right.turn_set.session_id].add(left.turn_set.session_id)
    visited: set[str] = set()
    components: list[list[SessionTrace]] = []
    ordered_ids = sorted(
        trace_map,
        key=lambda session_id: (
            0 if session_id == anchor_session_id else 1,
            session_id,
        ),
    )
    for session_id in ordered_ids:
        if session_id in visited:
            continue
        stack = [session_id]
        component_ids: list[str] = []
        while stack:
            current = stack.pop()
            if current in visited:
                continue
            visited.add(current)
            component_ids.append(current)
            stack.extend(sorted(adjacency[current] - visited, reverse=True))
        component_ids.sort(key=lambda value: (0 if value == anchor_session_id else 1, value))
        components.append([trace_map[item] for item in component_ids])
    components.sort(
        key=lambda component: (
            0 if any(trace.turn_set.session_id == anchor_session_id for trace in component) else 1,
            -len(component),
            component[0].turn_set.session_id,
        )
    )
    return components


def _cluster_traces(
    traces: list[SessionTrace],
    *,
    anchor_session_id: str = "",
) -> list[TraceCluster]:
    if not traces:
        return []
    if anchor_session_id:
        anchor = next((trace for trace in traces if trace.turn_set.session_id == anchor_session_id), None)
        if anchor is None:
            raise ValueError(f"Anchor session {anchor_session_id} is not available for clustering.")
        neighbors = [
            (other, _trace_similarity(anchor, other))
            for other in traces
            if other.turn_set.session_id != anchor_session_id
        ]
        neighbors = [(trace, score) for trace, score in neighbors if score >= 0.68]
        neighbors.sort(
            key=lambda item: (
                -item[1],
                item[0].turn_set.metadata.started_at.isoformat() if item[0].turn_set.metadata.started_at else "",
                item[0].turn_set.session_id,
            )
        )
        selected_ids = {anchor_session_id, *(trace.turn_set.session_id for trace, _score in neighbors[:4])}
        traces = [trace for trace in traces if trace.turn_set.session_id in selected_ids]
    clusters: list[TraceCluster] = []
    for component in _connected_components(traces, anchor_session_id=anchor_session_id):
        session_ids = [trace.turn_set.session_id for trace in component]
        cluster_id = _cluster_id(session_ids)
        skill_name = _cluster_skill_name(component, cluster_id)
        clusters.append(
            TraceCluster(
                cluster_id=cluster_id,
                skill_name=skill_name,
                strategy_name=f"{skill_name}-strategy",
                traces=component,
            )
        )
    if anchor_session_id:
        return [
            cluster
            for cluster in clusters
            if any(trace.turn_set.session_id == anchor_session_id for trace in cluster.traces)
        ][:1]
    return clusters


def _cluster_applicability(cluster: TraceCluster) -> str:
    primary = cluster.traces[0]
    language = primary.env_fingerprint.get("language") or "local"
    package_manager = primary.env_fingerprint.get("package_manager") or "default tools"
    frameworks = ", ".join(primary.env_fingerprint.get("frameworks", []))
    if frameworks:
        return f"Use for {language} workflows in {frameworks} projects with {package_manager}."
    return f"Use for {language} project workflows with {package_manager} and the same repo-local toolchain."


def _success_target(step: dict[str, Any]) -> str:
    command = (step.get("command") or "").strip().lower()
    label = step["label"].lower()
    if command.startswith(
        (
            "pytest",
            "pnpm exec eslint",
            "pnpm exec vitest",
            "pnpm test",
            "npm test",
            "yarn test",
            "bun test",
            "cargo test",
            "go test",
            "uv run pytest",
        )
    ):
        return "verification_loop"
    if any(token in label for token in ("verify", "validation", "lint", "check", "run the auth tests")):
        return "verification_loop"
    return "canonical_workflow"


def _bucket_candidates(
    items: list[dict[str, Any]],
    *,
    cluster: TraceCluster,
    fallback_target: str,
) -> list[dict[str, Any]]:
    buckets: dict[tuple[str, str], dict[str, Any]] = {}
    for item in items:
        key = (item["target"], item["title"])
        bucket = buckets.setdefault(
            key,
            {
                "target": item["target"],
                "title": item["title"],
                "rule": item["rule"],
                "applicability": item.get("applicability") or _cluster_applicability(cluster),
                "evidence_session_ids": set(),
                "examples": [],
                "representative_step": item.get("representative_step"),
                "kind": item.get("kind", fallback_target),
                "command": item.get("command"),
                "tool_name": item.get("tool_name"),
                "tool_target": item.get("tool_target"),
            },
        )
        bucket["evidence_session_ids"].update(item.get("evidence_session_ids", []))
        bucket["examples"].extend(item.get("examples", []))
    results: list[dict[str, Any]] = []
    for bucket in buckets.values():
        evidence_session_ids = sorted(bucket["evidence_session_ids"])
        results.append(
            {
                **bucket,
                "evidence_session_ids": evidence_session_ids,
                "support_count": max(len(evidence_session_ids), 1),
                "examples": _distinct_strings(bucket["examples"], limit=3),
            }
        )
    results.sort(key=lambda item: (-item["support_count"], item["title"]))
    return results


def _success_seed_candidates(cluster: TraceCluster) -> list[dict[str, Any]]:
    raw_candidates: list[dict[str, Any]] = []
    for trace in cluster.traces:
        for step in trace.success_steps:
            raw_candidates.append(
                {
                    "target": _success_target(step),
                    "title": step["label"],
                    "rule": _step_procedure_text(step),
                    "applicability": _cluster_applicability(cluster),
                    "evidence_session_ids": [trace.turn_set.session_id],
                    "examples": [step["evidence"]],
                    "representative_step": step,
                    "kind": step["kind"],
                    "command": step.get("command"),
                    "tool_name": step.get("tool_name"),
                    "tool_target": step.get("tool_target"),
                }
            )
    candidates = _bucket_candidates(raw_candidates, cluster=cluster, fallback_target="canonical_workflow")
    return candidates[: max(8, len(cluster.traces) * 3)]


def _correction_title(window: dict[str, Any]) -> str:
    recovery_steps = window.get("recovery_steps", [])
    lowered = " ".join(step["label"].lower() for step in recovery_steps)
    if any(token in lowered for token in ("inspect", "review", "check")):
        return "Inspect failing output before retrying"
    if any(token in lowered for token in ("search", "rg", "read")):
        return "Search the affected code before retrying"
    return "Recover with new evidence before retrying"


def _error_seed_candidates(cluster: TraceCluster) -> list[dict[str, Any]]:
    raw_candidates: list[dict[str, Any]] = []
    for trace in cluster.traces:
        for window in trace.correction_windows:
            error_step = window["error_step"]
            title = _correction_title(window)
            recovery_titles = [step["label"] for step in window["recovery_steps"][:2]]
            recovery_text = " then ".join(recovery_titles) if recovery_titles else "inspect the latest evidence"
            raw_candidates.append(
                {
                    "target": "correction_patterns",
                    "title": title,
                    "rule": f"When `{error_step['label']}` fails, {recovery_text} before retrying the workflow.",
                    "applicability": _cluster_applicability(cluster),
                    "evidence_session_ids": [trace.turn_set.session_id],
                    "examples": [error_step["evidence"], *(step["evidence"] for step in window["recovery_steps"][:2])],
                    "representative_step": window["recovery_steps"][0] if window["recovery_steps"] else error_step,
                    "kind": "analysis",
                    "command": None,
                    "tool_name": None,
                    "tool_target": None,
                }
            )
            raw_candidates.append(
                {
                    "target": "when_to_retry",
                    "title": f"Retry only after new evidence from `{error_step['label']}`",
                    "rule": f"Retry `{error_step['label']}` only after inspection or search yields a concrete next action.",
                    "applicability": _cluster_applicability(cluster),
                    "evidence_session_ids": [trace.turn_set.session_id],
                    "examples": [error_step["evidence"]],
                }
            )
        for window in trace.error_windows:
            error_step = window["error_step"]
            raw_candidates.append(
                {
                    "target": "failure_guards",
                    "title": f"Do not continue past `{error_step['label']}` failures",
                    "rule": f"Do not advance the workflow after `{error_step['label']}` fails without new evidence or a fix.",
                    "applicability": _cluster_applicability(cluster),
                    "evidence_session_ids": [trace.turn_set.session_id],
                    "examples": [error_step["evidence"]],
                    "representative_step": error_step,
                    "kind": error_step["kind"],
                    "command": error_step.get("command"),
                    "tool_name": error_step.get("tool_name"),
                    "tool_target": error_step.get("tool_target"),
                }
            )
            if not window["recovery_steps"]:
                raw_candidates.append(
                    {
                        "target": "when_to_stop",
                        "title": f"Stop repeating `{error_step['label']}` without change",
                        "rule": f"Stop retrying `{error_step['label']}` when the same failure repeats without any new observation.",
                        "applicability": _cluster_applicability(cluster),
                        "evidence_session_ids": [trace.turn_set.session_id],
                        "examples": [error_step["evidence"]],
                    }
                )
    candidates = _bucket_candidates(raw_candidates, cluster=cluster, fallback_target="failure_guards")
    return candidates[: max(8, len(cluster.traces) * 4)]


def _prompt_payload(marker: str, payload: dict[str, Any], schema_hint: str) -> str:
    return (
        f"MEGA_CODE_JSON_PASS::{marker}\n"
        "Return strict JSON only. Do not include Markdown, prose, or code fences.\n"
        f"Schema: {schema_hint}\n"
        "PAYLOAD_JSON_START\n"
        f"{json.dumps(payload, indent=2, sort_keys=True)}\n"
        "PAYLOAD_JSON_END\n"
    )


def _parse_llm_json(raw_text: str, label: str, model_cls: type[BaseModel]) -> BaseModel:
    try:
        return model_cls.model_validate_json(raw_text)
    except ValidationError as exc:
        raise ValueError(f"{label} returned schema-invalid JSON: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} returned invalid JSON: {exc}") from exc


def _proposal_lookup_key(target: str, title: str) -> tuple[str, str]:
    normalized = " ".join(_tokenize(title)) or title.strip().lower()
    return target, normalized


def _run_analyst_pass(
    *,
    llm: BaseLocalLLM,
    marker: str,
    cluster: TraceCluster,
    candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    stripped_candidates = [
        {
            "target": item["target"],
            "title": item["title"],
            "rule": item["rule"],
            "applicability": item["applicability"],
            "evidence_session_ids": item["evidence_session_ids"],
            "support_count": item["support_count"],
            "examples": item["examples"],
        }
        for item in candidates
    ]
    prompt = _prompt_payload(
        marker,
        {
            "cluster_id": cluster.cluster_id,
            "member_session_ids": [trace.turn_set.session_id for trace in cluster.traces],
            "keywords": _cluster_keywords(cluster.traces),
            "candidates": stripped_candidates,
        },
        '{"proposals":[{"target":"...","title":"...","rule":"...","applicability":"...","evidence_session_ids":["..."],"support_count":1,"examples":["..."]}]}',
    )
    result = _parse_llm_json(llm.generate_text(prompt), marker, _AnalystPass)
    candidate_map = {
        _proposal_lookup_key(item["target"], item["title"]): item
        for item in candidates
    }
    proposals: list[dict[str, Any]] = []
    for proposal in result.proposals:
        payload = proposal.model_dump()
        if source := candidate_map.get(_proposal_lookup_key(payload["target"], payload["title"])):
            payload.update(
                {
                    "representative_step": source.get("representative_step"),
                    "kind": source.get("kind", "analysis"),
                    "command": source.get("command"),
                    "tool_name": source.get("tool_name"),
                    "tool_target": source.get("tool_target"),
                }
            )
        proposals.append(payload)
    return proposals


def _group_proposals(proposals: list[dict[str, Any]], llm: BaseLocalLLM) -> list[dict[str, Any]]:
    if not proposals:
        return []
    embeddings = llm.embed_documents([f"{item['target']} {item['title']} {item['rule']}" for item in proposals])
    ranked_indexes = sorted(
        range(len(proposals)),
        key=lambda idx: (-int(proposals[idx].get("support_count", 1)), proposals[idx]["title"]),
    )
    assigned: set[int] = set()
    groups: list[dict[str, Any]] = []
    for idx in ranked_indexes:
        if idx in assigned:
            continue
        primary = proposals[idx]
        group_indexes = [idx]
        assigned.add(idx)
        for other_idx in ranked_indexes:
            if other_idx in assigned:
                continue
            other = proposals[other_idx]
            if primary["target"] != other["target"]:
                continue
            same_title = _proposal_lookup_key(primary["target"], primary["title"]) == _proposal_lookup_key(
                other["target"], other["title"]
            )
            if same_title or cosine_similarity(embeddings[idx], embeddings[other_idx]) >= 0.84:
                group_indexes.append(other_idx)
                assigned.add(other_idx)
        grouped_items = [proposals[item_idx] for item_idx in group_indexes]
        grouped_items.sort(
            key=lambda item: (-int(item.get("support_count", 1)), -len(item["rule"]), item["title"])
        )
        representative = grouped_items[0]
        evidence_ids = _distinct_strings(
            [session_id for item in grouped_items for session_id in item.get("evidence_session_ids", [])]
        )
        groups.append(
            {
                **representative,
                "evidence_session_ids": evidence_ids,
                "support_count": max(len(evidence_ids), max(int(item.get("support_count", 1)) for item in grouped_items)),
                "examples": _distinct_strings(
                    [example for item in grouped_items for example in item.get("examples", [])],
                    limit=4,
                ),
            }
        )
    groups.sort(key=lambda item: (-int(item.get("support_count", 1)), item["target"], item["title"]))
    return groups


def _default_memory_fragments(grouped_proposals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    fragments: list[dict[str, Any]] = []
    for proposal in grouped_proposals:
        kind = "error" if proposal["target"] in {"failure_guards", "correction_patterns", "when_to_retry", "when_to_stop"} else "success"
        fragments.append(
            {
                "name": proposal["title"],
                "procedure": proposal["rule"],
                "context": proposal["applicability"],
                "resultant": "Apply the repeated workflow reliably." if kind == "success" else "Avoid repeating the same failure pattern.",
                "constraints": "Ground the action in observed evidence from related sessions.",
                "evidence_session_ids": proposal.get("evidence_session_ids", []),
                "support_count": proposal.get("support_count", 1),
                "kind": kind,
            }
        )
    return fragments


def _run_consolidator_pass(
    *,
    llm: BaseLocalLLM,
    cluster: TraceCluster,
    grouped_proposals: list[dict[str, Any]],
) -> _ConsolidatedCluster:
    primary = cluster.traces[0]
    prompt = _prompt_payload(
        "CONSOLIDATOR",
        {
            "cluster_id": cluster.cluster_id,
            "skill_name": cluster.skill_name,
            "member_session_ids": [trace.turn_set.session_id for trace in cluster.traces],
            "keywords": _cluster_keywords(cluster.traces),
            "dominant_tools": _distinct_strings(
                [tool for trace in cluster.traces for tool in trace.dominant_tools],
                limit=8,
            ),
            "applicability_hints": [
                _cluster_applicability(cluster),
                f"Primary task pattern: {_first_user_prompt(primary.turn_set)}",
            ],
            "grouped_proposals": [
                {
                    "target": item["target"],
                    "title": item["title"],
                    "rule": item["rule"],
                    "applicability": item["applicability"],
                    "evidence_session_ids": item["evidence_session_ids"],
                    "support_count": item["support_count"],
                    "examples": item["examples"],
                }
                for item in grouped_proposals
            ],
        },
        '{"summary":"...","applicability":["..."],"canonical_workflow":[{"title":"...","rule":"...","evidence_session_ids":["..."],"support_count":1,"examples":["..."]}],"verification_loop":["..."],"failure_guards":["..."],"strategy":{"delta_rules":["..."],"correction_patterns":["..."],"when_to_retry":["..."],"when_to_stop":["..."],"support_signals":["..."]},"memory_fragments":[{"name":"...","procedure":"...","context":"...","resultant":"...","constraints":"...","evidence_session_ids":["..."],"support_count":1,"kind":"success"}],"keywords":["..."]}',
    )
    result = _parse_llm_json(llm.generate_text(prompt), "CONSOLIDATOR", _ConsolidatedCluster)
    consolidated = result.model_copy(deep=True)
    if not consolidated.applicability:
        consolidated.applicability = [_cluster_applicability(cluster)]
    if not consolidated.canonical_workflow:
        consolidated.canonical_workflow = [
            _WorkflowItem(
                title=item["title"],
                rule=item["rule"],
                evidence_session_ids=item.get("evidence_session_ids", []),
                support_count=item.get("support_count", 1),
                examples=item.get("examples", []),
            )
            for item in grouped_proposals
            if item["target"] == "canonical_workflow"
        ][:6]
    if not consolidated.memory_fragments:
        consolidated.memory_fragments = [_MemoryFragment.model_validate(item) for item in _default_memory_fragments(grouped_proposals)]
    if not consolidated.keywords:
        consolidated.keywords = _cluster_keywords(cluster.traces)
    return consolidated


def _cluster_env_fingerprint(cluster: TraceCluster) -> dict[str, Any]:
    primary = cluster.traces[0]
    language = next((trace.env_fingerprint.get("language") for trace in cluster.traces if trace.env_fingerprint.get("language")), "")
    package_manager = next(
        (trace.env_fingerprint.get("package_manager") for trace in cluster.traces if trace.env_fingerprint.get("package_manager")),
        "",
    )
    branch_counts: Counter[str] = Counter(
        trace.env_fingerprint.get("branch", "") for trace in cluster.traces if trace.env_fingerprint.get("branch")
    )
    model_counts: Counter[str] = Counter(
        trace.env_fingerprint.get("model", "") for trace in cluster.traces if trace.env_fingerprint.get("model")
    )
    frameworks = _distinct_strings(
        [framework for trace in cluster.traces for framework in trace.env_fingerprint.get("frameworks", [])],
        limit=6,
    )
    env_vars = _distinct_strings(
        [env_var for trace in cluster.traces for env_var in trace.referenced_env_vars],
        limit=8,
    )
    return {
        "project_path": primary.turn_set.metadata.project_path or "",
        "language": language or primary.env_fingerprint.get("language", ""),
        "frameworks": frameworks,
        "package_manager": package_manager or primary.env_fingerprint.get("package_manager", ""),
        "branch": branch_counts.most_common(1)[0][0] if branch_counts else primary.env_fingerprint.get("branch", ""),
        "model": model_counts.most_common(1)[0][0] if model_counts else primary.env_fingerprint.get("model", ""),
        "required_tools": _distinct_strings(
            [tool for trace in cluster.traces for tool in trace.dominant_tools],
            limit=8,
        ),
        "env_var_presence": {env_var: bool(os.environ.get(env_var)) for env_var in env_vars},
    }


def _workflow_step_lookup(grouped_proposals: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    lookup: dict[tuple[str, str], dict[str, Any]] = {}
    for proposal in grouped_proposals:
        lookup[_proposal_lookup_key("canonical_workflow", proposal["title"])] = proposal
        lookup[_proposal_lookup_key(proposal["target"], proposal["title"])] = proposal
    return lookup


def _operator_steps_from_consolidated(
    consolidated: _ConsolidatedCluster,
    grouped_proposals: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    lookup = _workflow_step_lookup(grouped_proposals)
    steps: list[dict[str, Any]] = []
    for item in consolidated.canonical_workflow[:8]:
        candidate = lookup.get(_proposal_lookup_key("canonical_workflow", item.title)) or lookup.get(
            _proposal_lookup_key("verification_loop", item.title)
        )
        representative = candidate or {}
        step = representative.get("representative_step") or {}
        steps.append(
            {
                "kind": step.get("kind", "analysis"),
                "label": item.title,
                "turn_id": 0,
                "evidence": item.examples[0] if item.examples else step.get("evidence", item.rule),
                "error": False,
                "command": representative.get("command") or step.get("command"),
                "tool_name": representative.get("tool_name") or step.get("tool_name"),
                "tool_target": representative.get("tool_target") or step.get("tool_target"),
            }
        )
    if not steps:
        steps.append(
            {
                "kind": "analysis",
                "label": "Review the clustered workflow before making changes.",
                "turn_id": 0,
                "evidence": "Derived from repeated project trajectories.",
                "error": False,
                "command": None,
                "tool_name": None,
                "tool_target": None,
            }
        )
    return steps


def _cluster_evidence_items(cluster: TraceCluster, grouped_proposals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    proposal_titles = [proposal["title"] for proposal in grouped_proposals[:6]]
    items: list[dict[str, Any]] = []
    for trace in cluster.traces:
        items.append(
            {
                "session_id": trace.turn_set.session_id,
                "prompt": _first_user_prompt(trace.turn_set),
                "dominant_tools": trace.dominant_tools[:4],
                "referenced_paths": trace.referenced_paths[:4],
                "error_count": len(trace.error_windows),
                "correction_count": len(trace.correction_windows),
                "evidence": proposal_titles[:4],
            }
        )
    return items


def _build_cluster_skill_markdown(
    *,
    cluster: TraceCluster,
    consolidated: _ConsolidatedCluster,
    keywords: list[str],
    metadata: dict[str, Any],
) -> str:
    project_name = Path(cluster.traces[0].turn_set.metadata.project_path or "project").name
    body_lines = [
        "---",
        f"name: {cluster.skill_name}",
        f'description: "Clustered workflow distilled from {len(cluster.traces)} related sessions for {project_name}."',
        "metadata:",
        f"  tags: [{', '.join(keywords[:4])}]",
        f'  author: "{get_author()}"',
        f'  version: "{DEFAULT_VERSION}"',
        f'  generated_at: "{datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")}"',
        f'  cluster_id: "{cluster.cluster_id}"',
        "---",
        "",
        "# Summary",
        consolidated.summary,
        "",
        "## Applicability",
    ]
    body_lines.extend(f"- {item}" for item in consolidated.applicability)
    body_lines.extend(["", "## Canonical Workflow"])
    for idx, item in enumerate(consolidated.canonical_workflow, 1):
        support = ", ".join(item.evidence_session_ids[:3]) or "cluster"
        body_lines.append(f"{idx}. {item.title}")
        body_lines.append(f"   Rule: {item.rule}")
        body_lines.append(f"   Support: {item.support_count} sessions ({support})")
        if item.examples:
            body_lines.append(f"   Example: {item.examples[0]}")
    body_lines.extend(["", "## Verification Loop"])
    if consolidated.verification_loop:
        body_lines.extend(f"- {item}" for item in consolidated.verification_loop)
    else:
        body_lines.append("- Verify each material change before finalizing.")
    body_lines.extend(["", "## Failure Guards"])
    if consolidated.failure_guards:
        body_lines.extend(f"- {item}" for item in consolidated.failure_guards)
    else:
        body_lines.append("- Stop when the workflow stops producing new evidence.")
    body_lines.extend(
        [
            "",
            "## Cluster Evidence",
            f"- Sessions: {', '.join(metadata['member_session_ids'])}",
            f"- Dominant tools: {', '.join(metadata['dominant_tools']) or 'none'}",
            f"- Error rate: {metadata['error_rate']:.3f}",
            f"- Corrections observed: {metadata['correction_count']}",
        ]
    )
    return "\n".join(body_lines) + "\n"


def _build_cluster_strategy_markdown(
    *,
    cluster: TraceCluster,
    consolidated: _ConsolidatedCluster,
    metadata: dict[str, Any],
) -> str:
    heading = f"# {cluster.skill_name.replace('-', ' ').title()} Strategy"
    lines = [heading, "", "## Delta Rules"]
    delta_rules = _distinct_strings(consolidated.strategy.delta_rules, limit=8)
    if delta_rules:
        lines.extend(f"- {item}" for item in delta_rules)
    else:
        lines.append("- Preserve the clustered workflow and only retry after new evidence appears.")
    lines.extend(["", "## Correction Patterns"])
    if consolidated.strategy.correction_patterns:
        lines.extend(f"- {item}" for item in consolidated.strategy.correction_patterns)
    else:
        lines.append("- Inspect the latest failure evidence before patching again.")
    lines.extend(["", "## When To Retry"])
    if consolidated.strategy.when_to_retry:
        lines.extend(f"- {item}" for item in consolidated.strategy.when_to_retry)
    else:
        lines.append("- Retry after inspection produces a concrete next step.")
    lines.extend(["", "## When To Stop"])
    if consolidated.strategy.when_to_stop:
        lines.extend(f"- {item}" for item in consolidated.strategy.when_to_stop)
    else:
        lines.append("- Stop repeating the same action when it produces no new evidence.")
    lines.extend(["", "## Support Signals"])
    support_signals = consolidated.strategy.support_signals or consolidated.verification_loop
    if support_signals:
        lines.extend(f"- {item}" for item in support_signals)
    else:
        lines.append("- Use the project verification command as the readiness signal.")
    lines.extend(
        [
            "",
            "## Cluster Evidence",
            f"- Cluster: `{cluster.cluster_id}`",
            f"- Sessions: {len(cluster.traces)}",
            f"- Corrections observed: {metadata['correction_count']}",
        ]
    )
    return "\n".join(lines) + "\n"


def _build_pcr_payloads(
    *,
    llm: BaseLocalLLM,
    cluster: TraceCluster,
    artifact_id: str,
    skill_name: str,
    memory_fragments: list[_MemoryFragment],
) -> list[dict[str, Any]]:
    if not memory_fragments:
        return []
    lexical_texts = [
        " ".join(
            [
                fragment.name,
                fragment.procedure,
                fragment.context,
                fragment.resultant,
                fragment.constraints,
                skill_name,
            ]
        )
        for fragment in memory_fragments
    ]
    embeddings = llm.embed_documents(lexical_texts)
    payloads: list[dict[str, Any]] = []
    for idx, fragment in enumerate(memory_fragments, 1):
        payloads.append(
            {
                "fragment_id": _stable_id(artifact_id, "fragment", idx, fragment.name),
                "artifact_id": artifact_id,
                "name": fragment.name,
                "procedure": fragment.procedure,
                "context": fragment.context,
                "resultant": fragment.resultant,
                "constraints": fragment.constraints,
                "evidence_refs": [{"session_id": session_id} for session_id in fragment.evidence_session_ids],
                "source_artifact": skill_name,
                "dependency_ids": [],
                "feedback_score": 0.0,
                "created_at": utcnow_iso(),
                "embedding": embeddings[idx - 1],
                "lexical_text": lexical_texts[idx - 1],
            }
        )
    return payloads


def distill_cluster(
    *,
    run_id: str,
    project_id: str,
    cluster: TraceCluster,
    llm: BaseLocalLLM,
    store: LocalStore,
) -> SessionArtifacts:
    keywords = _cluster_keywords(cluster.traces)
    success_candidates = _success_seed_candidates(cluster)
    error_candidates = _error_seed_candidates(cluster)
    success_proposals = _run_analyst_pass(
        llm=llm,
        marker="SUCCESS_ANALYST",
        cluster=cluster,
        candidates=success_candidates,
    )
    error_proposals = _run_analyst_pass(
        llm=llm,
        marker="ERROR_ANALYST",
        cluster=cluster,
        candidates=error_candidates,
    )
    grouped_proposals = _group_proposals([*success_proposals, *error_proposals], llm)
    consolidated = _run_consolidator_pass(llm=llm, cluster=cluster, grouped_proposals=grouped_proposals)
    env_fingerprint = _cluster_env_fingerprint(cluster)
    error_count = sum(len(trace.error_windows) for trace in cluster.traces)
    total_steps = sum(len(trace.steps) for trace in cluster.traces) or 1
    correction_count = sum(len(trace.correction_windows) for trace in cluster.traces)
    metadata = {
        "generated_at": utcnow_iso(),
        "workflow": {
            "domains": keywords[:4],
            "cluster_id": cluster.cluster_id,
        },
        "pcr_model": "procedure-context-resultant",
        "cluster_id": cluster.cluster_id,
        "member_session_ids": [trace.turn_set.session_id for trace in cluster.traces],
        "support_count": len(cluster.traces),
        "error_rate": round(error_count / total_steps, 6),
        "correction_count": correction_count,
        "dominant_tools": _distinct_strings(
            [tool for trace in cluster.traces for tool in trace.dominant_tools],
            limit=8,
        ),
        "analyst_summaries": {
            "success_titles": [item["title"] for item in success_proposals[:4]],
            "error_titles": [item["title"] for item in error_proposals[:4]],
            "grouped_titles": [item["title"] for item in grouped_proposals[:6]],
        },
    }
    skill_md = _build_cluster_skill_markdown(
        cluster=cluster,
        consolidated=consolidated,
        keywords=keywords,
        metadata=metadata,
    )
    strategy_md = _build_cluster_strategy_markdown(
        cluster=cluster,
        consolidated=consolidated,
        metadata=metadata,
    )
    evidence_items = _cluster_evidence_items(cluster, grouped_proposals)
    injection_rules = {
        "mode": "local",
        "cluster_id": cluster.cluster_id,
        "trigger_keywords": keywords[:6],
        "project_path": cluster.traces[0].turn_set.metadata.project_path or "",
    }
    artifact_embedding = llm.embed_documents([skill_md + "\n" + strategy_md])[0]
    skill_artifact_id = _artifact_id(run_id, cluster.cluster_id, "skill", cluster.skill_name)
    skill_source_path = store.write_source_tree(
        artifact_type="skill",
        name=cluster.skill_name,
        content=skill_md,
    )
    strategy_artifact_id = _artifact_id(run_id, cluster.cluster_id, "strategy", cluster.strategy_name)
    strategy_source_path = store.write_source_tree(
        artifact_type="strategy",
        name=cluster.strategy_name,
        content=strategy_md,
    )
    pending_skill = PendingSkillData(
        skill_name=cluster.skill_name,
        skill_md=skill_md,
        injection_rules=json.dumps(injection_rules, indent=2),
        evidence=json.dumps(evidence_items, indent=2),
        metadata=json.dumps(metadata, indent=2),
        author=get_author(),
        version=DEFAULT_VERSION,
        tags=keywords[:4],
    )
    pending_strategy = PendingStrategyData(
        strategy_name=cluster.strategy_name,
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
            "name": cluster.skill_name,
            "version": DEFAULT_VERSION,
            "content": skill_md,
            "metadata": metadata,
            "source_path": skill_source_path,
            "session_id": cluster.cluster_id,
            "created_at": utcnow_iso(),
            "embedding": artifact_embedding,
        },
        {
            "artifact_id": strategy_artifact_id,
            "artifact_type": "strategy",
            "name": cluster.strategy_name,
            "version": DEFAULT_VERSION,
            "content": strategy_md,
            "metadata": metadata,
            "source_path": strategy_source_path,
            "session_id": cluster.cluster_id,
            "created_at": utcnow_iso(),
            "embedding": artifact_embedding,
        },
    ]
    pcr_payloads = _build_pcr_payloads(
        llm=llm,
        cluster=cluster,
        artifact_id=skill_artifact_id,
        skill_name=cluster.skill_name,
        memory_fragments=consolidated.memory_fragments,
    )
    operator_steps = _operator_steps_from_consolidated(consolidated, grouped_proposals)
    context_text = _build_context_text(cluster.traces[0].turn_set, env_fingerprint)
    operator_payloads = _operator_payloads(
        run_id=run_id,
        project_id=project_id,
        session_id=cluster.traces[0].turn_set.session_id,
        artifact_id=skill_artifact_id,
        skill_name=cluster.skill_name,
        turn_set=cluster.traces[0].turn_set,
        steps=operator_steps,
        llm=llm,
        context_text=context_text,
        env_fingerprint=env_fingerprint,
    )
    return SessionArtifacts(
        pending_skill=pending_skill,
        pending_strategy=pending_strategy,
        artifact_payloads=artifact_payloads,
        pcr_payloads=pcr_payloads,
        operator_payloads=operator_payloads,
    )


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
        pcr_payloads=[],
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
        anchor = _load_turnset_from_session_id(session_id, store)
        related_turnsets = [anchor]
        anchor_project_path = anchor.metadata.project_path or project_path
        if anchor_project_path:
            sessions = load_sessions_from_project(
                Path(anchor_project_path),
                include_claude=include_claude,
                include_codex=include_codex,
                limit=limit,
            )
            seen = {anchor.session_id}
            for session in sessions:
                turn_set = _session_to_turnset(session)
                if turn_set is None or turn_set.session_id in seen:
                    continue
                seen.add(turn_set.session_id)
                related_turnsets.append(turn_set)
        return related_turnsets
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
    store.update_progress(
        run_id,
        phase="tracing",
        processed=0,
        total=len(turnsets),
        clusters_processed=0,
        clusters_total=0,
    )
    traces = _build_session_traces(turnsets, llm)
    clusters = _cluster_traces(traces, anchor_session_id=config.get("session_id") or "")
    store.update_progress(
        run_id,
        phase="clustering",
        processed=len(turnsets),
        total=len(turnsets),
        clusters_processed=0,
        clusters_total=len(clusters),
    )
    pending_skills: list[PendingSkillData] = []
    pending_strategies: list[PendingStrategyData] = []
    artifact_payloads: list[dict[str, Any]] = []
    pcr_payloads: list[dict[str, Any]] = []
    operator_payloads: list[dict[str, Any]] = []
    processed_sessions = 0
    for idx, cluster in enumerate(clusters, 1):
        if store.is_stop_requested(run_id):
            raise RuntimeError("Pipeline stop requested.")
        artifacts = distill_cluster(
            run_id=run_id,
            project_id=config["project_id"],
            cluster=cluster,
            llm=llm,
            store=store,
        )
        pending_skills.append(artifacts.pending_skill)
        pending_strategies.append(artifacts.pending_strategy)
        artifact_payloads.extend(artifacts.artifact_payloads)
        pcr_payloads.extend(artifacts.pcr_payloads)
        operator_payloads.extend(artifacts.operator_payloads)
        processed_sessions += len(cluster.traces)
        store.update_progress(
            run_id,
            phase="distilling",
            processed=processed_sessions,
            total=len(turnsets),
            clusters_processed=idx,
            clusters_total=len(clusters),
        )
    store.save_artifacts(
        run_id=run_id,
        project_id=config["project_id"],
        session_id=config.get("session_id") or "",
        artifact_payloads=artifact_payloads,
        pcr_payloads=pcr_payloads,
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


def _ranked_ids(scores: dict[str, float], *, limit: int | None = None) -> list[str]:
    ranked = sorted(scores, key=scores.get, reverse=True)
    return ranked[:limit] if limit is not None else ranked


def _rrf_fuse(rankings: list[list[str]], *, rank_constant: int = 60) -> dict[str, float]:
    fused: defaultdict[str, float] = defaultdict(float)
    for ranking in rankings:
        for rank, operator_id in enumerate(ranking, 1):
            fused[operator_id] += 1.0 / (rank_constant + rank)
    if not fused:
        return {}
    max_score = max(fused.values()) or 1.0
    return {operator_id: round(score / max_score, 6) for operator_id, score in fused.items()}


def _structural_dependency_ids(operator: dict[str, Any], selected_ids: set[str] | None = None) -> list[str]:
    ids: list[str] = []
    for edge in operator.get("edges", []):
        if edge.get("edge_type") not in {"depends_on", "requires_context"}:
            continue
        target_id = edge["target_operator_id"]
        if selected_ids is not None and target_id not in selected_ids:
            continue
        ids.append(target_id)
    return ids


def _operator_contextual_text(operator: dict[str, Any], operator_map: dict[str, dict[str, Any]]) -> str:
    depends_on = [
        operator_map[target_id]["title"]
        for target_id in _structural_dependency_ids(operator)
        if target_id in operator_map
    ]
    requires_context = [
        operator_map[edge["target_operator_id"]]["title"]
        for edge in operator.get("edges", [])
        if edge.get("edge_type") == "requires_context" and edge["target_operator_id"] in operator_map
    ]
    parts = [
        operator.get("title", ""),
        operator.get("source_artifact", ""),
        operator.get("normalized_intent", ""),
        operator["indexes"]["procedure"].get("lexical_text", ""),
        operator["indexes"]["context"].get("lexical_text", ""),
        operator["indexes"]["outcome"].get("lexical_text", ""),
        operator["env_fingerprint"].get("lexical_text", ""),
    ]
    if depends_on:
        parts.append("depends_on " + " ".join(depends_on))
    if requires_context:
        parts.append("requires_context " + " ".join(requires_context))
    return " ".join(part for part in parts if part)


def _contextual_candidate_scores(
    *,
    query_tokens: list[str],
    operators: list[dict[str, Any]],
    operator_map: dict[str, dict[str, Any]],
) -> dict[str, float]:
    docs = [_tokenize(_operator_contextual_text(item, operator_map)) for item in operators]
    lexical_scores = normalize_scores(_bm25_scores(query_tokens, docs))
    return {
        item["operator_id"]: round(lexical_scores[idx], 6)
        for idx, item in enumerate(operators)
    }


def _personalized_pagerank(
    *,
    seed_scores: dict[str, float],
    operator_map: dict[str, dict[str, Any]],
    allowed_ids: set[str],
    alpha: float = 0.82,
    max_iter: int = 40,
    tol: float = 1e-6,
) -> dict[str, float]:
    if not allowed_ids:
        return {}
    ordered_ids = sorted(allowed_ids)
    personalized = {operator_id: max(seed_scores.get(operator_id, 0.0), 0.0) for operator_id in allowed_ids}
    total_personalized = sum(personalized.values())
    if total_personalized <= 0:
        uniform = 1.0 / len(allowed_ids)
        personalized = dict.fromkeys(allowed_ids, uniform)
    else:
        personalized = {
            operator_id: score / total_personalized
            for operator_id, score in personalized.items()
        }
    scores = dict(personalized)
    edge_weights = {"depends_on": 1.0, "requires_context": 0.85}
    outgoing: dict[str, list[tuple[str, float]]] = {}
    for operator_id in allowed_ids:
        neighbors: list[tuple[str, float]] = []
        for edge in operator_map[operator_id].get("edges", []):
            if edge.get("edge_type") not in edge_weights:
                continue
            target_id = edge["target_operator_id"]
            if target_id not in allowed_ids:
                continue
            neighbors.append((target_id, edge_weights[edge["edge_type"]]))
        outgoing[operator_id] = neighbors
    for _ in range(max_iter):
        next_scores = {
            operator_id: (1.0 - alpha) * personalized[operator_id]
            for operator_id in allowed_ids
        }
        for operator_id, value in scores.items():
            neighbors = outgoing[operator_id]
            if not neighbors:
                next_scores[operator_id] += alpha * value
                continue
            total_weight = sum(weight for _target_id, weight in neighbors) or 1.0
            for target_id, weight in neighbors:
                next_scores[target_id] += alpha * value * (weight / total_weight)
        delta = sum(abs(next_scores[operator_id] - scores[operator_id]) for operator_id in allowed_ids)
        scores = next_scores
        if delta <= tol:
            break
    normalized = normalize_scores([scores[operator_id] for operator_id in ordered_ids])
    return {operator_id: round(normalized[idx], 6) for idx, operator_id in enumerate(ordered_ids)}


def _expand_dependency_closure(
    seed_ids: list[str],
    *,
    operator_map: dict[str, dict[str, Any]],
    allowed_ids: set[str],
) -> set[str]:
    selected_ids = {operator_id for operator_id in seed_ids if operator_id in allowed_ids}
    stack = list(selected_ids)
    while stack:
        operator_id = stack.pop()
        for target_id in _structural_dependency_ids(operator_map[operator_id]):
            if target_id not in allowed_ids or target_id in selected_ids:
                continue
            selected_ids.add(target_id)
            stack.append(target_id)
    return selected_ids


def _incoming_structural_support(
    selected_ids: set[str],
    operator_map: dict[str, dict[str, Any]],
) -> dict[str, list[tuple[str, str]]]:
    support: dict[str, list[tuple[str, str]]] = {operator_id: [] for operator_id in selected_ids}
    for operator_id in selected_ids:
        for edge in operator_map[operator_id].get("edges", []):
            if edge.get("edge_type") not in {"depends_on", "requires_context"}:
                continue
            target_id = edge["target_operator_id"]
            if target_id not in selected_ids:
                continue
            support[target_id].append((operator_id, edge["edge_type"]))
    return support


def _topological_waves(
    *,
    selected_ids: set[str],
    operator_map: dict[str, dict[str, Any]],
    score_lookup: dict[str, dict[str, float]],
) -> list[list[str]]:
    dependents: defaultdict[str, list[str]] = defaultdict(list)
    indegree: dict[str, int] = dict.fromkeys(selected_ids, 0)
    for operator_id in selected_ids:
        for target_id in _structural_dependency_ids(operator_map[operator_id], selected_ids):
            indegree[operator_id] += 1
            dependents[target_id].append(operator_id)
    frontier = [
        operator_id
        for operator_id, degree in indegree.items()
        if degree == 0
    ]
    frontier.sort(key=lambda operator_id: score_lookup.get(operator_id, {}).get("score", 0.0), reverse=True)
    waves: list[list[str]] = []
    visited: set[str] = set()
    while frontier:
        wave = list(frontier)
        waves.append(wave)
        frontier = []
        for operator_id in wave:
            visited.add(operator_id)
            for dependent_id in dependents.get(operator_id, []):
                indegree[dependent_id] -= 1
                if indegree[dependent_id] == 0:
                    frontier.append(dependent_id)
        frontier.sort(key=lambda operator_id: score_lookup.get(operator_id, {}).get("score", 0.0), reverse=True)
    remaining = [
        operator_id
        for operator_id in selected_ids
        if operator_id not in visited
    ]
    if remaining:
        remaining.sort(key=lambda operator_id: score_lookup.get(operator_id, {}).get("score", 0.0), reverse=True)
        waves.append(remaining)
    return waves


def _minimal_context_package(operator: dict[str, Any]) -> list[str]:
    return [
        f"Do: {_first_sentence(operator['procedure'], operator['title'])}",
        f"Context: {_snippet(operator['context'], 140)}",
        f"Done when: {_snippet(operator['outcome'], 140)}",
    ]


def _inclusion_reason(
    operator_id: str,
    *,
    seed_ids: set[str],
    incoming_support: dict[str, list[tuple[str, str]]],
    title_lookup: dict[str, str],
) -> str:
    if operator_id in seed_ids:
        return "Direct hybrid seed from semantic, lexical, and contextual retrieval."
    supporters = incoming_support.get(operator_id, [])
    context_parents = [title_lookup[parent_id] for parent_id, edge_type in supporters if edge_type == "requires_context"]
    dependency_parents = [title_lookup[parent_id] for parent_id, edge_type in supporters if edge_type == "depends_on"]
    if context_parents:
        return f"Context prerequisite recovered for {', '.join(context_parents[:2])}."
    if dependency_parents:
        return f"Dependency recovered for {', '.join(dependency_parents[:2])}."
    return "Recovered by structural diffusion and reranking."


def _clamp(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, value))


def _current_prediction_metrics(
    *,
    operator: dict[str, Any],
    seed_score: float,
    structural_score: float,
    facet_score: float,
    contextual_score: float,
    env_match_score: float,
    support_score: float,
    dependency_penalty: float,
) -> dict[str, float | bool | str]:
    reliability = operator.get("reliability") or {}
    prior_success = float(reliability.get("prior_success", 0.5))
    prior_confidence = float(reliability.get("confidence", 0.35))
    empirical_reliability = float(reliability.get("empirical_reliability", 0.0))
    abstain_probability = float(reliability.get("abstain_probability", 0.0))
    retrieval_signal = _clamp(
        0.38 * seed_score
        + 0.18 * structural_score
        + 0.14 * facet_score
        + 0.10 * contextual_score
        + 0.12 * env_match_score
        + 0.08 * support_score
    )
    dependency_stability = _clamp(1.0 - min(dependency_penalty * 12.0, 0.8))
    predicted_success = _clamp(0.55 * retrieval_signal + 0.45 * prior_success)
    confidence = _clamp(
        0.45 * prior_confidence + 0.35 * retrieval_signal + 0.20 * dependency_stability,
        lower=0.05,
        upper=0.99,
    )
    current_abstain_probability = _clamp(
        0.65 * abstain_probability
        + max(0.0, 0.52 - predicted_success)
        + max(0.0, 0.45 - confidence) * 0.8
        + max(0.0, 0.55 - env_match_score) * 0.2,
        lower=0.0,
        upper=0.99,
    )
    should_abstain = bool(current_abstain_probability >= 0.55)
    if not should_abstain:
        abstain_reason = ""
    elif predicted_success < 0.45:
        abstain_reason = "Low predicted success given current retrieval evidence."
    elif confidence < 0.45:
        abstain_reason = "Not enough calibrated evidence to recommend this step confidently."
    elif env_match_score < 0.55:
        abstain_reason = "Environment match is too weak for a strong recommendation."
    else:
        abstain_reason = "Historical feedback indicates this step should be treated cautiously."
    reliability_boost = (
        (predicted_success - 0.5) * 0.16
        + empirical_reliability * 0.08
        + (confidence - 0.5) * 0.04
        - current_abstain_probability * 0.12
    )
    return {
        "predicted_success": round(predicted_success, 6),
        "confidence": round(confidence, 6),
        "abstain_probability": round(current_abstain_probability, 6),
        "should_abstain": should_abstain,
        "abstain_reason": abstain_reason,
        "reliability_boost": round(reliability_boost, 6),
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
            confidence=0.0,
            should_abstain=True,
            abstain_reason="No operator graph data is available yet.",
            token_count=0,
            cost_usd=0.0,
        )
        store.save_curation(result)
        return result
    current_env = _current_runtime_fingerprint(query)
    operator_map = {item["operator_id"]: item for item in operators}
    superseded_ids = {
        edge["target_operator_id"]
        for item in operators
        for edge in item.get("edges", [])
        if edge.get("edge_type") == "supersedes"
    }
    eligible_operators = [
        item for item in operators if item["operator_id"] not in superseded_ids
    ]
    eligible_ids = {item["operator_id"] for item in eligible_operators}
    query_tokens = _tokenize(query)
    procedure_scores = _facet_candidate_scores(
        query_embedding=query_embedding,
        query_tokens=query_tokens,
        operators=eligible_operators,
        facet_name="procedure",
    )
    context_scores = _facet_candidate_scores(
        query_embedding=query_embedding,
        query_tokens=query_tokens,
        operators=eligible_operators,
        facet_name="context",
    )
    outcome_scores = _facet_candidate_scores(
        query_embedding=query_embedding,
        query_tokens=query_tokens,
        operators=eligible_operators,
        facet_name="outcome",
    )
    contextual_scores = _contextual_candidate_scores(
        query_tokens=query_tokens,
        operators=eligible_operators,
        operator_map=operator_map,
    )
    seed_candidate_budget = min(max(top_k * 2, 5), len(eligible_operators))
    seed_rankings = [
        _ranked_ids(procedure_scores, limit=seed_candidate_budget),
        _ranked_ids(context_scores, limit=seed_candidate_budget),
        _ranked_ids(outcome_scores, limit=seed_candidate_budget),
        _ranked_ids(contextual_scores, limit=seed_candidate_budget),
    ]
    seed_scores = _rrf_fuse(seed_rankings)
    seed_count = min(max(top_k, 1), 6, len(seed_scores) or 1)
    seed_ids = set(_ranked_ids(seed_scores, limit=seed_count))
    structural_scores = _personalized_pagerank(
        seed_scores=seed_scores,
        operator_map=operator_map,
        allowed_ids=eligible_ids,
    )
    diffusion_budget = min(max(top_k * 3, 6), len(eligible_operators))
    structural_floor = max(0.08, max(structural_scores.values(), default=0.0) * 0.3)
    frontier_ids: list[str] = []
    for operator_id in _ranked_ids(structural_scores):
        if operator_id in seed_ids:
            continue
        if structural_scores.get(operator_id, 0.0) < structural_floor:
            break
        frontier_ids.append(operator_id)
        if len(frontier_ids) >= diffusion_budget:
            break
    selected_ids = _expand_dependency_closure(
        list(seed_ids) + frontier_ids,
        operator_map=operator_map,
        allowed_ids=eligible_ids,
    )
    selected = [operator_map[item_id] for item_id in selected_ids if item_id in operator_map]
    incoming_support = _incoming_structural_support(selected_ids, operator_map)
    support_counts = {
        operator_id: len(incoming_support.get(operator_id, []))
        for operator_id in selected_ids
    }
    ordered_selected_ids = sorted(selected_ids)
    normalized_support = normalize_scores([support_counts[operator_id] for operator_id in ordered_selected_ids])
    support_scores = {
        operator_id: normalized_support[idx]
        for idx, operator_id in enumerate(ordered_selected_ids)
    }
    scored: list[dict[str, Any]] = []
    score_lookup: dict[str, dict[str, float]] = {}
    for operator in selected:
        operator_id = operator["operator_id"]
        candidate_fingerprint = json.loads(operator["env_fingerprint"].get("fingerprint_json", "{}"))
        env_match_score = _env_match_score(current_env, candidate_fingerprint)
        recency_boost = max(0.0, 0.08 - min(_days_since(operator["created_at"]) / 365.0, 0.08))
        provenance_boost = 0.04 if operator.get("source_path") else 0.0
        dependency_penalty = 0.02 * max(len(_structural_dependency_ids(operator, selected_ids)) - 1, 0)
        facet_score = max(
            procedure_scores.get(operator_id, 0.0),
            context_scores.get(operator_id, 0.0),
            outcome_scores.get(operator_id, 0.0),
        )
        prediction = _current_prediction_metrics(
            operator=operator,
            seed_score=seed_scores.get(operator_id, 0.0),
            structural_score=structural_scores.get(operator_id, 0.0),
            facet_score=facet_score,
            contextual_score=contextual_scores.get(operator_id, 0.0),
            env_match_score=env_match_score,
            support_score=support_scores.get(operator_id, 0.0),
            dependency_penalty=dependency_penalty,
        )
        rerank_score = (
            0.34 * seed_scores.get(operator_id, 0.0)
            + 0.24 * structural_scores.get(operator_id, 0.0)
            + 0.14 * facet_score
            + 0.08 * contextual_scores.get(operator_id, 0.0)
            + 0.14 * env_match_score
            + 0.06 * support_scores.get(operator_id, 0.0)
            + recency_boost
            + provenance_boost
            + float(prediction["reliability_boost"])
            - dependency_penalty
        )
        entry = {
            **operator,
            "seed_score": round(seed_scores.get(operator_id, 0.0), 6),
            "structural_score": round(structural_scores.get(operator_id, 0.0), 6),
            "env_match_score": round(env_match_score, 6),
            "predicted_success": float(prediction["predicted_success"]),
            "confidence": float(prediction["confidence"]),
            "abstain_probability": float(prediction["abstain_probability"]),
            "should_abstain": bool(prediction["should_abstain"]),
            "abstain_reason": str(prediction["abstain_reason"]),
            "score": round(rerank_score, 6),
        }
        scored.append(entry)
        score_lookup[operator_id] = {
            "score": float(entry["score"]),
            "env_match_score": float(entry["env_match_score"]),
            "seed_score": float(entry["seed_score"]),
            "structural_score": float(entry["structural_score"]),
            "predicted_success": float(entry["predicted_success"]),
            "confidence": float(entry["confidence"]),
            "abstain_probability": float(entry["abstain_probability"]),
        }
    scored.sort(key=lambda item: item["score"], reverse=True)
    scored_map = {item["operator_id"]: item for item in scored}
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
    selected_map = {item_id: scored_map[item_id] for item_id in kept_ids if item_id in scored_map}
    selected_kept_ids = set(selected_map)
    title_lookup = {operator_id: selected_map[operator_id]["title"] for operator_id in selected_map}
    incoming_support = _incoming_structural_support(selected_kept_ids, operator_map)
    waves = _topological_waves(
        selected_ids=selected_kept_ids,
        operator_map=operator_map,
        score_lookup=score_lookup,
    )
    wave_lookup = {
        operator_id: wave_index
        for wave_index, wave in enumerate(waves)
        for operator_id in wave
    }
    parallel_lookup = {
        operator_id: len(wave) > 1
        for wave in waves
        for operator_id in wave
    }
    ordered: list[dict[str, Any]] = [
        {
            **selected_map[operator_id],
            "score": score_lookup.get(operator_id, {"score": 0.0})["score"],
            "env_match_score": score_lookup.get(operator_id, {"env_match_score": 0.0})["env_match_score"],
            "seed_score": score_lookup.get(operator_id, {"seed_score": 0.0})["seed_score"],
            "structural_score": score_lookup.get(operator_id, {"structural_score": 0.0})["structural_score"],
            "wave": wave_lookup.get(operator_id, 0),
            "parallelizable": parallel_lookup.get(operator_id, False),
            "is_seed": operator_id in seed_ids,
        }
        for wave in waves
        for operator_id in wave
    ]
    plan_items: list[OperatorPlanItem] = []
    status_lookup: dict[str, str] = {}
    for item in ordered:
        depends_on = [
            edge["target_operator_id"]
            for edge in item.get("edges", [])
            if edge.get("edge_type") == "depends_on" and edge["target_operator_id"] in selected_kept_ids
        ]
        requires_context = [
            edge["target_operator_id"]
            for edge in item.get("edges", [])
            if edge.get("edge_type") == "requires_context" and edge["target_operator_id"] in selected_kept_ids
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
                is_seed=bool(item.get("is_seed")),
                wave=int(item.get("wave", 0)),
                parallelizable=bool(item.get("parallelizable", False)),
                inclusion_reason=_inclusion_reason(
                    item["operator_id"],
                    seed_ids=seed_ids,
                    incoming_support=incoming_support,
                    title_lookup=title_lookup,
                ),
                context_package=_minimal_context_package(item),
                depends_on=depends_on,
                requires_context=requires_context,
                conflicts_with=sorted(_operator_conflict_ids(item).intersection(selected_kept_ids)),
                missing_preconditions=missing_preconditions,
                missing_slots=missing_slots,
                env_match_score=float(item["env_match_score"]),
                predicted_success=float(item.get("predicted_success", 0.5)),
                confidence=float(item.get("confidence", 0.35)),
                should_abstain=bool(item.get("should_abstain", False)),
                abstain_reason=str(item.get("abstain_reason", "")),
                reliability=item.get("reliability"),
            )
        )
    readiness_summary = dict(Counter(item.status for item in plan_items))
    top_plan_items = plan_items[: min(3, len(plan_items))]
    best_confidence = max((item.confidence for item in top_plan_items), default=0.0)
    best_success = max((item.predicted_success for item in top_plan_items), default=0.0)
    average_success = (
        sum(item.predicted_success for item in top_plan_items) / len(top_plan_items)
        if top_plan_items
        else 0.0
    )
    curation_confidence = round(0.6 * best_confidence + 0.4 * average_success, 6)
    curation_should_abstain = (
        not top_plan_items
        or all(item.should_abstain for item in top_plan_items)
        or best_confidence < 0.45
        or best_success < 0.42
    )
    if not top_plan_items:
        curation_abstain_reason = "No operators survived retrieval and conflict filtering."
    elif all(item.should_abstain for item in top_plan_items):
        curation_abstain_reason = top_plan_items[0].abstain_reason or "Top candidates should be treated cautiously."
    elif best_confidence < 0.45:
        curation_abstain_reason = "Top retrieved operators lack enough calibrated evidence."
    elif best_success < 0.42:
        curation_abstain_reason = "No retrieved operator is likely enough to help on this task."
    else:
        curation_abstain_reason = ""
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
        "Overview: Hybrid seed retrieval, structural expansion, reranking, topological wave planning, and compact context packaging.",
        f"Readiness: {readiness_summary.get('ready', 0)} ready, {readiness_summary.get('blocked', 0)} blocked.",
        f"Seeds: {len(seed_ids)} direct matches. Bundle: {len(plan_items)} operators after structural expansion.",
        (
            "Reliability: "
            f"bundle confidence {curation_confidence:.3f}, "
            f"best predicted success {best_success:.3f}, "
            f"abstain={'yes' if curation_should_abstain else 'no'}."
        ),
    ]
    if curation_should_abstain and curation_abstain_reason:
        lines.append(f"Abstain Reason: {curation_abstain_reason}")
    lines.extend(["", "Seed Matches:"])
    seed_plan_items = [item for item in plan_items if item.is_seed]
    if seed_plan_items:
        for item in seed_plan_items:
            lines.append(
                f"- {item.title} ({item.score:.3f}, success {item.predicted_success:.3f}, confidence {item.confidence:.3f})"
            )
    else:
        lines.append("- No direct seeds exceeded the retrieval threshold; using the best structural bundle.")
    lines.extend(
        [
            "",
            "Execution Waves:",
        ]
    )
    for wave_index, wave in enumerate(waves):
        lines.append(f"Wave {wave_index}: {'parallel' if len(wave) > 1 else 'serial'}")
        wave_items = [item for item in plan_items if item.wave == wave_index]
        for idx, item in enumerate(wave_items, 1):
            lines.append(f"{idx}. {item.title} — Skill: {item.source_artifact} [{item.status}]")
            lines.append(f"   Why: {item.inclusion_reason}")
            for package_line in item.context_package:
                lines.append(f"   {package_line}")
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
            empirical_reliability = item.reliability.empirical_reliability if item.reliability else 0.0
            lines.append(
                "   Score: "
                f"{item.score:.3f} | Env Match: {item.env_match_score:.3f} | "
                f"Predicted Success: {item.predicted_success:.3f} | "
                f"Confidence: {item.confidence:.3f} | "
                f"Empirical Reliability: {empirical_reliability:.3f}"
            )
            if item.should_abstain and item.abstain_reason:
                lines.append(f"   Abstain: {item.abstain_reason}")
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
                predicted_success=float(item.predicted_success),
                confidence=float(item.confidence),
                should_abstain=bool(item.should_abstain),
                abstain_reason=item.abstain_reason,
            )
            for item in plan_items
        ],
        operator_plan=plan_items,
        readiness_summary=readiness_summary,
        confidence=curation_confidence,
        should_abstain=curation_should_abstain,
        abstain_reason=curation_abstain_reason,
        token_count=0,
        cost_usd=0.0,
    )
    store.save_curation(result)
    return result
