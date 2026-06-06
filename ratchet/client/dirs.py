"""Platform-aware directory resolution for ratchet."""

from __future__ import annotations

import os
from pathlib import Path


def _default_data_dir() -> Path:
    return Path.home() / ".local" / "ratchet"


def data_dir() -> Path:
    """User data root: sessions, pipeline output, skills, and config."""
    if env := os.environ.get("RATCHET_DATA_DIR"):
        path = Path(env)
        path.mkdir(parents=True, exist_ok=True)
        return path

    target_dir = _default_data_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    return target_dir
