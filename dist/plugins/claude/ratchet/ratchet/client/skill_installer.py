"""Skill installer for local skill references.

The local-only runtime installs from ``SkillRefItem.path``. URL-only references
are skipped because remote downloads are disabled.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from ratchet.client.api.protocol import SkillRefItem
from ratchet.client.dirs import data_dir

logger = logging.getLogger(__name__)


def skills_dir() -> Path:
    """Skills directory: {data_dir}/skills/."""
    d = data_dir() / "skills"
    d.mkdir(parents=True, exist_ok=True)
    return d


def install_skill(skill: SkillRefItem) -> str:
    """Install a skill from a local source path.

    Returns: "installed" | "skipped" (no usable source).
    """
    sd = skills_dir()
    dest = (sd / skill.name).resolve()
    if not dest.is_relative_to(sd.resolve()):
        raise ValueError(f"Invalid skill name: {skill.name}")

    source_path = Path(skill.path).expanduser() if skill.path else None
    if source_path and source_path.exists():
        if source_path.is_file():
            source_dir = source_path.parent
        else:
            source_dir = source_path
        if not (source_dir / "SKILL.md").exists():
            raise ValueError(f"Local skill source is missing SKILL.md: {source_dir}")
        source_dir = source_dir.resolve()
        if source_dir == dest:
            logger.info("Skill %s is already installed at destination", skill.name)
            return "installed"
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(source_dir, dest)
        logger.info("Installed local skill %s → %s", skill.name, dest)
        return "installed"

    if skill.url:
        logger.warning("Remote skill downloads are disabled; skipping %s", skill.name)
    return "skipped"


def install_skills(skills: list[SkillRefItem]) -> dict[str, str]:
    """Install all local skill references. Returns {name: status}."""
    results: dict[str, str] = {}
    for skill in skills:
        try:
            results[skill.name] = install_skill(skill)
        except (OSError, ValueError) as e:
            logger.warning("Failed to install skill %s: %s", skill.name, e)
            results[skill.name] = "failed"
    return results


def list_installed_skills() -> list[str]:
    """List skill names installed in the skills directory."""
    sd = skills_dir()
    return sorted(d.name for d in sd.iterdir() if d.is_dir() and (d / "SKILL.md").exists())


def get_skill_path(skill_name: str) -> Path | None:
    """Get path to an installed skill, or None if not found."""
    p = skills_dir() / skill_name
    return p if (p / "SKILL.md").exists() else None
