"""Static plugin and skill contract tests."""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

MEGA_DIR_PATTERN = 'MEGA_DIR="${CLAUDE_PLUGIN_ROOT:-$(cat ~/.local/share/mega-code/plugin-root 2>/dev/null)}"'
ENV_LOAD_SNIPPET = 'set -a && . "$MEGA_DIR/.env" 2>/dev/null && set +a'
TOP_LEVEL_REF_RE = re.compile(r"(?<![A-Za-z0-9_])((?:\.claude-plugin|hooks|mega_code|scripts|skills)/[A-Za-z0-9._/-]+)")
MEGA_DIR_REF_RE = re.compile(r"\$MEGA_DIR/([A-Za-z0-9._/-]+)")
LOCAL_REF_RE = re.compile(r"(?<![A-Za-z0-9_])((?:references|scripts)/[A-Za-z0-9._/-]+)")


def _load_frontmatter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    match = re.match(r"^---\n(.*?)\n---\n", text, flags=re.DOTALL)
    assert match, f"{path} is missing YAML frontmatter at the top of the file"
    data = yaml.safe_load(match.group(1))
    assert isinstance(data, dict), f"{path} frontmatter must parse to a mapping"
    return data


def _iter_skill_refs(skill_path: Path, repo_root: Path) -> list[Path]:
    text = skill_path.read_text(encoding="utf-8")
    resolved: set[Path] = set()
    for candidate in TOP_LEVEL_REF_RE.findall(text):
        if candidate.endswith(".env"):
            continue
        candidate_path = repo_root / candidate
        if candidate.startswith("skills/") and not candidate_path.exists():
            continue
        resolved.add(candidate_path)
    for candidate in MEGA_DIR_REF_RE.findall(text):
        if candidate.endswith(".env"):
            continue
        resolved.add(repo_root / candidate)
    for candidate in LOCAL_REF_RE.findall(text):
        if candidate.endswith(".env"):
            continue
        local_path = skill_path.parent / candidate
        if local_path.exists():
            resolved.add(local_path)
        else:
            resolved.add(repo_root / candidate)
    return sorted(resolved)


def test_plugin_json_has_required_structure(repo_root: Path):
    plugin_path = repo_root / ".claude-plugin" / "plugin.json"
    plugin = json.loads(plugin_path.read_text(encoding="utf-8"))

    assert plugin["name"] == "mega-code"
    assert isinstance(plugin["description"], str) and plugin["description"].strip()
    assert isinstance(plugin["license"], str) and plugin["license"].strip()
    assert isinstance(plugin["homepage"], str) and plugin["homepage"].startswith("https://")
    assert isinstance(plugin["repository"], str) and plugin["repository"].startswith("https://")
    assert isinstance(plugin["keywords"], list) and plugin["keywords"]

    author = plugin["author"]
    assert isinstance(author, dict)
    assert isinstance(author.get("name"), str) and author["name"].strip()
    assert isinstance(author.get("email"), str) and "@" in author["email"]


def test_hooks_json_obeys_repo_contract(repo_root: Path):
    hooks_path = repo_root / "hooks" / "hooks.json"
    config = json.loads(hooks_path.read_text(encoding="utf-8"))
    hooks = config["hooks"]

    assert {"SessionStart", "SessionEnd", "UserPromptSubmit", "Stop"} <= set(hooks)

    for event_name, groups in hooks.items():
        for group in groups:
            for hook in group["hooks"]:
                assert hook["type"] == "command", f"{event_name} hook must be a command"
                command = hook["command"]
                timeout = hook["timeout"]

                assert "${CLAUDE_PLUGIN_ROOT}" in command, (
                    f"{event_name} hook must reference ${{CLAUDE_PLUGIN_ROOT}}: {command}"
                )
                assert isinstance(timeout, int) and timeout > 0
                if event_name in {"SessionStart", "SessionEnd"}:
                    assert timeout <= 30, f"{event_name} timeout must be <= 30s"
                else:
                    assert timeout <= 5, f"{event_name} timeout must be <= 5s"

                bash_match = re.search(r"\$\{CLAUDE_PLUGIN_ROOT\}/([A-Za-z0-9._/-]+)", command)
                if bash_match:
                    assert (repo_root / bash_match.group(1)).exists(), (
                        f"{event_name} hook references a missing file: {bash_match.group(1)}"
                    )
                python_match = re.search(r"python\s+([A-Za-z0-9._/-]+\.py)", command)
                if python_match:
                    assert (repo_root / python_match.group(1)).exists(), (
                        f"{event_name} hook references a missing Python entrypoint: {python_match.group(1)}"
                    )


def test_skill_markdown_frontmatter_and_repo_rules(repo_root: Path):
    skill_paths = sorted((repo_root / "skills").glob("*/SKILL.md"))
    assert skill_paths, "Expected at least one skill document"

    for skill_path in skill_paths:
        frontmatter = _load_frontmatter(skill_path)
        content = skill_path.read_text(encoding="utf-8")

        assert isinstance(frontmatter.get("description"), str) and frontmatter["description"].strip(), (
            f"{skill_path} is missing required `description` frontmatter"
        )
        allowed_tools = frontmatter.get("allowed-tools")
        assert isinstance(allowed_tools, (str, list)) and allowed_tools, (
            f"{skill_path} is missing required `allowed-tools` frontmatter"
        )

        if "uv run" in content:
            assert MEGA_DIR_PATTERN in content, (
                f"{skill_path} must resolve MEGA_DIR with the repo-standard fallback pattern"
            )
            assert ENV_LOAD_SNIPPET in content, (
                f"{skill_path} must source $MEGA_DIR/.env before Python-dependent commands"
            )
            for match in re.finditer(r"uv run", content):
                window = content[match.start() : match.start() + 160]
                assert '--directory "$MEGA_DIR"' in window, (
                    f"{skill_path} has a uv invocation without --directory \"$MEGA_DIR\": {window!r}"
                )


def test_skill_references_point_to_existing_repo_files(repo_root: Path):
    for skill_path in sorted((repo_root / "skills").glob("*/SKILL.md")):
        for referenced_path in _iter_skill_refs(skill_path, repo_root):
            assert referenced_path.exists(), (
                f"{skill_path} references a missing file or directory: {referenced_path}"
            )
