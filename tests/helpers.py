"""Test helpers for subprocess execution and seeded local-runtime state."""

from __future__ import annotations

import json
import re
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any

from ratchet.client.api import create_client
from ratchet.client.models import SessionMetadata, Turn, TurnSet


def make_project_root(tmp_path: Path, *, name: str = "repo") -> Path:
    """Create a small project tree that produces meaningful runtime fingerprints."""
    project_root = tmp_path / name
    (project_root / "src" / "auth").mkdir(parents=True, exist_ok=True)
    (project_root / "tests").mkdir(parents=True, exist_ok=True)
    (project_root / "src" / "auth" / "refresh.py").write_text(
        "def refresh_token(existing_token: str) -> str:\n    return existing_token + '-refreshed'\n",
        encoding="utf-8",
    )
    (project_root / "tests" / "test_auth.py").write_text(
        "from src.auth.refresh import refresh_token\n\n\ndef test_refresh_token():\n    assert refresh_token('abc') == 'abc-refreshed'\n",
        encoding="utf-8",
    )
    (project_root / "pyproject.toml").write_text(
        """
[project]
name = "ratchet-test-project"
version = "0.1.0"
dependencies = ["fastapi", "pytest"]
""".strip()
        + "\n",
        encoding="utf-8",
    )
    (project_root / "uv.lock").write_text("version = 1\n", encoding="utf-8")
    return project_root


def make_turnset(session_id: str, session_dir: Path, project_root: Path) -> TurnSet:
    """Build a representative turnset for local distillation and curation tests."""
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
            Turn(
                turn_id=1,
                role="user",
                content=(
                    "Fix the auth token refresh flow in src/auth/refresh.py and verify the "
                    "tests while keeping OPENAI_API_KEY handling intact."
                ),
            ),
            Turn(
                turn_id=2,
                role="assistant",
                content="Inspect the refresh path and map the existing failure mode first.",
            ),
            Turn(
                turn_id=3,
                role="assistant",
                content="Search the refresh code and test coverage before editing.",
                command='rg -n "refresh_token|OPENAI_API_KEY" src/auth/refresh.py tests/test_auth.py',
            ),
            Turn(
                turn_id=4,
                role="assistant",
                content="Patch the refresh implementation and rerun the focused test.",
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


def seed_uploaded_session(
    tmp_path: Path,
    *,
    project_id: str = "proj-local",
    project_root: Path | None = None,
) -> dict[str, Any]:
    """Create a project and upload one local trajectory into the runtime store."""
    project_root = project_root or make_project_root(tmp_path)
    session_id = str(uuid.uuid4())
    session_dir = tmp_path / "collector" / session_id
    turn_set = make_turnset(session_id, session_dir, project_root)
    client = create_client()
    upload = client.upload_trajectory(turn_set=turn_set, project_id=project_id)
    return {
        "client": client,
        "project_id": project_id,
        "project_root": project_root,
        "session_id": session_id,
        "session_dir": session_dir,
        "turn_set": turn_set,
        "upload": upload,
    }


def wait_for_completion(run_id: str, timeout: float = 20.0):
    """Poll the local client until a run reaches a terminal state."""
    client = create_client()
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = client.get_pipeline_status(run_id=run_id)
        if status.status in {"completed", "failed", "stopped", "timeout"}:
            return status
        time.sleep(0.1)
    raise TimeoutError(f"Timed out waiting for local run {run_id}")


def run_subprocess(
    argv: list[str],
    *,
    env: dict[str, str],
    cwd: Path,
    input_text: str = "",
    timeout: float = 20.0,
) -> tuple[subprocess.CompletedProcess[str], float]:
    """Run a subprocess and return the completed process plus wall-clock time."""
    started = time.monotonic()
    result = subprocess.run(
        argv,
        cwd=cwd,
        env=env,
        input=input_text,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    return result, time.monotonic() - started


def run_bash(
    script: str,
    *,
    env: dict[str, str],
    cwd: Path,
    input_text: str = "",
    timeout: float = 20.0,
) -> tuple[subprocess.CompletedProcess[str], float]:
    """Run a bash script with the supplied environment and stdin."""
    return run_subprocess(
        ["bash", "-c", script],
        env=env,
        cwd=cwd,
        input_text=input_text,
        timeout=timeout,
    )


def parse_last_json_line(output: str) -> dict[str, Any]:
    """Parse the last JSON object emitted in a mixed stdout stream."""
    stripped = output.strip()
    if stripped:
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            pass
    for line in reversed(output.splitlines()):
        candidate = line.strip()
        if not candidate:
            continue
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    raise ValueError(f"No JSON object found in output:\n{output}")


def extract_bash_blocks(markdown_path: Path) -> list[str]:
    """Extract fenced bash code blocks from a skill document."""
    text = markdown_path.read_text(encoding="utf-8")
    return re.findall(r"```bash\n(.*?)```", text, flags=re.DOTALL)


def find_bash_block(markdown_path: Path, needle: str) -> str:
    """Return the first bash code block containing ``needle``."""
    for block in extract_bash_blocks(markdown_path):
        if needle in block:
            return block.strip()
    raise AssertionError(f"Unable to find bash block containing {needle!r} in {markdown_path}")
