"""Shared profile I/O — used by both cli.py and client/api/remote.py.

Provides get_profile_path(), load_profile(), and save_profile() without
creating circular imports between the CLI and client layers.
"""

import json
from pathlib import Path

from ratchet.client.api.protocol import UserProfile
from ratchet.client.utils.io import atomic_write


def get_profile_path() -> Path:
    """Get the path to the user profile file."""
    from ratchet.client.dirs import data_dir

    return data_dir() / "profile.json"


def load_profile() -> UserProfile:
    """Load user profile from disk. Returns default UserProfile if no profile."""
    path = get_profile_path()
    if not path.exists():
        return UserProfile()
    data = json.loads(path.read_text(encoding="utf-8"))
    return UserProfile(**data)


def save_profile(profile: UserProfile | dict) -> None:
    """Save user profile to disk (atomic write).

    Ensures all default fields are included by round-tripping through UserProfile.

    Args:
        profile: UserProfile instance or dict of profile fields.
    """
    if isinstance(profile, dict):
        profile = UserProfile(**profile)
    content = json.dumps(profile.model_dump(by_alias=True), indent=2)
    atomic_write(get_profile_path(), content)
