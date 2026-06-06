"""Ratchet: Open-source Claude and Codex plugin runtime for AI optimization.

Collects interaction data, extracts reusable skills, and optimizes
AI workflows via the Ratchet framework.
"""

from importlib.metadata import version as _pkg_version

try:
    __version__ = _pkg_version("ratchet-agent")
except Exception:
    __version__ = "0.0.0-dev"
