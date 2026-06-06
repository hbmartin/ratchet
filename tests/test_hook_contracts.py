"""Hook contract tests for deterministic Claude and Codex plugin execution paths."""

from __future__ import annotations

import json
from pathlib import Path

from ratchet.client.stats import get_project_folder_name
from ratchet.pipeline.store import LocalStore
from tests.helpers import make_project_root, run_bash


def _plugin_root(repo_root: Path, host: str) -> Path:
    return repo_root / "dist" / "plugins" / host / "ratchet"


def _hook_config(repo_root: Path, event_name: str, index: int = 0, host: str = "claude") -> dict:
    hooks = json.loads(
        (_plugin_root(repo_root, host) / "hooks" / "hooks.json").read_text(encoding="utf-8")
    )["hooks"]
    return hooks[event_name][index]["hooks"][0]


def _run_hook(
    repo_root: Path,
    env: dict[str, str],
    *,
    event_name: str,
    input_data: dict,
    index: int = 0,
    host: str = "claude",
) -> tuple[object, float]:
    plugin_root = _plugin_root(repo_root, host)
    hook = _hook_config(repo_root, event_name, index=index, host=host)
    command = hook["command"].replace("${CLAUDE_PLUGIN_ROOT}", str(plugin_root))
    timeout = max(10, hook["timeout"] + 5)
    env = dict(env)
    if host == "claude":
        env["CLAUDE_PLUGIN_ROOT"] = str(plugin_root)
    if host == "codex":
        env["RATCHET_PLUGIN_ROOT"] = str(plugin_root)
    return run_bash(
        command,
        env=env,
        cwd=plugin_root,
        input_text=json.dumps(input_data),
        timeout=timeout,
    )


