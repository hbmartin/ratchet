"""Local worker runtime for distillation and curation."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mega_code.client.api.protocol import (
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


def _pcr_fragment_payloads(
    *,
    run_id: str,
    project_id: str,
    session_id: str,
    artifact_id: str,
    skill_name: str,
    steps: list[dict[str, Any]],
    embedding_vectors: list[list[float]],
    context_text: str,
) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    dependency_ids: list[str] = []
    for idx, (step, embedding) in enumerate(zip(steps, embedding_vectors, strict=False), 1):
        fragment_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{artifact_id}:pcr:{idx}"))
        payloads.append(
            {
                "fragment_id": fragment_id,
                "artifact_id": artifact_id,
                "run_id": run_id,
                "project_id": project_id,
                "name": f"{skill_name}-step-{idx}",
                "procedure": step["label"],
                "context": context_text,
                "resultant": step["evidence"],
                "constraints": "Retry only after checking evidence and local project context.",
                "evidence_refs": [session_id, str(step["turn_id"])],
                "source_artifact": skill_name,
                "dependency_ids": dependency_ids[-1:] if dependency_ids else [],
                "feedback_score": 0.0,
                "created_at": utcnow_iso(),
                "embedding": embedding,
                "lexical_text": " ".join([step["label"], context_text, step["evidence"], skill_name]),
            }
        )
        dependency_ids.append(fragment_id)
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
    context_text = (
        f"project={turn_set.metadata.project_path or 'unknown'} "
        f"branch={turn_set.metadata.git_branch or 'unknown'} "
        f"model={turn_set.metadata.model_id or 'unknown'}"
    )
    fragment_texts = [
        " ".join([step["label"], context_text, step["evidence"], skill_name]) for step in steps
    ]
    fragment_embeddings = llm.embed_documents(fragment_texts)
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
    pcr_payloads = _pcr_fragment_payloads(
        run_id=run_id,
        project_id=project_id,
        session_id=turn_set.session_id,
        artifact_id=skill_artifact_id,
        skill_name=skill_name,
        steps=steps,
        embedding_vectors=fragment_embeddings,
        context_text=context_text,
    )
    return SessionArtifacts(
        pending_skill=pending_skill,
        pending_strategy=pending_strategy,
        artifact_payloads=artifact_payloads,
        pcr_payloads=pcr_payloads,
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
    pcr_payloads: list[dict[str, Any]] = []
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
        pcr_payloads.extend(artifacts.pcr_payloads)
        store.update_progress(run_id, phase="distilling", processed=idx, total=len(turnsets))
    store.save_artifacts(
        run_id=run_id,
        project_id=config["project_id"],
        session_id=config.get("session_id") or "",
        artifact_payloads=artifact_payloads,
        pcr_payloads=pcr_payloads,
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
    fragments = store.fetch_fragments()
    lexical_docs = [_tokenize(fragment["lexical_text"]) for fragment in fragments]
    lexical_scores = _bm25_scores(_tokenize(query), lexical_docs)
    normalized_lexical = normalize_scores(lexical_scores)
    scored: list[dict[str, Any]] = []
    semantic_scores = [
        cosine_similarity(query_embedding, json.loads(fragment["embedding_json"])) for fragment in fragments
    ]
    normalized_semantic = normalize_scores(semantic_scores)
    for idx, fragment in enumerate(fragments):
        feedback_boost = float(fragment["feedback_score"]) * 0.15
        recency_boost = max(0.0, 0.1 - min(_days_since(fragment["created_at"]) / 365.0, 0.1))
        provenance_boost = 0.05 if fragment.get("source_path") else 0.0
        final_score = (
            0.5 * normalized_semantic[idx]
            + 0.3 * normalized_lexical[idx]
            + feedback_boost
            + recency_boost
            + provenance_boost
        )
        scored.append(
            {
                **fragment,
                "score": round(final_score, 6),
                "seed": idx < top_k,
            }
        )
    scored.sort(key=lambda item: item["score"], reverse=True)
    selected = scored[:top_k]
    dependency_ids = set()
    for fragment in list(selected):
        dependency_ids.update(json.loads(fragment["dependency_ids_json"]))
    if dependency_ids:
        extras = [item for item in scored[top_k:] if item["fragment_id"] in dependency_ids]
        selected.extend(extras)
    selected_map = {item["fragment_id"]: item for item in selected}
    ordered: list[dict[str, Any]] = []
    visited: set[str] = set()

    def visit(fragment_id: str) -> None:
        if fragment_id in visited or fragment_id not in selected_map:
            return
        visited.add(fragment_id)
        for dep_id in json.loads(selected_map[fragment_id]["dependency_ids_json"]):
            visit(dep_id)
        ordered.append(selected_map[fragment_id])

    for item in selected:
        visit(item["fragment_id"])

    grouped_steps: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in ordered:
        grouped_steps[item["source_artifact"]].append(item)

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
        "Overview: Local hybrid retrieval over PCR fragments, dependency links, and feedback-adjusted scores.",
        "",
        "Steps:",
    ]
    step_index = 1
    for skill_name, items in grouped_steps.items():
        lead = items[0]
        lines.append(f"{step_index}. {lead['procedure']} — Skill: {skill_name}")
        lines.append(f"   Context: {lead['context']}")
        lines.append(f"   Resultant: {lead['resultant']}")
        lines.append(f"   Score: {lead['score']:.3f}")
        step_index += 1
    curation = "\n".join(lines) + "\n"
    result = WisdomCurateResult(
        session_id=session_id or str(uuid.uuid4()),
        query=query,
        curation=curation,
        skills=skills,
        wisdoms=[
            WisdomResultItem(
                wisdom_id=item["fragment_id"],
                score=float(item["score"]),
                is_seed=item["fragment_id"] in {seed["fragment_id"] for seed in scored[:top_k]},
            )
            for item in ordered
        ],
        token_count=0,
        cost_usd=0.0,
    )
    store.save_curation(result)
    return result
