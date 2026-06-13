"""Tests for run_pipeline source defaults and terminal notifications."""

from __future__ import annotations

import argparse
import json

from ratchet.client import pending as pending_module
from ratchet.client.api.protocol import (
    OutputsResult,
    PendingSkillData,
    PendingStrategyData,
    PipelineStatusResult,
)
from ratchet.client.pending import (
    PendingResult,
    format_pipeline_notification,
    get_pending_strategies,
    save_outputs_to_pending,
)
from ratchet.client.run_pipeline import _resolve_include_flags


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


def test_project_mode_uses_source_registry_defaults(tmp_path, monkeypatch):
    monkeypatch.setenv("RATCHET_DATA_DIR", str(tmp_path / "data"))
    include_claude, include_codex = _resolve_include_flags(
        _make_args(project=""),
        env={"CODEX_SHELL": "1"},
    )

    assert include_claude is True
    assert include_codex is True


def test_explicit_source_selection_overrides_source_registry(tmp_path, monkeypatch):
    monkeypatch.setenv("RATCHET_DATA_DIR", str(tmp_path / "data"))
    include_claude, include_codex = _resolve_include_flags(
        _make_args(project="", include_claude=True),
        env={"CODEX_SHELL": "1"},
    )

    assert include_claude is True
    assert include_codex is False


def test_non_project_mode_does_not_use_project_source_defaults(tmp_path, monkeypatch):
    monkeypatch.setenv("RATCHET_DATA_DIR", str(tmp_path / "data"))
    include_claude, include_codex = _resolve_include_flags(
        _make_args(project=None),
        env={"CODEX_SHELL": "1"},
    )

    assert include_claude is False
    assert include_codex is False


def test_project_mode_does_not_require_codex_env(tmp_path, monkeypatch):
    monkeypatch.setenv("RATCHET_DATA_DIR", str(tmp_path / "data"))
    include_claude, include_codex = _resolve_include_flags(
        _make_args(project=""),
        env={"CODEX_HOME": "/tmp/codex-home"},
    )

    assert include_claude is True
    assert include_codex is True


def test_pending_save_uses_metadata_governance_for_default_fields(tmp_path, monkeypatch):
    monkeypatch.setenv("RATCHET_DATA_DIR", str(tmp_path / "data"))
    metadata = {
        "validation_level": "verified",
        "trust_tier": "trusted",
        "safety_gate_status": "approved",
        "safety_gate_reason": "verified in regression test",
    }
    status = PipelineStatusResult(
        run_id="run-1",
        project_id="project-1",
        status="completed",
        outputs=OutputsResult(
            pending_skills=[
                PendingSkillData(
                    skill_name="auth-refresh",
                    skill_md="# Auth Refresh\n",
                    injection_rules="{}",
                    evidence="[]",
                    metadata=json.dumps(metadata),
                )
            ]
        ),
    )

    result = save_outputs_to_pending(status)

    assert result.skills[0].validation_passed is True
    assert result.skills[0].validation_level == "verified"
    assert result.skills[0].trust_tier == "trusted"
    assert result.skills[0].safety_gate_status == "approved"
    assert result.skills[0].safety_gate_reason == "verified in regression test"


def test_pending_strategy_save_uses_defaults_and_body_description(tmp_path, monkeypatch):
    monkeypatch.setattr(
        pending_module,
        "PENDING_STRATEGIES_DIR",
        tmp_path / "data" / "pending-strategies",
    )
    status = PipelineStatusResult(
        run_id="run-1",
        project_id="project-1",
        status="completed",
        outputs=OutputsResult(
            pending_strategies=[
                PendingStrategyData(
                    strategy_name="retry-auth",
                    content="Retry auth refresh before rebuilding the client.\n",
                    category="",
                    validation_level="",
                    trust_tier="",
                    safety_gate_status="",
                    safety_gate_reason="",
                )
            ]
        ),
    )

    result = save_outputs_to_pending(status)

    strategy = result.strategies[0]
    assert strategy.description == "Retry auth refresh before rebuilding the client."
    assert strategy.category == "local-runtime"
    assert strategy.validation_level == "observed"
    assert strategy.trust_tier == "provisional"
    assert strategy.safety_gate_status == "review_required"
    assert strategy.safety_gate_reason == ""


def test_pending_strategy_description_fallback_skips_frontmatter(tmp_path, monkeypatch):
    strategy_dir = tmp_path / "pending-strategies"
    strategy_dir.mkdir()
    monkeypatch.setattr(pending_module, "PENDING_STRATEGIES_DIR", strategy_dir)
    (strategy_dir / "retry-auth.md").write_text(
        "\n".join(
            [
                "---",
                "category: local-runtime",
                "validation_level: observed",
                "trust_tier: provisional",
                "---",
                "",
                "Retry auth refresh before rebuilding the client.",
            ]
        ),
        encoding="utf-8",
    )

    strategies = get_pending_strategies()

    assert strategies[0].description == "Retry auth refresh before rebuilding the client."


def test_error_only_pipeline_notification_uses_error_template():
    notification = format_pipeline_notification(PendingResult(errors=["429 Too Many Requests"]))

    assert "PIPELINE ERROR" in notification
    assert "429 Too Many Requests" in notification
    assert "NO NEW OUTPUTS" not in notification
