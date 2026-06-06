#!/usr/bin/env python3
"""
Ratchet CLI - Manage the Ratchet plugin runtime for Claude and Codex.

Usage:
    ratchet status
    ratchet configure [--llm-mode deterministic|host-cli] [--host-agent claude|codex]
    ratchet login
    ratchet profile [--language <lang>] [--level <level>] [--style <style>]

Installation is handled via host plugin packages.
"""

import argparse
import json
import os
import shutil
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from ratchet.client.dirs import data_dir as get_data_dir
from ratchet.client.profile import get_profile_path

# ═══════════════════════════════════════════════════════════════════
# Path helpers
# ═══════════════════════════════════════════════════════════════════


def get_projects_data_dir() -> Path:
    """Get the data directory for project data storage."""
    return get_data_dir() / "projects"


def _get_plugin_root() -> Path | None:
    """Get the plugin root directory.

    Priority:
    1. CLAUDE_PLUGIN_ROOT environment variable (set by Claude Code)
    2. Breadcrumb file <data_dir>/plugin-root
    3. None if not found
    """
    # Check env var first (available inside hook execution)
    env_root = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if env_root:
        return Path(env_root)

    # Check breadcrumb written by session-start.sh
    breadcrumb = get_data_dir() / "plugin-root"
    if breadcrumb.exists():
        root = breadcrumb.read_text().strip()
        if root and Path(root).is_dir():
            return Path(root)

    return None


def get_env_path() -> Path:
    """Get the path to the stable .env settings file."""
    return get_data_dir() / ".env"


# ═══════════════════════════════════════════════════════════════════
# Env file helpers (used by configure)
# ═══════════════════════════════════════════════════════════════════


def load_env_file(env_path: Path) -> dict[str, str]:
    """Load environment variables from .env file using python-dotenv."""
    if not env_path.exists():
        return {}
    from dotenv import dotenv_values

    return {k: v for k, v in dotenv_values(env_path).items() if v is not None}


