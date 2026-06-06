"""Ratchet open-source client package.

Canonical imports:
    from ratchet.client.api import create_client
    from ratchet.client.api.protocol import RatchetBaseClient
    from ratchet.client.api.remote import RatchetRemote
    from ratchet.client.models import Turn, TurnSet, SessionMetadata
    from ratchet.client.schema import SessionStats, estimate_cost
    from ratchet.client.stats import load_stats, save_stats
"""

import importlib

# Lazy re-exports so that `from ratchet.client import create_client` works
# without capturing early references (estimate_cost may be patched at runtime).
_LAZY_IMPORTS = {
    "create_client": "ratchet.client.api",
    "RatchetBaseClient": "ratchet.client.api.protocol",
    "RatchetRemote": "ratchet.client.api.remote",
    "Turn": "ratchet.client.models",
    "TurnSet": "ratchet.client.models",
    "SessionMetadata": "ratchet.client.models",
    "SessionStats": "ratchet.client.schema",
    "estimate_cost": "ratchet.client.schema",
    "load_stats": "ratchet.client.stats",
    "save_stats": "ratchet.client.stats",
}


__all__ = list(_LAZY_IMPORTS.keys())


def __getattr__(name):
    if name in _LAZY_IMPORTS:
        module = importlib.import_module(_LAZY_IMPORTS[name])
        return getattr(module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
