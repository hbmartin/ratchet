"""SQLite-backed local runtime store."""

from __future__ import annotations

import json
import math
import os
import signal
import sqlite3
import uuid
from collections import defaultdict
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mega_code.client.api.protocol import (
    ACTIVE_STATUSES,
    ActivePipelineItem,
    ActivePipelinesResult,
    CausalStepFeedbackItem,
    OutputsResult,
    PipelineStatusResult,
    ReliabilityMetrics,
    TriggerPipelineResult,
    WisdomCurateResult,
    WisdomFeedbackResult,
)
from mega_code.client.dirs import data_dir
from mega_code.client.models import TurnSet
from mega_code.client.turns import load_turns_jsonl, save_turns_jsonl


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

    def _ensure_column(
        self,
        conn: sqlite3.Connection,
        table_name: str,
        column_name: str,
        definition: str,
    ) -> None:
        columns = {
            row["name"]
            for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()
        }
        if column_name in columns:
            return
        conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")

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

                CREATE TABLE IF NOT EXISTS operators (
                    operator_id TEXT PRIMARY KEY,
                    artifact_id TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    title TEXT NOT NULL,
                    procedure TEXT NOT NULL,
                    context TEXT NOT NULL,
                    outcome TEXT NOT NULL,
                    source_artifact TEXT NOT NULL,
                    normalized_intent TEXT NOT NULL,
                    slot_signature TEXT NOT NULL,
                    feedback_score REAL NOT NULL DEFAULT 0.0,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS operator_procedure_index (
                    operator_id TEXT PRIMARY KEY,
                    facet_text TEXT NOT NULL,
                    embedding_json TEXT NOT NULL,
                    lexical_text TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS operator_context_index (
                    operator_id TEXT PRIMARY KEY,
                    facet_text TEXT NOT NULL,
                    embedding_json TEXT NOT NULL,
                    lexical_text TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS operator_outcome_index (
                    operator_id TEXT PRIMARY KEY,
                    facet_text TEXT NOT NULL,
                    embedding_json TEXT NOT NULL,
                    lexical_text TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS operator_edges (
                    edge_id TEXT PRIMARY KEY,
                    source_operator_id TEXT NOT NULL,
                    target_operator_id TEXT NOT NULL,
                    edge_type TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS operator_preconditions (
                    precondition_id TEXT PRIMARY KEY,
                    operator_id TEXT NOT NULL,
                    precondition_type TEXT NOT NULL,
                    key_name TEXT NOT NULL,
                    value TEXT NOT NULL,
                    description TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS operator_postconditions (
                    postcondition_id TEXT PRIMARY KEY,
                    operator_id TEXT NOT NULL,
                    postcondition_type TEXT NOT NULL,
                    key_name TEXT NOT NULL,
                    value TEXT NOT NULL,
                    description TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS operator_slots (
                    slot_id TEXT PRIMARY KEY,
                    operator_id TEXT NOT NULL,
                    slot_name TEXT NOT NULL,
                    slot_type TEXT NOT NULL,
                    slot_value TEXT NOT NULL,
                    required INTEGER NOT NULL DEFAULT 1,
                    description TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS operator_env_fingerprints (
                    operator_id TEXT PRIMARY KEY,
                    fingerprint_json TEXT NOT NULL,
                    lexical_text TEXT NOT NULL,
                    fingerprint_hash TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS curation_sessions (
                    session_id TEXT PRIMARY KEY,
                    query TEXT NOT NULL,
                    curation TEXT NOT NULL,
                    skills_json TEXT NOT NULL,
                    wisdoms_json TEXT NOT NULL,
                    operator_plan_json TEXT NOT NULL DEFAULT '[]',
                    confidence REAL NOT NULL DEFAULT 0.0,
                    should_abstain INTEGER NOT NULL DEFAULT 0,
                    abstain_reason TEXT NOT NULL DEFAULT '',
                    token_count INTEGER NOT NULL DEFAULT 0,
                    cost_usd REAL NOT NULL DEFAULT 0.0,
                    created_at TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending'
                );

                CREATE TABLE IF NOT EXISTS curation_feedback (
                    feedback_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    feedback_text TEXT NOT NULL,
                    failure_stage TEXT NOT NULL DEFAULT 'unknown',
                    should_abstain INTEGER NOT NULL DEFAULT 0,
                    summary_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS curation_feedback_steps (
                    step_feedback_id TEXT PRIMARY KEY,
                    feedback_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    operator_id TEXT,
                    operator_title TEXT NOT NULL DEFAULT '',
                    verdict TEXT NOT NULL,
                    failure_stage TEXT NOT NULL DEFAULT 'unknown',
                    selected INTEGER NOT NULL DEFAULT 1,
                    predicted_success REAL,
                    predicted_confidence REAL,
                    note TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS operator_reliability (
                    operator_id TEXT PRIMARY KEY,
                    selection_count INTEGER NOT NULL DEFAULT 0,
                    helped_count INTEGER NOT NULL DEFAULT 0,
                    hurt_count INTEGER NOT NULL DEFAULT 0,
                    unused_count INTEGER NOT NULL DEFAULT 0,
                    retrieval_miss_count INTEGER NOT NULL DEFAULT 0,
                    execution_miss_count INTEGER NOT NULL DEFAULT 0,
                    abstain_count INTEGER NOT NULL DEFAULT 0,
                    predicted_success_sum REAL NOT NULL DEFAULT 0.0,
                    confidence_sum REAL NOT NULL DEFAULT 0.0,
                    calibration_error_sum REAL NOT NULL DEFAULT 0.0,
                    brier_score_sum REAL NOT NULL DEFAULT 0.0,
                    outcome_count INTEGER NOT NULL DEFAULT 0,
                    last_feedback_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_pipeline_runs_status
                    ON pipeline_runs(status);
                CREATE INDEX IF NOT EXISTS idx_artifacts_name_type
                    ON artifacts(name, artifact_type);
                CREATE INDEX IF NOT EXISTS idx_pcr_fragments_artifact
                    ON pcr_fragments(source_artifact);
                CREATE INDEX IF NOT EXISTS idx_operators_project_created
                    ON operators(project_id, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_operators_intent_signature
                    ON operators(project_id, normalized_intent, slot_signature);
                CREATE INDEX IF NOT EXISTS idx_operator_edges_source_type
                    ON operator_edges(source_operator_id, edge_type);
                CREATE INDEX IF NOT EXISTS idx_operator_edges_target_type
                    ON operator_edges(target_operator_id, edge_type);
                CREATE INDEX IF NOT EXISTS idx_operator_preconditions_operator
                    ON operator_preconditions(operator_id);
                CREATE INDEX IF NOT EXISTS idx_operator_postconditions_operator
                    ON operator_postconditions(operator_id);
                CREATE INDEX IF NOT EXISTS idx_operator_slots_operator
                    ON operator_slots(operator_id);
                CREATE INDEX IF NOT EXISTS idx_curation_feedback_session
                    ON curation_feedback(session_id);
                CREATE INDEX IF NOT EXISTS idx_feedback_steps_feedback
                    ON curation_feedback_steps(feedback_id);
                CREATE INDEX IF NOT EXISTS idx_feedback_steps_operator
                    ON curation_feedback_steps(operator_id);
                """
            )
            self._ensure_column(conn, "curation_sessions", "operator_plan_json", "TEXT NOT NULL DEFAULT '[]'")
            self._ensure_column(conn, "curation_sessions", "confidence", "REAL NOT NULL DEFAULT 0.0")
            self._ensure_column(conn, "curation_sessions", "should_abstain", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(conn, "curation_sessions", "abstain_reason", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(conn, "curation_feedback", "failure_stage", "TEXT NOT NULL DEFAULT 'unknown'")
            self._ensure_column(conn, "curation_feedback", "should_abstain", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(conn, "curation_feedback", "summary_json", "TEXT NOT NULL DEFAULT '{}'")

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
        progress = {
            "current_phase": "queued",
            "sessions_processed": 0,
            "sessions_total": 0,
            "clusters_processed": 0,
            "clusters_total": 0,
        }
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
                (
                    pid,
                    json.dumps(
                        {
                            "current_phase": "starting",
                            "sessions_processed": 0,
                            "sessions_total": 0,
                            "clusters_processed": 0,
                            "clusters_total": 0,
                        }
                    ),
                    run_id,
                ),
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
        clusters_processed: int | None = None,
        clusters_total: int | None = None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE pipeline_runs
                SET status=?,
                    progress_json=?
                WHERE run_id=?
                """,
                (
                    status,
                    json.dumps(
                        {
                            "current_phase": phase,
                            "sessions_processed": processed,
                            "sessions_total": total,
                            "clusters_processed": clusters_processed if clusters_processed is not None else 0,
                            "clusters_total": clusters_total if clusters_total is not None else 0,
                        }
                    ),
                    run_id,
                ),
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
                    json.dumps(
                        {
                            "current_phase": status,
                            "sessions_processed": 0,
                            "sessions_total": 0,
                            "clusters_processed": 0,
                            "clusters_total": 0,
                        }
                    ),
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
        pcr_payloads: list[dict[str, Any]] | None = None,
        operator_payloads: list[dict[str, Any]] | None = None,
    ) -> None:
        pcr_payloads = pcr_payloads or []
        operator_payloads = operator_payloads or []
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
                        artifact.get("session_id", session_id),
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
            existing_by_signature = conn.execute(
                """
                SELECT operator_id, normalized_intent, slot_signature, created_at
                FROM operators
                WHERE project_id = ?
                """,
                (project_id,),
            ).fetchall()
            existing_by_signature_map: defaultdict[tuple[str, str], list[sqlite3.Row]] = defaultdict(list)
            for row in existing_by_signature:
                existing_by_signature_map[(row["normalized_intent"], row["slot_signature"])].append(row)
            new_fingerprint_hashes = {
                payload["operator_id"]: payload["env_fingerprint"]["fingerprint_hash"]
                for payload in operator_payloads
            }
            for operator in operator_payloads:
                self._delete_operator_graph(conn, operator["operator_id"])
                conn.execute(
                    """
                    INSERT INTO operators(
                        operator_id, artifact_id, run_id, project_id, session_id, name,
                        title, procedure, context, outcome, source_artifact,
                        normalized_intent, slot_signature, feedback_score, created_at
                    )
                    VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        operator["operator_id"],
                        operator["artifact_id"],
                        run_id,
                        project_id,
                        session_id,
                        operator["name"],
                        operator["title"],
                        operator["procedure"],
                        operator["context"],
                        operator["outcome"],
                        operator["source_artifact"],
                        operator["normalized_intent"],
                        operator["slot_signature"],
                        float(operator.get("feedback_score", 0.0)),
                        operator["created_at"],
                    ),
                )
                self._insert_operator_index(conn, "operator_procedure_index", operator["operator_id"], operator["indexes"]["procedure"])
                self._insert_operator_index(conn, "operator_context_index", operator["operator_id"], operator["indexes"]["context"])
                self._insert_operator_index(conn, "operator_outcome_index", operator["operator_id"], operator["indexes"]["outcome"])
                for edge in operator.get("edges", []):
                    self._insert_operator_edge(
                        conn,
                        source_operator_id=operator["operator_id"],
                        target_operator_id=edge["target_operator_id"],
                        edge_type=edge["edge_type"],
                        metadata=edge.get("metadata", {}),
                        created_at=operator["created_at"],
                    )
                for item in operator.get("preconditions", []):
                    conn.execute(
                        """
                        INSERT INTO operator_preconditions(
                            precondition_id, operator_id, precondition_type, key_name,
                            value, description, created_at
                        )
                        VALUES(?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            item["precondition_id"],
                            operator["operator_id"],
                            item["precondition_type"],
                            item["key_name"],
                            item["value"],
                            item["description"],
                            operator["created_at"],
                        ),
                    )
                for item in operator.get("postconditions", []):
                    conn.execute(
                        """
                        INSERT INTO operator_postconditions(
                            postcondition_id, operator_id, postcondition_type, key_name,
                            value, description, created_at
                        )
                        VALUES(?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            item["postcondition_id"],
                            operator["operator_id"],
                            item["postcondition_type"],
                            item["key_name"],
                            item["value"],
                            item["description"],
                            operator["created_at"],
                        ),
                    )
                for item in operator.get("slots", []):
                    conn.execute(
                        """
                        INSERT INTO operator_slots(
                            slot_id, operator_id, slot_name, slot_type,
                            slot_value, required, description, created_at
                        )
                        VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            item["slot_id"],
                            operator["operator_id"],
                            item["slot_name"],
                            item["slot_type"],
                            item["slot_value"],
                            int(item.get("required", True)),
                            item["description"],
                            operator["created_at"],
                        ),
                    )
                conn.execute(
                    """
                    INSERT INTO operator_env_fingerprints(
                        operator_id, fingerprint_json, lexical_text, fingerprint_hash
                    )
                    VALUES(?, ?, ?, ?)
                    """,
                    (
                        operator["operator_id"],
                        json.dumps(operator["env_fingerprint"]["fingerprint"]),
                        operator["env_fingerprint"]["lexical_text"],
                        operator["env_fingerprint"]["fingerprint_hash"],
                    ),
                )
                for previous in existing_by_signature_map[
                    (operator["normalized_intent"], operator["slot_signature"])
                ]:
                    self._insert_operator_edge(
                        conn,
                        source_operator_id=operator["operator_id"],
                        target_operator_id=previous["operator_id"],
                        edge_type="supersedes",
                        metadata={"reason": "newer operator with same normalized intent and slot signature"},
                        created_at=operator["created_at"],
                    )
                for other in operator_payloads:
                    if other["operator_id"] == operator["operator_id"]:
                        continue
                    if operator["normalized_intent"] != other["normalized_intent"]:
                        continue
                    if (
                        operator["env_fingerprint"]["fingerprint"].get("package_manager")
                        and other["env_fingerprint"]["fingerprint"].get("package_manager")
                        and operator["env_fingerprint"]["fingerprint"].get("package_manager")
                        != other["env_fingerprint"]["fingerprint"].get("package_manager")
                    ):
                        self._insert_operator_edge(
                            conn,
                            source_operator_id=operator["operator_id"],
                            target_operator_id=other["operator_id"],
                            edge_type="conflicts_with",
                            metadata={
                                "reason": "package-manager mismatch",
                                "left": operator["env_fingerprint"]["fingerprint"].get("package_manager"),
                                "right": other["env_fingerprint"]["fingerprint"].get("package_manager"),
                            },
                            created_at=operator["created_at"],
                        )
                for row in conn.execute(
                    """
                    SELECT operator_id, fingerprint_hash
                    FROM operator_env_fingerprints
                    WHERE operator_id != ?
                    """,
                    (operator["operator_id"],),
                ).fetchall():
                    if row["fingerprint_hash"] == new_fingerprint_hashes[operator["operator_id"]]:
                        continue
                    other_operator = conn.execute(
                        """
                        SELECT normalized_intent
                        FROM operators
                        WHERE operator_id = ?
                        """,
                        (row["operator_id"],),
                    ).fetchone()
                    if not other_operator or other_operator["normalized_intent"] != operator["normalized_intent"]:
                        continue
                    if operator["slot_signature"] != conn.execute(
                        "SELECT slot_signature FROM operators WHERE operator_id = ?",
                        (row["operator_id"],),
                    ).fetchone()["slot_signature"]:
                        self._insert_operator_edge(
                            conn,
                            source_operator_id=operator["operator_id"],
                            target_operator_id=row["operator_id"],
                            edge_type="conflicts_with",
                            metadata={"reason": "different slot signature for same intent"},
                            created_at=operator["created_at"],
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

    def fetch_operators(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            operator_rows = conn.execute(
                """
                SELECT o.*, a.source_path, a.artifact_type, a.content AS artifact_content
                FROM operators o
                JOIN artifacts a ON a.artifact_id = o.artifact_id
                ORDER BY o.created_at DESC
                """
            ).fetchall()
            if not operator_rows:
                return []
            operator_ids = [row["operator_id"] for row in operator_rows]
            indexes = {
                "procedure": self._fetch_index_rows(conn, "operator_procedure_index", operator_ids),
                "context": self._fetch_index_rows(conn, "operator_context_index", operator_ids),
                "outcome": self._fetch_index_rows(conn, "operator_outcome_index", operator_ids),
            }
            edges = self._fetch_related_rows(conn, "operator_edges", "source_operator_id", operator_ids)
            incoming = self._fetch_related_rows(conn, "operator_edges", "target_operator_id", operator_ids)
            preconditions = self._fetch_related_rows(
                conn, "operator_preconditions", "operator_id", operator_ids
            )
            postconditions = self._fetch_related_rows(
                conn, "operator_postconditions", "operator_id", operator_ids
            )
            slots = self._fetch_related_rows(conn, "operator_slots", "operator_id", operator_ids)
            fingerprints = self._fetch_index_rows(conn, "operator_env_fingerprints", operator_ids)
            reliability_rows = self._fetch_index_rows(conn, "operator_reliability", operator_ids)
        operators: list[dict[str, Any]] = []
        for row in operator_rows:
            operator_id = row["operator_id"]
            operators.append(
                {
                    **dict(row),
                    "indexes": {
                        "procedure": indexes["procedure"].get(operator_id, {}),
                        "context": indexes["context"].get(operator_id, {}),
                        "outcome": indexes["outcome"].get(operator_id, {}),
                    },
                    "edges": edges.get(operator_id, []),
                    "incoming_edges": incoming.get(operator_id, []),
                    "preconditions": preconditions.get(operator_id, []),
                    "postconditions": postconditions.get(operator_id, []),
                    "slots": slots.get(operator_id, []),
                    "env_fingerprint": fingerprints.get(operator_id, {}),
                    "reliability": self._summarize_operator_reliability(
                        reliability_rows.get(operator_id)
                    ).model_dump(),
                }
            )
        return operators

    def save_curation(self, result: WisdomCurateResult, status: str = "pending") -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO curation_sessions(
                    session_id, query, curation, skills_json, wisdoms_json,
                    operator_plan_json, confidence, should_abstain, abstain_reason,
                    token_count, cost_usd, created_at, status
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    result.session_id,
                    result.query,
                    result.curation,
                    json.dumps([item.model_dump() for item in result.skills]),
                    json.dumps([item.model_dump() for item in result.wisdoms]),
                    json.dumps([item.model_dump() for item in result.operator_plan]),
                    float(result.confidence),
                    int(result.should_abstain),
                    result.abstain_reason,
                    result.token_count,
                    result.cost_usd,
                    utcnow_iso(),
                    status,
                ),
            )

    def save_feedback(
        self,
        session_id: str,
        feedback_text: str,
        *,
        failure_stage: str = "unknown",
        should_abstain: bool | None = None,
        step_feedback: list[CausalStepFeedbackItem] | None = None,
    ) -> WisdomFeedbackResult:
        feedback_id = str(uuid.uuid4())
        created_at = utcnow_iso()
        inferred = infer_feedback_summary(feedback_text)
        resolved_failure_stage = normalize_failure_stage(
            failure_stage if failure_stage != "unknown" else inferred["failure_stage"]
        )
        resolved_should_abstain = (
            bool(should_abstain)
            if should_abstain is not None
            else bool(inferred["should_abstain"])
        )
        explicit_step_feedback = [item.model_dump() for item in (step_feedback or [])]
        with self._connect() as conn:
            session_row = conn.execute(
                "SELECT wisdoms_json, operator_plan_json FROM curation_sessions WHERE session_id=?",
                (session_id,),
            ).fetchone()
            if session_row is None:
                raise KeyError(f"Unknown session_id: {session_id}")
            operator_plan = (
                json.loads(session_row["operator_plan_json"])
                if session_row["operator_plan_json"]
                else []
            )
            resolved_steps = resolve_step_feedback(
                feedback_text=feedback_text,
                operator_plan=operator_plan,
                explicit_step_feedback=explicit_step_feedback,
                failure_stage=resolved_failure_stage,
            )
            summary = {
                "inferred_failure_stage": inferred["failure_stage"],
                "resolved_failure_stage": resolved_failure_stage,
                "explicit_step_feedback": bool(explicit_step_feedback),
                "applied_step_feedback": len(resolved_steps),
            }
            conn.execute(
                """
                INSERT INTO curation_feedback(
                    feedback_id, session_id, feedback_text, failure_stage,
                    should_abstain, summary_json, created_at
                )
                VALUES(?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    feedback_id,
                    session_id,
                    feedback_text,
                    resolved_failure_stage,
                    int(resolved_should_abstain),
                    json.dumps(summary),
                    created_at,
                ),
            )
            plan_lookup = {
                item["operator_id"]: item
                for item in operator_plan
                if item.get("operator_id")
            }
            updated_operator_ids: set[str] = set()
            for item in resolved_steps:
                operator_id = item.get("operator_id", "").strip() or None
                verdict = normalize_feedback_verdict(item.get("verdict"))
                step_stage = normalize_failure_stage(item.get("failure_stage") or resolved_failure_stage)
                selected = int(item.get("selected", verdict != "missing"))
                plan_item = plan_lookup.get(operator_id or "", {})
                predicted_success = _coerce_float(plan_item.get("predicted_success"))
                predicted_confidence = _coerce_float(plan_item.get("confidence"))
                conn.execute(
                    """
                    INSERT INTO curation_feedback_steps(
                        step_feedback_id, feedback_id, session_id, operator_id, operator_title,
                        verdict, failure_stage, selected, predicted_success, predicted_confidence,
                        note, created_at
                    )
                    VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(uuid.uuid4()),
                        feedback_id,
                        session_id,
                        operator_id,
                        item.get("title") or plan_item.get("title") or "",
                        verdict,
                        step_stage,
                        selected,
                        predicted_success,
                        predicted_confidence,
                        item.get("note", ""),
                        created_at,
                    ),
                )
                if not operator_id:
                    continue
                self._apply_operator_feedback_event(
                    conn,
                    operator_id=operator_id,
                    verdict=verdict,
                    failure_stage=step_stage,
                    selected=bool(selected),
                    should_abstain=resolved_should_abstain,
                    predicted_success=predicted_success,
                    predicted_confidence=predicted_confidence,
                    created_at=created_at,
                )
                updated_operator_ids.add(operator_id)
            conn.execute(
                "UPDATE curation_sessions SET status='completed' WHERE session_id=?",
                (session_id,),
            )
        return WisdomFeedbackResult(
            session_id=session_id,
            feedback_id=feedback_id,
            status="saved",
            failure_stage=resolved_failure_stage,
            applied_steps=len(resolved_steps),
            updated_operator_ids=sorted(updated_operator_ids),
        )

    def _apply_operator_feedback_event(
        self,
        conn: sqlite3.Connection,
        *,
        operator_id: str,
        verdict: str,
        failure_stage: str,
        selected: bool,
        should_abstain: bool,
        predicted_success: float | None,
        predicted_confidence: float | None,
        created_at: str,
    ) -> None:
        row = conn.execute(
            "SELECT * FROM operator_reliability WHERE operator_id=?",
            (operator_id,),
        ).fetchone()
        current = dict(row) if row else {}
        selection_count = int(current.get("selection_count", 0)) + int(selected)
        helped_count = int(current.get("helped_count", 0)) + int(verdict == "helped")
        hurt_count = int(current.get("hurt_count", 0)) + int(verdict == "hurt")
        unused_count = int(current.get("unused_count", 0)) + int(verdict == "unused")
        retrieval_miss_count = int(current.get("retrieval_miss_count", 0)) + int(
            failure_stage in {"retrieval", "mixed"}
        )
        execution_miss_count = int(current.get("execution_miss_count", 0)) + int(
            failure_stage in {"execution", "mixed"}
        )
        abstain_count = int(current.get("abstain_count", 0)) + int(should_abstain)
        predicted_success_sum = float(current.get("predicted_success_sum", 0.0))
        confidence_sum = float(current.get("confidence_sum", 0.0))
        calibration_error_sum = float(current.get("calibration_error_sum", 0.0))
        brier_score_sum = float(current.get("brier_score_sum", 0.0))
        outcome_count = int(current.get("outcome_count", 0))
        if predicted_success is not None:
            observed = 1.0 if verdict == "helped" else 0.0
            predicted_success_sum += predicted_success
            confidence_sum += predicted_confidence if predicted_confidence is not None else 0.35
            calibration_error_sum += abs(predicted_success - observed)
            brier_score_sum += (predicted_success - observed) ** 2
            outcome_count += 1
        conn.execute(
            """
            INSERT OR REPLACE INTO operator_reliability(
                operator_id, selection_count, helped_count, hurt_count, unused_count,
                retrieval_miss_count, execution_miss_count, abstain_count,
                predicted_success_sum, confidence_sum, calibration_error_sum,
                brier_score_sum, outcome_count, last_feedback_at
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                operator_id,
                selection_count,
                helped_count,
                hurt_count,
                unused_count,
                retrieval_miss_count,
                execution_miss_count,
                abstain_count,
                predicted_success_sum,
                confidence_sum,
                calibration_error_sum,
                brier_score_sum,
                outcome_count,
                created_at,
            ),
        )
        summary = self._summarize_operator_reliability(
            {
                "operator_id": operator_id,
                "selection_count": selection_count,
                "helped_count": helped_count,
                "hurt_count": hurt_count,
                "unused_count": unused_count,
                "retrieval_miss_count": retrieval_miss_count,
                "execution_miss_count": execution_miss_count,
                "abstain_count": abstain_count,
                "predicted_success_sum": predicted_success_sum,
                "confidence_sum": confidence_sum,
                "calibration_error_sum": calibration_error_sum,
                "brier_score_sum": brier_score_sum,
                "outcome_count": outcome_count,
            }
        )
        conn.execute(
            """
            UPDATE operators
            SET feedback_score = ?
            WHERE operator_id = ?
            """,
            (feedback_score_from_reliability(summary), operator_id),
        )

    def _summarize_operator_reliability(
        self,
        row: dict[str, Any] | sqlite3.Row | None,
    ) -> ReliabilityMetrics:
        payload = dict(row) if row else {}
        selection_count = int(payload.get("selection_count", 0))
        helped_count = int(payload.get("helped_count", 0))
        hurt_count = int(payload.get("hurt_count", 0))
        unused_count = int(payload.get("unused_count", 0))
        retrieval_miss_count = int(payload.get("retrieval_miss_count", 0))
        execution_miss_count = int(payload.get("execution_miss_count", 0))
        abstain_count = int(payload.get("abstain_count", 0))
        outcome_count = int(payload.get("outcome_count", 0))
        calibration_error = (
            float(payload.get("calibration_error_sum", 0.0)) / outcome_count
            if outcome_count
            else 0.25
        )
        brier_score = (
            float(payload.get("brier_score_sum", 0.0)) / outcome_count
            if outcome_count
            else 0.25
        )
        prior_success = (
            (helped_count + 1.0) / (selection_count + 2.0)
            if selection_count
            else 0.5
        )
        retrieval_precision = (
            helped_count / selection_count
            if selection_count
            else 0.5
        )
        execution_trials = helped_count + execution_miss_count
        execution_success_rate = (
            helped_count / execution_trials
            if execution_trials
            else 0.5
        )
        evidence_strength = 1.0 - math.exp(-selection_count / 3.0) if selection_count else 0.0
        confidence = clamp(
            0.2
            + 0.3 * evidence_strength
            + 0.25 * max(0.0, 1.0 - calibration_error)
            + 0.25 * retrieval_precision,
            lower=0.05,
            upper=0.99,
        )
        empirical_reliability = clamp(
            evidence_strength
            * max(0.0, 1.0 - calibration_error)
            * (0.5 * retrieval_precision + 0.5 * execution_success_rate),
            lower=0.0,
            upper=0.99,
        )
        abstain_probability = clamp(
            max(0.0, 0.55 - prior_success)
            + max(0.0, 0.45 - confidence)
            + (hurt_count / selection_count if selection_count else 0.0) * 0.35
            + (retrieval_miss_count / selection_count if selection_count else 0.0) * 0.25
            + (abstain_count / selection_count if selection_count else 0.0) * 0.45,
            lower=0.0,
            upper=0.99,
        )
        return ReliabilityMetrics(
            selection_count=selection_count,
            helped_count=helped_count,
            hurt_count=hurt_count,
            unused_count=unused_count,
            retrieval_miss_count=retrieval_miss_count,
            execution_miss_count=execution_miss_count,
            abstain_count=abstain_count,
            prior_success=round(prior_success, 6),
            confidence=round(confidence, 6),
            retrieval_precision=round(retrieval_precision, 6),
            execution_success_rate=round(execution_success_rate, 6),
            calibration_error=round(calibration_error, 6),
            brier_score=round(brier_score, 6),
            empirical_reliability=round(empirical_reliability, 6),
            abstain_probability=round(abstain_probability, 6),
        )

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

    def _delete_operator_graph(self, conn: sqlite3.Connection, operator_id: str) -> None:
        for table, column in (
            ("operator_procedure_index", "operator_id"),
            ("operator_context_index", "operator_id"),
            ("operator_outcome_index", "operator_id"),
            ("operator_preconditions", "operator_id"),
            ("operator_postconditions", "operator_id"),
            ("operator_slots", "operator_id"),
            ("operator_env_fingerprints", "operator_id"),
            ("operator_edges", "source_operator_id"),
            ("operator_edges", "target_operator_id"),
            ("operators", "operator_id"),
        ):
            conn.execute(f"DELETE FROM {table} WHERE {column}=?", (operator_id,))

    def _insert_operator_index(
        self,
        conn: sqlite3.Connection,
        table_name: str,
        operator_id: str,
        payload: dict[str, Any],
    ) -> None:
        conn.execute(
            f"""
            INSERT INTO {table_name}(operator_id, facet_text, embedding_json, lexical_text)
            VALUES(?, ?, ?, ?)
            """,
            (
                operator_id,
                payload["facet_text"],
                json.dumps(payload["embedding"]),
                payload["lexical_text"],
            ),
        )

    def _insert_operator_edge(
        self,
        conn: sqlite3.Connection,
        *,
        source_operator_id: str,
        target_operator_id: str,
        edge_type: str,
        metadata: dict[str, Any],
        created_at: str,
    ) -> None:
        edge_id = str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"{source_operator_id}:{edge_type}:{target_operator_id}",
            )
        )
        conn.execute(
            """
            INSERT OR REPLACE INTO operator_edges(
                edge_id, source_operator_id, target_operator_id, edge_type, metadata_json, created_at
            )
            VALUES(?, ?, ?, ?, ?, ?)
            """,
            (edge_id, source_operator_id, target_operator_id, edge_type, json.dumps(metadata), created_at),
        )

    def _fetch_index_rows(
        self,
        conn: sqlite3.Connection,
        table_name: str,
        operator_ids: list[str],
    ) -> dict[str, dict[str, Any]]:
        placeholders = ",".join("?" for _ in operator_ids)
        rows = conn.execute(
            f"SELECT * FROM {table_name} WHERE operator_id IN ({placeholders})",
            operator_ids,
        ).fetchall()
        return {row["operator_id"]: dict(row) for row in rows}

    def _fetch_related_rows(
        self,
        conn: sqlite3.Connection,
        table_name: str,
        id_column: str,
        operator_ids: list[str],
    ) -> dict[str, list[dict[str, Any]]]:
        placeholders = ",".join("?" for _ in operator_ids)
        rows = conn.execute(
            f"SELECT * FROM {table_name} WHERE {id_column} IN ({placeholders})",
            operator_ids,
        ).fetchall()
        grouped: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            grouped[row[id_column]].append(dict(row))
        return grouped


def _coerce_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def clamp(value: float, *, lower: float = 0.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, value))


def normalize_failure_stage(value: str | None) -> str:
    normalized = (value or "unknown").strip().lower()
    if normalized in {"none", "retrieval", "execution", "mixed", "unknown"}:
        return normalized
    return "unknown"


def normalize_feedback_verdict(value: str | None) -> str:
    normalized = (value or "unused").strip().lower()
    if normalized in {"helped", "hurt", "unused", "missing"}:
        return normalized
    return "unused"


def infer_feedback_summary(feedback_text: str) -> dict[str, Any]:
    text = feedback_text.lower()
    retrieval_terms = ("retriev", "wrong step", "wrong match", "didn't find", "did not find", "missing step")
    execution_terms = ("execute", "execution", "ran", "runtime", "test failed", "broke", "regression")
    should_abstain = any(
        marker in text
        for marker in ("abstain", "shouldn't answer", "should not answer", "shouldn't recommend", "do not recommend")
    )
    if any(term in text for term in retrieval_terms) and any(term in text for term in execution_terms):
        failure_stage = "mixed"
    elif any(term in text for term in retrieval_terms):
        failure_stage = "retrieval"
    elif any(term in text for term in execution_terms):
        failure_stage = "execution"
    elif any(marker in text for marker in ("useful", "helpful", "worked", "great", "good", "5/5", "4/5")):
        failure_stage = "none"
    else:
        failure_stage = "unknown"
    return {
        "failure_stage": failure_stage,
        "should_abstain": should_abstain,
    }


def infer_feedback_verdict(feedback_text: str, *, failure_stage: str) -> str:
    text = feedback_text.lower()
    if any(marker in text for marker in ("unused", "didn't use", "did not use", "ignored", "not needed")):
        return "unused"
    if any(marker in text for marker in ("harmful", "misleading", "wrong", "bad", "broke", "regression", "hurt", "failed")):
        return "hurt"
    if any(marker in text for marker in ("useful", "helpful", "worked", "great", "good", "5/5", "4/5", "resolved", "fixed")):
        return "helped"
    if failure_stage in {"retrieval", "execution", "mixed"}:
        return "hurt"
    return "unused"


def resolve_step_feedback(
    *,
    feedback_text: str,
    operator_plan: list[dict[str, Any]],
    explicit_step_feedback: list[dict[str, Any]],
    failure_stage: str,
) -> list[dict[str, Any]]:
    if explicit_step_feedback:
        resolved: list[dict[str, Any]] = []
        for item in explicit_step_feedback:
            resolved.append(
                {
                    "operator_id": str(item.get("operator_id", "")).strip(),
                    "title": str(item.get("title", "")).strip(),
                    "verdict": normalize_feedback_verdict(item.get("verdict")),
                    "failure_stage": normalize_failure_stage(item.get("failure_stage") or failure_stage),
                    "selected": item.get("selected", item.get("verdict") != "missing"),
                    "note": str(item.get("note", "")).strip(),
                }
            )
        return resolved
    if not operator_plan:
        return []
    lower_text = feedback_text.lower()
    matched: list[dict[str, Any]] = []
    inferred_verdict = infer_feedback_verdict(feedback_text, failure_stage=failure_stage)
    for item in operator_plan:
        title = str(item.get("title", "")).strip()
        source_artifact = str(item.get("source_artifact", "")).strip()
        if (title and title.lower() in lower_text) or (source_artifact and source_artifact.lower() in lower_text):
            matched.append(
                {
                    "operator_id": item.get("operator_id", ""),
                    "title": title,
                    "verdict": inferred_verdict,
                    "failure_stage": failure_stage,
                    "selected": True,
                    "note": feedback_text.strip(),
                }
            )
    if matched:
        return matched
    if len(operator_plan) == 1:
        only = operator_plan[0]
        return [
            {
                "operator_id": only.get("operator_id", ""),
                "title": only.get("title", ""),
                "verdict": inferred_verdict,
                "failure_stage": failure_stage,
                "selected": True,
                "note": feedback_text.strip(),
            }
        ]
    if inferred_verdict in {"helped", "hurt"}:
        top = operator_plan[0]
        return [
            {
                "operator_id": top.get("operator_id", ""),
                "title": top.get("title", ""),
                "verdict": inferred_verdict,
                "failure_stage": failure_stage,
                "selected": True,
                "note": feedback_text.strip(),
            }
        ]
    return []


def feedback_score_from_reliability(metrics: ReliabilityMetrics) -> float:
    net_helpfulness = (metrics.prior_success - 0.5) * (0.5 + 0.5 * metrics.confidence)
    abstain_penalty = metrics.abstain_probability * 0.2
    reliability_bonus = metrics.empirical_reliability * 0.1
    return round(net_helpfulness + reliability_bonus - abstain_penalty, 6)


def normalize_scores(values: Iterable[float]) -> list[float]:
    values_list = list(values)
    if not values_list:
        return []
    lo = min(values_list)
    hi = max(values_list)
    if math.isclose(lo, hi):
        return [1.0 if hi > 0 else 0.0 for _ in values_list]
    return [(value - lo) / (hi - lo) for value in values_list]