def save_env_file(
    env_path: Path,
    env_vars: dict[str, str],
    *,
    remove_absent: bool = False,
) -> None:
    """Save environment variables to .env file."""
    existing_lines = []
    existing_keys = set()

    if env_path.exists():
        with open(env_path) as f:
            for line in f:
                stripped = line.strip()
                if stripped and not stripped.startswith("#") and "=" in stripped:
                    key = stripped.split("=", 1)[0].strip()
                    if key in env_vars:
                        existing_lines.append(f"{key}={env_vars[key]}\n")
                        existing_keys.add(key)
                    elif not remove_absent:
                        existing_lines.append(line)
                else:
                    existing_lines.append(line)

    for key, value in env_vars.items():
        if key not in existing_keys:
            existing_lines.append(f"{key}={value}\n")

    fd = os.open(env_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.writelines(existing_lines)


# ═══════════════════════════════════════════════════════════════════
# Shared helpers
# ═══════════════════════════════════════════════════════════════════


def _load_env() -> None:
    """Load .env settings into os.environ (setdefault, won't override)."""
    for key, value in load_env_file(get_env_path()).items():
        os.environ.setdefault(key, value)


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _age_seconds(value: str | None) -> int | None:
    timestamp = _parse_iso(value)
    if timestamp is None:
        return None
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    return max(0, int((datetime.now(UTC) - timestamp.astimezone(UTC)).total_seconds()))


def _format_age(value: str | None) -> str:
    seconds = _age_seconds(value)
    if seconds is None:
        return "unknown"
    if seconds < 60:
        return f"{seconds}s"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m"
    return f"{minutes // 60}h{minutes % 60:02d}m"


def _progress_summary(progress: dict | None) -> str:
    if not progress:
        return ""
    phase = progress.get("current_phase", "")
    processed = progress.get("sessions_processed", "?")
    total = progress.get("sessions_total", "?")
    clusters_done = progress.get("clusters_processed", 0)
    clusters_total = progress.get("clusters_total", 0)
    pieces = []
    if phase:
        pieces.append(f"phase={phase}")
    pieces.append(f"sessions={processed}/{total}")
    if clusters_total:
        pieces.append(f"clusters={clusters_done}/{clusters_total}")
    return " ".join(pieces)


def _local_store():
    from ratchet.pipeline.store import LocalStore

    _load_env()
    return LocalStore()


def _provider_auth_warning() -> str | None:
    return None


def _debug_snapshot(store, run_id: str) -> dict:
    status = store.get_pipeline_status(run_id)
    row = store.get_pipeline_run_row(run_id)
    events = store.list_pipeline_events(run_id)
    llm_calls = store.list_pipeline_llm_calls(run_id)
    with store._connect() as conn:
        artifacts = [
            dict(item)
            for item in conn.execute(
                """
                SELECT artifact_id, artifact_type, name, source_path, validation_level,
                       trust_tier, safety_gate_status, created_at
                FROM artifacts
                WHERE run_id=?
                ORDER BY created_at ASC
                """,
                (run_id,),
            ).fetchall()
        ]
        trajectories = [
            dict(item)
            for item in conn.execute(
                """
                SELECT session_id, project_id, session_dir, turn_count, updated_at
                FROM trajectories
                WHERE project_id=?
                ORDER BY updated_at DESC
                LIMIT 100
                """,
                (status.project_id,),
            ).fetchall()
        ]
    return {
        "status": status.model_dump(mode="json"),
        "run": row,
        "events": events,
        "llm_calls": llm_calls,
        "artifacts": artifacts,
        "trajectories": trajectories,
    }


def _print_debug_snapshot(snapshot: dict) -> None:
    status = snapshot["status"]
    print("Pipeline Run")
    print("=" * 60)
    print(f"Run ID:     {status['run_id']}")
    print(f"Project:    {status['project_id']}")
    print(f"Status:     {status['status']}")
    print(f"Trace ID:   {status.get('trace_id') or 'unknown'}")
    print(f"Started:    {status.get('started_at') or 'unknown'}")
    print(f"Completed:  {status.get('completed_at') or 'not completed'}")
    print(f"Heartbeat:  {_format_age(status.get('last_heartbeat_at'))} ago ({status.get('heartbeat_count', 0)} beats)")
    if status.get("progress"):
        print(f"Progress:   {_progress_summary(status['progress'])}")
    if status.get("error"):
        print(f"Error:      {status['error']}")
    print(f"Run dir:    {status.get('run_dir') or 'unknown'}")
    print(f"Log path:   {status.get('log_path') or 'unknown'}")
    print(f"Events:     {status.get('events_path') or 'unknown'}")

    print("\nTimeline")
    print("-" * 60)
    for event in snapshot["events"]:
        print(
            f"{event['created_at']} [{event['level']}] "
            f"{event['phase'] or '-'} {event['event_type']}: {event['message']}"
        )

    print("\nLLM Calls")
    print("-" * 60)
    if snapshot["llm_calls"]:
        for call in snapshot["llm_calls"]:
            print(
                f"{call['call_seq']}. {call['label']} "
                f"{call['provider']}/{call['model'] or 'unknown'} "
                f"{call['call_type']} {call['status']} {call['duration_ms']}ms"
            )
            if call["prompt_path"]:
                print(f"   prompt:   {call['prompt_path']}")
            if call["response_path"]:
                print(f"   response: {call['response_path']}")
            if call["error"]:
                print(f"   error:    {call['error']}")
    else:
        print("(none)")

    print("\nArtifacts")
    print("-" * 60)
    if snapshot["artifacts"]:
        for artifact in snapshot["artifacts"]:
            print(
                f"- {artifact['artifact_type']} {artifact['name']} "
                f"[{artifact['validation_level']}/{artifact['trust_tier']}/{artifact['safety_gate_status']}]"
            )
            if artifact["source_path"]:
                print(f"  source: {artifact['source_path']}")
    else:
        print("(none)")


def _relative_file_list(root: Path) -> list[str]:
    if not root.is_dir():
        return []
    return sorted(str(path.relative_to(root)) for path in root.rglob("*") if path.is_file())


def _copy_file_to_bundle(bundle_dir: Path, source: str | None, relative_name: str) -> list[str]:
    if not source:
        return []
    source_path = Path(source)
    if not source_path.exists() or not source_path.is_file():
        return []
    target = bundle_dir / relative_name
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_path, target)
    return [relative_name]


