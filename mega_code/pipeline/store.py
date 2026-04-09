"""SQLite-backed local runtime store."""

from __future__ import annotations

import json
import math
import os
import signal
import sqlite3
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mega_code.client.api.protocol import (
    ACTIVE_STATUSES,
    ActivePipelineItem,
    ActivePipelinesResult,
    OutputsResult,
    PipelineStatusResult,
    TriggerPipelineResult,
    WisdomCurateResult,
    WisdomFeedbackResult,
    WisdomResultItem,
)
from mega_code.client.dirs import data_dir
from mega_code.client.models import TurnSet
from mega_code.client.turns import load_turns_jsonl
from mega_code.client.turns import save_turns_jsonl


def utcnow_iso() -> str:
    return datetime.now(UTC).isoformat()


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    denom_left = math.sqrt(sum(v * v for v in left))
    denom_right = math.sqrt(sum(v * v for v in right))
    if denom_left <= 0 or denom_right <= 0:
        return 0.0
    return sum(a * b for a, b in zip(left, right, strict=False)) / (denom_left * denom_right)


class LocalStore:
    """Persist local pipeline runs, artifacts, and curation feedback."""

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or (data_dir() / "local-runtime.sqlite3")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS trajectories (
                    session_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    session_dir TEXT NOT NULL,
                    turn_count INTEGER NOT NULL,
                    metadata_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS pipeline_runs (
                    run_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    project_path TEXT,
                    session_id TEXT,
                    steps_json TEXT,
                    model TEXT,
                    include_claude INTEGER NOT NULL DEFAULT 0,
                    include_codex INTEGER NOT NULL DEFAULT 0,
                    limit_value INTEGER,
                    concurrency INTEGER NOT NULL DEFAULT 4,
                    status TEXT NOT NULL,
                    progress_json TEXT NOT NULL,
                    outputs_json TEXT,
                    error TEXT,
                    pid INTEGER,
                    requested_stop INTEGER NOT NULL DEFAULT 0,
                    started_at TEXT NOT NULL,
                    completed_at TEXT
                );

                CREATE TABLE IF NOT EXISTS artifacts (
                    artifact_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    session_id TEXT,
                    artifact_type TEXT NOT NULL,
                    name TEXT NOT NULL,
                    version TEXT NOT NULL,
                    content TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    source_path TEXT,
                    created_at TEXT NOT NULL,
                    embedding_json TEXT
                );

                CREATE TABLE IF NOT EXISTS pcr_fragments (
                    fragment_id TEXT PRIMARY KEY,
                    artifact_id TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    procedure TEXT NOT NULL,
                    context TEXT NOT NULL,
                    resultant TEXT NOT NULL,
                    constraints TEXT NOT NULL,
                    evidence_refs_json TEXT NOT NULL,
                    source_artifact TEXT NOT NULL,
                    dependency_ids_json TEXT NOT NULL,
                    feedback_score REAL NOT NULL DEFAULT 0.0,
                    created_at TEXT NOT NULL,
                    embedding_json TEXT NOT NULL,
                    lexical_text TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS curation_sessions (
                    session_id TEXT PRIMARY KEY,
                    query TEXT NOT NULL,
                    curation TEXT NOT NULL,
                    skills_json TEXT NOT NULL,
                    wisdoms_json TEXT NOT NULL,
                    token_count INTEGER NOT NULL DEFAULT 0,
                    cost_usd REAL NOT NULL DEFAULT 0.0,
                    created_at TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending'
                );

                CREATE TABLE IF NOT EXISTS curation_feedback (
                    feedback_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    feedback_text TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_pipeline_runs_status
                    ON pipeline_runs(status);
                CREATE INDEX IF NOT EXISTS idx_artifacts_name_type
                    ON artifacts(name, artifact_type);
                CREATE INDEX IF NOT EXISTS idx_pcr_fragments_artifact
                    ON pcr_fragments(source_artifact);
                """
            )

    def project_knowledge_dir(self) -> Path:
        root = data_dir() / "knowledge"
        root.mkdir(parents=True, exist_ok=True)
        return root

    def skill_source_dir(self) -> Path:
        path = self.project_knowledge_dir() / "skills"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def strategy_source_dir(self) -> Path:
        path = self.project_knowledge_dir() / "strategies"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def save_trajectory(self, turn_set: TurnSet, project_id: str) -> Path:
        session_dir = turn_set.session_dir
        if str(session_dir) in ("", "."):
            session_dir = data_dir() / "projects" / project_id / turn_set.session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        turns_path = save_turns_jsonl(turn_set.turns, turn_set.metadata, session_dir)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO trajectories(session_id, project_id, session_dir, turn_count, metadata_json, updated_at)
                VALUES(?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    project_id=excluded.project_id,
                    session_dir=excluded.session_dir,
                    turn_count=excluded.turn_count,
                    metadata_json=excluded.metadata_json,
                    updated_at=excluded.updated_at
                """,
                (
                    turn_set.session_id,
                    project_id,
                    str(session_dir),
                    len(turn_set.turns),
                    turn_set.metadata.model_dump_json(),
                    utcnow_iso(),
                ),
            )
        return turns_path

    def create_run(
        self,
        *,
        run_id: str,
        project_id: str,
        project_path: str | None,
        session_id: str | None,
        steps: list[str] | None,
        model: str | None,
        include_claude: bool,
        include_codex: bool,
        limit: int | None,
        concurrency: int,
    ) -> TriggerPipelineResult:
        progress = {"current_phase": "queued", "sessions_processed": 0, "sessions_total": 0}
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO pipeline_runs(
                    run_id, project_id, project_path, session_id, steps_json, model,
                    include_claude, include_codex, limit_value, concurrency,
                    status, progress_json, started_at, requested_stop
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
                """,
                (
                    run_id,
                    project_id,
                    project_path,
                    session_id,
                    json.dumps(steps or []),
                    model,
                    int(include_claude),
                    int(include_codex),
                    limit,
                    concurrency,
                    "queued",
                    json.dumps(progress),
                    utcnow_iso(),
                ),
            )
        return TriggerPipelineResult(run_id=run_id, status="queued", message="Local worker scheduled")

    def set_run_pid(self, run_id: str, pid: int) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE pipeline_runs
                SET pid=?, status='running',
                    progress_json=?
                WHERE run_id=?
                """,
                (pid, json.dumps({"current_phase": "starting", "sessions_processed": 0, "sessions_total": 0}), run_id),
            )

    def _is_pid_alive(self, pid: int | None) -> bool:
        if not pid:
            return False
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        return True

    def _reconcile_row(self, row: sqlite3.Row) -> sqlite3.Row:
        if row["status"] in ACTIVE_STATUSES and not self._is_pid_alive(row["pid"]):
            with self._connect() as conn:
                conn.execute(
                    """
                    UPDATE pipeline_runs
                    SET status='failed',
                        error=?,
                        completed_at=?
                    WHERE run_id=?
                    """,
                    ("Local worker exited before finishing.", utcnow_iso(), row["run_id"]),
                )
                row = conn.execute("SELECT * FROM pipeline_runs WHERE run_id=?", (row["run_id"],)).fetchone()
        return row

    def get_run_config(self, run_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM pipeline_runs WHERE run_id=?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(f"Unknown run_id: {run_id}")
        return dict(row)

    def load_saved_turnset(self, session_id: str) -> TurnSet | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT session_dir FROM trajectories WHERE session_id=?",
                (session_id,),
            ).fetchone()
        if row is None:
            return None
        turns_path = Path(row["session_dir"]) / "turns.jsonl"
        if not turns_path.exists():
            return None
        return load_turns_jsonl(turns_path)

    def update_progress(
        self,
        run_id: str,
        *,
        phase: str,
        processed: int,
        total: int,
        status: str = "running",
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE pipeline_runs
                SET status=?,
                    progress_json=?
                WHERE run_id=?
                """,
                (status, json.dumps({"current_phase": phase, "sessions_processed": processed, "sessions_total": total}), run_id),
            )

    def finish_run(
        self,
        run_id: str,
        *,
        status: str,
        outputs: OutputsResult | None = None,
        error: str | None = None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE pipeline_runs
                SET status=?,
                    outputs_json=?,
                    error=?,
                    completed_at=?,
                    progress_json=?
                WHERE run_id=?
                """,
                (
                    status,
                    outputs.model_dump_json() if outputs else None,
                    error,
                    utcnow_iso(),
                    json.dumps({"current_phase": status, "sessions_processed": 0, "sessions_total": 0}),
                    run_id,
                ),
            )

    def stop_run(self, run_id: str) -> tuple[int | None, PipelineStatusResult]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM pipeline_runs WHERE run_id=?", (run_id,)).fetchone()
            if row is None:
                raise KeyError(f"Unknown run_id: {run_id}")
            conn.execute(
                """
                UPDATE pipeline_runs
                SET requested_stop=1,
                    status='stopped',
                    completed_at=?,
                    error=?
                WHERE run_id=?
                """,
                (utcnow_iso(), "Stopped by user.", run_id),
            )
        status = self.get_pipeline_status(run_id)
        return row["pid"], status

    def is_stop_requested(self, run_id: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT requested_stop FROM pipeline_runs WHERE run_id=?",
                (run_id,),
            ).fetchone()
        return bool(row and row["requested_stop"])

    def get_pipeline_status(self, run_id: str) -> PipelineStatusResult:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM pipeline_runs WHERE run_id=?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(f"Unknown run_id: {run_id}")
        row = self._reconcile_row(row)
        outputs = OutputsResult.model_validate_json(row["outputs_json"]) if row["outputs_json"] else None
        progress = json.loads(row["progress_json"]) if row["progress_json"] else None
        return PipelineStatusResult(
            run_id=row["run_id"],
            project_id=row["project_id"],
            status=row["status"],
            started_at=row["started_at"],
            completed_at=row["completed_at"],
            progress=progress,
            outputs=outputs,
            error=row["error"],
        )

    def get_outputs(self, run_id: str) -> OutputsResult:
        status = self.get_pipeline_status(run_id)
        return status.outputs or OutputsResult()

    def get_active_pipelines(self) -> ActivePipelinesResult:
        items: list[ActivePipelineItem] = []
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM pipeline_runs WHERE status IN ('queued','running') ORDER BY started_at DESC"
            ).fetchall()
        for row in rows:
            row = self._reconcile_row(row)
            if row["status"] not in ACTIVE_STATUSES:
                continue
            progress = json.loads(row["progress_json"]) if row["progress_json"] else None
            items.append(
                ActivePipelineItem(
                    run_id=row["run_id"],
                    project_id=row["project_id"],
                    status=row["status"],
                    started_at=row["started_at"],
                    progress=progress,
                )
            )
        return ActivePipelinesResult(active=bool(items), runs=items)

    def find_active_run_for_project(self, project_id: str) -> str | None:
        active = self.get_active_pipelines()
        for run in active.runs:
            if run.project_id == project_id:
                return run.run_id
        return None

    def artifact_dir_for(self, artifact_type: str, name: str) -> Path:
        root = self.skill_source_dir() if artifact_type == "skill" else self.strategy_source_dir()
        path = root / name
        path.mkdir(parents=True, exist_ok=True)
        return path

    def save_artifacts(
        self,
        *,
        run_id: str,
        project_id: str,
        session_id: str,
        artifact_payloads: list[dict[str, Any]],
        pcr_payloads: list[dict[str, Any]],
    ) -> None:
        with self._connect() as conn:
            for artifact in artifact_payloads:
                conn.execute("DELETE FROM artifacts WHERE artifact_id=?", (artifact["artifact_id"],))
                conn.execute(
                    """
                    INSERT INTO artifacts(
                        artifact_id, run_id, project_id, session_id, artifact_type,
                        name, version, content, metadata_json, source_path, created_at, embedding_json
                    )
                    VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        artifact["artifact_id"],
                        run_id,
                        project_id,
                        session_id,
                        artifact["artifact_type"],
                        artifact["name"],
                        artifact["version"],
                        artifact["content"],
                        json.dumps(artifact["metadata"]),
                        artifact.get("source_path"),
                        artifact["created_at"],
                        json.dumps(artifact["embedding"]),
                    ),
                )
            for fragment in pcr_payloads:
                conn.execute("DELETE FROM pcr_fragments WHERE fragment_id=?", (fragment["fragment_id"],))
                conn.execute(
                    """
                    INSERT INTO pcr_fragments(
                        fragment_id, artifact_id, run_id, project_id, name,
                        procedure, context, resultant, constraints, evidence_refs_json,
                        source_artifact, dependency_ids_json, feedback_score, created_at,
                        embedding_json, lexical_text
                    )
                    VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        fragment["fragment_id"],
                        fragment["artifact_id"],
                        run_id,
                        project_id,
                        fragment["name"],
                        fragment["procedure"],
                        fragment["context"],
                        fragment["resultant"],
                        fragment["constraints"],
                        json.dumps(fragment["evidence_refs"]),
                        fragment["source_artifact"],
                        json.dumps(fragment["dependency_ids"]),
                        float(fragment.get("feedback_score", 0.0)),
                        fragment["created_at"],
                        json.dumps(fragment["embedding"]),
                        fragment["lexical_text"],
                    ),
                )

    def fetch_fragments(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT p.*, a.source_path, a.artifact_type, a.content AS artifact_content
                FROM pcr_fragments p
                JOIN artifacts a ON a.artifact_id = p.artifact_id
                ORDER BY p.created_at DESC
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def save_curation(self, result: WisdomCurateResult, status: str = "pending") -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO curation_sessions(
                    session_id, query, curation, skills_json, wisdoms_json,
                    token_count, cost_usd, created_at, status
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    result.session_id,
                    result.query,
                    result.curation,
                    json.dumps([item.model_dump() for item in result.skills]),
                    json.dumps([item.model_dump() for item in result.wisdoms]),
                    result.token_count,
                    result.cost_usd,
                    utcnow_iso(),
                    status,
                ),
            )

    def save_feedback(self, session_id: str, feedback_text: str) -> WisdomFeedbackResult:
        feedback_id = str(uuid.uuid4())
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO curation_feedback(feedback_id, session_id, feedback_text, created_at)
                VALUES(?, ?, ?, ?)
                """,
                (feedback_id, session_id, feedback_text, utcnow_iso()),
            )
            row = conn.execute(
                "SELECT wisdoms_json FROM curation_sessions WHERE session_id=?",
                (session_id,),
            ).fetchone()
            wisdoms = json.loads(row["wisdoms_json"]) if row and row["wisdoms_json"] else []
            delta = feedback_delta(feedback_text)
            for wisdom in wisdoms:
                conn.execute(
                    """
                    UPDATE pcr_fragments
                    SET feedback_score = feedback_score + ?
                    WHERE fragment_id = ?
                    """,
                    (delta, wisdom.get("wisdom_id")),
                )
            conn.execute(
                "UPDATE curation_sessions SET status='completed' WHERE session_id=?",
                (session_id,),
            )
        return WisdomFeedbackResult(session_id=session_id, feedback_id=feedback_id, status="saved")

    def signal_pid(self, pid: int | None) -> None:
        if not pid:
            return
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            return

    def write_source_tree(self, *, artifact_type: str, name: str, content: str) -> str:
        target_dir = self.artifact_dir_for(artifact_type, name)
        if artifact_type == "skill":
            target = target_dir / "SKILL.md"
        else:
            target = target_dir / f"{name}.md"
        target.write_text(content, encoding="utf-8")
        return str(target_dir if artifact_type == "skill" else target)


def feedback_delta(feedback_text: str) -> float:
    text = feedback_text.lower()
    if "1/5" in text or "2/5" in text or "harmful" in text or "bad" in text:
        return -0.2
    if "5/5" in text or "4/5" in text or "useful" in text or "great" in text:
        return 0.2
    return 0.05


def normalize_scores(values: Iterable[float]) -> list[float]:
    values_list = list(values)
    if not values_list:
        return []
    lo = min(values_list)
    hi = max(values_list)
    if math.isclose(lo, hi):
        return [1.0 if hi > 0 else 0.0 for _ in values_list]
    return [(value - lo) / (hi - lo) for value in values_list]
