"""Tests for the canonical local runtime."""

from __future__ import annotations

import asyncio
import time
import uuid
from pathlib import Path

from mega_code.client.api import create_client
from mega_code.client.api.protocol import OutputsResult
from mega_code.client.models import SessionMetadata, Turn, TurnSet
from mega_code.client.skill_installer import get_skill_path, install_skill
from mega_code.pipeline.store import LocalStore


def _make_turnset(session_id: str, session_dir: Path, project_root: Path) -> TurnSet:
    return TurnSet(
        session_id=session_id,
        session_dir=session_dir,
        metadata=SessionMetadata(
            session_id=session_id,
            project_path=str(project_root),
            git_branch="main",
            model_id="fake-local",
        ),
        turns=[
            Turn(turn_id=1, role="user", content="Fix the auth token refresh flow."),
            Turn(
                turn_id=2,
                role="assistant",
                content="I will inspect the refresh token handling and then run tests.",
            ),
            Turn(
                turn_id=3,
                role="assistant",
                content="Search for auth refresh logic.",
                command="rg -n refresh_token src tests",
            ),
            Turn(
                turn_id=4,
                role="assistant",
                content="Run the auth tests after patching.",
                command="pytest tests/test_auth.py",
            ),
            Turn(
                turn_id=5,
                role="assistant",
                content="If the first fix fails, inspect the failing request and retry once.",
                is_error=True,
            ),
        ],
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
    monkeypatch.setenv("MEGA_CODE_DATA_DIR", str(tmp_path / "data"))
    client = create_client()
    assert type(client).__name__ == "MegaCodeLocal"


def test_local_pipeline_ingest_lifecycle_and_feedback(tmp_path, monkeypatch):
    monkeypatch.setenv("MEGA_CODE_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("MEGA_CODE_TEST_FAKE_LLM", "1")
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

    curation = fresh_client.wisdom_curate(query="auth token refresh workflow", top_k=5)
    assert curation.skills
    assert curation.operator_plan
    assert curation.readiness_summary is not None
    assert any(skill.name == skill_name for skill in curation.skills)
    first_wisdom = curation.wisdoms[0]
    first_operator = curation.operator_plan[0]
    assert first_operator.operator_id == first_wisdom.wisdom_id
    assert first_operator.source_artifact == skill_name

    feedback = fresh_client.wisdom_feedback(
        session_id=curation.session_id,
        feedback_text="Overall: 5/5. Very useful auth workflow.",
    )
    assert feedback.status == "saved"

    curation_after = fresh_client.wisdom_curate(query="auth token refresh workflow", top_k=5)
    rescored = {item.wisdom_id: item.score for item in curation_after.wisdoms}
    assert rescored[first_wisdom.wisdom_id] >= first_wisdom.score


def test_local_pipeline_status_and_stop_are_persisted(tmp_path, monkeypatch):
    monkeypatch.setenv("MEGA_CODE_DATA_DIR", str(tmp_path / "data"))
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


def test_install_skill_from_local_source_path(tmp_path, monkeypatch):
    monkeypatch.setenv("MEGA_CODE_DATA_DIR", str(tmp_path / "data"))
    source = tmp_path / "knowledge" / "sample-skill"
    source.mkdir(parents=True)
    (source / "SKILL.md").write_text("# Sample Skill\n", encoding="utf-8")

    from mega_code.client.api.protocol import SkillRefItem

    result = install_skill(
        SkillRefItem(name="sample-skill", path=str(source), url="")
    )
    assert result == "installed"
    assert get_skill_path("sample-skill") is not None
