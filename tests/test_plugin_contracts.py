"""Static plugin and skill contract tests."""

from __future__ import annotations

import json
import re
import subprocess
import tomllib
from pathlib import Path

import yaml

RATCHET_DIR_PATTERN = (
    'RATCHET_DIR="${RATCHET_PLUGIN_ROOT:-${CLAUDE_PLUGIN_ROOT:-'
    '${CODEX_PLUGIN_ROOT:-$(cat ~/.local/ratchet/plugin-root 2>/dev/null)}}}"'
)
ENV_LOAD_SNIPPET = 'set -a && . "$RATCHET_DIR/.env" 2>/dev/null && set +a'
TOP_LEVEL_REF_RE = re.compile(
    r"(?<![A-Za-z0-9_/])((?:assets|hooks|ratchet|scripts|skills)/[A-Za-z0-9._/-]+)"
)
RATCHET_DIR_REF_RE = re.compile(r"\$RATCHET_DIR/([A-Za-z0-9._/-]+)")
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
    for candidate in RATCHET_DIR_REF_RE.findall(text):
        if candidate.endswith(".env"):
            continue
        resolved.add(repo_root / candidate)
    for candidate in LOCAL_REF_RE.findall(text):
        if candidate.endswith(".env"):
            continue
        local_path = skill_path.parent / candidate
        resolved.add(local_path if local_path.exists() else repo_root / candidate)
    return sorted(resolved)


def _files_under(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
        and ".venv" not in path.relative_to(root).parts
        and "__pycache__" not in path.relative_to(root).parts
        and path.name != ".env"
    }


def test_python_distribution_identity(repo_root: Path):
    pyproject = tomllib.loads((repo_root / "pyproject.toml").read_text(encoding="utf-8"))
    project = pyproject["project"]

    assert project["name"] == "ratchet-agent"
    assert project["version"] == "2.0.0b1"
    assert project["scripts"]["ratchet"] == "ratchet.client.cli:main"
    assert pyproject["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"] == ["ratchet"]


def test_generated_package_manifests(repo_root: Path):
    claude = json.loads(
        (repo_root / "dist" / "plugins" / "claude" / "ratchet" / ".claude-plugin" / "plugin.json").read_text(
            encoding="utf-8"
        )
    )
    codex = json.loads(
        (repo_root / "dist" / "plugins" / "codex" / "ratchet" / ".codex-plugin" / "plugin.json").read_text(
            encoding="utf-8"
        )
    )

    for manifest in (claude, codex):
        assert manifest["name"] == "ratchet"
        assert manifest["version"] == "2.0.0b1"
        assert manifest["homepage"].startswith("https://")
        assert manifest["repository"].startswith("https://")
        assert manifest["license"] == "Apache-2.0"
        assert "ratchet" in manifest["keywords"]

    assert codex["skills"] == "./skills/"
    assert codex["interface"]["displayName"] == "Ratchet"
    assert codex["interface"]["composerIcon"] == "./assets/logo_ratchet.png"


def test_codex_marketplace_file(repo_root: Path):
    marketplace = json.loads(
        (repo_root / "dist" / "plugins" / "codex" / ".agents" / "plugins" / "marketplace.json").read_text(
            encoding="utf-8"
        )
    )
    entry = marketplace["plugins"][0]

    assert marketplace["name"] == "ratchet-local"
    assert entry["name"] == "ratchet"
    assert entry["source"] == {"source": "local", "path": "./ratchet"}
    assert entry["policy"] == {"installation": "AVAILABLE", "authentication": "ON_INSTALL"}
    assert entry["category"] == "Developer Tools"


def _assert_hook_config(repo_root: Path, host: str, expected_events: set[str]) -> None:
    hooks_path = repo_root / "dist" / "plugins" / host / "ratchet" / "hooks" / "hooks.json"
    hooks = json.loads(hooks_path.read_text(encoding="utf-8"))["hooks"]
    assert set(hooks) == expected_events

    for event_name, groups in hooks.items():
        for group in groups:
            for hook in group["hooks"]:
                assert hook["type"] == "command"
                assert isinstance(hook["timeout"], int) and hook["timeout"] > 0
                if event_name in {"SessionStart", "SessionEnd"}:
                    assert hook["timeout"] <= 30
                else:
                    assert hook["timeout"] <= 5


def test_generated_hook_configs(repo_root: Path):
    _assert_hook_config(
        repo_root,
        "claude",
        {"SessionStart", "SessionEnd", "UserPromptSubmit", "Stop"},
    )
    _assert_hook_config(repo_root, "codex", {"SessionStart", "UserPromptSubmit", "Stop"})


def test_skill_markdown_frontmatter_and_repo_rules(repo_root: Path):
    skill_paths = sorted((repo_root / "skills").glob("*/SKILL.md"))
    assert skill_paths, "Expected at least one skill document"

    for skill_path in skill_paths:
        frontmatter = _load_frontmatter(skill_path)
        content = skill_path.read_text(encoding="utf-8")

        assert isinstance(frontmatter.get("name"), str)
        assert frontmatter["name"].startswith("ratchet-")
        assert isinstance(frontmatter.get("description"), str) and frontmatter["description"].strip()
        allowed_tools = frontmatter.get("allowed-tools")
        assert isinstance(allowed_tools, (str, list)) and allowed_tools

        if "uv run" in content:
            assert RATCHET_DIR_PATTERN in content
            assert ENV_LOAD_SNIPPET in content
            for match in re.finditer(r"uv run", content):
                window = content[match.start() : match.start() + 180]
                assert '--directory "$RATCHET_DIR"' in window


def test_codex_skill_metadata(repo_root: Path):
    for skill_path in sorted((repo_root / "skills").glob("*/SKILL.md")):
        openai_yaml = skill_path.parent / "agents" / "openai.yaml"
        assert openai_yaml.is_file(), f"{skill_path} is missing Codex skill metadata"
        data = yaml.safe_load(openai_yaml.read_text(encoding="utf-8"))
        interface = data["interface"]
        for key in ("display_name", "short_description", "icon_small", "icon_large", "default_prompt"):
            assert isinstance(interface.get(key), str) and interface[key].strip()
        assert (openai_yaml.parent / interface["icon_small"]).resolve().is_file()
        assert (openai_yaml.parent / interface["icon_large"]).resolve().is_file()


def test_skill_references_point_to_existing_repo_files(repo_root: Path):
    for skill_path in sorted((repo_root / "skills").glob("*/SKILL.md")):
        for referenced_path in _iter_skill_refs(skill_path, repo_root):
            assert referenced_path.exists(), (
                f"{skill_path} references a missing file or directory: {referenced_path}"
            )


def test_generated_plugin_artifacts_are_current(repo_root: Path, tmp_path: Path):
    output_root = tmp_path / "plugins"
    subprocess.run(
        [
            "uv",
            "run",
            "python",
            "scripts/generate_plugin_packages.py",
            "--output-root",
            str(output_root),
        ],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )

    committed = repo_root / "dist" / "plugins"
    assert _files_under(committed) == _files_under(output_root)
