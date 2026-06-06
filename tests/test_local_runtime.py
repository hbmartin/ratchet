"""Tests for the canonical local runtime."""

from __future__ import annotations

import asyncio
import json
import sys
import time
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

from ratchet.client.api import create_client
from ratchet.client.api.protocol import OutputsResult
from ratchet.client.models import SessionMetadata, Turn, TurnSet
from ratchet.client.skill_installer import get_skill_path, install_skill
from ratchet.pipeline import runtime as local_runtime
from ratchet.pipeline.llm import FakeLocalLLM
from ratchet.pipeline.store import LocalStore
from tests.helpers import run_subprocess


class _BadJSONLLM:
    def generate_text(self, _prompt: str) -> str:
        return "{not valid json"

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[1.0] for _text in texts]


def _make_turnset(
    session_id: str,
    session_dir: Path,
    project_root: Path,
    *,
    prompt: str = "Fix the auth token refresh flow.",
    inspect_message: str = "I will inspect the refresh token handling and then run tests.",
    search_message: str = "Search for auth refresh logic.",
    search_command: str = "rg -n refresh_token src/auth.py tests/test_auth.py",
    verify_message: str = "Run the auth tests after patching.",
    verify_command: str = "pytest tests/test_auth.py -k refresh",
    error_message: str | None = "If the first fix fails, inspect the failing request and retry once.",
    recovery_message: str | None = None,
    recovery_command: str | None = None,
) -> TurnSet:
    turns = [
        Turn(turn_id=1, role="user", content=prompt),
        Turn(turn_id=2, role="assistant", content=inspect_message),
        Turn(turn_id=3, role="assistant", content=search_message, command=search_command),
        Turn(turn_id=4, role="assistant", content=verify_message, command=verify_command),
    ]
    next_turn_id = 5
    if error_message:
        turns.append(
            Turn(
                turn_id=next_turn_id,
                role="assistant",
                content=error_message,
                is_error=True,
            )
        )
        next_turn_id += 1
    if recovery_message:
        turns.append(
            Turn(
                turn_id=next_turn_id,
                role="assistant",
                content=recovery_message,
                command=recovery_command,
            )
        )
        next_turn_id += 1
        turns.append(
            Turn(
                turn_id=next_turn_id,
                role="assistant",
                content="Re-run the verification command after the correction.",
                command=verify_command,
            )
        )
    return TurnSet(
        session_id=session_id,
        session_dir=session_dir,
        metadata=SessionMetadata(
            session_id=session_id,
            project_path=str(project_root),
            git_branch="main",
            model_id="fake-local",
        ),
        turns=turns,
    )


def _create_run(
    store: LocalStore,
    *,
    project_id: str,
    project_path: Path,
    session_id: str | None,
) -> str:
    run_id = str(uuid.uuid4())
    store.create_run(
        run_id=run_id,
        project_id=project_id,
        project_path=str(project_path),
        session_id=session_id,
        steps=None,
        model="fake-local",
        include_claude=False,
        include_codex=False,
        limit=10,
        concurrency=1,
    )
    return run_id


def test_project_fingerprint_ignores_malformed_package_json(tmp_path):
    project_root = tmp_path / "repo"
    project_root.mkdir()
    (project_root / "package.json").write_text("{not json", encoding="utf-8")

    fingerprint = local_runtime._inspect_project_fingerprint(str(project_root))

    assert fingerprint["language"] == "javascript"
    assert fingerprint["package_manager"] == "npm"


def test_project_fingerprint_ignores_non_object_package_json(tmp_path):
    project_root = tmp_path / "repo"
    project_root.mkdir()
    (project_root / "package.json").write_text('["react"]', encoding="utf-8")

    fingerprint = local_runtime._inspect_project_fingerprint(str(project_root))

    assert fingerprint["frameworks"] == []


def test_llm_json_parser_repairs_trailing_commas():
    parsed = local_runtime._parse_llm_json(
        """
        {
          "proposals": [
            {
              "target": "canonical_workflow",
              "title": "Run tests",
              "rule": "Run tests before finishing.",
              "applicability": "Python projects.",
            },
          ],
        }
        """,
        "TEST",
        local_runtime._AnalystPass,
    )

    assert parsed.proposals[0].title == "Run tests"


