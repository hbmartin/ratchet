"""Canonical local client implementation."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import uuid
from pathlib import Path

import httpx

from mega_code.client.api.protocol import (
    ActivePipelinesResult,
    CausalStepFeedbackItem,
    EnhanceSkillResult,
    OutputsResult,
    PipelineStatusResult,
    PipelineStopResult,
    ProfileResult,
    TriggerPipelineResult,
    UploadResult,
    UserProfile,
    WisdomCurateResult,
    WisdomFeedbackResult,
)
from mega_code.client.models import TurnSet
from mega_code.client.profile import load_profile as load_local_profile
from mega_code.client.profile import save_profile as save_local_profile
from mega_code.pipeline.runtime import curate_local_wisdom
from mega_code.pipeline.store import LocalStore


class MegaCodeLocal:
    """Filesystem- and SQLite-backed local MEGA-Code runtime."""

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
            request = httpx.Request("POST", "http://local/pipeline/run")
            response = httpx.Response(
                409,
                request=request,
                text=f"Pipeline already running for project {project_id}; run_id={active_run_id}",
            )
            raise httpx.HTTPStatusError("Pipeline already running", request=request, response=response)
        if active_run_id and force:
            self.stop_pipeline(run_id=active_run_id)

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
        cmd = [sys.executable, "-m", "mega_code.pipeline.worker", "--run-id", run_id]
        env = os.environ.copy()
        kwargs = {
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
            "stdin": subprocess.DEVNULL,
            "close_fds": True,
            "env": env,
        }
        if os.name != "nt":
            kwargs["start_new_session"] = True
        proc = subprocess.Popen(cmd, **kwargs)
        self.store.set_run_pid(run_id, proc.pid)
        await asyncio.sleep(0)
        return result

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
        return curate_local_wisdom(query=query, session_id=session_id, top_k=top_k, store=self.store)

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