def _copy_dir_to_bundle(bundle_dir: Path, source: Path, relative_name: str) -> list[str]:
    if not source.exists() or not source.is_dir():
        return []
    target = bundle_dir / relative_name
    shutil.copytree(source, target)
    return sorted(str(path.relative_to(bundle_dir)) for path in target.rglob("*") if path.is_file())


def _debug_bundle_command_text() -> str:
    return " ".join(["ratchet", *sys.argv[1:]])


def _create_debug_bundle(snapshot: dict, output_arg: str = "") -> dict:
    status = snapshot["status"]
    run_id = status["run_id"]
    run_dir = Path(status.get("run_dir") or get_data_dir() / "runs" / status["project_id"] / run_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    output = Path(output_arg) if output_arg else run_dir / "debug-bundle"
    output.parent.mkdir(parents=True, exist_ok=True)

    if output.exists():
        return {
            "path": str(output),
            "created": False,
            "skipped_reason": "exists",
            "files": _relative_file_list(output),
        }

    output.mkdir(parents=True)
    copied_files: list[str] = []

    (output / "snapshot.json").write_text(
        json.dumps(snapshot, indent=2, default=str),
        encoding="utf-8",
    )
    copied_files.append("snapshot.json")
    (output / "status.json").write_text(
        json.dumps(status, indent=2, default=str),
        encoding="utf-8",
    )
    copied_files.append("status.json")

    copied_files.extend(_copy_file_to_bundle(output, status.get("log_path"), "worker.log"))
    copied_files.extend(_copy_file_to_bundle(output, status.get("events_path"), "events.jsonl"))

    llm_dir = run_dir / "llm"
    copied_files.extend(_copy_dir_to_bundle(output, llm_dir, "llm"))

    for trajectory in snapshot["trajectories"]:
        session_dir = Path(trajectory["session_dir"])
        copied_files.extend(
            _copy_dir_to_bundle(output, session_dir, f"sessions/{trajectory['session_id']}")
        )

    manifest = {
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "command": _debug_bundle_command_text(),
        "run_id": run_id,
        "project_id": status["project_id"],
        "run_dir": str(run_dir),
        "bundle_dir": str(output),
        "copied_files": sorted([*copied_files, "manifest.json"]),
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2, default=str),
        encoding="utf-8",
    )
    copied_files.append("manifest.json")

    return {
        "path": str(output),
        "created": True,
        "skipped_reason": "",
        "files": sorted(copied_files),
    }


# ═══════════════════════════════════════════════════════════════════
# Commands
# ═══════════════════════════════════════════════════════════════════


def cmd_status(args: argparse.Namespace) -> int:
    """Check ratchet installation status."""
    data_root = get_data_dir()
    data_dir = get_projects_data_dir()
    plugin_root = _get_plugin_root()
    env_vars = load_env_file(get_env_path())

    print("Ratchet Status")
    print("=" * 60)

    # Check plugin installation
    print("\nPlugin:")
    if plugin_root:
        print(f"   Root: {plugin_root}")
        print("   Status: Installed (marketplace)")
    else:
        print("   Status: Not detected")
        print("   Install via: /install-plugin ratchet@mind-ai-ratchet")

    # Check profile
    profile_path = data_root / "profile.json"
    print(f"\nProfile: {profile_path}")
    if profile_path.exists():
        try:
            with open(profile_path) as f:
                profile = json.load(f)
            print(f"   Language: {profile.get('language') or 'not set'}")
            print(f"   Level: {profile.get('level') or 'not set'}")
            print(f"   Style: {profile.get('style') or 'not set'}")
        except (json.JSONDecodeError, OSError):
            print("   Status: Error reading profile")
    else:
        print("   Status: Not initialized (will be created on first session)")

    print("\nLocal Runtime:")
    print("   Client Mode: local")
    print(f"   LLM Mode: {env_vars.get('RATCHET_LLM_MODE') or 'deterministic'}")
    print(f"   Host Agent: {env_vars.get('RATCHET_HOST_AGENT') or 'auto'}")
    print("   Credentials: not required")

    # Check Python environment
    if plugin_root:
        venv_path = plugin_root / ".venv"
        print(f"\nEnvironment: {venv_path}")
        print(f"   Status: {'Ready' if venv_path.is_dir() else 'Not synced (will auto-sync)'}")

    # Check data — count sessions across all project folders
    print(f"\nData: {data_dir}")
    if data_dir.exists():
        session_count = sum(
            1
            for project_folder in data_dir.iterdir()
            if project_folder.is_dir()
            for session_dir in project_folder.iterdir()
            if session_dir.is_dir()
        )
        project_count = sum(1 for d in data_dir.iterdir() if d.is_dir())
        print(f"   Status: {session_count} sessions across {project_count} projects")
    else:
        print("   Status: No data yet")

    # Overall
    print("\n" + "=" * 60)
    if plugin_root:
        print("Ratchet is installed and ready")
        return 0
    else:
        print("Ratchet plugin not detected")
        return 1