def test_analyst_pass_raises_on_bad_json():
    cluster = local_runtime.TraceCluster(
        cluster_id="cluster-1",
        skill_name="auth-flow",
        strategy_name="auth-flow-strategy",
        traces=[
            SimpleNamespace(
                turn_set=SimpleNamespace(session_id="session-1"),
                keywords=["auth"],
            )
        ],
    )
    candidates = [
        {
            "target": "canonical_workflow",
            "title": "Inspect auth flow",
            "rule": "Inspect auth flow before editing.",
            "applicability": "Auth projects.",
            "evidence_session_ids": ["session-1"],
            "support_count": 1,
            "examples": ["auth evidence"],
            "kind": "analysis",
        }
    ]

    with pytest.raises(ValueError, match="SUCCESS_ANALYST returned invalid JSON"):
        local_runtime._run_analyst_pass(
            llm=_BadJSONLLM(),
            marker="SUCCESS_ANALYST",
            cluster=cluster,
            candidates=candidates,
        )


def _wait_for_completion(run_id: str, timeout: float = 15.0):
    client = create_client()
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = client.get_pipeline_status(run_id=run_id)
        if status.status in {"completed", "failed", "stopped", "timeout"}:
            return status
        time.sleep(0.1)
    raise TimeoutError(f"Timed out waiting for local run {run_id}")


def test_create_client_returns_local_runtime(tmp_path, monkeypatch):
    monkeypatch.setenv("RATCHET_DATA_DIR", str(tmp_path / "data"))
    client = create_client()
    assert type(client).__name__ == "RatchetLocal"


