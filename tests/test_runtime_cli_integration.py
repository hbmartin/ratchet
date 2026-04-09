"""Direct local-runtime integration tests for CLI and store behavior."""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from pathlib import Path

from mega_code.client.api.protocol import SkillRefItem
from mega_code.client.skill_installer import get_skill_path, install_skills
from mega_code.pipeline.store import LocalStore
from tests.helpers import (
    make_project_root,
    parse_last_json_line,
    run_subprocess,
    seed_uploaded_session,
)


def _apply_env(monkeypatch, env: dict[str, str]) -> None:
    for key, value in env.items():
        if key in {"MEGA_CODE_DATA_DIR", "MEGA_CODE_TEST_FAKE_LLM", "OPENAI_API_KEY", "PYTHONPATH"}:
            monkeypatch.setenv(key, value)


def test_local_runtime_cli_end_to_end_covers_pipeline_curate_install_feedback_and_reranking(
    tmp_path: Path, test_env: dict[str, str], monkeypatch
):
    _apply_env(monkeypatch, test_env)
    seeded = seed_uploaded_session(tmp_path / "seed", project_root=make_project_root(tmp_path / "seed"))

    pipeline_result, _ = run_subprocess(
        [
            sys.executable,
            "-m",
            "mega_code.client.run_pipeline",
            "--session-id",
            seeded["session_id"],
            "--poll-timeout",
            "30",
        ],
        env=test_env,
        cwd=seeded["project_root"],
        timeout=40,
    )
    assert pipeline_result.returncode == 0, pipeline_result.stderr
    pipeline_payload = parse_last_json_line(pipeline_result.stdout)
    assert "PIPELINE COMPLETE" in pipeline_payload["additionalContext"]

    pending_skills = list((Path(test_env["MEGA_CODE_DATA_DIR"]) / "data" / "pending-skills").glob("*/SKILL.md"))
    pending_strategies = list(
        (Path(test_env["MEGA_CODE_DATA_DIR"]) / "data" / "pending-strategies").glob("*.md")
    )
    assert pending_skills
    assert pending_strategies

    store = LocalStore()
    with sqlite3.connect(store.db_path) as conn:
        artifact_count = conn.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0]
        operator_count = conn.execute("SELECT COUNT(*) FROM operators").fetchone()[0]
        run_count = conn.execute("SELECT COUNT(*) FROM pipeline_runs").fetchone()[0]
    assert artifact_count >= 2
    assert operator_count >= 1
    assert run_count >= 1

    curate_result, _ = run_subprocess(
        [
            sys.executable,
            "-m",
            "mega_code.client.cli",
            "wisdom-curate",
            "auth",
            "token",
            "refresh",
            "workflow",
            "--session-id",
            "runtime-curation-session",
            "--top-k",
            "5",
        ],
        env=test_env,
        cwd=seeded["project_root"],
        timeout=30,
    )
    assert curate_result.returncode == 0, curate_result.stderr
    curation = json.loads(curate_result.stdout)
    assert "Execution Waves:" in curation["curation"]
    assert curation["skills"]
    assert curation["operator_plan"]
    assert sum(curation["readiness_summary"].values()) == len(curation["operator_plan"])

    install_results = install_skills([SkillRefItem.model_validate(item) for item in curation["skills"]])
    assert install_results
    assert all(status == "installed" for status in install_results.values())
    for skill in curation["skills"]:
        assert get_skill_path(skill["name"]) is not None

    initial_scores = {item["wisdom_id"]: item["score"] for item in curation["wisdoms"]}
    initial_top_id = curation["wisdoms"][0]["wisdom_id"]

    feedback_result, _ = run_subprocess(
        [
            sys.executable,
            "-m",
            "mega_code.client.cli",
            "wisdom-feedback",
            "--session-id",
            "runtime-curation-session",
            "--feedback-text",
            "Overall: 5/5. Very useful auth workflow.",
        ],
        env=test_env,
        cwd=seeded["project_root"],
        timeout=20,
    )
    assert feedback_result.returncode == 0, feedback_result.stderr
    feedback_payload = json.loads(feedback_result.stdout)
    assert feedback_payload["status"] == "saved"

    reranked_result, _ = run_subprocess(
        [
            sys.executable,
            "-m",
            "mega_code.client.cli",
            "wisdom-curate",
            "auth",
            "token",
            "refresh",
            "workflow",
            "--session-id",
            "runtime-curation-session-2",
            "--top-k",
            "5",
        ],
        env=test_env,
        cwd=seeded["project_root"],
        timeout=30,
    )
    assert reranked_result.returncode == 0, reranked_result.stderr
    reranked = json.loads(reranked_result.stdout)
    reranked_scores = {item["wisdom_id"]: item["score"] for item in reranked["wisdoms"]}
    assert initial_top_id == reranked["wisdoms"][0]["wisdom_id"]
    assert reranked_scores[initial_top_id] >= initial_scores[initial_top_id]

    with sqlite3.connect(store.db_path) as conn:
        feedback_rows = conn.execute("SELECT COUNT(*) FROM curation_feedback").fetchone()[0]
        status = conn.execute(
            "SELECT status FROM curation_sessions WHERE session_id=?",
            ("runtime-curation-session",),
        ).fetchone()[0]
        boosted_score = conn.execute(
            "SELECT feedback_score FROM operators WHERE operator_id=?",
            (initial_top_id,),
        ).fetchone()[0]
    assert feedback_rows >= 1
    assert status == "completed"
    assert boosted_score > 0


def test_cli_pipeline_status_reports_live_run(tmp_path: Path, test_env: dict[str, str], monkeypatch):
    _apply_env(monkeypatch, test_env)
    project_root = make_project_root(tmp_path / "workspace", name="pipeline-status-project")
    store = LocalStore()
    run_id = "cli-live-run"
    store.create_run(
        run_id=run_id,
        project_id="proj-pipeline-status",
        project_path=str(project_root),
        session_id=None,
        steps=None,
        model="fake-local",
        include_claude=False,
        include_codex=False,
        limit=1,
        concurrency=1,
    )
    store.set_run_pid(run_id, os.getpid())

    result, _ = run_subprocess(
        [sys.executable, "-m", "mega_code.client.cli", "pipeline-status"],
        env=test_env,
        cwd=project_root,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    assert run_id in result.stdout
    assert "proj-pipeline-status" in result.stdout
