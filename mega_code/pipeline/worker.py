"""Detached local worker entrypoint."""

from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
from pathlib import Path

from mega_code.pipeline.runtime import run_local_pipeline
from mega_code.pipeline.store import LocalStore

logger = logging.getLogger(__name__)


def _handle_sigterm(signum: int, frame) -> None:  # noqa: ARG001
    raise SystemExit(0)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a local MEGA-Code pipeline worker.")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--db-path", default="")
    parser.add_argument("--pid", type=int, default=0)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    signal.signal(signal.SIGTERM, _handle_sigterm)
    store = LocalStore(db_path=None if not args.db_path else Path(args.db_path))
    try:
        store.set_run_pid(args.run_id, os.getpid())
        outputs = run_local_pipeline(args.run_id, store=store)
        if store.is_stop_requested(args.run_id):
            store.finish_run(args.run_id, status="stopped", outputs=outputs, error="Stopped by user.")
        else:
            store.finish_run(args.run_id, status="completed", outputs=outputs)
        return 0
    except SystemExit:
        store.finish_run(args.run_id, status="stopped", error="Stopped by user.")
        return 0
    except Exception as exc:  # noqa: BLE001
        logger.exception("Local pipeline worker failed")
        store.finish_run(args.run_id, status="failed", error=str(exc))
        return 1


if __name__ == "__main__":
    sys.exit(main())
