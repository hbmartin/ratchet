"""Path matching utilities for session enrichment."""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def normalize_path(path: str | Path) -> Path:
    """Normalize path for comparison.

    Resolves symlinks and relative paths while preserving path casing.

    Args:
        path: Path to normalize (string or Path object)

    Returns:
        Normalized Path object (resolved)

    Example:
        >>> normalize_path("/Users/Foo/Project")
        PosixPath('/Users/Foo/Project')
    """
    return Path(path).resolve()


def should_include_session(
    claude_project_path: str | Path,
    ratchet_project_paths: set[Path],
    exact_match: bool = False,
) -> bool:
    """Check if Claude session should be included based on project path.

    Args:
        claude_project_path: Project path from Claude session
        ratchet_project_paths: Set of normalized Ratchet project paths
        exact_match: If False, subdirectories are also included (default).
                    If True, only exact matches are included.

    Returns:
        True if session should be included

    Example:
        >>> ratchet_paths = {normalize_path("/Users/foo/project")}
        >>> should_include_session("/Users/foo/project", ratchet_paths)
        True
        >>> should_include_session("/Users/foo/project/backend", ratchet_paths)
        True
        >>> should_include_session("/Users/foo/project/backend", ratchet_paths, exact_match=True)
        False
    """
    if not ratchet_project_paths:
        return False

    normalized = normalize_path(claude_project_path)

    for ratchet_path in ratchet_project_paths:
        # Exact match
        if normalized == ratchet_path:
            return True

        # Subdirectory match (only if exact_match is False)
        if not exact_match:
            try:
                if normalized.is_relative_to(ratchet_path):
                    return True
            except (ValueError, TypeError):
                # is_relative_to raises ValueError if paths are on different drives (Windows)
                # or TypeError for invalid inputs - continue to next path
                pass

    return False