def test_local_pipeline_ingest_lifecycle_and_feedback(tmp_path, monkeypatch):
    monkeypatch.setenv("RATCHET_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("RATCHET_TEST_FAKE_LLM", "1")
    project_root = tmp_path / "repo"
    project_root.mkdir()
    session_id = str(uuid.uuid4())
    session_dir = tmp_path / "collector" / session_id
    turn_set = _make_turnset(session_id, session_dir, project_root)
    client = create_client()

    upload = client.upload_trajectory(turn_set=turn_set, project_id="proj-local")
    assert upload.status == "accepted"
    assert (session_dir / "turns.jsonl").is_file()

    trigger = asyncio.run(
        client.trigger_pipeline_run(
            project_id="proj-local",
            session_id=session_id,
            limit=1,
        )
    )
    assert trigger.status == "queued"

    fresh_client = create_client()
    status = _wait_for_completion(trigger.run_id)
    assert status.status == "completed"
    assert status.outputs is not None
    assert status.outputs.pending_skills
    assert status.outputs.pending_strategies
    assert status.run_dir
    assert status.log_path
    assert status.events_path
    assert status.last_heartbeat_at
    assert status.heartbeat_count > 0
    assert status.trace_id
    assert Path(status.run_dir).is_dir()
    assert Path(status.log_path).is_file()
    assert Path(status.events_path).is_file()
    worker_log = Path(status.log_path).read_text(encoding="utf-8", errors="replace")
    assert "Local pipeline worker starting" in worker_log

    outputs = fresh_client.get_outputs(project_id="proj-local", run_id=trigger.run_id)
    assert isinstance(outputs, OutputsResult)
    assert outputs.pending_skills[0].skill_name

    skill_name = outputs.pending_skills[0].skill_name
    knowledge_skill = Path(tmp_path / "data" / "knowledge" / "skills" / skill_name / "SKILL.md")
    assert knowledge_skill.is_file()
    store = LocalStore()
    operators = store.fetch_operators()
    assert operators
    assert all(item["indexes"]["procedure"] for item in operators)
    assert all(item["indexes"]["context"] for item in operators)
    assert all(item["indexes"]["outcome"] for item in operators)
    assert any(item["preconditions"] for item in operators)
    assert any(item["postconditions"] for item in operators)
    assert any(item["slots"] for item in operators)
    assert all(item["env_fingerprint"] for item in operators)
    events = store.list_pipeline_events(trigger.run_id)
    event_types = [event["event_type"] for event in events]
    assert "worker_started" in event_types
    assert "runtime_started" in event_types
    assert "runtime_completed" in event_types
    assert "worker_completed" in event_types
    jsonl_events = [
        json.loads(line)
        for line in Path(status.events_path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    jsonl_event_types = [event["event_type"] for event in jsonl_events]
    assert len(jsonl_event_types) == len(event_types)
    assert set(jsonl_event_types) == set(event_types)
    llm_calls = store.list_pipeline_llm_calls(trigger.run_id)
    assert llm_calls
    assert any(call["call_type"] == "generation" for call in llm_calls)
    assert any(call["call_type"] == "embedding" for call in llm_calls)
    for call in llm_calls[:5]:
        assert Path(call["prompt_path"]).is_file()
        assert Path(call["response_path"]).is_file()
    llm_text = "\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for path in Path(status.run_dir, "llm").glob("*.txt")
    )
    assert "sk-test-local" not in llm_text

    curation = fresh_client.wisdom_curate(query="auth token refresh workflow", top_k=5)
    assert curation.skills
    assert curation.operator_plan
    assert curation.readiness_summary is not None
    assert curation.confidence > 0
    assert any(skill.name == skill_name for skill in curation.skills)
    first_wisdom = curation.wisdoms[0]
    first_operator = curation.operator_plan[0]
    assert first_operator.operator_id == first_wisdom.wisdom_id
    assert first_operator.source_artifact == skill_name
    assert first_operator.confidence > 0
    assert first_operator.reliability is not None
    assert first_wisdom.confidence > 0

    feedback = fresh_client.wisdom_feedback(
        session_id=curation.session_id,
        feedback_text="Overall: 5/5. Very useful auth workflow.",
    )
    assert feedback.status == "saved"

    curation_after = fresh_client.wisdom_curate(query="auth token refresh workflow", top_k=5)
    rescored = {item.wisdom_id: item.score for item in curation_after.wisdoms}
    assert rescored[first_wisdom.wisdom_id] >= first_wisdom.score


def test_project_mode_clusters_related_sessions(tmp_path, monkeypatch):
    monkeypatch.setenv("RATCHET_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("RATCHET_TEST_FAKE_LLM", "1")
    project_root = tmp_path / "repo"
    project_root.mkdir()
    store = LocalStore()
    auth_a = _make_turnset("auth-a", tmp_path / "collector" / "auth-a", project_root)
    auth_b = _make_turnset(
        "auth-b",
        tmp_path / "collector" / "auth-b",
        project_root,
        prompt="Repair the auth refresh token retry path.",
        inspect_message="Inspect the token refresh branch and run the focused auth tests.",
        search_message="Search for refresh token handling in auth code.",
        error_message="If the patch still fails, inspect the failing request payload before retrying.",
        recovery_message="Inspect the failing refresh request and patch the auth branch before retrying.",
        recovery_command="rg -n refresh_token src/auth.py tests/test_auth.py",
    )
    lint = _make_turnset(
        "lint-a",
        tmp_path / "collector" / "lint-a",
        project_root,
        prompt="Fix the dashboard import ordering lint failure.",
        inspect_message="Inspect the dashboard imports and run lint.",
        search_message="Search for dashboard imports.",
        search_command="rg -n import src/dashboard.tsx eslint.config.js",
        verify_message="Run the dashboard lint command.",
        verify_command="pnpm exec eslint src/dashboard.tsx",
        error_message=None,
    )
    run_id = _create_run(store, project_id="proj-cluster", project_path=project_root, session_id=None)
    monkeypatch.setattr(
        local_runtime,
        "load_turnsets_for_run",
        lambda config, store: [auth_a, auth_b, lint],
    )

    outputs = local_runtime.run_local_pipeline(run_id, store=store)

    assert len(outputs.pending_skills) == 2
    metadata_items = [json.loads(item.metadata) for item in outputs.pending_skills]
    support_counts = sorted(item["support_count"] for item in metadata_items)
    assert support_counts == [1, 2]
    assert all("cluster_id" in item for item in metadata_items)
    clustered_item = next(item for item in metadata_items if item["support_count"] == 2)
    assert clustered_item["member_session_ids"] == ["auth-a", "auth-b"]


def test_anchor_mode_expands_to_neighbors(tmp_path, monkeypatch):
    monkeypatch.setenv("RATCHET_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("RATCHET_TEST_FAKE_LLM", "1")
    project_root = tmp_path / "repo"
    project_root.mkdir()
    store = LocalStore()
    anchor = _make_turnset("auth-anchor", tmp_path / "collector" / "auth-anchor", project_root)
    neighbor = _make_turnset(
        "auth-neighbor",
        tmp_path / "collector" / "auth-neighbor",
        project_root,
        prompt="Repair the auth refresh retry branch.",
        inspect_message="Inspect the auth refresh branch before running the focused tests.",
        search_message="Search for auth refresh handling.",
        error_message="If the first patch fails, inspect the failing refresh request and retry once.",
        recovery_message="Inspect the failing request payload and patch the auth code before retrying.",
        recovery_command="rg -n refresh_token src/auth.py tests/test_auth.py",
    )
    unrelated = _make_turnset(
        "unrelated",
        tmp_path / "collector" / "unrelated",
        project_root,
        prompt="Fix the CLI help text formatting bug.",
        inspect_message="Inspect the CLI formatter and run the help snapshot.",
        search_message="Search for the CLI help renderer.",
        search_command="rg -n format_help ratchet/client/cli.py tests/test_cli.py",
        verify_message="Run the CLI snapshot test.",
        verify_command="pytest tests/test_cli.py -k help",
        error_message=None,
    )
    run_id = _create_run(
        store,
        project_id="proj-anchor",
        project_path=project_root,
        session_id=anchor.session_id,
    )
    monkeypatch.setattr(
        local_runtime,
        "load_turnsets_for_run",
        lambda config, store: [anchor, neighbor, unrelated],
    )

    outputs = local_runtime.run_local_pipeline(run_id, store=store)

    assert len(outputs.pending_skills) == 1
    metadata = json.loads(outputs.pending_skills[0].metadata)
    assert metadata["support_count"] == 2
    assert metadata["member_session_ids"] == ["auth-anchor", "auth-neighbor"]


def test_singleton_cluster_fallback_when_no_neighbor_matches(tmp_path, monkeypatch):
    monkeypatch.setenv("RATCHET_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("RATCHET_TEST_FAKE_LLM", "1")
    project_root = tmp_path / "repo"
    project_root.mkdir()
    store = LocalStore()
    anchor = _make_turnset("solo-auth", tmp_path / "collector" / "solo-auth", project_root)
    unrelated = _make_turnset(
        "solo-unrelated",
        tmp_path / "collector" / "solo-unrelated",
        project_root,
        prompt="Resolve the docs sidebar build failure.",
        inspect_message="Inspect the docs sidebar configuration.",
        search_message="Search for sidebar config entries.",
        search_command="rg -n sidebar docs site.config.ts",
        verify_message="Run the docs build check.",
        verify_command="pnpm exec next build docs",
        error_message=None,
    )
    run_id = _create_run(
        store,
        project_id="proj-singleton",
        project_path=project_root,
        session_id=anchor.session_id,
    )
    monkeypatch.setattr(
        local_runtime,
        "load_turnsets_for_run",
        lambda config, store: [anchor, unrelated],
    )

    outputs = local_runtime.run_local_pipeline(run_id, store=store)

    metadata = json.loads(outputs.pending_skills[0].metadata)
    assert metadata["support_count"] == 1
    assert metadata["member_session_ids"] == ["solo-auth"]


def test_correction_learning_persists_pcr_fragments(tmp_path, monkeypatch):
    monkeypatch.setenv("RATCHET_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("RATCHET_TEST_FAKE_LLM", "1")
    project_root = tmp_path / "repo"
    project_root.mkdir()
    store = LocalStore()
    auth_a = _make_turnset(
        "corr-a",
        tmp_path / "collector" / "corr-a",
        project_root,
        error_message="The auth verification failed, inspect the failing request and retry once.",
        recovery_message="Inspect the failing request payload and patch the auth branch before retrying.",
        recovery_command="rg -n refresh_token src/auth.py tests/test_auth.py",
    )
    auth_b = _make_turnset(
        "corr-b",
        tmp_path / "collector" / "corr-b",
        project_root,
        prompt="Repair the auth refresh request handling.",
        inspect_message="Inspect the auth refresh path and then run the tests.",
        search_message="Search for refresh request handling in auth code.",
        error_message="The auth verification failed, inspect the failing request and retry once.",
        recovery_message="Inspect the failing request payload and patch the auth branch before retrying.",
        recovery_command="rg -n refresh_token src/auth.py tests/test_auth.py",
    )
    run_id = _create_run(store, project_id="proj-correct", project_path=project_root, session_id=None)
    monkeypatch.setattr(
        local_runtime,
        "load_turnsets_for_run",
        lambda config, store: [auth_a, auth_b],
    )

    outputs = local_runtime.run_local_pipeline(run_id, store=store)

    strategy_content = outputs.pending_strategies[0].content
    assert "Correction Patterns" in strategy_content
    assert "retry" in strategy_content.lower()
    fragments = store.fetch_fragments()
    assert fragments
    assert any("retry" in fragment["procedure"].lower() for fragment in fragments)
    metadata = json.loads(outputs.pending_skills[0].metadata)
    assert metadata["correction_count"] >= 2


def test_distilled_skill_metadata_includes_governance(tmp_path, monkeypatch):
    monkeypatch.setenv("RATCHET_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("RATCHET_TEST_FAKE_LLM", "1")
    project_root = tmp_path / "repo"
    project_root.mkdir()
    store = LocalStore()
    auth_a = _make_turnset(
        "gov-a",
        tmp_path / "collector" / "gov-a",
        project_root,
        recovery_message="Inspect the failing refresh request and patch the auth branch before retrying.",
        recovery_command="rg -n refresh_token src/auth.py tests/test_auth.py",
    )
    auth_b = _make_turnset(
        "gov-b",
        tmp_path / "collector" / "gov-b",
        project_root,
        prompt="Repair the auth refresh token regression and verify it.",
        verify_command="pytest tests/test_auth.py -k refresh",
        recovery_message="Inspect the failing refresh request and patch the auth branch before retrying.",
        recovery_command="rg -n refresh_token src/auth.py tests/test_auth.py",
    )
    run_id = _create_run(store, project_id="proj-governance", project_path=project_root, session_id=None)
    monkeypatch.setattr(
        local_runtime,
        "load_turnsets_for_run",
        lambda config, store: [auth_a, auth_b],
    )

    outputs = local_runtime.run_local_pipeline(run_id, store=store)

    metadata = json.loads(outputs.pending_skills[0].metadata)
    assert metadata["validation_passed"] is True
    assert metadata["validation_level"] == "reproduced"
    assert metadata["trust_tier"] in {"trusted", "hardened"}
    assert metadata["safety_gate_status"] == "approved"
    assert metadata["content_digest"]
    assert metadata["provenance"]["test_artifacts"]
    assert metadata["provenance"]["revalidation_triggers"]
    assert metadata["provenance"]["rollback_lineage"]
    fragments = store.fetch_fragments()
    assert fragments[0]["validation_level"] == "reproduced"
    assert fragments[0]["trust_tier"] in {"trusted", "hardened"}
    assert fragments[0]["safety_gate_status"] == "approved"
    assert fragments[0]["provenance"]["source_artifact_digest"]


def test_curation_ignores_superseded_cluster_operators(tmp_path, monkeypatch):
    monkeypatch.setenv("RATCHET_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("RATCHET_TEST_FAKE_LLM", "1")
    project_root = tmp_path / "repo"
    project_root.mkdir()
    store = LocalStore()
    auth_a = _make_turnset("sup-a", tmp_path / "collector" / "sup-a", project_root)
    auth_b = _make_turnset(
        "sup-b",
        tmp_path / "collector" / "sup-b",
        project_root,
        prompt="Repair the auth refresh token retry path.",
        inspect_message="Inspect the token refresh branch and run the focused auth tests.",
        search_message="Search for refresh token handling in auth code.",
        error_message="If the patch still fails, inspect the failing request payload before retrying.",
        recovery_message="Inspect the failing refresh request and patch the auth branch before retrying.",
        recovery_command="rg -n refresh_token src/auth.py tests/test_auth.py",
    )
    monkeypatch.setattr(
        local_runtime,
        "load_turnsets_for_run",
        lambda config, store: [auth_a, auth_b],
    )

    first_run = _create_run(store, project_id="proj-sup", project_path=project_root, session_id=None)
    local_runtime.run_local_pipeline(first_run, store=store)
    second_run = _create_run(store, project_id="proj-sup", project_path=project_root, session_id=None)
    second_outputs = local_runtime.run_local_pipeline(second_run, store=store)

    curation = local_runtime.curate_local_wisdom(
        query="auth token refresh workflow",
        top_k=10,
        store=store,
    )
    operators = store.fetch_operators()
    superseded_ids = {
        edge["target_operator_id"]
        for operator in operators
        for edge in operator.get("edges", [])
        if edge.get("edge_type") == "supersedes"
    }
    assert curation.operator_plan
    assert all(item.operator_id not in superseded_ids for item in curation.operator_plan)
    assert all(item.source_artifact == second_outputs.pending_skills[0].skill_name for item in curation.operator_plan)


def test_local_pipeline_status_and_stop_are_persisted(tmp_path, monkeypatch):
    monkeypatch.setenv("RATCHET_DATA_DIR", str(tmp_path / "data"))
    store = LocalStore()
    run_id = str(uuid.uuid4())
    store.create_run(
        run_id=run_id,
        project_id="proj-stop",
        project_path=str(tmp_path / "project"),
        session_id=None,
        steps=None,
        model="fake-local",
        include_claude=False,
        include_codex=False,
        limit=1,
        concurrency=1,
    )
    client = create_client()
    result = client.stop_pipeline(run_id=run_id)
    assert result.status == "stopped"
    status = client.get_pipeline_status(run_id=run_id)
    assert status.status == "stopped"
    events = store.list_pipeline_events(run_id)
    assert "stop_requested" in [event["event_type"] for event in events]


def test_invalid_llm_response_records_failure_artifacts_and_inspect_output(
    tmp_path,
    test_env: dict[str, str],
    monkeypatch,
):
    for key in ("RATCHET_DATA_DIR", "RATCHET_TEST_FAKE_LLM", "OPENAI_API_KEY", "PYTHONPATH"):
        monkeypatch.setenv(key, test_env[key])

    class InvalidAnalystLLM(FakeLocalLLM):
        def generate_text(self, prompt: str, *, model: str | None = None) -> str:
            _ = prompt, model
            return "{not-json"

    project_root = tmp_path / "repo"
    project_root.mkdir()
    store = LocalStore()
    turn_set = _make_turnset("bad-analyst", tmp_path / "collector" / "bad-analyst", project_root)
    run_id = _create_run(store, project_id="proj-bad-analyst", project_path=project_root, session_id=None)
    store.set_run_pid(run_id, __import__("os").getpid())
    monkeypatch.setattr(local_runtime, "create_llm_client", lambda: InvalidAnalystLLM())
    monkeypatch.setattr(local_runtime, "load_turnsets_for_run", lambda config, store: [turn_set])

    with pytest.raises(ValueError) as exc_info:
        local_runtime.run_local_pipeline(run_id, store=store)
    store.finish_run(run_id, status="failed", error=str(exc_info.value))

    events = store.list_pipeline_events(run_id)
    assert "runtime_failed" in [event["event_type"] for event in events]
    failed_event = next(event for event in events if event["event_type"] == "runtime_failed")
    assert "returned invalid JSON" in failed_event["payload"]["error"]

    llm_calls = store.list_pipeline_llm_calls(run_id)
    bad_call = next(
        call
        for call in llm_calls
        if Path(call["response_path"]).read_text(encoding="utf-8") == "{not-json"
    )
    assert bad_call["status"] == "ok"
    assert Path(bad_call["response_path"]).read_text(encoding="utf-8") == "{not-json"

    inspect_result, _ = run_subprocess(
        [sys.executable, "-m", "ratchet.client.cli", "pipeline-inspect", "--run-id", run_id],
        env=test_env,
        cwd=project_root,
        timeout=20,
    )
    assert inspect_result.returncode == 0, inspect_result.stderr
    assert "runtime_failed" in inspect_result.stdout
    assert "returned invalid JSON" in inspect_result.stdout
    assert bad_call["response_path"] in inspect_result.stdout


def test_install_skill_from_local_source_path(tmp_path, monkeypatch):
    monkeypatch.setenv("RATCHET_DATA_DIR", str(tmp_path / "data"))
    source = tmp_path / "knowledge" / "sample-skill"
    source.mkdir(parents=True)
    (source / "SKILL.md").write_text("# Sample Skill\n", encoding="utf-8")

    from ratchet.client.api.protocol import SkillRefItem

    result = install_skill(
        SkillRefItem(name="sample-skill", path=str(source), url="")
    )
    assert result == "installed"
    assert get_skill_path("sample-skill") is not None


def test_parse_llm_json_accepts_fenced_consolidator_payload():
    raw = """```json
{
  "summary": "Consolidated auth workflow.",
  "applicability": ["Auth refresh fixes."],
  "canonical_workflow": [],
  "verification_loop": [],
  "failure_guards": [],
  "strategy": {
    "delta_rules": [],
    "correction_patterns": [],
    "when_to_retry": [],
    "when_to_stop": [],
    "support_signals": []
  },
  "memory_fragments": [],
  "keywords": ["auth"]
}
```"""

    parsed = local_runtime._parse_llm_json(raw, "CONSOLIDATOR", local_runtime._ConsolidatedCluster)

    assert parsed.summary == "Consolidated auth workflow."
    assert parsed.keywords == ["auth"]


def test_parse_llm_json_repairs_invalid_escape_sequences_in_strings():
    raw = r"""{
  "proposals": [
    {
      "target": "canonical_workflow",
      "title": "Normalize vendor\_name before diffing",
      "rule": "Keep vendor\_name escaped in JSON output.",
      "applicability": "When underscores appear in API field names.",
      "evidence_session_ids": ["sess-1"],
      "support_count": 1,
      "examples": ["vendor\_name mismatch"]
    }
  ]
}"""

    parsed = local_runtime._parse_llm_json(raw, "ERROR_ANALYST", local_runtime._AnalystPass)

    assert parsed.proposals[0].title == r"Normalize vendor\_name before diffing"
    assert parsed.proposals[0].examples == [r"vendor\_name mismatch"]


def test_parse_llm_json_accepts_bare_analyst_proposal_lists():
    raw = """[
  {
    "target": "canonical_workflow",
    "title": "Use the project build command",
    "rule": "Run the project build before finalizing.",
    "applicability": "When the repo has a build step.",
    "evidence_session_ids": ["sess-1"],
    "support_count": 1,
    "examples": ["pnpm build"]
  }
]"""

    parsed = local_runtime._parse_llm_json(raw, "ERROR_ANALYST", local_runtime._AnalystPass)

    assert len(parsed.proposals) == 1
    assert parsed.proposals[0].title == "Use the project build command"


def test_parse_llm_json_coerces_consolidator_dict_items_in_string_lists():
    raw = """{
  "summary": "Consolidated workflow.",
  "applicability": [{"title": "Fix form build failures."}],
  "canonical_workflow": [],
  "verification_loop": [
    {
      "title": "Run the form build",
      "rule": "pnpm build"
    }
  ],
  "failure_guards": [
    {
      "rule": "Stop after repeated identical build failures."
    }
  ],
  "strategy": {
    "delta_rules": [{"rule": "Prefer the focused build before a full test run."}],
    "correction_patterns": [],
    "when_to_retry": [],
    "when_to_stop": [],
    "support_signals": []
  },
  "memory_fragments": [],
  "keywords": [{"name": "forms"}]
}"""

    parsed = local_runtime._parse_llm_json(raw, "CONSOLIDATOR", local_runtime._ConsolidatedCluster)

    assert parsed.applicability == ["Fix form build failures."]
    assert parsed.verification_loop == ["pnpm build"]
    assert parsed.failure_guards == ["Stop after repeated identical build failures."]
    assert parsed.strategy.delta_rules == ["Prefer the focused build before a full test run."]
    assert parsed.keywords == ["forms"]
