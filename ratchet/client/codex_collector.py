#!/usr/bin/env python3
"""Codex hook collector for Ratchet.

Codex does not provide a SessionEnd dependency for Ratchet.  SessionStart and
UserPromptSubmit reuse the host-neutral collector paths; Stop performs a
best-effort import from Codex's native ``~/.codex/sessions`` store.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

from ratchet.client.api import create_client
from ratchet.client.collector import (
    _load_env,
    handle_session_start,
    handle_user_prompt_submit,
    output_json,
)
from ratchet.client.filters import filter_metadata, filter_turns
from ratchet.client.history.sources.codex import CodexSource
from ratchet.client.models import TurnSet
from ratchet.client.stats import get_project_folder_name
from ratchet.client.turns import extract_turns

logger = logging.getLogger(__name__)


def _read_stdin() -> dict[str, Any]:
    try:
        return json.load(sys.stdin)
    except json.JSONDecodeError:
        return {}


def _load_codex_session(input_data: dict[str, Any]):
    session_id = input_data.get("session_id") or input_data.get("sessionId")
    transcript_path = input_data.get("transcript_path") or input_data.get("transcriptPath")
    source = CodexSource()

    if transcript_path and Path(transcript_path).exists():
        path = Path(transcript_path)
        entries = source._load_jsonl_entries(path)
        if entries:
            return source._load_session_from_entries(entries, path)

    if not source.base_path.exists():
        raise KeyError("Codex sessions directory not found")

    if session_id:
        return source.load_session(str(session_id))

    cwd = input_data.get("cwd")
    if cwd:
        entries = list(source.iter_sessions_by_project_paths([str(cwd)]))
        if entries:
            latest = entries[-1]
            path = Path(latest["session_file_path"])
            return source._load_session_from_entries(source._load_jsonl_entries(path), path)

    raise KeyError("Codex session not found")


def handle_stop(input_data: dict[str, Any]) -> dict[str, Any]:
    try:
        session = _load_codex_session(input_data)
        turns, metadata = extract_turns(session)
        if not turns:
            return {}

        project_dir = metadata.project_path or input_data.get("cwd") or ""
        turns = filter_turns(turns, project_dir=project_dir)
        metadata = filter_metadata(metadata, project_dir=project_dir)
        turn_set = TurnSet(
            session_id=metadata.session_id or input_data.get("session_id", ""),
            session_dir=Path(session.metadata.extra.get("codex_session_file", "") or "."),
            turns=turns,
            metadata=metadata,
        )
        project_id = get_project_folder_name(project_dir) if project_dir else "unknown"
        client = create_client()
        client.upload_trajectory(turn_set=turn_set, project_id=project_id)
    except Exception:
        logger.debug("Codex Stop import skipped", exc_info=True)
    return {}


def main() -> int:
    _load_env()
    logging.basicConfig(
        level=logging.WARNING,
        format="%(name)s:%(levelname)s: %(message)s",
        stream=sys.stderr,
    )
    parser = argparse.ArgumentParser(description="Ratchet Codex hook collector")
    parser.add_argument(
        "--event",
        required=True,
        choices=["SessionStart", "UserPromptSubmit", "Stop"],
    )
    args = parser.parse_args()

    input_data = _read_stdin()
    handlers = {
        "SessionStart": handle_session_start,
        "UserPromptSubmit": handle_user_prompt_submit,
        "Stop": handle_stop,
    }
    result = handlers[args.event](input_data)
    if result:
        output_json(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
