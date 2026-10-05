"""
adapters/storage/metadata_store.py — Persistent metadata store with idempotency
"""
from __future__ import annotations
import json
import sqlite3
from typing import Any, Dict, List, Optional
from domain.sessions.models import ResearchSession, SessionStatus, AuditEvent
from domain.tasks.models import Task
from domain.checkpoints.models import Checkpoint


class MetadataStoreInterface:
    def save_session(self, session: ResearchSession) -> None:
        raise NotImplementedError

    def get_session(self, session_id: str) -> Optional[ResearchSession]:
        raise NotImplementedError

    def list_sessions(self, status: Optional[SessionStatus] = None) -> List[ResearchSession]:
        raise NotImplementedError

    def delete_session(self, session_id: str) -> bool:
        raise NotImplementedError

    def save_task(self, task: Task) -> None:
        raise NotImplementedError

    def get_task(self, task_id: str) -> Optional[Task]:
        raise NotImplementedError

    def save_checkpoint(self, checkpoint: Checkpoint) -> None:
        raise NotImplementedError

    def list_checkpoints(self, session_id: str) -> List[Checkpoint]:
        raise NotImplementedError

    def check_idempotency(self, key: str) -> Optional[Dict[str, Any]]:
        raise NotImplementedError

    def record_idempotency(self, key: str, response_data: Dict[str, Any]) -> None:
        raise NotImplementedError


