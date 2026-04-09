"""Local setup gate for mega-code skills.

Usage:
    python -m mega_code.client.check_auth

Exit 0 = local provider configured, Exit 1 = missing provider key.
"""

from __future__ import annotations

import os
import sys

from mega_code.client.cli import get_env_path, load_env_file

_NOT_CONFIGURED = (
    "No local model provider configured. Set OPENAI_API_KEY or GEMINI_API_KEY "
    "with `mega-code configure --openai-api-key ...` or "
    "`mega-code configure --gemini-api-key ...`."
)


def check_auth() -> bool:
    """Check that a local provider key is configured.

    Local mode does not require a MEGA-Code API key or server reachability.
    """
    for key, value in load_env_file(get_env_path()).items():
        os.environ.setdefault(key, value)

    if os.environ.get("GEMINI_API_KEY") or os.environ.get("OPENAI_API_KEY"):
        return True
    print(_NOT_CONFIGURED)
    return False


def main() -> int:
    return 0 if check_auth() else 1


if __name__ == "__main__":
    sys.exit(main())
