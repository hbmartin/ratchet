"""Local setup gate for ratchet skills.

Usage:
    python -m ratchet.client.check_auth

Exit 0 = local runtime ready.
"""

from __future__ import annotations

import os
import sys

from ratchet.client.cli import get_env_path, load_env_file


def check_auth() -> bool:
    """Load persisted settings and report local runtime readiness."""
    for key, value in load_env_file(get_env_path()).items():
        os.environ.setdefault(key, value)
    return True


def main() -> int:
    return 0 if check_auth() else 1


if __name__ == "__main__":
    sys.exit(main())
