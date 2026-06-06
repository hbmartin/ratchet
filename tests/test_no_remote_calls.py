"""Static guard against reintroducing remote network calls."""

from __future__ import annotations

import re
from pathlib import Path


SCAN_ROOTS = ("ratchet", "scripts", "skills", "hooks", "dist/plugins")
SCAN_SUFFIXES = {".py", ".sh", ".js", ".ts", ".tsx", ".jsx"}
ALLOWLIST_EXACT = {
    Path("scripts/generate_plugin_packages.py"),  # package metadata URLs
}
ALLOWLIST_SUFFIXES = {
    "ratchet/client/enhancement_viewer.py",  # localhost review UI
    "ratchet/client/utils/tracing.py",  # optional localhost OTEL endpoint
    "ratchet/client/skill_security_audit.py",  # audit signatures, not calls
    "ratchet/client/check_pending.py",  # documentation comment
    "scripts/check_pending_skills.py",  # documentation comment
    "scripts/generate_plugin_packages.py",  # package metadata URLs
    "skills/skill-enhance/scripts/launch-viewer.sh",  # localhost review UI
}

DISALLOWED_PATTERNS = [
    re.compile(r"\bimport\s+httpx\b"),
    re.compile(r"\bfrom\s+httpx\b"),
    re.compile(r"\bimport\s+requests\b"),
    re.compile(r"\bfrom\s+requests\b"),
    re.compile(r"\bimport\s+urllib\b"),
    re.compile(r"\bfrom\s+urllib\b"),
    re.compile(r"\bcurl\s+(?![^\n]*(?:http://localhost|http://127\.0\.0\.1))"),
    re.compile(r"https?://(?!localhost\b|127\.0\.0\.1\b|\[::1\])"),
]


def _iter_executable_repo_files(repo_root: Path):
    for root_name in SCAN_ROOTS:
        root = repo_root / root_name
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if path.is_file() and path.suffix in SCAN_SUFFIXES:
                rel = path.relative_to(repo_root)
                rel_posix = rel.as_posix()
                allowed = rel in ALLOWLIST_EXACT or any(
                    rel_posix.endswith(suffix) for suffix in ALLOWLIST_SUFFIXES
                )
                if not allowed:
                    yield rel, path


def test_no_remote_network_calls_in_runtime_files(repo_root: Path):
    findings: list[str] = []
    for rel, path in _iter_executable_repo_files(repo_root):
        text = path.read_text(encoding="utf-8", errors="ignore")
        for lineno, line in enumerate(text.splitlines(), start=1):
            for pattern in DISALLOWED_PATTERNS:
                if pattern.search(line):
                    findings.append(f"{rel}:{lineno}: {line.strip()}")
                    break

    assert not findings, "Remote network call patterns found:\n" + "\n".join(findings)