def _bootstrap_session(repo_root: Path, env: dict[str, str], project_root: Path, session_id: str) -> Path:
    result, elapsed = _run_hook(
        repo_root,
        env,
        event_name="SessionStart",
        input_data={"session_id": session_id, "cwd": str(project_root)},
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    assert result.stderr == ""
    assert elapsed < _hook_config(repo_root, "SessionStart")["timeout"]
    project_dir = Path(env["RATCHET_DATA_DIR"]) / "projects" / get_project_folder_name(str(project_root))
    return project_dir / session_id


def test_session_start_hook_bootstraps_data_and_session(repo_root: Path, test_env: dict[str, str], tmp_path: Path):
    project_root = make_project_root(tmp_path / "workspace", name="hook-project")
    session_id = "hook-session-start"

    session_dir = _bootstrap_session(repo_root, test_env, project_root, session_id)

    data_dir = Path(test_env["RATCHET_DATA_DIR"])
    assert (data_dir / "plugin-root").read_text(encoding="utf-8").strip() == str(
        _plugin_root(repo_root, "claude")
    )
    assert (data_dir / "profile.json").read_text(encoding="utf-8") == "{}"
    assert (data_dir / ".env").is_file()
    assert (session_dir / "metadata.json").is_file()
    assert (session_dir / "stats.json").is_file()
    assert (session_dir / "events.jsonl").is_file()
    assert "run --directory" in Path(test_env["RATCHET_TEST_UV_LOG"]).read_text(encoding="utf-8")


def test_user_prompt_submit_hooks_increment_stats_and_emit_pending_notice(
    repo_root: Path, test_env: dict[str, str], tmp_path: Path
):
    project_root = make_project_root(tmp_path / "workspace", name="prompt-project")
    session_id = "hook-user-prompt"
    session_dir = _bootstrap_session(repo_root, test_env, project_root, session_id)

    prompt_result, prompt_elapsed = _run_hook(
        repo_root,
        test_env,
        event_name="UserPromptSubmit",
        input_data={"session_id": session_id},
        index=0,
    )
    assert prompt_result.returncode == 0, prompt_result.stderr
    assert prompt_result.stdout == ""
    assert prompt_result.stderr == ""
    assert prompt_elapsed < _hook_config(repo_root, "UserPromptSubmit", index=0)["timeout"]

    stats = json.loads((session_dir / "stats.json").read_text(encoding="utf-8"))
    assert stats["counts"]["user_prompts"] == 1

    pending_skill_dir = Path(test_env["RATCHET_DATA_DIR"]) / "data" / "pending-skills" / "auth-refresh"
    pending_skill_dir.mkdir(parents=True, exist_ok=True)
    (pending_skill_dir / "SKILL.md").write_text(
        "---\ndescription: Repair auth refresh flows.\nallowed-tools: Bash, Read\n---\n",
        encoding="utf-8",
    )
    (pending_skill_dir / "metadata.json").write_text("{}", encoding="utf-8")
    pending_strategy = Path(test_env["RATCHET_DATA_DIR"]) / "data" / "pending-strategies" / "auth-refresh.md"
    pending_strategy.parent.mkdir(parents=True, exist_ok=True)
    pending_strategy.write_text("# Auth Refresh Strategy\n", encoding="utf-8")

    pending_result, pending_elapsed = _run_hook(
        repo_root,
        test_env,
        event_name="UserPromptSubmit",
        input_data={"session_id": session_id},
        index=1,
    )
    assert pending_result.returncode == 0, pending_result.stderr
    assert pending_result.stderr == ""
    assert pending_elapsed < _hook_config(repo_root, "UserPromptSubmit", index=1)["timeout"]

    payload = json.loads(pending_result.stdout)
    assert payload["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"
    assert "auth-refresh" in payload["hookSpecificOutput"]["additionalContext"]


def test_stop_hook_appends_transcript_once_and_updates_stats(
    repo_root: Path, test_env: dict[str, str], tmp_path: Path
):
    project_root = make_project_root(tmp_path / "workspace", name="stop-project")
    session_id = "hook-stop"
    session_dir = _bootstrap_session(repo_root, test_env, project_root, session_id)

    transcript_path = tmp_path / "transcript.jsonl"
    transcript_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "type": "assistant",
                        "version": "1.0.0",
                        "gitBranch": "feature/auth-refresh",
                        "message": {
                            "role": "assistant",
                            "model": "claude-sonnet-test",
                            "usage": {
                                "input_tokens": 11,
                                "output_tokens": 7,
                                "cache_read_input_tokens": 2,
                                "cache_creation_input_tokens": 1,
                            },
                            "content": [
                                {"type": "text", "text": "Inspect refresh flow."},
                                {"type": "tool_use", "name": "Bash", "input": {"command": "pytest tests/test_auth.py"}},
                            ],
                        },
                    }
                ),
                json.dumps(
                    {
                        "type": "user",
                        "message": {
                            "role": "user",
                            "content": [
                                {"type": "tool_result", "content": "boom", "is_error": True}
                            ],
                        },
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    result, elapsed = _run_hook(
        repo_root,
        test_env,
        event_name="Stop",
        input_data={"session_id": session_id, "transcript_path": str(transcript_path)},
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    assert result.stderr == ""
    assert elapsed < _hook_config(repo_root, "Stop")["timeout"]

    events_lines = (session_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(events_lines) == 2
    assert (session_dir / ".transcript_offset").read_text(encoding="utf-8").strip() == "2"

    stats = json.loads((session_dir / "stats.json").read_text(encoding="utf-8"))
    metadata = json.loads((session_dir / "metadata.json").read_text(encoding="utf-8"))
    assert stats["counts"]["assistant_responses"] == 1
    assert stats["counts"]["tool_calls"] == 1
    assert stats["counts"]["errors"] == 1
    assert stats["tokens"]["total_input"] == 11
    assert stats["tokens"]["total_output"] == 7
    assert metadata["model_id"] == "claude-sonnet-test"
    assert metadata["version"] == "1.0.0"
    assert metadata["git_branch"] == "feature/auth-refresh"

    repeat_result, repeat_elapsed = _run_hook(
        repo_root,
        test_env,
        event_name="Stop",
        input_data={"session_id": session_id, "transcript_path": str(transcript_path)},
    )
    assert repeat_result.returncode == 0, repeat_result.stderr
    assert repeat_elapsed < _hook_config(repo_root, "Stop")["timeout"]
    assert len((session_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()) == 2


def test_session_end_hook_finalizes_and_uploads_trajectory(
    repo_root: Path, test_env: dict[str, str], tmp_path: Path
):
    project_root = make_project_root(tmp_path / "workspace", name="end-project")
    session_id = "hook-session-end"
    session_dir = _bootstrap_session(repo_root, test_env, project_root, session_id)

    transcript_path = tmp_path / "session-end-transcript.jsonl"
    transcript_path.write_text(
        json.dumps(
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "model": "claude-sonnet-test",
                    "usage": {"input_tokens": 5, "output_tokens": 3},
                    "content": [
                        {"type": "text", "text": "Run the focused auth test."},
                        {"type": "tool_use", "name": "Bash", "input": {"command": "pytest tests/test_auth.py"}},
                    ],
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )

    result, elapsed = _run_hook(
        repo_root,
        test_env,
        event_name="SessionEnd",
        input_data={
            "session_id": session_id,
            "reason": "end_turn",
            "transcript_path": str(transcript_path),
        },
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    assert result.stderr == ""
    assert elapsed < _hook_config(repo_root, "SessionEnd")["timeout"]

    metadata = json.loads((session_dir / "metadata.json").read_text(encoding="utf-8"))
    stats = json.loads((session_dir / "stats.json").read_text(encoding="utf-8"))
    assert metadata["ended_at"]
    assert metadata["end_reason"] == "end_turn"
    assert stats["timing"]["total_duration_ms"] >= 0
    assert (session_dir / "turns.jsonl").is_file()

    store = LocalStore(db_path=Path(test_env["RATCHET_DATA_DIR"]) / "local-runtime.sqlite3")
    saved_turnset = store.load_saved_turnset(session_id)
    assert saved_turnset is not None
    assert saved_turnset.turns


def test_codex_session_start_bootstraps_data_and_session(
    repo_root: Path, test_env: dict[str, str], tmp_path: Path
):
    project_root = make_project_root(tmp_path / "workspace", name="codex-hook-project")
    session_id = "codex-session-start"

    result, elapsed = _run_hook(
        repo_root,
        test_env,
        host="codex",
        event_name="SessionStart",
        input_data={"session_id": session_id, "cwd": str(project_root)},
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    assert result.stderr == ""
    assert elapsed < _hook_config(repo_root, "SessionStart", host="codex")["timeout"]
    data_dir = Path(test_env["RATCHET_DATA_DIR"])
    assert (data_dir / "plugin-root").read_text(encoding="utf-8").strip() == str(
        _plugin_root(repo_root, "codex")
    )
    assert (data_dir / "profile.json").read_text(encoding="utf-8") == "{}"
    assert (data_dir / "config.yaml").is_file()
    session_dir = data_dir / "projects" / get_project_folder_name(str(project_root)) / session_id
    assert (session_dir / "metadata.json").is_file()
    assert (session_dir / "stats.json").is_file()


def test_codex_pending_notification_hook(repo_root: Path, test_env: dict[str, str], tmp_path: Path):
    project_root = make_project_root(tmp_path / "workspace", name="codex-pending-project")
    session_id = "codex-pending"
    _run_hook(
        repo_root,
        test_env,
        host="codex",
        event_name="SessionStart",
        input_data={"session_id": session_id, "cwd": str(project_root)},
    )

    pending_skill_dir = Path(test_env["RATCHET_DATA_DIR"]) / "data" / "pending-skills" / "codex-auth"
    pending_skill_dir.mkdir(parents=True, exist_ok=True)
    (pending_skill_dir / "SKILL.md").write_text(
        "---\nname: codex-auth\ndescription: Repair auth flows.\nallowed-tools: Bash, Read\n---\n",
        encoding="utf-8",
    )
    (pending_skill_dir / "metadata.json").write_text("{}", encoding="utf-8")

    pending_result, _elapsed = _run_hook(
        repo_root,
        test_env,
        host="codex",
        event_name="UserPromptSubmit",
        input_data={"session_id": session_id},
        index=1,
    )

    assert pending_result.returncode == 0, pending_result.stderr
    payload = json.loads(pending_result.stdout)
    assert payload["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"
    assert "codex-auth" in payload["hookSpecificOutput"]["additionalContext"]


def test_codex_stop_import_is_best_effort(repo_root: Path, test_env: dict[str, str], tmp_path: Path):
    project_root = make_project_root(tmp_path / "workspace", name="codex-stop-project")
    result, elapsed = _run_hook(
        repo_root,
        test_env,
        host="codex",
        event_name="Stop",
        input_data={"session_id": "missing-codex-session", "cwd": str(project_root)},
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    assert result.stderr == ""
    assert elapsed < _hook_config(repo_root, "Stop", host="codex")["timeout"]


def test_codex_session_start_auto_installs_approved_items(
    repo_root: Path, test_env: dict[str, str], tmp_path: Path
):
    project_root = make_project_root(tmp_path / "workspace", name="codex-auto-install")
    data_dir = Path(test_env["RATCHET_DATA_DIR"])
    pending_skill_dir = data_dir / "data" / "pending-skills" / "auth-refresh"
    pending_skill_dir.mkdir(parents=True, exist_ok=True)
    (pending_skill_dir / "SKILL.md").write_text(
        "---\nname: auth-refresh\ndescription: Repair auth refresh flows.\nallowed-tools: Bash, Read\n---\n# Auth Refresh\n",
        encoding="utf-8",
    )
    (pending_skill_dir / "metadata.json").write_text(
        json.dumps({"safety_gate_status": "approved"}),
        encoding="utf-8",
    )
    pending_strategy = data_dir / "data" / "pending-strategies" / "auth-refresh.md"
    pending_strategy.parent.mkdir(parents=True, exist_ok=True)
    pending_strategy.write_text("# Auth Refresh Strategy\nRetry once after checking the failing request.\n", encoding="utf-8")

    result, _elapsed = _run_hook(
        repo_root,
        test_env,
        host="codex",
        event_name="SessionStart",
        input_data={"session_id": "codex-auto-install", "cwd": str(project_root)},
    )

    assert result.returncode == 0, result.stderr
    assert (project_root / ".agents" / "skills" / "auth-refresh" / "SKILL.md").is_file()
    assert (
        project_root / ".agents" / "skills" / "ratchet-strategy-auth-refresh" / "SKILL.md"
    ).is_file()
    assert not (project_root / ".claude").exists()
    assert not pending_skill_dir.exists()
    assert not pending_strategy.exists()