def cmd_configure(args: argparse.Namespace) -> int:
    """Configure Ratchet settings."""
    env_path = get_env_path()

    print("Configuring Ratchet...")
    print(f"   Config file: {env_path}")

    env_vars = load_env_file(env_path)
    updated = []
    ignored = []
    removed = []

    legacy_keys = {
        "RATCHET_API_KEY",
        "RATCHET_CLIENT_MODE",
        "RATCHET_SERVER_URL",
        "OPENAI_API_KEY",
        "GEMINI_API_KEY",
        "ANTHROPIC_API_KEY",
        "RATCHET_OPENAI_COMPAT_API_KEY",
    }
    for key in sorted(legacy_keys):
        if key in env_vars:
            env_vars.pop(key, None)
            removed.append(key)

    for attr in (
        "user_id",
        "api_key",
        "server_url",
        "client_mode",
        "openai_api_key",
        "gemini_api_key",
    ):
        value = getattr(args, attr, None)
        if value:
            ignored.append(attr.replace("_", "-"))

    _CONFIG_FIELDS = [
        ("llm_mode", "RATCHET_LLM_MODE"),
        ("host_agent", "RATCHET_HOST_AGENT"),
    ]

    for attr, env_key in _CONFIG_FIELDS:
        value = getattr(args, attr, None)
        if value:
            env_vars[env_key] = value
            updated.append(f"{env_key}={value}")

    if not updated and not ignored and not removed:
        print("\nCurrent configuration:")
        for key, value in env_vars.items():
            if "TOKEN" in key or "KEY" in key:
                print(f"   {key}=***")
            else:
                print(f"   {key}={value}")
        print("\nUse --llm-mode and --host-agent to update local runtime values")
        return 0

    save_env_file(env_path, env_vars, remove_absent=True)

    if ignored:
        print("\nDeprecated remote/provider options ignored:")
        for item in ignored:
            print(f"   --{item}")
    if removed:
        print("\nRemoved stale remote/provider settings:")
        for item in removed:
            print(f"   {item}")
    print("\nConfiguration updated:")
    if updated:
        for item in updated:
            print(f"   {item}")
    else:
        print("   local runtime is ready")

    return 0


def cmd_login(args: argparse.Namespace) -> int:
    """Legacy login shim.

    Local mode no longer uses OAuth. Keep the command so existing skills and
    muscle memory do not crash, but point users at local setup.
    """
    from ratchet.client.login import run_login

    return run_login(provider=args.provider or "local")


