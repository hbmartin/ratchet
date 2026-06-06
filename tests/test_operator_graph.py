"""Tests for the operator graph local runtime."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from pathlib import Path

import pytest

from mega_code.client.api.protocol import CausalStepFeedbackItem
from mega_code.pipeline.llm import batch_embed_texts
from mega_code.pipeline.runtime import curate_local_wisdom
from mega_code.pipeline.store import LocalStore, utcnow_iso


def _prepare_project_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    project_root = tmp_path / "repo"
    project_root.mkdir()
    (project_root / "pyproject.toml").write_text(
        """
[project]
name = "operator-graph-test"
dependencies = ["fastapi", "pytest"]
""".strip()
        + "\n",
        encoding="utf-8",
    )
    (project_root / "uv.lock").write_text("version = 1\n", encoding="utf-8")
    monkeypatch.chdir(project_root)
    return project_root


def _artifact_payload(tmp_path: Path, artifact_name: str) -> tuple[str, dict]:
    artifact_id = str(uuid.uuid4())
    source_dir = tmp_path / "knowledge" / artifact_name
    source_dir.mkdir(parents=True, exist_ok=True)
    (source_dir / "SKILL.md").write_text(f"# {artifact_name}\n", encoding="utf-8")
    embedding = batch_embed_texts([artifact_name])[0]
    return artifact_id, {
        "artifact_id": artifact_id,
        "artifact_type": "skill",
        "name": artifact_name,
        "version": "0.1.0",
        "content": f"# {artifact_name}\n",
        "metadata": {"generated_at": utcnow_iso()},
        "source_path": str(source_dir),
        "created_at": utcnow_iso(),
        "embedding": embedding,
    }


def _normalize_preconditions(preconditions: list[dict] | None) -> list[dict]:
    result: list[dict] = []
    for index, item in enumerate(preconditions or [], 1):
        result.append(
            {
                "precondition_id": item.get("precondition_id", str(uuid.uuid4())),
                "precondition_type": item["precondition_type"],
                "key_name": item.get("key_name", item["precondition_type"]),
                "value": item.get("value", ""),
                "description": item.get("description", f"precondition-{index}"),
            }
        )
    return result


def _normalize_postconditions(postconditions: list[dict] | None) -> list[dict]:
    result: list[dict] = []
    for index, item in enumerate(postconditions or [], 1):
        result.append(
            {
                "postcondition_id": item.get("postcondition_id", str(uuid.uuid4())),
                "postcondition_type": item["postcondition_type"],
                "key_name": item.get("key_name", item["postcondition_type"]),
                "value": item.get("value", ""),
                "description": item.get("description", f"postcondition-{index}"),
            }
        )
    return result


def _normalize_slots(slots: list[dict] | None) -> list[dict]:
    result: list[dict] = []
    for index, item in enumerate(slots or [], 1):
        result.append(
            {
                "slot_id": item.get("slot_id", str(uuid.uuid4())),
                "slot_name": item.get("slot_name", f"slot_{index}"),
                "slot_type": item.get("slot_type", "value"),
                "slot_value": item.get("slot_value", ""),
                "required": item.get("required", True),
                "description": item.get("description", f"slot-{index}"),
            }
        )
    return result


def _slot_signature(slots: list[dict]) -> str:
    if not slots:
        return "no-slots"
    joined = "|".join(
        f"{item['slot_type']}:{item['slot_name']}:{item.get('slot_value', '')}"
        for item in sorted(slots, key=lambda value: (value["slot_type"], value["slot_name"]))
    )
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:16]


def _operator_payload(
    *,
    artifact_id: str,
    artifact_name: str,
    title: str,
    procedure: str,
    context: str,
    outcome: str,
    operator_id: str | None = None,
    normalized_intent: str | None = None,
    slot_signature: str | None = None,
    created_at: str | None = None,
    edges: list[dict] | None = None,
    preconditions: list[dict] | None = None,
    postconditions: list[dict] | None = None,
    slots: list[dict] | None = None,
    env_fingerprint: dict | None = None,
) -> dict:
    procedure_embedding, context_embedding, outcome_embedding = batch_embed_texts(
        [procedure, context, outcome]
    )
    normalized_slots = _normalize_slots(slots)
    fingerprint = env_fingerprint or {
        "project_path": "",
        "language": "python",
        "frameworks": ["fastapi", "pytest"],
        "package_manager": "uv",
        "branch": "main",
        "model": "fake-local",
        "required_tools": [],
        "env_var_presence": {},
    }
    fingerprint_hash = hashlib.sha256(
        json.dumps(fingerprint, sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]
    return {
        "operator_id": operator_id or str(uuid.uuid4()),
        "artifact_id": artifact_id,
        "name": f"{artifact_name}-{title.lower().replace(' ', '-')}",
        "title": title,
        "procedure": procedure,
        "context": context,
        "outcome": outcome,
        "source_artifact": artifact_name,
        "normalized_intent": normalized_intent or title.lower(),
        "slot_signature": slot_signature or _slot_signature(normalized_slots),
        "feedback_score": 0.0,
        "created_at": created_at or utcnow_iso(),
        "indexes": {
            "procedure": {
                "facet_text": procedure,
                "embedding": procedure_embedding,
                "lexical_text": procedure,
            },
            "context": {
                "facet_text": context,
                "embedding": context_embedding,
                "lexical_text": context,
            },
            "outcome": {
                "facet_text": outcome,
                "embedding": outcome_embedding,
                "lexical_text": outcome,
            },
        },
        "edges": edges or [],
        "preconditions": _normalize_preconditions(preconditions),
        "postconditions": _normalize_postconditions(postconditions),
        "slots": normalized_slots,
        "env_fingerprint": {
            "fingerprint": fingerprint,
            "lexical_text": " ".join(
                [
                    fingerprint.get("language", ""),
                    " ".join(fingerprint.get("frameworks", [])),
                    fingerprint.get("package_manager", ""),
                    fingerprint.get("branch", ""),
                    fingerprint.get("model", ""),
                ]
            ),
            "fingerprint_hash": fingerprint_hash,
        },
    }


def _persist_operators(
    *,
    store: LocalStore,
    tmp_path: Path,
    operators: list[dict],
    artifact_name: str = "operator-skill",
    run_id: str | None = None,
    project_id: str = "proj-operators",
    session_id: str = "session-operators",
) -> None:
    run_id = run_id or str(uuid.uuid4())
    artifact_id, artifact_payload = _artifact_payload(tmp_path, artifact_name)
    prepared: list[dict] = []
    for item in operators:
        payload = {**item}
        payload["artifact_id"] = artifact_id
        prepared.append(payload)
    store.save_artifacts(
        run_id=run_id,
        project_id=project_id,
        session_id=session_id,
        artifact_payloads=[artifact_payload],
        operator_payloads=prepared,
    )


def test_operator_graph_schema_is_created(tmp_path, monkeypatch):
    monkeypatch.setenv("MEGA_CODE_DATA_DIR", str(tmp_path / "data"))
    store = LocalStore()

    with sqlite3.connect(store.db_path) as conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}

    assert {
        "operators",
        "operator_procedure_index",
        "operator_context_index",
        "operator_outcome_index",
        "operator_edges",
        "operator_preconditions",
        "operator_postconditions",
        "operator_slots",
        "operator_env_fingerprints",
        "curation_feedback_steps",
        "operator_reliability",
    }.issubset(tables)


def test_curate_matches_context_and_outcome_indexes(tmp_path, monkeypatch):
    monkeypatch.setenv("MEGA_CODE_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("MEGA_CODE_TEST_FAKE_LLM", "1")
    _prepare_project_root(tmp_path, monkeypatch)
    store = LocalStore()

    _persist_operators(
        store=store,
        tmp_path=tmp_path,
        operators=[
            _operator_payload(
                artifact_id="placeholder",
                artifact_name="router-skill",
                title="Inspect router context",
                procedure="Inspect the API router before editing.",
                context="python fastapi uv router endpoint context service",
                outcome="Understand the route ownership before patching.",
            ),
            _operator_payload(
                artifact_id="placeholder",
                artifact_name="auth-skill",
                title="Verify token refresh outcome",
                procedure="Run the auth verification loop.",
                context="python uv auth testing",
                outcome="token refresh verification passes and auth workflow succeeds",
            ),
        ],
    )

    context_result = curate_local_wisdom(query="fastapi router endpoint", top_k=1, store=store)
    outcome_result = curate_local_wisdom(query="token refresh verification", top_k=1, store=store)

    assert context_result.operator_plan[0].title == "Inspect router context"
    assert outcome_result.operator_plan[0].title == "Verify token refresh outcome"


def test_curate_expands_dependency_and_context_edges(tmp_path, monkeypatch):
    monkeypatch.setenv("MEGA_CODE_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("MEGA_CODE_TEST_FAKE_LLM", "1")
    _prepare_project_root(tmp_path, monkeypatch)
    store = LocalStore()

    context_operator_id = str(uuid.uuid4())
    dependency_operator_id = str(uuid.uuid4())
    target_operator_id = str(uuid.uuid4())
    _persist_operators(
        store=store,
        tmp_path=tmp_path,
        operators=[
            _operator_payload(
                artifact_id="placeholder",
                artifact_name="auth-graph",
                operator_id=context_operator_id,
                title="Inspect auth context",
                procedure="Inspect the auth module context first.",
                context="python fastapi uv auth module context",
                outcome="Understand the auth module boundaries.",
            ),
            _operator_payload(
                artifact_id="placeholder",
                artifact_name="auth-graph",
                operator_id=dependency_operator_id,
                title="Open auth module",
                procedure="Open the auth module and inspect the failing path.",
                context="python fastapi uv auth module file",
                outcome="Locate the affected auth module file.",
            ),
            _operator_payload(
                artifact_id="placeholder",
                artifact_name="auth-graph",
                operator_id=target_operator_id,
                title="Run auth regression tests",
                procedure="Run auth regression tests for the refresh flow.",
                context="python fastapi uv pytest auth tests",
                outcome="refresh flow tests pass without regressions",
                edges=[
                    {"edge_type": "depends_on", "target_operator_id": dependency_operator_id, "metadata": {}},
                    {
                        "edge_type": "requires_context",
                        "target_operator_id": context_operator_id,
                        "metadata": {},
                    },
                ],
            ),
        ],
    )

    result = curate_local_wisdom(query="run auth regression tests", top_k=1, store=store)
    titles = [item.title for item in result.operator_plan]

    assert "Inspect auth context" in titles
    assert "Open auth module" in titles
    assert titles.index("Inspect auth context") < titles.index("Run auth regression tests")
    assert titles.index("Open auth module") < titles.index("Run auth regression tests")
    target = next(item for item in result.operator_plan if item.operator_id == target_operator_id)
    context_item = next(item for item in result.operator_plan if item.operator_id == context_operator_id)
    dependency_item = next(item for item in result.operator_plan if item.operator_id == dependency_operator_id)
    assert dependency_operator_id in target.depends_on
    assert context_operator_id in target.requires_context
    assert target.wave == 1
    assert context_item.wave == 0
    assert dependency_item.wave == 0
    assert target.parallelizable is False
    assert "Dependency recovered" in dependency_item.inclusion_reason
    assert "Context prerequisite recovered" in context_item.inclusion_reason
    assert target.context_package[0].startswith("Do: ")
    assert any(line.startswith("Done when: ") for line in target.context_package)
    assert "Execution Waves:" in result.curation
    assert "Wave 0: parallel" in result.curation
    assert "Wave 1: serial" in result.curation


def test_curate_suppresses_conflicts_and_superseded_ops(tmp_path, monkeypatch):
    monkeypatch.setenv("MEGA_CODE_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("MEGA_CODE_TEST_FAKE_LLM", "1")
    _prepare_project_root(tmp_path, monkeypatch)
    store = LocalStore()

    old_operator_id = str(uuid.uuid4())
    _persist_operators(
        store=store,
        tmp_path=tmp_path,
        artifact_name="auth-tests",
        run_id="run-old",
        operators=[
            _operator_payload(
                artifact_id="placeholder",
                artifact_name="auth-tests",
                operator_id=old_operator_id,
                title="Run auth tests legacy",
                procedure="Run auth tests for the refresh flow.",
                context="python uv auth tests legacy",
                outcome="legacy auth test flow passes",
                normalized_intent="run auth tests",
                slot_signature="shared-auth-tests",
            )
        ],
    )

    new_operator_id = str(uuid.uuid4())
    alt_operator_id = str(uuid.uuid4())
    _persist_operators(
        store=store,
        tmp_path=tmp_path,
        artifact_name="auth-tests",
        run_id="run-new",
        operators=[
            _operator_payload(
                artifact_id="placeholder",
                artifact_name="auth-tests",
                operator_id=new_operator_id,
                title="Run auth tests current",
                procedure="Run auth tests current refresh verification.",
                context="python uv auth tests current",
                outcome="current auth refresh tests pass with verification",
                normalized_intent="run auth tests",
                slot_signature="shared-auth-tests",
                edges=[
                    {"edge_type": "conflicts_with", "target_operator_id": alt_operator_id, "metadata": {}}
                ],
            ),
            _operator_payload(
                artifact_id="placeholder",
                artifact_name="auth-tests",
                operator_id=alt_operator_id,
                title="Run auth tests via npm",
                procedure="Run auth tests through a node wrapper.",
                context="javascript npm auth tests alternate",
                outcome="alternate auth test runner passes",
                normalized_intent="run auth tests",
                slot_signature="alt-auth-tests",
                edges=[
                    {"edge_type": "conflicts_with", "target_operator_id": new_operator_id, "metadata": {}}
                ],
                env_fingerprint={
                    "project_path": "",
                    "language": "javascript",
                    "frameworks": ["react"],
                    "package_manager": "npm",
                    "branch": "main",
                    "model": "fake-local",
                    "required_tools": [],
                    "env_var_presence": {},
                },
            ),
        ],
    )

    result = curate_local_wisdom(query="run auth tests", top_k=3, store=store)
    operator_ids = [item.operator_id for item in result.operator_plan]

    assert new_operator_id in operator_ids
    assert old_operator_id not in operator_ids
    assert alt_operator_id not in operator_ids


def test_curate_marks_missing_preconditions_and_slots_blocked(tmp_path, monkeypatch):
    monkeypatch.setenv("MEGA_CODE_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("MEGA_CODE_TEST_FAKE_LLM", "1")
    _prepare_project_root(tmp_path, monkeypatch)
    store = LocalStore()

    _persist_operators(
        store=store,
        tmp_path=tmp_path,
        operators=[
            _operator_payload(
                artifact_id="placeholder",
                artifact_name="blocked-skill",
                title="Apply protected deployment step",
                procedure="Apply the protected deployment step.",
                context="python uv deployment auth",
                outcome="deployment completes once credentials are configured",
                preconditions=[
                    {
                        "precondition_type": "env_var",
                        "value": "MISSING_DEPLOY_TOKEN",
                        "description": "Environment variable `MISSING_DEPLOY_TOKEN` must be configured.",
                    }
                ],
                slots=[
                    {
                        "slot_name": "target_path",
                        "slot_type": "path",
                        "slot_value": "",
                        "required": True,
                        "description": "Target path for the deployment step.",
                    }
                ],
            )
        ],
    )

    result = curate_local_wisdom(query="protected deployment step", top_k=1, store=store)
    item = result.operator_plan[0]

    assert item.status == "blocked"
    assert any("MISSING_DEPLOY_TOKEN" in value for value in item.missing_preconditions)
    assert "target_path" in item.missing_slots


def test_curate_excludes_review_required_operator(tmp_path, monkeypatch):
    monkeypatch.setenv("MEGA_CODE_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("MEGA_CODE_TEST_FAKE_LLM", "1")
    _prepare_project_root(tmp_path, monkeypatch)
    store = LocalStore()

    payload = _operator_payload(
        artifact_id="placeholder",
        artifact_name="review-required-skill",
        title="Use unverified deployment shortcut",
        procedure="Use the unverified deployment shortcut.",
        context="python uv deployment shortcut",
        outcome="deployment completes quickly",
    )
    payload.update(
        {
            "validation_level": "observed",
            "trust_tier": "provisional",
            "safety_gate_status": "review_required",
            "safety_gate_reason": "Needs a successful verification artifact before reuse.",
            "provenance": {
                "source_sessions": ["session-review-required"],
                "source_paths": ["deploy.py"],
                "evidence_digest": "digest-review-required",
                "test_artifacts": [],
                "revalidation_triggers": ["source_artifact_digest_changed"],
                "rollback_lineage": [],
            },
        }
    )
    _persist_operators(store=store, tmp_path=tmp_path, operators=[payload])

    result = curate_local_wisdom(query="deployment shortcut", top_k=1, store=store)

    assert result.operator_plan == []
    assert result.should_abstain is True
    assert "safety gate" in result.abstain_reason.lower()
    assert "none passed the validation/trust safety gate" in result.curation.lower()


def test_feedback_increases_operator_rank(tmp_path, monkeypatch):
    monkeypatch.setenv("MEGA_CODE_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("MEGA_CODE_TEST_FAKE_LLM", "1")
    _prepare_project_root(tmp_path, monkeypatch)
    store = LocalStore()

    _persist_operators(
        store=store,
        tmp_path=tmp_path,
        operators=[
            _operator_payload(
                artifact_id="placeholder",
                artifact_name="feedback-skill",
                title="Run feedback-sensitive check",
                procedure="Run the feedback-sensitive check.",
                context="python uv checks",
                outcome="feedback sensitive verification passes",
            )
        ],
    )

    first = curate_local_wisdom(query="feedback-sensitive check", top_k=1, store=store)
    feedback = store.save_feedback(first.session_id, "Overall: 5/5. Very useful operator.")
    second = curate_local_wisdom(query="feedback-sensitive check", top_k=1, store=store)

    assert feedback.status == "saved"
    assert second.operator_plan[0].score > first.operator_plan[0].score
    assert second.operator_plan[0].confidence > 0
    assert second.operator_plan[0].reliability is not None


def test_structured_feedback_updates_only_targeted_operator(tmp_path, monkeypatch):
    monkeypatch.setenv("MEGA_CODE_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("MEGA_CODE_TEST_FAKE_LLM", "1")
    _prepare_project_root(tmp_path, monkeypatch)
    store = LocalStore()

    helped_id = str(uuid.uuid4())
    hurt_id = str(uuid.uuid4())
    _persist_operators(
        store=store,
        tmp_path=tmp_path,
        operators=[
            _operator_payload(
                artifact_id="placeholder",
                artifact_name="feedback-skill",
                operator_id=helped_id,
                title="Inspect auth refresh flow",
                procedure="Inspect the auth refresh flow.",
                context="python uv auth refresh",
                outcome="refresh flow is understood",
            ),
            _operator_payload(
                artifact_id="placeholder",
                artifact_name="feedback-skill",
                operator_id=hurt_id,
                title="Inspect unrelated billing hook",
                procedure="Inspect the unrelated billing hook.",
                context="python uv billing hook",
                outcome="billing hook is understood",
            ),
        ],
    )

    first = curate_local_wisdom(query="inspect auth refresh flow", top_k=2, store=store)
    feedback = store.save_feedback(
        first.session_id,
        "The auth step helped, but the billing step was the wrong retrieval.",
        step_feedback=[
            CausalStepFeedbackItem(operator_id=helped_id, verdict="helped", failure_stage="none"),
            CausalStepFeedbackItem(operator_id=hurt_id, verdict="hurt", failure_stage="retrieval"),
        ],
    )
    second = curate_local_wisdom(query="inspect auth refresh flow", top_k=2, store=store)
    second_by_id = {item.operator_id: item for item in second.operator_plan}

    assert feedback.applied_steps == 2
    assert second_by_id[helped_id].score > second_by_id[hurt_id].score
    assert second_by_id[helped_id].reliability is not None
    assert second_by_id[helped_id].reliability.helped_count == 1
    assert second_by_id[hurt_id].reliability is not None
    assert second_by_id[hurt_id].reliability.hurt_count == 1
    assert second_by_id[hurt_id].reliability.retrieval_miss_count == 1


def test_feedback_can_mark_operator_for_abstention(tmp_path, monkeypatch):
    monkeypatch.setenv("MEGA_CODE_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("MEGA_CODE_TEST_FAKE_LLM", "1")
    _prepare_project_root(tmp_path, monkeypatch)
    store = LocalStore()

    operator_id = str(uuid.uuid4())
    _persist_operators(
        store=store,
        tmp_path=tmp_path,
        operators=[
            _operator_payload(
                artifact_id="placeholder",
                artifact_name="abstain-skill",
                operator_id=operator_id,
                title="Apply risky database patch",
                procedure="Apply the risky database patch.",
                context="python uv postgres migration",
                outcome="database patch is applied",
            )
        ],
    )

    first = curate_local_wisdom(query="apply risky database patch", top_k=1, store=store)
    store.save_feedback(
        first.session_id,
        "This step should have been avoided.",
        failure_stage="execution",
        should_abstain=True,
        step_feedback=[
            CausalStepFeedbackItem(
                operator_id=operator_id,
                verdict="hurt",
                failure_stage="execution",
                note="Execution path was too risky for a recommendation.",
            )
        ],
    )
    second = curate_local_wisdom(query="apply risky database patch", top_k=1, store=store)

    assert second.should_abstain is True
    assert second.abstain_reason
    assert second.operator_plan[0].should_abstain is True
    assert second.operator_plan[0].abstain_reason
    assert second.operator_plan[0].reliability is not None
    assert second.operator_plan[0].reliability.abstain_count == 1
    assert second.operator_plan[0].reliability.execution_miss_count == 1


def test_curate_marks_seeds_and_parallel_waves(tmp_path, monkeypatch):
    monkeypatch.setenv("MEGA_CODE_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("MEGA_CODE_TEST_FAKE_LLM", "1")
    _prepare_project_root(tmp_path, monkeypatch)
    store = LocalStore()

    first_seed_id = str(uuid.uuid4())
    second_seed_id = str(uuid.uuid4())
    _persist_operators(
        store=store,
        tmp_path=tmp_path,
        operators=[
            _operator_payload(
                artifact_id="placeholder",
                artifact_name="parallel-skill",
                operator_id=first_seed_id,
                title="Inspect payment config",
                procedure="Inspect the payment configuration before editing.",
                context="python fastapi payments config",
                outcome="payment configuration scope is understood",
            ),
            _operator_payload(
                artifact_id="placeholder",
                artifact_name="parallel-skill",
                operator_id=second_seed_id,
                title="Inspect billing jobs",
                procedure="Inspect the billing jobs before editing.",
                context="python fastapi billing jobs",
                outcome="billing job scope is understood",
            ),
        ],
    )

    result = curate_local_wisdom(query="inspect payment billing config", top_k=2, store=store)

    assert len(result.operator_plan) == 2
    assert all(item.is_seed for item in result.operator_plan)
    assert all(item.wave == 0 for item in result.operator_plan)
    assert all(item.parallelizable for item in result.operator_plan)
    assert all(item.inclusion_reason.startswith("Direct hybrid seed") for item in result.operator_plan)
    assert "Seed Matches:" in result.curation
    assert "Wave 0: parallel" in result.curation


def test_curate_returns_empty_plan_without_operators(tmp_path, monkeypatch):
    monkeypatch.setenv("MEGA_CODE_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("MEGA_CODE_TEST_FAKE_LLM", "1")
    _prepare_project_root(tmp_path, monkeypatch)
    store = LocalStore()

    result = curate_local_wisdom(query="nothing stored yet", top_k=3, store=store)

    assert result.operator_plan == []
    assert result.wisdoms == []
    assert result.readiness_summary == {"ready": 0, "blocked": 0}
    assert result.should_abstain is True
    assert "No operator graph data is available yet" in result.curation
