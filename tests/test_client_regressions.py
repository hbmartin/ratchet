"""Regression tests for client utility review fixes."""

from __future__ import annotations

import argparse
from pathlib import Path

from ratchet.client import cli
from ratchet.client import config as config_module
from ratchet.client.compaction import CodeBlockCompactor
from ratchet.client.filters.secrets import SecretMasker
from ratchet.client.skill_utils import ensure_strategy_frontmatter, parse_frontmatter
from ratchet.client.utils.io import atomic_write
from ratchet.client.utils.path_utils import normalize_path


def test_secret_masker_masks_non_bearer_authorization_headers():
    masker = SecretMasker()

    masked = masker.filter_text(
        "Authorization: Basic dXNlcjpwYXNz\n"
        "Authorization: Bearer token-123\n"
        "Authorization: CustomScheme abc123"
    )

    assert masked == "Authorization: ****\nAuthorization: ****\nAuthorization: ****"


def test_atomic_write_uses_replace_for_existing_targets(tmp_path, monkeypatch):
    target = tmp_path / "profile.json"
    target.write_text("old", encoding="utf-8")
    replace_calls: list[tuple[Path, Path]] = []
    original_replace = Path.replace

    def record_replace(self: Path, other: Path) -> Path:
        replace_calls.append((self, Path(other)))
        return original_replace(self, other)

    monkeypatch.setattr(Path, "replace", record_replace)

    atomic_write(target, "new")

    assert target.read_text(encoding="utf-8") == "new"
    assert replace_calls == [(target.with_suffix(".tmp"), target)]


def test_source_enabled_honors_explicit_empty_config(monkeypatch):
    monkeypatch.setattr(
        config_module,
        "load_config",
        lambda: {"sources": {"claude": {"enabled": False}}},
    )

    assert config_module.source_enabled("claude", {}) is True


def test_normalize_path_preserves_case(tmp_path):
    project_path = tmp_path / "CamelCaseProject"
    project_path.mkdir()

    normalized = normalize_path(project_path)

    assert normalized == project_path.resolve()
    assert normalized.name == "CamelCaseProject"


def test_code_block_compactor_handles_info_strings_and_regex_prefixes():
    compactor = CodeBlockCompactor(prefix="CODE.BLOCK")
    content = 'before\n```tsx title="Widget"\nconst x = 1;\n```\nafter'

    result = compactor.compact(content)

    assert "[CODE.BLOCK_0_1_LINES]" in result.compacted
    assert "const x = 1;" not in result.compacted
    assert compactor.restore(result.compacted, result.code_blocks) == content


def test_ensure_strategy_frontmatter_leaves_unclosed_frontmatter_unchanged():
    content = "---\ncategory: broken\n# Strategy Body\n"

    assert ensure_strategy_frontmatter(content, "local-runtime") == content


def test_ensure_strategy_frontmatter_keeps_core_fields_ahead_of_extra_fields():
    rendered = ensure_strategy_frontmatter(
        "Use retries before rebuilding the client.\n",
        "local-runtime",
        author="ratchet",
        version="1.2.3",
        extra_frontmatter={
            "category": "override",
            "author": "override",
            "version": "9.9.9",
            "validation_level": "verified",
        },
    )

    frontmatter = parse_frontmatter(rendered)

    assert frontmatter["category"] == "local-runtime"
    assert frontmatter["author"] == "ratchet"
    assert frontmatter["version"] == "1.2.3"
    assert frontmatter["validation_level"] == "verified"


def test_pipeline_logs_follow_streams_new_lines_without_rereading(tmp_path, monkeypatch, capsys):
    log_path = tmp_path / "worker.log"
    log_path.write_text("line one\nline two\nline three\n", encoding="utf-8")

    class Store:
        def get_pipeline_status(self, run_id: str):
            return argparse.Namespace(log_path=str(log_path))

    monkeypatch.setattr(cli, "_local_store", lambda: Store())
    monkeypatch.setattr(
        Path,
        "read_text",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("read_text called")),
    )

    sleep_calls = 0

    def fake_sleep(seconds: float) -> None:
        nonlocal sleep_calls
        sleep_calls += 1
        if sleep_calls == 1:
            with open(log_path, "a", encoding="utf-8") as log_file:
                log_file.write("line four\n")
            return
        raise KeyboardInterrupt

    monkeypatch.setattr(cli.time, "sleep", fake_sleep)

    exit_code = cli.cmd_pipeline_logs(argparse.Namespace(run_id="run-1", tail=2, follow=True))

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "line one" not in output
    assert "line two" in output
    assert "line three" in output
    assert "line four" in output
