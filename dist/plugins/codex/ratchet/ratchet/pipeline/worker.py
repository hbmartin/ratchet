"""Detached local worker entrypoint."""

from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
import traceback
from pathlib import Path

from ratchet.pipeline.runtime import run_local_pipeline
from ratchet.pipeline.store import LocalStore

logger = logging.getLogger(__name__)


def _handle_sigterm(signum: int, frame) -> None:
    raise SystemExit(0)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a local Ratchet pipeline worker.")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--db-path", default="")
    parser.add_argument("--pid", type=int, default=0)
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format=f"%(asctime)s %(levelname)s run_id={args.run_id} %(message)s",
    )
    signal.signal(signal.SIGTERM, _handle_sigterm)
    store = LocalStore(db_path=None if not args.db_path else Path(args.db_path))
    try:
        logger.info("Local pipeline worker starting pid=%s", os.getpid())
        store.set_run_pid(args.run_id, os.getpid())
        store.record_pipeline_event(
            args.run_id,
            event_type="worker_started",
            message="Local pipeline worker started.",
            phase="starting",
            payload={"pid": os.getpid()},
        )
        outputs = run_local_pipeline(args.run_id, store=store)
        if store.is_stop_requested(args.run_id):
            logger.info("Local pipeline worker stopped by user")
            store.record_pipeline_event(
                args.run_id,
                event_type="worker_stopped",
                message="Local pipeline worker stopped by user.",
                phase="stopped",
            )
            store.finish_run(args.run_id, status="stopped", outputs=outputs, error="Stopped by user.")
        else:
            logger.info("Local pipeline worker completed")
            store.record_pipeline_event(
                args.run_id,
                event_type="worker_completed",
                message="Local pipeline worker completed.",
                phase="completed",
            )
            store.finish_run(args.run_id, status="completed", outputs=outputs)
        return 0
    except SystemExit:
        logger.info("Local pipeline worker received stop signal")
        store.record_pipeline_event(
            args.run_id,
            event_type="worker_stopped",
            message="Local pipeline worker received a stop signal.",
            phase="stopped",
        )
        store.finish_run(args.run_id, status="stopped", error="Stopped by user.")
        return 0
    except Exception as exc:
        logger.exception("Local pipeline worker failed")
        store.record_pipeline_event(
            args.run_id,
            event_type="worker_failed",
            message="Local pipeline worker failed.",
            level="error",
            phase="failed",
            payload={
                "error": f"{type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc(),
            },
        )
        store.finish_run(args.run_id, status="failed", error=str(exc))
        return 1


if __name__ == "__main__":
    sys.exit(main())
