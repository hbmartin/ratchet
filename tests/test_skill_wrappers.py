"""Pseudo integration tests for slash-command wrapper bash flows."""

from __future__ import annotations

import json
from pathlib import Path

from mega_code.pipeline.store import LocalStore
from tests.helpers import (
    find_bash_block,
    make_project_root,
    parse_last_json_line,
    run_bash,
    seed_uploaded_session,
)


def _apply_env(monkeypatch, env: dict[str, str]) -> None:
    for key in ("MEGA_CODE_DATA_DIR", "MEGA_CODE_TEST_FAKE_LLM", "OPENAI_API_KEY"):
        monkeypatch.setenv(key, env[key])


def test_wisdom_gen_skill_bash_flow_runs_pipeline_and_emits_review_context(
    repo_root: Path, test_env: dict[str, str], tmp_path: Path, monkeypatch
):
    _apply_env(monkeypatch, test_env)
    seeded = seed_uploaded_session(tmp_path / "seed", project_root=make_project_root(tmp_path / "seed"))
    skill_path = repo_root / "skills" / "wisdom-gen" / "SKILL.md"

    setup_block = find_bash_block(skill_path, "mega_code.client.check_auth")
    run_block = find_bash_block(skill_path, "python -m mega_code.client.run_pipeline [FLAGS]")
    run_block = run_block.replace("[FLAGS]", f"--session-id {seeded['session_id']} --poll-timeout 30")

    result, elapsed = run_bash(
        f"{setup_block}\n{run_block}",
        env=test_env,
        cwd=seeded["project_root"],
        timeout=40,
    )

    assert result.returncode == 0, result.stderr
    assert elapsed < 40
    payload = parse_last_json_line(result.stdout)
    additional_context = payload["additionalContext"]
    assert "PIPELINE COMPLETE" in additional_context
    assert "<RUN_ID>" not in additional_context
    assert "PENDING SKILLS" in additional_context
    assert list((Path(test_env["MEGA_CODE_DATA_DIR"]) / "data" / "pending-skills").glob("*/SKILL.md"))


