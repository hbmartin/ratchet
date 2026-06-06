#!/usr/bin/env python3
"""Generate committed Claude and Codex plugin packages from shared sources."""

from __future__ import annotations

import argparse
import json
import shutil
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DIST_ROOT = REPO_ROOT / "dist" / "plugins"
PLUGIN_NAME = "ratchet"
DESCRIPTION = "Self-evolving AI coding infrastructure for skills, strategies, and session learning."
AUTHOR = {"name": "Mind AI", "email": "support@ratchetai.ai"}
HOMEPAGE = "https://www.ratchetai.ai"
REPOSITORY = "https://github.com/wisdomgraph/ratchetai"
LICENSE = "Apache-2.0"
KEYWORDS = [
    "ratchet",
    "codex",
    "claude",
    "skills",
    "session-learning",
    "optimization",
]


def _project_version() -> str:
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return str(data["project"]["version"])


def _copy_tree(src: Path, dst: Path) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(
        src,
        dst,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store"),
    )


def _copy_common(root: Path, host: str) -> None:
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)

    for dirname in ("ratchet", "skills", "scripts", "assets"):
        _copy_tree(REPO_ROOT / dirname, root / dirname)

    for filename in ("pyproject.toml", "README.md", "uv.lock"):
        source = REPO_ROOT / filename
        if source.exists():
            shutil.copy2(source, root / filename)

    hooks_dir = root / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(REPO_ROOT / "hooks" / host / "hooks.json", hooks_dir / "hooks.json")


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _claude_manifest(version: str) -> dict:
    return {
        "name": PLUGIN_NAME,
        "version": version,
        "description": DESCRIPTION,
        "author": AUTHOR,
        "homepage": HOMEPAGE,
        "repository": REPOSITORY,
        "license": LICENSE,
        "keywords": KEYWORDS,
    }


def _claude_marketplace(version: str) -> dict:
    return {
        "$schema": "https://anthropic.com/claude-code/marketplace.schema.json",
        "name": "mind-ai-ratchet",
        "owner": AUTHOR,
        "metadata": {"description": DESCRIPTION},
        "plugins": [
            {
                "name": PLUGIN_NAME,
                "source": "./ratchet",
                "description": DESCRIPTION,
                "version": version,
                "author": AUTHOR,
                "category": "productivity",
                "tags": [
                    "agent-evolution",
                    "skill-extraction",
                    "session-learning",
                    "compound-intelligence",
                ],
                "homepage": HOMEPAGE,
                "repository": REPOSITORY,
                "license": LICENSE,
            }
        ],
    }


def _codex_manifest(version: str) -> dict:
    return {
        "name": PLUGIN_NAME,
        "version": version,
        "description": DESCRIPTION,
        "author": {
            "name": AUTHOR["name"],
            "email": AUTHOR["email"],
            "url": HOMEPAGE,
        },
        "homepage": HOMEPAGE,
        "repository": REPOSITORY,
        "license": LICENSE,
        "keywords": KEYWORDS,
        "skills": "./skills/",
        "interface": {
            "displayName": "Ratchet",
            "shortDescription": "Turn coding sessions into reusable skills and strategies",
            "longDescription": (
                "Ratchet collects local agent sessions, extracts reusable skills and strategies, "
                "curates workflows from local wisdom, and supports Claude and Codex as first-class hosts."
            ),
            "developerName": AUTHOR["name"],
            "category": "Developer Tools",
            "capabilities": ["Interactive", "Write"],
            "websiteURL": HOMEPAGE,
            "defaultPrompt": [
                "Use Ratchet to generate reusable skills and strategies from this project.",
                "Show my pending Ratchet items and recent pipeline status.",
            ],
            "composerIcon": "./assets/logo_ratchet.png",
            "logo": "./assets/logo_ratchet.png",
            "screenshots": [],
            "brandColor": "#2563EB",
        },
    }


def _codex_marketplace() -> dict:
    return {
        "name": "ratchet-local",
        "interface": {"displayName": "Ratchet Local"},
        "plugins": [
            {
                "name": PLUGIN_NAME,
                "source": {"source": "local", "path": "./ratchet"},
                "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
                "category": "Developer Tools",
            }
        ],
    }


def generate(dist_root: Path = DEFAULT_DIST_ROOT) -> None:
    version = _project_version()

    claude_root = dist_root / "claude" / PLUGIN_NAME
    _copy_common(claude_root, "claude")
    _write_json(claude_root / ".claude-plugin" / "plugin.json", _claude_manifest(version))
    _write_json(dist_root / "claude" / "marketplace.json", _claude_marketplace(version))

    codex_root = dist_root / "codex" / PLUGIN_NAME
    _copy_common(codex_root, "codex")
    _write_json(codex_root / ".codex-plugin" / "plugin.json", _codex_manifest(version))
    _write_json(dist_root / "codex" / ".agents" / "plugins" / "marketplace.json", _codex_marketplace())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_DIST_ROOT)
    args = parser.parse_args()
    generate(args.output_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