class SQLiteMetadataStore(MetadataStoreInterface):
    """Production-shaped SQLite metadata store."""

    def __init__(self, db_path: str = "agent_lab.db"):
        self.db_path = db_path
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._get_connection() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS research_sessions (
                    id TEXT PRIMARY KEY,
                    objective TEXT NOT NULL,
                    target TEXT NOT NULL,
                    role TEXT NOT NULL,
                    atespace TEXT NOT NULL,
                    workspace_id TEXT,
                    active_task_id TEXT,
                    active_worker_ip TEXT,
                    status TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    metadata_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS audit_events (
                    event_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    task_id TEXT,
                    from_status TEXT,
                    to_status TEXT NOT NULL,
                    reason TEXT,
                    actor TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    details_json TEXT NOT NULL,
                    FOREIGN KEY(session_id) REFERENCES research_sessions(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    atespace TEXT NOT NULL,
                    phase TEXT NOT NULL,
                    actor_id TEXT,
                    worker_ip TEXT,
                    started_at TEXT,
                    finished_at TEXT,
                    checkpoint_state_key TEXT,
                    created_at TEXT NOT NULL,
                    metadata_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS checkpoints (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    workspace_version TEXT NOT NULL,
                    execution_state_key TEXT,
                    created_at TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    FOREIGN KEY(session_id) REFERENCES research_sessions(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS idempotency_keys (
                    idempotency_key TEXT PRIMARY KEY,
                    response_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
            """)

    def save_session(self, session: ResearchSession) -> None:
        with self._get_connection() as conn:
            conn.execute("""
                INSERT INTO research_sessions (
                    id, objective, target, role, atespace, workspace_id,
                    active_task_id, active_worker_ip, status, version,
                    created_at, updated_at, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    objective=excluded.objective,
                    target=excluded.target,
                    role=excluded.role,
                    atespace=excluded.atespace,
                    workspace_id=excluded.workspace_id,
                    active_task_id=excluded.active_task_id,
                    active_worker_ip=excluded.active_worker_ip,
                    status=excluded.status,
                    version=excluded.version,
                    updated_at=excluded.updated_at,
                    metadata_json=excluded.metadata_json
            """, (
                session.id,
                session.objective,
                session.target,
                session.role,
                session.atespace,
                session.workspace_id,
                session.active_task_id,
                session.active_worker_ip,
                session.status.value,
                session.version,
                session.created_at,
                session.updated_at,
                json.dumps(session.metadata),
            ))

            # Save newly added audit events
            for event in session.audit_trail:
                conn.execute("""
                    INSERT OR IGNORE INTO audit_events (
                        event_id, session_id, task_id, from_status,
                        to_status, reason, actor, timestamp, details_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    event.event_id,
                    event.session_id,
                    event.task_id,
                    event.from_status,
                    event.to_status,
                    event.reason,
                    event.actor,
                    event.timestamp,
                    json.dumps(event.details),
                ))

    def get_session(self, session_id: str) -> Optional[ResearchSession]:
        with self._get_connection() as conn:
            row = conn.execute("SELECT * FROM research_sessions WHERE id = ?", (session_id,)).fetchone()
            if not row:
                return None

            audit_rows = conn.execute(
                "SELECT * FROM audit_events WHERE session_id = ? ORDER BY timestamp ASC",
                (session_id,)
            ).fetchall()

            audit_trail = [
                AuditEvent(
                    event_id=ar["event_id"],
                    session_id=ar["session_id"],
                    task_id=ar["task_id"],
                    from_status=ar["from_status"],
                    to_status=ar["to_status"],
                    reason=ar["reason"],
                    actor=ar["actor"],
                    timestamp=ar["timestamp"],
                    details=json.loads(ar["details_json"]),
                )
                for ar in audit_rows
            ]

            return ResearchSession(
                id=row["id"],
                objective=row["objective"],
                target=row["target"],
                role=row["role"],
                atespace=row["atespace"],
                workspace_id=row["workspace_id"],
                active_task_id=row["active_task_id"],
                active_worker_ip=row["active_worker_ip"],
                status=SessionStatus(row["status"]),
                version=row["version"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                metadata=json.loads(row["metadata_json"]),
                audit_trail=audit_trail,
            )

    def list_sessions(self, status: Optional[SessionStatus] = None) -> List[ResearchSession]:
        with self._get_connection() as conn:
            if status is not None:
                rows = conn.execute(
                    "SELECT id FROM research_sessions WHERE status = ? ORDER BY created_at DESC",
                    (status.value,)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT id FROM research_sessions ORDER BY created_at DESC"
                ).fetchall()

            sessions = []
            for r in rows:
                sess = self.get_session(r["id"])
                if sess:
                    sessions.append(sess)
            return sessions

    def delete_session(self, session_id: str) -> bool:
        with self._get_connection() as conn:
            cursor = conn.execute("DELETE FROM research_sessions WHERE id = ?", (session_id,))
            return cursor.rowcount > 0

    def save_task(self, task: Task) -> None:
        with self._get_connection() as conn:
            conn.execute("""
                INSERT INTO tasks (
                    id, session_id, atespace, phase, actor_id, worker_ip,
                    started_at, finished_at, checkpoint_state_key, created_at, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    phase=excluded.phase,
                    actor_id=excluded.actor_id,
                    worker_ip=excluded.worker_ip,
                    started_at=excluded.started_at,
                    finished_at=excluded.finished_at,
                    checkpoint_state_key=excluded.checkpoint_state_key,
                    metadata_json=excluded.metadata_json
            """, (
                task.id,
                task.session_id,
                task.atespace,
                task.phase.value,
                task.actor_id,
                task.worker_ip,
                task.started_at,
                task.finished_at,
                task.checkpoint_state_key,
                task.created_at,
                json.dumps(task.metadata),
            ))

    def get_task(self, task_id: str) -> Optional[Task]:
        with self._get_connection() as conn:
            row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
            if not row:
                return None
            return Task(
                id=row["id"],
                session_id=row["session_id"],
                atespace=row["atespace"],
                phase=row["phase"],
                actor_id=row["actor_id"],
                worker_ip=row["worker_ip"],
                started_at=row["started_at"],
                finished_at=row["finished_at"],
                checkpoint_state_key=row["checkpoint_state_key"],
                created_at=row["created_at"],
                metadata=json.loads(row["metadata_json"]),
            )

    def save_checkpoint(self, checkpoint: Checkpoint) -> None:
        with self._get_connection() as conn:
            conn.execute("""
                INSERT INTO checkpoints (
                    id, session_id, task_id, workspace_version,
                    execution_state_key, created_at, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO NOTHING
            """, (
                checkpoint.id,
                checkpoint.session_id,
                checkpoint.task_id,
                checkpoint.workspace_version,
                checkpoint.execution_state_key,
                checkpoint.created_at,
                json.dumps(checkpoint.metadata),
            ))

    def list_checkpoints(self, session_id: str) -> List[Checkpoint]:
        with self._get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM checkpoints WHERE session_id = ? ORDER BY created_at ASC",
                (session_id,)
            ).fetchall()
            return [
                Checkpoint(
                    id=r["id"],
                    session_id=r["session_id"],
                    task_id=r["task_id"],
                    workspace_version=r["workspace_version"],
                    execution_state_key=r["execution_state_key"],
                    created_at=r["created_at"],
                    metadata=json.loads(r["metadata_json"]),
                )
                for r in rows
            ]

    def check_idempotency(self, key: str) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT response_json FROM idempotency_keys WHERE idempotency_key = ?",
                (key,)
            ).fetchone()
            if row:
                return json.loads(row["response_json"])
            return None

    def record_idempotency(self, key: str, response_data: Dict[str, Any]) -> None:
        import datetime
        with self._get_connection() as conn:
            conn.execute("""
                INSERT INTO idempotency_keys (idempotency_key, response_json, created_at)
                VALUES (?, ?, ?)
                ON CONFLICT(idempotency_key) DO NOTHING
            """, (
                key,
                json.dumps(response_data),
                datetime.datetime.now(datetime.timezone.utc).isoformat(),
            ))
