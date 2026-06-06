"""Client factory for the local Ratchet runtime."""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

from ratchet.client.api.protocol import RatchetBaseClient

if TYPE_CHECKING:
    from ratchet.client.api.remote import RatchetRemote
    from ratchet.pipeline.local_client import RatchetLocal

logger = logging.getLogger(__name__)

_LEGACY_REMOTE_KWARGS = {"server_url", "api_key", "timeout"}


def create_client(mode: str | None = None, **kwargs) -> RatchetBaseClient:
    """Create a Ratchet client.

    Args:
        mode: Deprecated. Always uses local mode.
        **kwargs: Local runtime arguments. Deprecated remote arguments
            (server_url, api_key, timeout) are accepted and ignored.

    Returns:
        A RatchetBaseClient implementation.
    """

    if mode and mode != "local":
        logger.warning("Remote mode is deprecated in OSS; using local runtime instead.")
    ignored = sorted(key for key in kwargs if key in _LEGACY_REMOTE_KWARGS)
    for key in ignored:
        kwargs.pop(key, None)
    if ignored:
        logger.warning("Ignoring deprecated remote client arguments: %s", ", ".join(ignored))
    from ratchet.pipeline.local_client import RatchetLocal

    return RatchetLocal(**kwargs)


def resolve_mode(mode_arg: str | None = None) -> str:
    """Return the canonical execution mode.

    Local mode is always used. Any persisted or explicit ``remote`` selection is
    ignored with a warning to keep the runtime decision-free.
    """
    requested = mode_arg or os.environ.get("RATCHET_CLIENT_MODE", "local")
    if requested != "local":
        logger.warning("Ignoring deprecated RATCHET_CLIENT_MODE=%r; using local mode.", requested)
    return "local"


__all__ = [
    "RatchetBaseClient",
    "RatchetRemote",
    "create_client",
    "resolve_mode",
]


def __getattr__(name: str):
    if name == "RatchetRemote":
        from ratchet.client.api.remote import RatchetRemote

        return RatchetRemote
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
