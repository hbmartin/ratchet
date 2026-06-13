"""Canonical local client implementation."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

from ratchet.client.api.protocol import (
    ACTIVE_STATUSES,
    ActivePipelinesResult,
    CausalStepFeedbackItem,
    EnhanceSkillResult,
    OutputsResult,
    PipelineConflictError,
    PipelineStatusResult,
    PipelineStopResult,
    ProfileResult,
    TriggerPipelineResult,
    UploadResult,
    UserProfile,
    WisdomCurateResult,
    WisdomFeedbackResult,
)
from ratchet.client.models import TurnSet
from ratchet.client.profile import load_profile as load_local_profile
from ratchet.client.profile import save_profile as save_local_profile
from ratchet.pipeline.runtime import curate_local_wisdom
from ratchet.pipeline.store import LocalStore

_FORCE_REPLACEMENT_TIMEOUT_SECONDS = 10.0
_FORCE_REPLACEMENT_POLL_SECONDS = 0.1


class RatchetLocal:
    """Filesystem- and SQLite-backed local Ratchet runtime."""

    def __init__(
        self,
        *,
        backend: str | None = None,
        project_id: str | None = None,
        model_name: str | None = None,
        db_path: Path | None = None,
    ) -> None:
        self.backend = backend or "local"
        self.project_id = project_id or ""
        self.model_name = model_name
        self.store = LocalStore(db_path=db_path)

    def upload_trajectory(
        self,
        *,
        turn_set: TurnSet,
        project_id: str,
    ) -> UploadResult:
        self.store.save_trajectory(turn_set, project_id)
        return UploadResult(
            status="accepted",
            session_id=turn_set.session_id,
            message="Trajectory stored locally.",
        )

    def get_outputs(
        self,
        *,
        project_id: str,
        run_id: str,
    ) -> OutputsResult:
        _ = project_id
        return self.store.get_outputs(run_id)

    async def trigger_pipeline_run(
        self,
        *,
        project_id: str,
        project_path: Path | None = None,
        session_id: str | None = None,
        steps: list[str] | None = None,
        force: bool = False,
        limit: int | None = None,
        concurrency: int = 64,
        model: str | None = None,
        include_claude: bool = False,
        include_codex: bool = False,
    ) -> TriggerPipelineResult:
        active_run_id = self.store.find_active_run_for_project(project_id)
        if active_run_id and not force:
            raise PipelineConflictError(project_id=project_id, run_id=active_run_id)
        if active_run_id and force:
            try:
                active_row = self.store.get_pipeline_run_row(active_run_id)
            except KeyError:
                active_row = None
            if active_row is not None:
                active_pid = active_row.get("pid")
                self.stop_pipeline(run_id=active_run_id)
                await self._wait_for_run_exit(active_run_id, active_pid)

        run_id = str(uuid.uuid4())
        result = self.store.create_run(
            run_id=run_id,
            project_id=project_id,
            project_path=str(project_path) if project_path else None,
            session_id=session_id,
            steps=steps,
            model=model or self.model_name,
            include_claude=include_claude,
            include_codex=include_codex,
            limit=limit,
            concurrency=concurrency,
        )
        cmd = [sys.executable, "-m", "ratchet.pipeline.worker", "--run-id", run_id]
        env = os.environ.copy()
        paths = self.store.ensure_run_debug_paths(run_id)
        try:
            with open(paths["log_path"], "ab", buffering=0) as log_handle:
                if os.name != "nt":
                    proc = subprocess.Popen(
                        cmd,
                        stdout=log_handle,
                        stderr=subprocess.STDOUT,
                        stdin=subprocess.DEVNULL,
                        close_fds=True,
                        env=env,
                        start_new_session=True,
                    )
                else:
                    proc = subprocess.Popen(
                        cmd,
                        stdout=log_handle,
                        stderr=subprocess.STDOUT,
                        stdin=subprocess.DEVNULL,
                        close_fds=True,
                        env=env,
                    )
        except Exception as exc:
            self.store.record_pipeline_event(
                run_id,
                event_type="worker_spawn_failed",
                message="Failed to spawn local pipeline worker.",
                level="error",
                phase="starting",
                payload={"error": f"{type(exc).__name__}: {exc}", "command": cmd},
            )
            self.store.finish_run(run_id, status="failed", error=str(exc))
            raise
        self.store.set_run_pid(run_id, proc.pid)
        self.store.record_pipeline_event(
            run_id,
            event_type="worker_spawned",
            message="Local pipeline worker spawned.",
            phase="starting",
            payload={"pid": proc.pid, "command": cmd, **paths},
        )
        await asyncio.sleep(0)
        return result

    async def _wait_for_run_exit(
        self,
        run_id: str,
        pid: int | None,
        *,
        timeout: float = _FORCE_REPLACEMENT_TIMEOUT_SECONDS,
        poll_interval: float = _FORCE_REPLACEMENT_POLL_SECONDS,
    ) -> None:
        """Wait for a stopped worker PID to exit before replacing it."""
        deadline = time.monotonic() + timeout
        while True:
            try:
                status = self.store.get_pipeline_status(run_id)
            except KeyError:
                return
            pid_running = self._pid_is_running(pid)
            if not pid_running or status.status not in ACTIVE_STATUSES:
                return

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(
                    f"Timed out waiting for previous pipeline worker to exit "
                    f"(run_id={run_id}, pid={pid})"
                )
            await asyncio.sleep(min(poll_interval, remaining))

    @staticmethod
    def _pid_is_running(pid: int | None) -> bool:
        if not pid or pid <= 0:
            return False
        if os.name == "nt":
            return RatchetLocal._windows_pid_is_running(pid)
        return RatchetLocal._posix_pid_is_running(pid)

    @staticmethod
    def _posix_pid_is_running(pid: int) -> bool:
        try:
            waited_pid, _status = os.waitpid(pid, os.WNOHANG)
        except ChildProcessError:
            pass
        except OSError:
            return False
        else:
            if waited_pid == pid:
                return False

        try:
            os.kill(pid, 0)
        except OSError:
            return False
        return True

    @staticmethod
    def _windows_pid_is_running(pid: int) -> bool:
        import ctypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        synchronize = 0x00100000
        query_limited_information = 0x1000
        wait_timeout = 0x00000102
        kernel32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
        kernel32.OpenProcess.restype = ctypes.c_void_p
        kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        kernel32.WaitForSingleObject.restype = ctypes.c_uint32
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel32.CloseHandle.restype = ctypes.c_int

        handle = kernel32.OpenProcess(synchronize | query_limited_information, False, pid)
        if not handle:
            return False
        try:
            return kernel32.WaitForSingleObject(handle, 0) == wait_timeout
        finally:
            kernel32.CloseHandle(handle)

    def get_pipeline_status(
        self,
        *,
        run_id: str,
    ) -> PipelineStatusResult:
        return self.store.get_pipeline_status(run_id)

    def save_profile(
        self,
        *,
        profile: UserProfile,
    ) -> ProfileResult:
        save_local_profile(profile)
        return ProfileResult(success=True, message="Profile saved locally.")

    def load_profile(self) -> UserProfile:
        return load_local_profile()

    def stop_pipeline(
        self,
        *,
        run_id: str,
    ) -> PipelineStopResult:
        pid, status = self.store.stop_run(run_id)
        self.store.signal_pid(pid)
        return PipelineStopResult(run_id=run_id, status=status.status, message=status.error or "")

    def get_active_pipelines(self) -> ActivePipelinesResult:
        return self.store.get_active_pipelines()

    def enhance_skill(
        self,
        *,
        skill_name: str,
        skill_md: str,
        version: str,
        metadata: dict | None = None,
    ) -> EnhanceSkillResult:
        store_path = self.store.write_source_tree(
            artifact_type="skill",
            name=skill_name,
            content=skill_md,
        )
        _ = metadata
        return EnhanceSkillResult(
            success=True,
            message=f"Enhanced skill saved locally at {store_path} (version {version}).",
        )

    def wisdom_curate(
        self,
        *,
        query: str,
        session_id: str = "",
        top_k: int = 20,
    ) -> WisdomCurateResult:
        return curate_local_wisdom(
            query=query, session_id=session_id, top_k=top_k, store=self.store
        )

    def wisdom_feedback(
        self,
        *,
        session_id: str,
        feedback_text: str,
        failure_stage: str = "unknown",
        should_abstain: bool | None = None,
        step_feedback: list[CausalStepFeedbackItem] | None = None,
    ) -> WisdomFeedbackResult:
        return self.store.save_feedback(
            session_id,
            feedback_text,
            failure_stage=failure_stage,
            should_abstain=should_abstain,
            step_feedback=step_feedback,
        )
