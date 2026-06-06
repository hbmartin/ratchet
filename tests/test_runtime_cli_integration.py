"""Direct local-runtime integration tests for CLI and store behavior."""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from pathlib import Path

from ratchet.client.api.protocol import SkillRefItem
from ratchet.client.skill_installer import get_skill_path, install_skills
from ratchet.pipeline.store import LocalStore
from tests.helpers import (
    make_project_root,
    parse_last_json_line,
    run_subprocess,
    seed_uploaded_session,
)


def _apply_env(monkeypatch, env: dict[str, str]) -> None:
    for key, value in env.items():
        if key in {"RATCHET_DATA_DIR", "RATCHET_TEST_FAKE_LLM", "OPENAI_API_KEY", "PYTHONPATH"}:
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
            "ratchet.client.run_pipeline",
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

    pending_skills = list((Path(test_env["RATCHET_DATA_DIR"]) / "data" / "pending-skills").glob("*/SKILL.md"))
    pending_strategies = list(
        (Path(test_env["RATCHET_DATA_DIR"]) / "data" / "pending-strategies").glob("*.md")
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
            "ratchet.client.cli",
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
            "ratchet.client.cli",
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
            "ratchet.client.cli",
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
        [sys.executable, "-m", "ratchet.client.cli", "pipeline-status"],
        env=test_env,
        cwd=project_root,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    assert run_id in result.stdout
    assert "proj-pipeline-status" in result.stdout

    json_result, _ = run_subprocess(
        [sys.executable, "-m", "ratchet.client.cli", "pipeline-status", "--json"],
        env=test_env,
        cwd=project_root,
        timeout=20,
    )
    assert json_result.returncode == 0, json_result.stderr
    runs = json.loads(json_result.stdout)
    live_run = next(item for item in runs if item["run_id"] == run_id)
    assert live_run["run_dir"]
    assert live_run["log_path"]
    assert live_run["events_path"]
    assert live_run["last_heartbeat_at"]
    assert live_run["heartbeat_count"] > 0
    assert live_run["trace_id"]


def test_store_migrates_debug_schema_and_records_ordered_events(tmp_path: Path):
    db_path = tmp_path / "old-runtime.sqlite3"
    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE pipeline_runs (
                run_id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                project_path TEXT,
                session_id TEXT,
                steps_json TEXT,
                model TEXT,
                include_claude INTEGER NOT NULL DEFAULT 0,
                include_codex INTEGER NOT NULL DEFAULT 0,
                limit_value INTEGER,
                concurrency INTEGER NOT NULL DEFAULT 4,
                status TEXT NOT NULL,
                progress_json TEXT NOT NULL,
                outputs_json TEXT,
                error TEXT,
                pid INTEGER,
                requested_stop INTEGER NOT NULL DEFAULT 0,
                started_at TEXT NOT NULL,
                completed_at TEXT
            );
            """
        )

    store = LocalStore(db_path=db_path)
    with sqlite3.connect(db_path) as conn:
        run_columns = {row[1] for row in conn.execute("PRAGMA table_info(pipeline_runs)").fetchall()}
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }

    assert {
        "run_dir",
        "log_path",
        "events_path",
        "last_heartbeat_at",
        "heartbeat_count",
        "trace_id",
    } <= run_columns
    assert {"pipeline_events", "pipeline_llm_calls"} <= tables

    run_id = "ordered-events-run"
    store.create_run(
        run_id=run_id,
        project_id="proj-events",
        project_path=str(tmp_path / "workspace"),
        session_id=None,
        steps=None,
        model="fake-local",
        include_claude=False,
        include_codex=False,
        limit=1,
        concurrency=1,
    )
    store.set_run_pid(run_id, os.getpid())
    store.record_pipeline_event(run_id, event_type="event_one", message="First event.", phase="test")
    store.record_pipeline_event(run_id, event_type="event_two", message="Second event.", phase="test")

    status = store.get_pipeline_status(run_id)
    events = store.list_pipeline_events(run_id)
    assert [event["event_type"] for event in events][-2:] == ["event_one", "event_two"]
    assert status.heartbeat_count >= 4
    assert Path(status.run_dir or "").is_dir()
    assert Path(status.log_path or "").is_file()
    assert Path(status.events_path or "").is_file()
    jsonl_events = [
        json.loads(line)
        for line in Path(status.events_path or "").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert [event["event_type"] for event in jsonl_events][-2:] == ["event_one", "event_two"]


def test_pipeline_debug_cli_inspect_logs_and_bundle(
    tmp_path: Path,
    test_env: dict[str, str],
    monkeypatch,
):
    _apply_env(monkeypatch, test_env)
    project_root = make_project_root(tmp_path / "workspace", name="debug-cli-project")
    store = LocalStore()
    run_id = "debug-cli-run"
    store.create_run(
        run_id=run_id,
        project_id="proj-debug-cli",
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
    status = store.get_pipeline_status(run_id)
    Path(status.log_path or "").write_text(
        "line one\nline two\nline three\n",
        encoding="utf-8",
    )
    store.record_pipeline_event(
        run_id,
        event_type="debug_test",
        message="Debug CLI test event.",
        phase="testing",
        payload={"detail": "visible"},
    )
    llm_call = store.record_llm_call(
        run_id,
        label="debug_generation",
        provider="fake",
        model="fake-local",
        call_type="generation",
        duration_ms=12,
        status="ok",
        prompt_text="Prompt body",
        response_text='{"ok": true}',
    )

    inspect_json, _ = run_subprocess(
        [sys.executable, "-m", "ratchet.client.cli", "pipeline-inspect", "--run-id", run_id, "--json"],
        env=test_env,
        cwd=project_root,
        timeout=20,
    )
    assert inspect_json.returncode == 0, inspect_json.stderr
    snapshot = json.loads(inspect_json.stdout)
    assert snapshot["status"]["run_id"] == run_id
    assert any(event["event_type"] == "debug_test" for event in snapshot["events"])
    assert any(call["label"] == "debug_generation" for call in snapshot["llm_calls"])

    inspect_text, _ = run_subprocess(
        [sys.executable, "-m", "ratchet.client.cli", "pipeline-inspect", "--run-id", run_id],
        env=test_env,
        cwd=project_root,
        timeout=20,
    )
    assert inspect_text.returncode == 0, inspect_text.stderr
    assert "Timeline" in inspect_text.stdout
    assert "debug_test" in inspect_text.stdout
    assert llm_call["prompt_path"] in inspect_text.stdout
    assert llm_call["response_path"] in inspect_text.stdout

    logs_result, _ = run_subprocess(
        [sys.executable, "-m", "ratchet.client.cli", "pipeline-logs", "--run-id", run_id, "--tail", "2"],
        env=test_env,
        cwd=project_root,
        timeout=20,
    )
    assert logs_result.returncode == 0, logs_result.stderr
    assert "line two" in logs_result.stdout
    assert "line three" in logs_result.stdout
    assert "line one" not in logs_result.stdout

    bundle_path = tmp_path / "debug-bundle.tar.gz"
    bundle_result, _ = run_subprocess(
        [
            sys.executable,
            "-m",
            "ratchet.client.cli",
            "debug-bundle",
            "--run-id",
            run_id,
            "--output",
            str(bundle_path),
            "--json",
        ],
        env=test_env,
        cwd=project_root,
        timeout=20,
    )
    assert bundle_result.returncode == 0, bundle_result.stderr
    bundle_payload = json.loads(bundle_result.stdout)
    assert bundle_payload["path"] == str(bundle_path)
    assert bundle_payload["created"] is True
    assert bundle_payload["skipped_reason"] == ""
    assert bundle_path.is_dir()
    names = {str(path.relative_to(bundle_path)) for path in bundle_path.rglob("*") if path.is_file()}
    assert {"snapshot.json", "status.json", "manifest.json", "worker.log", "events.jsonl"} <= names
    assert any(name.startswith("llm/") and name.endswith("-prompt.txt") for name in names)
    assert any(name.startswith("llm/") and name.endswith("-response.txt") for name in names)

    marker = bundle_path / "manual.txt"
    marker.write_text("keep me\n", encoding="utf-8")
    second_bundle, _ = run_subprocess(
        [
            sys.executable,
            "-m",
            "ratchet.client.cli",
            "debug-bundle",
            "--run-id",
            run_id,
            "--output",
            str(bundle_path),
            "--json",
        ],
        env=test_env,
        cwd=project_root,
        timeout=20,
    )
    assert second_bundle.returncode == 0, second_bundle.stderr
    second_payload = json.loads(second_bundle.stdout)
    assert second_payload["path"] == str(bundle_path)
    assert second_payload["created"] is False
    assert second_payload["skipped_reason"] == "exists"
    assert marker.read_text(encoding="utf-8") == "keep me\n"
    assert "manual.txt" in second_payload["files"]


def test_debug_command_auto_selects_run_writes_json_and_warns_without_provider(
    tmp_path: Path,
    test_env: dict[str, str],
    monkeypatch,
):
    _apply_env(monkeypatch, test_env)
    project_root = make_project_root(tmp_path / "workspace", name="debug-auto-project")
    store = LocalStore()
    completed_run = "debug-completed-run"
    failed_run = "debug-failed-run"
    for run_id in (completed_run, failed_run):
        store.create_run(
            run_id=run_id,
            project_id="proj-debug-auto",
            project_path=str(project_root),
            session_id=None,
            steps=None,
            model="fake-local",
            include_claude=False,
            include_codex=False,
            limit=1,
            concurrency=1,
        )
    store.finish_run(completed_run, status="completed")
    store.finish_run(failed_run, status="failed", error="Synthetic failure.")

    env_without_provider = dict(test_env)
    env_without_provider.pop("OPENAI_API_KEY", None)
    debug_result, _ = run_subprocess(
        [sys.executable, "-m", "ratchet.client.cli", "debug", "--json"],
        env=env_without_provider,
        cwd=project_root,
        timeout=20,
    )
    assert debug_result.returncode == 0, debug_result.stderr
    payload = json.loads(debug_result.stdout)
    assert payload["selected_run"]["run_id"] == failed_run
    assert payload["auth_warning"] is None
    assert payload["bundle"]["created"] is True
    assert Path(payload["bundle"]["path"]).is_dir()
    assert payload["snapshot"]["status"]["run_id"] == failed_run
    assert payload["paths"]["log_path"]
    assert payload["paths"]["events_path"]


def test_debug_command_reports_no_runs(tmp_path: Path, test_env: dict[str, str], monkeypatch):
    _apply_env(monkeypatch, test_env)
    project_root = make_project_root(tmp_path / "workspace", name="debug-empty-project")
    result, _ = run_subprocess(
        [sys.executable, "-m", "ratchet.client.cli", "debug"],
        env=test_env,
        cwd=project_root,
        timeout=20,
    )
    assert result.returncode == 1
    assert "No pipeline runs found" in result.stderr
