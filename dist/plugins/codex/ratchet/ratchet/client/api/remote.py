"""Legacy remote client import path.

Ratchet no longer connects to a hosted service. ``RatchetRemote`` remains as a
compatibility shim for callers that still import or instantiate it; all methods
delegate to the local SQLite/filesystem runtime.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from ratchet.pipeline.local_client import RatchetLocal

logger = logging.getLogger(__name__)


class RatchetRemote(RatchetLocal):
    """Deprecated no-network wrapper around :class:`RatchetLocal`."""

    def __init__(
        self,
        *,
        server_url: str | None = None,
        api_key: str = "",
        timeout: float = 30.0,
        backend: str | None = None,
        project_id: str | None = None,
        model_name: str | None = None,
        db_path: Path | None = None,
        **kwargs: Any,
    ) -> None:
        if server_url or api_key or timeout != 30.0:
            logger.warning(
                "RatchetRemote is deprecated and no longer performs network calls; "
                "using the local runtime instead."
            )
        if kwargs:
            unexpected = ", ".join(sorted(kwargs))
            raise TypeError(f"Unexpected RatchetRemote argument(s): {unexpected}")
        self._legacy_server_url = server_url or "local"
        super().__init__(
            backend=backend,
            project_id=project_id,
            model_name=model_name,
            db_path=db_path,
        )

    @property
    def server_url(self) -> str:
        """Return a compatibility value for older ledger/debug code."""
        return "local"

    def close(self) -> None:
        """Compatibility no-op."""

    async def aclose(self) -> None:
        """Compatibility no-op."""

    def __enter__(self):
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.aclose()