def cmd_profile(args: argparse.Namespace) -> int:
    """View or update user profile."""
    from ratchet.client.api import create_client
    from ratchet.client.api.protocol import UserProfile

    _load_env()
    client = create_client()

    # Reset
    if args.reset:
        profile_path = get_profile_path()
        profile_existed = profile_path.exists()
        if profile_existed:
            profile_path.unlink()
        client.save_profile(profile=UserProfile())
        if profile_existed:
            print("Profile reset.")
        else:
            print("No profile to reset.")
        return 0

    has_updates = any(x is not None for x in [args.language, args.level, args.style])

    if not has_updates:
        # Show current profile via client.
        user_profile = client.load_profile()
        if all(v is None for v in [user_profile.language, user_profile.level, user_profile.style]):
            print("No profile set.")
            print("\nSet your profile with:")
            print("  ratchet profile --language English --level Expert --style Concise")
            return 0

        print("Current profile:")
        for key, value in user_profile.model_dump(by_alias=True).items():
            print(f"   {key}: {value}")
        return 0

    # Load existing from authoritative source, merge updates, save
    user_profile = client.load_profile()
    data = user_profile.model_dump(by_alias=True)

    if args.language is not None:
        data["language"] = args.language
    if args.level is not None:
        data["level"] = args.level
    if args.style is not None:
        data["style"] = args.style

    updated_profile = UserProfile(**data)
    client.save_profile(profile=updated_profile)

    print("Profile updated:")
    for key, value in updated_profile.model_dump(by_alias=True).items():
        print(f"   {key}: {value}")
    return 0


# ═══════════════════════════════════════════════════════════════════
# Pipeline control commands
# ═══════════════════════════════════════════════════════════════════


def cmd_pipeline_status(args: argparse.Namespace) -> int:
    """Show pipeline runs."""
    store = _local_store()
    try:
        runs = store.list_pipeline_runs(include_terminal=args.all, limit=args.recent)
    except Exception as e:
        print(f"Could not read local pipeline status: {e}")
        return 1

    if args.json:
        print(json.dumps([run.model_dump(mode="json") for run in runs], indent=2))
        return 0

    if not runs:
        if args.all:
            print("No pipeline runs found.")
        else:
            print("No active pipeline runs.")
        return 0

    title = "Recent pipeline runs" if args.all else "Active pipeline runs"
    print(f"{title}:\n")
    for i, run in enumerate(runs, 1):
        progress = _progress_summary(run.progress)
        heartbeat_age = _format_age(run.last_heartbeat_at)
        stale = ""
        age_seconds = _age_seconds(run.last_heartbeat_at)
        if run.status in {"queued", "running"} and age_seconds is not None and age_seconds > 120:
            stale = " | WARNING: heartbeat stale"
        line = f"  [{i}] {run.run_id} | project: {run.project_id} | status={run.status}"
        if progress:
            line += f" | {progress}"
        if run.started_at:
            line += f" | started={run.started_at}"
        line += f" | heartbeat={heartbeat_age}{stale}"
        print(line)
        if run.log_path:
            print(f"      log: {run.log_path}")
        if run.run_dir:
            print(f"      run_dir: {run.run_dir}")
        if run.error:
            print(f"      error: {run.error}")
    return 0


