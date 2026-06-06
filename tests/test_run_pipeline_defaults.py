"""Tests for run_pipeline source defaults and terminal notifications."""

from __future__ import annotations

import argparse

from mega_code.client.pending import PendingResult, format_pipeline_notification
from mega_code.client.run_pipeline import _resolve_include_flags


def _make_args(
    *,
    project: str | None,
    include_claude: bool = False,
    include_codex: bool = False,
    include_all: bool = False,
) -> argparse.Namespace:
    return argparse.Namespace(
        project=project,
        include_claude=include_claude,
        include_codex=include_codex,
        include_all=include_all,
    )


def test_project_mode_in_codex_includes_codex_by_default():
    include_claude, include_codex = _resolve_include_flags(
        _make_args(project=""),
        env={"CODEX_SHELL": "1"},
    )

    assert include_claude is False
    assert include_codex is True


def test_explicit_source_selection_disables_codex_autoinclude():
    include_claude, include_codex = _resolve_include_flags(
        _make_args(project="", include_claude=True),
        env={"CODEX_SHELL": "1"},
    )

    assert include_claude is True
    assert include_codex is False


def test_non_project_mode_does_not_autoinclude_codex():
    include_claude, include_codex = _resolve_include_flags(
        _make_args(project=None),
        env={"CODEX_SHELL": "1"},
    )

    assert include_claude is False
    assert include_codex is False


def test_error_only_pipeline_notification_uses_error_template():
    notification = format_pipeline_notification(PendingResult(errors=["429 Too Many Requests"]))

    assert "PIPELINE ERROR" in notification
    assert "429 Too Many Requests" in notification
    assert "NO NEW OUTPUTS" not in notification
