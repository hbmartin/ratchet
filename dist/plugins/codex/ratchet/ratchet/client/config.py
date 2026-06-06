"""User runtime configuration helpers for Ratchet."""

from __future__ import annotations

import logging
import os
from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml

from ratchet.client.dirs import data_dir

logger = logging.getLogger(__name__)

DEFAULT_CONFIG: dict[str, Any] = {
    "sources": {
        "ratchet": {"enabled": True},
        "claude": {"enabled": True},
        "codex": {"enabled": True},
        "cursor": {"enabled": False},
        "gemini": {"enabled": False},
        "opencode": {"enabled": False},
        "parquet": {"enabled": False, "datasets": {}},
    },
    "llm": {
        "mode": "deterministic",
        "generation_order": ["deterministic"],
        "embedding_order": ["deterministic"],
        "providers": {},
    },
}


def config_path() -> Path:
    """Path to the non-secret user config file."""
    if env_path := os.environ.get("RATCHET_CONFIG"):
        return Path(env_path).expanduser()
    return data_dir() / "config.yaml"


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_config() -> dict[str, Any]:
    """Load user config merged with Ratchet defaults."""
    path = config_path()
    if not path.exists():
        return deepcopy(DEFAULT_CONFIG)
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        logger.warning("Unable to read Ratchet config %s; using defaults: %s", path, exc)
        return deepcopy(DEFAULT_CONFIG)
    except yaml.YAMLError as exc:
        logger.warning("Unable to parse Ratchet config %s; using defaults: %s", path, exc)
        return deepcopy(DEFAULT_CONFIG)
    if not isinstance(loaded, dict):
        logger.warning("Ratchet config %s is not a mapping; using defaults.", path)
        return deepcopy(DEFAULT_CONFIG)
    return _deep_merge(DEFAULT_CONFIG, loaded)


def write_default_config_if_missing() -> Path:
    """Create ``config.yaml`` with default non-secret settings when absent."""
    path = config_path()
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(DEFAULT_CONFIG, sort_keys=False), encoding="utf-8")
    return path


def source_enabled(name: str, config: dict[str, Any] | None = None) -> bool:
    """Return whether a configured source is enabled."""
    cfg = load_config() if config is None else config
    sources = cfg.get("sources", {})
    if not isinstance(sources, dict):
        return bool(DEFAULT_CONFIG["sources"].get(name, {}).get("enabled", False))
    source_cfg = sources.get(name, {})
    if isinstance(source_cfg, dict) and "enabled" in source_cfg:
        return bool(source_cfg["enabled"])
    return bool(DEFAULT_CONFIG["sources"].get(name, {}).get("enabled", False))
