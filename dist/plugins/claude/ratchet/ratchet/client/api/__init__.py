"""Client factory.

The OSS runtime is now always local. Remote mode is retained only as a legacy
import path for older code, not as the default execution backend.
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

from ratchet.client.api.protocol import RatchetBaseClient
from ratchet.client.api.remote import RatchetRemote

if TYPE_CHECKING:
    from ratchet.pipeline.local_client import RatchetLocal

logger = logging.getLogger(__name__)


def create_client(mode: str | None = None, **kwargs) -> RatchetBaseClient:
    """Create a Ratchet client.

    Args:
        mode: Deprecated. Always uses local mode.
        **kwargs: Backend-specific arguments.
            local: backend, model_name, project_id, + create_store kwargs.
            remote: server_url, api_key, timeout.

    Returns:
        A RatchetBaseClient implementation.
    """

    if mode and mode != "local":
        logger.warning("Remote mode is deprecated in OSS; using local runtime instead.")
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