def test_wisdom_curate_skill_bash_flow_curates_installs_saves_and_records_feedback(
    repo_root: Path, test_env: dict[str, str], tmp_path: Path, monkeypatch
):
    _apply_env(monkeypatch, test_env)
    seeded = seed_uploaded_session(tmp_path / "seed", project_root=make_project_root(tmp_path / "seed"))
    store = LocalStore()
    run_id = "wrapper-curate-run"
    store.create_run(
        run_id=run_id,
        project_id="proj-wrapper-curate",
        project_path=str(seeded["project_root"]),
        session_id=seeded["session_id"],
        steps=None,
        model="fake-local",
        include_claude=False,
        include_codex=False,
        limit=1,
        concurrency=1,
    )
    outputs = __import__("mega_code.pipeline.runtime", fromlist=["run_local_pipeline"]).run_local_pipeline(
        run_id, store=store
    )
    store.finish_run(run_id, status="completed", outputs=outputs)

    skill_path = repo_root / "skills" / "wisdom-curate" / "SKILL.md"
    setup_block = find_bash_block(skill_path, "mega_code.client.check_auth")
    curate_block = find_bash_block(skill_path, "mega-code wisdom-curate")
    install_block = find_bash_block(skill_path, "from mega_code.client.skill_installer import install_skills")
    save_block = find_bash_block(skill_path, "from mega_code.client.curation_store import save_curation")
    feedback_block = find_bash_block(skill_path, "mega-code wisdom-feedback")

    session_id = "wrapper-curate-session"
    curate_script = "\n".join(
        [
            setup_block,
            'FORMATTED_QUERY="auth token refresh workflow"',
            f'SESSION_ID="{session_id}"',
            curate_block,
        ]
    )
    curate_result, _ = run_bash(curate_script, env=test_env, cwd=seeded["project_root"], timeout=30)
    assert curate_result.returncode == 0, curate_result.stderr
    curated = json.loads(curate_result.stdout)
    assert curated["skills"]
    assert curated["operator_plan"]

    install_script = install_block.replace(
        "<JSON array of not-yet-installed skills from Step 3>",
        json.dumps(curated["skills"], indent=2),
    )
    install_result, _ = run_bash(
        "\n".join([setup_block, install_script]),
        env=test_env,
        cwd=seeded["project_root"],
        timeout=30,
    )
    assert install_result.returncode == 0, install_result.stderr
    for item in curated["skills"]:
        installed_skill = Path(test_env["MEGA_CODE_DATA_DIR"]) / "skills" / item["name"] / "SKILL.md"
        assert installed_skill.is_file()

    save_script = save_block.replace("<full curate result JSON from Step 3>", json.dumps(curated, indent=2))
    save_result, _ = run_bash(
        "\n".join([setup_block, save_script]),
        env=test_env,
        cwd=seeded["project_root"],
        timeout=30,
    )
    assert save_result.returncode == 0, save_result.stderr
    saved_curation = Path(test_env["MEGA_CODE_DATA_DIR"]) / "curations" / "pending" / f"{session_id}.json"
    assert saved_curation.is_file()

    feedback_text = """
Overall: 5/5. Strong auth refresh coverage.

Step 1 (Inspect the refresh path and map the existing failure mode first.): 5/5
- auth-refresh: applied. Helped route the test-first workflow.

Missing: none

Unexpected: The operator bundle was already well aligned.

Recommendations:
- Keep prioritizing the auth refresh operator for token workflow queries.
""".strip()
    feedback_script = "\n".join(
        [
            setup_block,
            f'SESSION_ID="{session_id}"',
            feedback_block.replace(
                """
Overall: <rating>/5. <impact estimates>

Step 1 (<step name>): <rating>/5
- <wisdom/item>: <applied|partial|not used>. <effect estimate>.

Missing: <what knowledge was needed but not provided>

Unexpected: <any surprises>

Recommendations:
- <per-item improvement suggestions>
""".strip(),
                feedback_text,
            ),
        ]
    )
    feedback_result, _ = run_bash(
        feedback_script,
        env=test_env,
        cwd=seeded["project_root"],
        timeout=30,
    )
    assert feedback_result.returncode == 0, feedback_result.stderr
    feedback_payload = parse_last_json_line(feedback_result.stdout)
    assert feedback_payload["status"] == "saved"


def test_status_skill_bash_flow_reports_active_runs_and_pending_items(
    repo_root: Path, test_env: dict[str, str], tmp_path: Path, monkeypatch
):
    _apply_env(monkeypatch, test_env)
    project_root = make_project_root(tmp_path / "workspace", name="status-project")
    data_dir = Path(test_env["MEGA_CODE_DATA_DIR"])

    pending_skill_dir = data_dir / "data" / "pending-skills" / "auth-refresh"
    pending_skill_dir.mkdir(parents=True, exist_ok=True)
    (pending_skill_dir / "SKILL.md").write_text(
        "---\ndescription: Repair auth refresh flows.\nallowed-tools: Bash, Read\n---\n",
        encoding="utf-8",
    )
    pending_strategy_dir = data_dir / "data" / "pending-strategies"
    pending_strategy_dir.mkdir(parents=True, exist_ok=True)
    (pending_strategy_dir / "auth-refresh.md").write_text("# Auth Refresh Strategy\n", encoding="utf-8")

    store = LocalStore()
    run_id = "status-live-run"
    store.create_run(
        run_id=run_id,
        project_id="proj-status",
        project_path=str(project_root),
        session_id=None,
        steps=None,
        model="fake-local",
        include_claude=False,
        include_codex=False,
        limit=1,
        concurrency=1,
    )
    store.set_run_pid(run_id, __import__("os").getpid())

    skill_path = repo_root / "skills" / "status" / "SKILL.md"
    setup_block = find_bash_block(skill_path, "mega_code.client.check_auth")
    pipeline_status_block = find_bash_block(skill_path, "mega-code pipeline-status")
    detailed_pending_block = find_bash_block(skill_path, 'echo "=== Pending Skills ==="')

    result, _ = run_bash(
        "\n".join([setup_block, pipeline_status_block, detailed_pending_block]),
        env=test_env,
        cwd=project_root,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert run_id in result.stdout
    assert "auth-refresh" in result.stdout
