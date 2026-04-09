"""Client factory.

The OSS runtime is now always local. Remote mode is retained only as a legacy
import path for older code, not as the default execution backend.
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

from mega_code.client.api.protocol import MegaCodeBaseClient
from mega_code.client.api.remote import MegaCodeRemote

if TYPE_CHECKING:
    from mega_code.pipeline.local_client import MegaCodeLocal

logger = logging.getLogger(__name__)


def create_client(mode: str | None = None, **kwargs) -> MegaCodeBaseClient:
    """Create a MEGA-Code client.

    Args:
        mode: Deprecated. Always uses local mode.
        **kwargs: Backend-specific arguments.
            local: backend, model_name, project_id, + create_store kwargs.
            remote: server_url, api_key, timeout.

    Returns:
        A MegaCodeBaseClient implementation.
    """

    if mode and mode != "local":
        logger.warning("Remote mode is deprecated in OSS; using local runtime instead.")
    from mega_code.pipeline.local_client import MegaCodeLocal

    return MegaCodeLocal(**kwargs)


def resolve_mode(mode_arg: str | None = None) -> str:
    """Return the canonical execution mode.

    Local mode is always used. Any persisted or explicit ``remote`` selection is
    ignored with a warning to keep the runtime decision-free.
    """
    requested = mode_arg or os.environ.get("MEGA_CODE_CLIENT_MODE", "local")
    if requested != "local":
        logger.warning("Ignoring deprecated MEGA_CODE_CLIENT_MODE=%r; using local mode.", requested)
    return "local"


__all__ = [
    "MegaCodeBaseClient",
    "MegaCodeRemote",
    "create_client",
    "resolve_mode",
]