def cmd_pipeline_inspect(args: argparse.Namespace) -> int:
    """Show a detailed pipeline run inspection."""
    store = _local_store()
    try:
        snapshot = _debug_snapshot(store, args.run_id)
    except Exception as e:
        print(f"Could not inspect pipeline run: {e}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(snapshot, indent=2, default=str))
        return 0

    _print_debug_snapshot(snapshot)
    return 0


def cmd_pipeline_logs(args: argparse.Namespace) -> int:
    """Show or follow a pipeline worker log."""
    store = _local_store()
    try:
        status = store.get_pipeline_status(args.run_id)
    except Exception as e:
        print(f"Could not read pipeline run: {e}", file=sys.stderr)
        return 1
    if not status.log_path:
        print("No log path recorded for this run.", file=sys.stderr)
        return 1
    log_path = Path(status.log_path)
    if not log_path.exists():
        print(f"Log file does not exist: {log_path}", file=sys.stderr)
        return 1

    def print_tail() -> int:
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        selected = lines[-args.tail :] if args.tail > 0 else lines
        for line in selected:
            print(line)
        return len(lines)

    seen = print_tail()
    if not args.follow:
        return 0

    try:
        while True:
            lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
            for line in lines[seen:]:
                print(line)
            seen = len(lines)
            time.sleep(1.0)
    except KeyboardInterrupt:
        return 0


def _select_debug_run(store, run_id: str, recent: int):
    if run_id:
        return store.get_pipeline_status(run_id)

    runs = store.list_pipeline_runs(include_terminal=True, limit=recent)
    if not runs:
        raise LookupError("No pipeline runs found. Run `/ratchet:wisdom-gen` first, then retry debug.")

    for run in runs:
        heartbeat_age = _age_seconds(run.last_heartbeat_at)
        if run.status == "failed":
            return run
        if run.status in {"queued", "running"} and heartbeat_age is not None and heartbeat_age > 120:
            return run
    return runs[0]


def cmd_debug(args: argparse.Namespace) -> int:
    """Collect local evidence for a pipeline run."""
    store = _local_store()
    auth_warning = _provider_auth_warning()
    try:
        selected = _select_debug_run(store, args.run_id, args.recent)
        snapshot = _debug_snapshot(store, selected.run_id)
    except LookupError as e:
        if args.json:
            print(json.dumps({"error": str(e), "runs": []}, indent=2))
        else:
            print(str(e), file=sys.stderr)
        return 1
    except Exception as e:
        if args.json:
            print(json.dumps({"error": str(e)}, indent=2))
        else:
            print(f"Could not collect debug evidence: {e}", file=sys.stderr)
        return 1

    bundle = _create_debug_bundle(snapshot, args.output)
    status = snapshot["status"]
    payload = {
        "selected_run": {
            "run_id": status["run_id"],
            "project_id": status["project_id"],
            "status": status["status"],
            "started_at": status.get("started_at"),
            "last_heartbeat_at": status.get("last_heartbeat_at"),
            "heartbeat_age_seconds": _age_seconds(status.get("last_heartbeat_at")),
        },
        "auth_warning": auth_warning,
        "bundle": bundle,
        "paths": {
            "run_dir": status.get("run_dir"),
            "log_path": status.get("log_path"),
            "events_path": status.get("events_path"),
        },
        "snapshot": snapshot,
    }

    if args.json:
        print(json.dumps(payload, indent=2, default=str))
        return 0

    if auth_warning:
        print(f"WARNING: {auth_warning}", file=sys.stderr)

    print("Ratchet Debug Evidence")
    print("=" * 60)
    print(f"Selected run: {status['run_id']} ({status['status']})")
    print(f"Bundle dir:   {bundle['path']}")
    if not bundle["created"]:
        print(f"Bundle note:  skipped existing directory ({bundle['skipped_reason']})")
    print(f"Log path:     {status.get('log_path') or 'unknown'}")
    print(f"Events:       {status.get('events_path') or 'unknown'}")
    print()
    _print_debug_snapshot(snapshot)
    return 0


def cmd_debug_bundle(args: argparse.Namespace) -> int:
    """Create a raw local debug bundle for a pipeline run."""
    store = _local_store()
    try:
        snapshot = _debug_snapshot(store, args.run_id)
    except Exception as e:
        print(f"Could not create debug bundle: {e}", file=sys.stderr)
        return 1

    bundle = _create_debug_bundle(snapshot, args.output)
    if args.json:
        print(json.dumps(bundle, indent=2, default=str))
        return 0
    if not bundle["created"]:
        print(
            f"Debug bundle already exists; leaving it unchanged: {bundle['path']}",
            file=sys.stderr,
        )
    print(bundle["path"])
    return 0


def cmd_pipeline_stop(args: argparse.Namespace) -> int:
    """Stop a running pipeline by run_id."""
    from ratchet.client.api import create_client

    _load_env()
    client = create_client()

    try:
        result = client.stop_pipeline(run_id=args.run_id)
    except Exception as e:
        print(json.dumps({"error": str(e)}))
        return 1
    print(json.dumps(result.model_dump(), default=str))
    return 0


# ═══════════════════════════════════════════════════════════════════
def cmd_wisdom_curate(args: argparse.Namespace) -> int:
    """Curate wisdoms for a problem description."""
    from ratchet.client.api import create_client

    _load_env()
    client = create_client()

    query = " ".join(args.query)
    try:
        result = client.wisdom_curate(query=query, session_id=args.session_id, top_k=args.top_k)
    except (ConnectionError, TimeoutError, ValueError, OSError) as e:
        print(f"Wisdom curate failed: {e}", file=sys.stderr)
        return 1

    print(result.model_dump_json(indent=2))
    return 0


def cmd_wisdom_feedback(args: argparse.Namespace) -> int:
    """Submit feedback on a wisdom curate session."""
    from ratchet.client.api import create_client
    from ratchet.client.api.protocol import CausalStepFeedbackItem

    _load_env()
    client = create_client()
    step_feedback: list[CausalStepFeedbackItem] | None = None
    if args.step_feedback_json or args.step_feedback_file:
        try:
            raw_payload = (
                Path(args.step_feedback_file).read_text(encoding="utf-8")
                if args.step_feedback_file
                else args.step_feedback_json
            )
            parsed = json.loads(raw_payload)
            if isinstance(parsed, dict):
                parsed = [parsed]
            step_feedback = [CausalStepFeedbackItem.model_validate(item) for item in parsed]
        except (OSError, ValueError, TypeError) as e:
            print(f"Wisdom feedback failed: invalid step feedback payload: {e}", file=sys.stderr)
            return 1

    try:
        result = client.wisdom_feedback(
            session_id=args.session_id,
            feedback_text=args.feedback_text,
            failure_stage=args.failure_stage,
            should_abstain=args.should_abstain or None,
            step_feedback=step_feedback,
        )
    except (ConnectionError, TimeoutError, ValueError, OSError) as e:
        print(f"Wisdom feedback failed: {e}", file=sys.stderr)
        return 1

    print(result.model_dump_json(indent=2))
    return 0


# Main entry point
# ═══════════════════════════════════════════════════════════════════


def main():
    """Main entry point for the CLI."""
    parser = argparse.ArgumentParser(
        prog="ratchet",
        description="Ratchet CLI - Manage the Ratchet plugin runtime for Claude and Codex",
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Status command
    subparsers.add_parser("status", help="Check installation status")

    # Configure command
    configure_parser = subparsers.add_parser("configure", help="Configure ratchet settings")
    configure_parser.add_argument(
        "--llm-mode",
        choices=["deterministic", "host-cli"],
        help="Set local generation mode",
    )
    configure_parser.add_argument(
        "--host-agent",
        choices=["claude", "codex"],
        help="Host-agent CLI to use when --llm-mode host-cli is selected",
    )
    configure_parser.add_argument("--user-id", "-u", type=str, help=argparse.SUPPRESS)
    configure_parser.add_argument("--api-key", "-k", type=str, help=argparse.SUPPRESS)
    configure_parser.add_argument(
        "--server-url",
        type=str,
        help=argparse.SUPPRESS,
    )
    configure_parser.add_argument(
        "--client-mode",
        type=str,
        choices=["local", "remote"],
        help=argparse.SUPPRESS,
    )
    configure_parser.add_argument("--openai-api-key", type=str, help=argparse.SUPPRESS)
    configure_parser.add_argument("--gemini-api-key", type=str, help=argparse.SUPPRESS)

    # Login command (default provider imported from login module)
    login_parser = subparsers.add_parser("login", help="Show local setup status")
    login_parser.add_argument(
        "--provider",
        default=None,  # defers to login.run_login default
        help=argparse.SUPPRESS,
    )

    # Profile command
    profile_parser = subparsers.add_parser("profile", help="View or update your developer profile")
    profile_parser.add_argument(
        "--language",
        "-l",
        type=str,
        help="Preferred communication language (e.g. 'English', 'Thai')",
    )
    profile_parser.add_argument(
        "--level",
        type=str,
        choices=["Beginner", "Intermediate", "Expert"],
        help="Experience level",
    )
    profile_parser.add_argument(
        "--style",
        type=str,
        choices=["Mentor", "Formal", "Concise"],
        help="Preferred teaching style",
    )
    profile_parser.add_argument("--reset", action="store_true", help="Reset profile to defaults")

    # Pipeline status command
    pstatus_parser = subparsers.add_parser("pipeline-status", help="Show pipeline runs")
    pstatus_parser.add_argument("--all", action="store_true", help="Show recent terminal runs too")
    pstatus_parser.add_argument("--recent", type=int, default=20, help="Max runs to show (default: 20)")
    pstatus_parser.add_argument("--json", action="store_true", help="Emit JSON")

    # Pipeline stop command
    pstop_parser = subparsers.add_parser("pipeline-stop", help="Stop a running pipeline")
    pstop_parser.add_argument("--run-id", required=True, help="Run ID to stop")

    pinspect_parser = subparsers.add_parser("pipeline-inspect", help="Inspect one pipeline run")
    pinspect_parser.add_argument("--run-id", required=True, help="Run ID to inspect")
    pinspect_parser.add_argument("--json", action="store_true", help="Emit JSON")

    plogs_parser = subparsers.add_parser("pipeline-logs", help="Show or follow a worker log")
    plogs_parser.add_argument("--run-id", required=True, help="Run ID to inspect")
    plogs_parser.add_argument("--tail", type=int, default=80, help="Lines to print first (default: 80)")
    plogs_parser.add_argument("--follow", action="store_true", help="Follow the log")

    debug_parser = subparsers.add_parser("debug", help="Collect local pipeline debug evidence")
    debug_parser.add_argument("--run-id", default="", help="Run ID to debug")
    debug_parser.add_argument("--recent", type=int, default=10, help="Recent runs to consider (default: 10)")
    debug_parser.add_argument("--output", default="", help="Output bundle directory")
    debug_parser.add_argument("--json", action="store_true", help="Emit JSON")

    bundle_parser = subparsers.add_parser("debug-bundle", help="Create a raw pipeline debug bundle directory")
    bundle_parser.add_argument("--run-id", required=True, help="Run ID to bundle")
    bundle_parser.add_argument("--output", default="", help="Output bundle directory")
    bundle_parser.add_argument("--json", action="store_true", help="Emit JSON")

    # Wisdom curate command
    curate_parser = subparsers.add_parser("wisdom-curate", help="Curate wisdoms for a problem")
    curate_parser.add_argument("query", nargs="+", help="Problem description")
    curate_parser.add_argument("--session-id", default="", help="Session ID for linking feedback")
    curate_parser.add_argument("--top-k", type=int, default=20, help="Max wisdoms to retrieve")

    # Wisdom feedback command
    fb_parser = subparsers.add_parser("wisdom-feedback", help="Submit feedback on a curate session")
    fb_parser.add_argument("--session-id", required=True, help="Session ID from curate")
    fb_parser.add_argument("--feedback-text", required=True, help="Natural language feedback")
    fb_parser.add_argument(
        "--failure-stage",
        default="unknown",
        choices=["none", "retrieval", "execution", "mixed", "unknown"],
        help="Where the miss occurred",
    )
    fb_parser.add_argument(
        "--should-abstain",
        action="store_true",
        help="Mark that the system should have abstained instead of recommending a step",
    )
    fb_parser.add_argument(
        "--step-feedback-json",
        default="",
        help="Inline JSON object or array with per-step causal feedback",
    )
    fb_parser.add_argument(
        "--step-feedback-file",
        default="",
        help="Path to JSON file with per-step causal feedback",
    )

    args = parser.parse_args()

    match args.command:
        case None:
            parser.print_help()
            return 1
        case "status":
            return cmd_status(args)
        case "configure":
            return cmd_configure(args)
        case "login":
            return cmd_login(args)
        case "profile":
            return cmd_profile(args)
        case "pipeline-status":
            return cmd_pipeline_status(args)
        case "pipeline-stop":
            return cmd_pipeline_stop(args)
        case "pipeline-inspect":
            return cmd_pipeline_inspect(args)
        case "pipeline-logs":
            return cmd_pipeline_logs(args)
        case "debug":
            return cmd_debug(args)
        case "debug-bundle":
            return cmd_debug_bundle(args)
        case "wisdom-curate":
            return cmd_wisdom_curate(args)
        case "wisdom-feedback":
            return cmd_wisdom_feedback(args)
        case _:
            return 0


if __name__ == "__main__":
    sys.exit(main())
