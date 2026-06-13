"""Tests for local pipeline execution constraints."""

from __future__ import annotations

import inspect
import json
import os
from types import SimpleNamespace

import pytest

from ratchet.client.api.protocol import (
    PipelineConflictError,
    PipelineStatusResult,
    TriggerPipelineResult,
)
from ratchet.client.api.remote import RatchetRemote
from ratchet.pipeline import local_client as local_client_module
from ratchet.pipeline.local_client import RatchetLocal


def _seed_active_run(client: RatchetLocal, *, project_id: str, run_id: str = "run-active") -> None:
    client.store.create_run(
        run_id=run_id,
        project_id=project_id,
        project_path=None,
        session_id=None,
        steps=None,
        model=None,
        include_claude=False,
        include_codex=False,
        limit=None,
        concurrency=4,
    )
    client.store.set_run_pid(run_id, os.getpid())


@pytest.fixture
def client(tmp_path):
    return RatchetLocal(db_path=tmp_path / "runtime.sqlite3")


class TestLocalPipelineConflicts:
    """Local client enforces one active pipeline per project."""

    @pytest.mark.asyncio
    async def test_trigger_raises_conflict_when_project_busy(self, client):
        _seed_active_run(client, project_id="test-project", run_id="run-1")

        with pytest.raises(PipelineConflictError) as exc_info:
            await client.trigger_pipeline_run(project_id="test-project")

        assert exc_info.value.project_id == "test-project"
        assert exc_info.value.run_id == "run-1"
        assert "already running" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_different_projects_can_trigger_independently(self, client, monkeypatch):
        _seed_active_run(client, project_id="project-a", run_id="run-a")
        monkeypatch.setattr(
            "ratchet.pipeline.local_client.subprocess.Popen",
            lambda *args, **kwargs: SimpleNamespace(pid=os.getpid()),
        )

        result = await client.trigger_pipeline_run(project_id="project-b")

        assert result.status == "queued"
        assert client.store.find_active_run_for_project("project-a") == "run-a"
        assert client.store.find_active_run_for_project("project-b") == result.run_id

    @pytest.mark.asyncio
    async def test_force_stops_existing_run_and_queues_new_one(self, client, monkeypatch):
        _seed_active_run(client, project_id="test-project", run_id="run-old")

        async def no_wait(run_id: str, pid: int | None) -> None:
            assert run_id == "run-old"
            assert pid == os.getpid()

        monkeypatch.setattr(
            "ratchet.pipeline.local_client.subprocess.Popen",
            lambda *args, **kwargs: SimpleNamespace(pid=os.getpid()),
        )
        monkeypatch.setattr(client.store, "signal_pid", lambda pid: None)
        monkeypatch.setattr(client, "_wait_for_run_exit", no_wait)

        result = await client.trigger_pipeline_run(project_id="test-project", force=True)

        old_status = client.get_pipeline_status(run_id="run-old")
        assert old_status.status == "stopped"
        assert result.status == "queued"
        assert client.store.find_active_run_for_project("test-project") == result.run_id

    @pytest.mark.asyncio
    async def test_force_waits_for_existing_worker_before_spawning(self, client, monkeypatch):
        _seed_active_run(client, project_id="test-project", run_id="run-old")
        calls: list[tuple[str, str, int | None]] = []

        async def record_wait(run_id: str, pid: int | None) -> None:
            calls.append(("wait", run_id, pid))

        def record_popen(*args, **kwargs):
            calls.append(("spawn", "run-new", None))
            return SimpleNamespace(pid=os.getpid())

        monkeypatch.setattr("ratchet.pipeline.local_client.subprocess.Popen", record_popen)
        monkeypatch.setattr(client.store, "signal_pid", lambda pid: None)
        monkeypatch.setattr(client, "_wait_for_run_exit", record_wait)

        await client.trigger_pipeline_run(project_id="test-project", force=True)

        assert calls[0] == ("wait", "run-old", os.getpid())
        assert calls[1] == ("spawn", "run-new", None)

    @pytest.mark.asyncio
    async def test_force_ignores_stale_active_run_id(self, client, monkeypatch):
        monkeypatch.setattr(
            client.store, "find_active_run_for_project", lambda project_id: "missing"
        )
        monkeypatch.setattr(
            client.store,
            "get_pipeline_run_row",
            lambda run_id: (_ for _ in ()).throw(KeyError(run_id)),
        )
        monkeypatch.setattr(
            "ratchet.pipeline.local_client.subprocess.Popen",
            lambda *args, **kwargs: SimpleNamespace(pid=os.getpid()),
        )

        result = await client.trigger_pipeline_run(project_id="test-project", force=True)

        assert result.status == "queued"

    @pytest.mark.asyncio
    async def test_wait_for_run_exit_returns_when_pid_is_dead_but_status_active(
        self, client, monkeypatch
    ):
        _seed_active_run(client, project_id="test-project", run_id="run-old")
        monkeypatch.setattr(client, "_pid_is_running", lambda pid: False)

        await client._wait_for_run_exit("run-old", os.getpid(), timeout=0.01)

    def test_posix_pid_liveness_treats_reaped_child_as_stopped(self, monkeypatch):
        monkeypatch.setattr(local_client_module.os, "waitpid", lambda pid, options: (pid, 0))

        assert RatchetLocal._posix_pid_is_running(12345) is False

    def test_windows_pid_liveness_uses_windows_probe(self, monkeypatch):
        calls: list[int] = []
        monkeypatch.setattr(local_client_module.os, "name", "nt")
        monkeypatch.setattr(
            RatchetLocal,
            "_windows_pid_is_running",
            staticmethod(lambda pid: calls.append(pid) is None or True),
        )

        assert RatchetLocal._pid_is_running(12345) is True
        assert calls == [12345]

    @pytest.mark.asyncio
    async def test_trigger_preserves_local_run_options(self, client, monkeypatch):
        monkeypatch.setattr(
            "ratchet.pipeline.local_client.subprocess.Popen",
            lambda *args, **kwargs: SimpleNamespace(pid=os.getpid()),
        )

        result = await client.trigger_pipeline_run(
            project_id="my-proj",
            steps=["step0", "step1"],
            force=True,
            limit=5,
            concurrency=8,
            model="deterministic-local",
            include_claude=True,
            include_codex=True,
        )

        row = client.store.get_pipeline_run_row(result.run_id)
        assert row["project_id"] == "my-proj"
        assert json.loads(row["steps_json"]) == ["step0", "step1"]
        assert row["limit_value"] == 5
        assert row["concurrency"] == 8
        assert row["model"] == "deterministic-local"
        assert row["include_claude"] == 1
        assert row["include_codex"] == 1


class TestPipelineConstraintsCompatibility:
    """Protocol models and compatibility shim keep expected fields."""

    def test_trigger_result_model_has_status_field(self):
        result = TriggerPipelineResult(run_id="r1", status="queued", message="ok")
        assert result.status == "queued"

    def test_pipeline_status_model_has_error_field(self):
        result = PipelineStatusResult(
            run_id="r1",
            project_id="p1",
            status="failed",
            error="Pipeline already running for project p1",
        )
        assert result.error is not None
        assert "already running" in result.error

    def test_force_flag_in_protocol(self):
        sig = inspect.signature(RatchetLocal.trigger_pipeline_run)
        assert "force" in sig.parameters
        assert sig.parameters["force"].default is False

    def test_remote_shim_rejects_unexpected_kwargs(self, tmp_path):
        with pytest.raises(TypeError, match="unexpected_option"):
            RatchetRemote(db_path=tmp_path / "runtime.sqlite3", unexpected_option=True)
