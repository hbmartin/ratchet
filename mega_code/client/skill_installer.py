"""Skill installer for local and remote skill references.

When ``SkillRefItem.url`` is present the installer downloads a ZIP archive.
When ``url`` is empty but ``path`` points at a local skill source, the
installer copies that source tree into the installed skills directory.
"""

from __future__ import annotations

import io
import logging
import os
import shutil
import zipfile
from pathlib import Path
from urllib.parse import urlparse

import httpx

from mega_code.client.api.protocol import SkillRefItem
from mega_code.client.dirs import data_dir

logger = logging.getLogger(__name__)

_MAX_DOWNLOAD_SIZE = min(int(os.environ.get("SKILL_MAX_DOWNLOAD_MB", "100")), 500) * 1024 * 1024
_DOWNLOAD_TIMEOUT = min(int(os.environ.get("SKILL_DOWNLOAD_TIMEOUT", "120")), 300)


def skills_dir() -> Path:
    """Skills directory: {data_dir}/skills/."""
    d = data_dir() / "skills"
    d.mkdir(parents=True, exist_ok=True)
    return d


def install_skill(skill: SkillRefItem) -> str:
    """Install a skill from a local source path or HTTPS ZIP.

    Returns: "installed" | "skipped" (no usable source).
    """
    sd = skills_dir()
    dest = (sd / skill.name).resolve()
    if not dest.is_relative_to(sd.resolve()):
        raise ValueError(f"Invalid skill name: {skill.name}")

    if dest.exists():
        shutil.rmtree(dest)

    source_path = Path(skill.path).expanduser() if skill.path else None
    if source_path and source_path.exists():
        if source_path.is_file():
            source_dir = source_path.parent
        else:
            source_dir = source_path
        if not (source_dir / "SKILL.md").exists():
            raise ValueError(f"Local skill source is missing SKILL.md: {source_dir}")
        shutil.copytree(source_dir, dest)
        logger.info("Installed local skill %s → %s", skill.name, dest)
        return "installed"

    if not skill.url:
        return "skipped"

    parsed = urlparse(skill.url)
    if parsed.scheme != "https":
        raise ValueError(f"Refusing non-HTTPS URL: {skill.url[:80]}")

    dest.mkdir(parents=True, exist_ok=True)

    resp = httpx.get(skill.url, timeout=_DOWNLOAD_TIMEOUT, follow_redirects=False)
    resp.raise_for_status()
    if len(resp.content) > _MAX_DOWNLOAD_SIZE:
        raise ValueError(f"Skill ZIP exceeds {_MAX_DOWNLOAD_SIZE // 1024 // 1024}MB limit")

    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        for info in zf.infolist():
            target = (dest / info.filename).resolve()
            if not target.is_relative_to(dest.resolve()):
                raise ValueError(f"Zip slip detected: {info.filename}")
        zf.extractall(dest)

    logger.info("Installed skill %s → %s", skill.name, dest)
    return "installed"


def install_skills(skills: list[SkillRefItem]) -> dict[str, str]:
    """Install all skills from presigned URLs. Returns {name: status}."""
    results: dict[str, str] = {}
    for skill in skills:
        try:
            results[skill.name] = install_skill(skill)
        except (OSError, ValueError, httpx.HTTPError, zipfile.BadZipFile) as e:
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
