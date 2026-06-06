"""Platform-aware directory resolution for mega-code."""

from __future__ import annotations

import os
import shutil
from pathlib import Path


def _default_data_dir() -> Path:
    return Path.home() / ".local" / "ratchetai"


def _legacy_data_dirs() -> tuple[Path, ...]:
    home = Path.home()
    return (
        home / ".local" / "share" / "mega-code",
        home / ".local" / "mega-code",
    )


def _merge_tree(src: Path, dst: Path) -> None:
    """Move files from ``src`` into ``dst`` without overwriting existing data."""
    dst.mkdir(parents=True, exist_ok=True)
    for entry in src.iterdir():
        target = dst / entry.name
        if entry.is_dir() and not entry.is_symlink():
            if target.exists() and target.is_dir():
                _merge_tree(entry, target)
                try:
                    entry.rmdir()
                except OSError:
                    pass
                continue
            if target.exists():
                continue
        elif target.exists():
            continue
        shutil.move(str(entry), str(target))


def _migrate_legacy_data_dirs(target_dir: Path) -> None:
    """Move legacy MEGA-Code data roots into the RatchetAI default directory."""
    for legacy_dir in _legacy_data_dirs():
        if legacy_dir == target_dir or not legacy_dir.exists() or legacy_dir.is_symlink():
            continue
        _merge_tree(legacy_dir, target_dir)
        if legacy_dir.exists():
            try:
                legacy_dir.rmdir()
            except OSError:
                continue
        legacy_dir.parent.mkdir(parents=True, exist_ok=True)
        try:
            legacy_dir.symlink_to(target_dir, target_is_directory=True)
        except FileExistsError:
            pass


def data_dir() -> Path:
    """User data root: sessions, pipeline output, skills, and config."""
    if env := os.environ.get("MEGA_CODE_DATA_DIR"):
        path = Path(env)
        path.mkdir(parents=True, exist_ok=True)
        return path

    target_dir = _default_data_dir()
    _migrate_legacy_data_dirs(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    return target_dir
