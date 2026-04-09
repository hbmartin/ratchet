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
    OutputsResult,
    PipelineStatusResult,
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
                }
            )
        return operators

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
                    UPDATE operators
                    SET feedback_score = feedback_score + ?
                    WHERE operator_id = ?
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
