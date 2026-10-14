"""
adapters/storage/metadata_store.py — Persistent metadata store with idempotency
"""
from __future__ import annotations
import json
import os
import sqlite3
from typing import Any, Dict, List, Optional
from domain.sessions.models import ResearchSession, SessionStatus, AuditEvent
from domain.tasks.models import Task
from domain.checkpoints.models import Checkpoint
from domain.checkpoints.branching import ExecutionBranch, BranchStatus, BranchLineage
from domain.speculative.models import BranchEvaluation, PromotionResult
from domain.agents.models import Agent, AgentLifecycleState


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

    def get_checkpoint(self, checkpoint_id: str) -> Optional[Checkpoint]:
        raise NotImplementedError

    def list_checkpoints(self, session_id: str) -> List[Checkpoint]:
        raise NotImplementedError

    def save_branch(self, branch: ExecutionBranch) -> None:
        raise NotImplementedError

    def get_branch(self, branch_id: str) -> Optional[ExecutionBranch]:
        raise NotImplementedError

    def list_branches(
        self,
        session_id: Optional[str] = None,
        parent_checkpoint_id: Optional[str] = None,
    ) -> List[ExecutionBranch]:
        raise NotImplementedError

    def update_branch_status(self, branch_id: str, status: BranchStatus) -> None:
        raise NotImplementedError

    def get_checkpoint_lineage(self, session_id: str) -> BranchLineage:
        raise NotImplementedError

    def save_evaluation(self, evaluation: BranchEvaluation) -> None:
        raise NotImplementedError

    def get_evaluation(self, evaluation_id: str) -> Optional[BranchEvaluation]:
        raise NotImplementedError

    def list_evaluations(self, session_id: str) -> List[BranchEvaluation]:
        raise NotImplementedError

    def save_promotion(self, promotion: PromotionResult) -> None:
        raise NotImplementedError

    def get_latest_promotion(self, session_id: str) -> Optional[PromotionResult]:
        raise NotImplementedError

    def set_session_head(self, session_id: str, checkpoint_id: str) -> None:
        raise NotImplementedError

    def get_session_head(self, session_id: str) -> Optional[str]:
        raise NotImplementedError

    def check_idempotency(self, key: str) -> Optional[Dict[str, Any]]:
        raise NotImplementedError

    def record_idempotency(self, key: str, response_data: Dict[str, Any]) -> None:
        raise NotImplementedError

    def save_agent(self, agent: Agent) -> None:
        raise NotImplementedError

    def get_agent(self, agent_id: str) -> Optional[Agent]:
        raise NotImplementedError

    def list_agents(
        self,
        role: Optional[str] = None,
        tenant: Optional[str] = None,
        lifecycle_state: Optional[AgentLifecycleState] = None,
    ) -> List[Agent]:
        raise NotImplementedError

    def delete_agent(self, agent_id: str) -> bool:
        raise NotImplementedError

    def record_revocation(self, jti: str, subject: str, reason: str = "") -> None:
        raise NotImplementedError

    def is_revoked(self, jti: str) -> bool:
        raise NotImplementedError

    def record_audit_event(self, event: AuditEvent) -> None:
        raise NotImplementedError

    def list_audit_events(
        self,
        session_id: Optional[str] = None,
        task_id: Optional[str] = None,
        limit: int = 100,
    ) -> List[AuditEvent]:
        raise NotImplementedError



class SQLiteMetadataStore(MetadataStoreInterface):
    """Production-shaped SQLite metadata store."""

    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            self.db_path = os.environ.get("AGENT_LAB_DB_PATH", "agent_lab.db")
        else:
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

                CREATE TABLE IF NOT EXISTS agents (
                    agent_id TEXT PRIMARY KEY,
                    role TEXT NOT NULL,
                    tenant TEXT NOT NULL,
                    environment TEXT NOT NULL,
                    capabilities_json TEXT NOT NULL,
                    identity_subject TEXT NOT NULL,
                    task_id TEXT,
                    workspace_id TEXT,
                    lifecycle_state TEXT NOT NULL,
                    session_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    metadata_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS identity_revocations (
                    jti TEXT PRIMARY KEY,
                    subject TEXT NOT NULL,
                    revoked_at TEXT NOT NULL,
                    reason TEXT
                );

                CREATE TABLE IF NOT EXISTS branches (
                    branch_id TEXT PRIMARY KEY,
                    parent_checkpoint_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    agent_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    workspace_id TEXT NOT NULL,
                    identity_subject TEXT NOT NULL,
                    scope_id TEXT NOT NULL,
                    delegation_chain_json TEXT NOT NULL,
                    workspace_generation INTEGER NOT NULL DEFAULT 1,
                    snapshot_reference TEXT NOT NULL,
                    hypothesis TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    FOREIGN KEY(parent_checkpoint_id) REFERENCES checkpoints(id),
                    FOREIGN KEY(session_id) REFERENCES research_sessions(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS evaluations (
                    evaluation_id TEXT PRIMARY KEY,
                    branch_id TEXT NOT NULL,
                    checkpoint_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    final_score REAL NOT NULL,
                    is_compliant INTEGER NOT NULL DEFAULT 1,
                    disqualified INTEGER NOT NULL DEFAULT 0,
                    disqualification_reason TEXT,
                    metrics_json TEXT NOT NULL,
                    details_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(session_id) REFERENCES research_sessions(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS promotions (
                    promotion_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    promoted_branch_id TEXT NOT NULL,
                    promoted_checkpoint_id TEXT NOT NULL,
                    previous_head_id TEXT,
                    new_head_id TEXT NOT NULL,
                    evaluation_id TEXT,
                    status TEXT NOT NULL,
                    promoted_at TEXT NOT NULL,
                    audit_id TEXT NOT NULL,
                    FOREIGN KEY(session_id) REFERENCES research_sessions(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS session_heads (
                    session_id TEXT PRIMARY KEY,
                    head_checkpoint_id TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(session_id) REFERENCES research_sessions(id) ON DELETE CASCADE
                );
            """)

            # Schema migrations for existing checkpoints table
            for col, col_type in [
                ("parent_checkpoint_id", "TEXT"),
                ("branch_id", "TEXT"),
                ("workspace_generation", "INTEGER DEFAULT 1"),
                ("snapshot_reference", "TEXT"),
                ("authorization_context_json", "TEXT"),
            ]:
                try:
                    conn.execute(f"ALTER TABLE checkpoints ADD COLUMN {col} {col_type}")
                except sqlite3.OperationalError:
                    pass

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

    def _row_to_checkpoint(self, r: sqlite3.Row) -> Checkpoint:
        keys = r.keys()
        auth_context = {}
        if "authorization_context_json" in keys and r["authorization_context_json"]:
            try:
                auth_context = json.loads(r["authorization_context_json"])
            except Exception:
                pass
        return Checkpoint(
            id=r["id"],
            session_id=r["session_id"],
            task_id=r["task_id"],
            workspace_version=r["workspace_version"],
            execution_state_key=r["execution_state_key"],
            parent_checkpoint_id=r["parent_checkpoint_id"] if "parent_checkpoint_id" in keys else None,
            branch_id=r["branch_id"] if "branch_id" in keys else None,
            workspace_generation=r["workspace_generation"] if "workspace_generation" in keys and r["workspace_generation"] is not None else 1,
            snapshot_reference=r["snapshot_reference"] if "snapshot_reference" in keys else None,
            authorization_context=auth_context,
            created_at=r["created_at"],
            metadata=json.loads(r["metadata_json"]) if r["metadata_json"] else {},
        )

    def _row_to_branch(self, r: sqlite3.Row) -> ExecutionBranch:
        keys = r.keys()
        delegation_chain = []
        if "delegation_chain_json" in keys and r["delegation_chain_json"]:
            try:
                delegation_chain = json.loads(r["delegation_chain_json"])
            except Exception:
                pass
        return ExecutionBranch(
            branch_id=r["branch_id"],
            parent_checkpoint_id=r["parent_checkpoint_id"],
            session_id=r["session_id"],
            agent_id=r["agent_id"],
            task_id=r["task_id"],
            workspace_id=r["workspace_id"],
            identity_subject=r["identity_subject"],
            scope_id=r["scope_id"],
            delegation_chain=delegation_chain,
            workspace_generation=r["workspace_generation"] if "workspace_generation" in keys and r["workspace_generation"] is not None else 1,
            snapshot_reference=r["snapshot_reference"],
            hypothesis=r["hypothesis"],
            status=BranchStatus(r["status"]) if isinstance(r["status"], str) else r["status"],
            created_at=r["created_at"],
            metadata=json.loads(r["metadata_json"]) if r["metadata_json"] else {},
        )

    def save_checkpoint(self, checkpoint: Checkpoint) -> None:
        with self._get_connection() as conn:
            conn.execute("""
                INSERT INTO checkpoints (
                    id, session_id, task_id, workspace_version,
                    execution_state_key, parent_checkpoint_id, branch_id,
                    workspace_generation, snapshot_reference, authorization_context_json,
                    created_at, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    execution_state_key=excluded.execution_state_key,
                    parent_checkpoint_id=excluded.parent_checkpoint_id,
                    branch_id=excluded.branch_id,
                    workspace_generation=excluded.workspace_generation,
                    snapshot_reference=excluded.snapshot_reference,
                    authorization_context_json=excluded.authorization_context_json,
                    metadata_json=excluded.metadata_json
            """, (
                checkpoint.id,
                checkpoint.session_id,
                checkpoint.task_id,
                checkpoint.workspace_version,
                checkpoint.execution_state_key,
                checkpoint.parent_checkpoint_id,
                checkpoint.branch_id,
                checkpoint.workspace_generation,
                checkpoint.snapshot_reference,
                json.dumps(checkpoint.authorization_context),
                checkpoint.created_at,
                json.dumps(checkpoint.metadata),
            ))

    def get_checkpoint(self, checkpoint_id: str) -> Optional[Checkpoint]:
        with self._get_connection() as conn:
            row = conn.execute("SELECT * FROM checkpoints WHERE id = ?", (checkpoint_id,)).fetchone()
            if not row:
                return None
            return self._row_to_checkpoint(row)

    def list_checkpoints(self, session_id: str) -> List[Checkpoint]:
        with self._get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM checkpoints WHERE session_id = ? ORDER BY created_at ASC",
                (session_id,)
            ).fetchall()
            return [self._row_to_checkpoint(r) for r in rows]

    def save_branch(self, branch: ExecutionBranch) -> None:
        with self._get_connection() as conn:
            conn.execute("""
                INSERT INTO branches (
                    branch_id, parent_checkpoint_id, session_id, agent_id,
                    task_id, workspace_id, identity_subject, scope_id,
                    delegation_chain_json, workspace_generation, snapshot_reference,
                    hypothesis, status, created_at, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(branch_id) DO UPDATE SET
                    status=excluded.status,
                    metadata_json=excluded.metadata_json
            """, (
                branch.branch_id,
                branch.parent_checkpoint_id,
                branch.session_id,
                branch.agent_id,
                branch.task_id,
                branch.workspace_id,
                branch.identity_subject,
                branch.scope_id,
                json.dumps(branch.delegation_chain),
                branch.workspace_generation,
                branch.snapshot_reference,
                branch.hypothesis,
                branch.status.value if isinstance(branch.status, BranchStatus) else branch.status,
                branch.created_at,
                json.dumps(branch.metadata),
            ))

    def get_branch(self, branch_id: str) -> Optional[ExecutionBranch]:
        with self._get_connection() as conn:
            row = conn.execute("SELECT * FROM branches WHERE branch_id = ?", (branch_id,)).fetchone()
            if not row:
                return None
            return self._row_to_branch(row)

    def list_branches(
        self,
        session_id: Optional[str] = None,
        parent_checkpoint_id: Optional[str] = None,
    ) -> List[ExecutionBranch]:
        query = "SELECT * FROM branches WHERE 1=1"
        params: List[Any] = []
        if session_id:
            query += " AND session_id = ?"
            params.append(session_id)
        if parent_checkpoint_id:
            query += " AND parent_checkpoint_id = ?"
            params.append(parent_checkpoint_id)
        query += " ORDER BY created_at ASC"
        with self._get_connection() as conn:
            rows = conn.execute(query, params).fetchall()
            return [self._row_to_branch(r) for r in rows]

    def update_branch_status(self, branch_id: str, status: BranchStatus) -> None:
        with self._get_connection() as conn:
            status_val = status.value if isinstance(status, BranchStatus) else status
            conn.execute("UPDATE branches SET status = ? WHERE branch_id = ?", (status_val, branch_id))

    def get_checkpoint_lineage(self, session_id: str) -> BranchLineage:
        checkpoints = self.list_checkpoints(session_id)
        branches = self.list_branches(session_id=session_id)
        dag: Dict[str, List[str]] = {}
        for c in checkpoints:
            dag[c.id] = []
        for b in branches:
            dag[b.branch_id] = []
            if b.parent_checkpoint_id in dag:
                dag[b.parent_checkpoint_id].append(b.branch_id)
        for c in checkpoints:
            if c.parent_checkpoint_id and c.parent_checkpoint_id in dag:
                dag[c.parent_checkpoint_id].append(c.id)
            if c.branch_id and c.branch_id in dag:
                dag[c.branch_id].append(c.id)

        root_chk = checkpoints[0].id if checkpoints else None
        return BranchLineage(
            session_id=session_id,
            root_checkpoint_id=root_chk,
            total_checkpoints=len(checkpoints),
            total_branches=len(branches),
            lineage_dag=dag,
            checkpoints=[c.to_dict() for c in checkpoints],
            branches=[b.to_dict() for b in branches],
        )

    def _row_to_evaluation(self, r: sqlite3.Row) -> BranchEvaluation:
        return BranchEvaluation(
            evaluation_id=r["evaluation_id"],
            branch_id=r["branch_id"],
            checkpoint_id=r["checkpoint_id"],
            session_id=r["session_id"],
            final_score=r["final_score"],
            is_compliant=bool(r["is_compliant"]),
            disqualified=bool(r["disqualified"]),
            disqualification_reason=r["disqualification_reason"],
            metrics=json.loads(r["metrics_json"]) if r["metrics_json"] else {},
            dimension_details=json.loads(r["details_json"]) if r["details_json"] else {},
            evaluated_at=r["created_at"],
        )

    def save_evaluation(self, evaluation: BranchEvaluation) -> None:
        with self._get_connection() as conn:
            conn.execute("""
                INSERT INTO evaluations (
                    evaluation_id, branch_id, checkpoint_id, session_id,
                    final_score, is_compliant, disqualified, disqualification_reason,
                    metrics_json, details_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(evaluation_id) DO UPDATE SET
                    final_score=excluded.final_score,
                    is_compliant=excluded.is_compliant,
                    disqualified=excluded.disqualified,
                    disqualification_reason=excluded.disqualification_reason,
                    metrics_json=excluded.metrics_json,
                    details_json=excluded.details_json
            """, (
                evaluation.evaluation_id,
                evaluation.branch_id,
                evaluation.checkpoint_id,
                evaluation.session_id,
                evaluation.final_score,
                1 if evaluation.is_compliant else 0,
                1 if evaluation.disqualified else 0,
                evaluation.disqualification_reason,
                json.dumps(evaluation.metrics),
                json.dumps(evaluation.dimension_details),
                evaluation.evaluated_at,
            ))

    def get_evaluation(self, evaluation_id: str) -> Optional[BranchEvaluation]:
        with self._get_connection() as conn:
            row = conn.execute("SELECT * FROM evaluations WHERE evaluation_id = ?", (evaluation_id,)).fetchone()
            if not row:
                return None
            return self._row_to_evaluation(row)

    def list_evaluations(self, session_id: str) -> List[BranchEvaluation]:
        with self._get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM evaluations WHERE session_id = ? ORDER BY final_score DESC",
                (session_id,)
            ).fetchall()
            return [self._row_to_evaluation(r) for r in rows]

    def save_promotion(self, promotion: PromotionResult) -> None:
        with self._get_connection() as conn:
            conn.execute("""
                INSERT INTO promotions (
                    promotion_id, session_id, promoted_branch_id, promoted_checkpoint_id,
                    previous_head_id, new_head_id, evaluation_id, status, promoted_at, audit_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(promotion_id) DO NOTHING
            """, (
                promotion.promotion_id,
                promotion.session_id,
                promotion.promoted_branch_id,
                promotion.promoted_checkpoint_id,
                promotion.previous_head_checkpoint_id,
                promotion.new_head_checkpoint_id,
                promotion.evaluation_id,
                promotion.status,
                promotion.promoted_at,
                promotion.audit_id,
            ))
            # Atomically update session_heads
            conn.execute("""
                INSERT INTO session_heads (session_id, head_checkpoint_id, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    head_checkpoint_id=excluded.head_checkpoint_id,
                    updated_at=excluded.updated_at
            """, (promotion.session_id, promotion.new_head_checkpoint_id, promotion.promoted_at))

    def get_latest_promotion(self, session_id: str) -> Optional[PromotionResult]:
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM promotions WHERE session_id = ? ORDER BY promoted_at DESC LIMIT 1",
                (session_id,)
            ).fetchone()
            if not row:
                return None
            return PromotionResult(
                promotion_id=row["promotion_id"],
                session_id=row["session_id"],
                promoted_branch_id=row["promoted_branch_id"],
                promoted_checkpoint_id=row["promoted_checkpoint_id"],
                previous_head_checkpoint_id=row["previous_head_id"],
                new_head_checkpoint_id=row["new_head_id"],
                evaluation_id=row["evaluation_id"],
                status=row["status"],
                promoted_at=row["promoted_at"],
                audit_id=row["audit_id"],
            )

    def set_session_head(self, session_id: str, checkpoint_id: str) -> None:
        import datetime
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with self._get_connection() as conn:
            conn.execute("""
                INSERT INTO session_heads (session_id, head_checkpoint_id, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    head_checkpoint_id=excluded.head_checkpoint_id,
                    updated_at=excluded.updated_at
            """, (session_id, checkpoint_id, now))

    def get_session_head(self, session_id: str) -> Optional[str]:
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT head_checkpoint_id FROM session_heads WHERE session_id = ?",
                (session_id,)
            ).fetchone()
            if row:
                return row["head_checkpoint_id"]
            chk = conn.execute(
                "SELECT id FROM checkpoints WHERE session_id = ? ORDER BY created_at ASC LIMIT 1",
                (session_id,)
            ).fetchone()
            return chk["id"] if chk else None

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

    def save_agent(self, agent: Agent) -> None:
        with self._get_connection() as conn:
            conn.execute("""
                INSERT INTO agents (
                    agent_id, role, tenant, environment, capabilities_json,
                    identity_subject, task_id, workspace_id, lifecycle_state,
                    session_id, created_at, updated_at, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(agent_id) DO UPDATE SET
                    role=excluded.role,
                    tenant=excluded.tenant,
                    environment=excluded.environment,
                    capabilities_json=excluded.capabilities_json,
                    identity_subject=excluded.identity_subject,
                    task_id=excluded.task_id,
                    workspace_id=excluded.workspace_id,
                    lifecycle_state=excluded.lifecycle_state,
                    session_id=excluded.session_id,
                    updated_at=excluded.updated_at,
                    metadata_json=excluded.metadata_json
            """, (
                agent.agent_id,
                agent.role,
                agent.tenant,
                agent.environment,
                json.dumps(agent.capabilities),
                agent.identity_subject,
                agent.task_id,
                agent.workspace_id,
                agent.lifecycle_state.value,
                agent.session_id,
                agent.created_at,
                agent.updated_at,
                json.dumps(agent.metadata),
            ))

    def get_agent(self, agent_id: str) -> Optional[Agent]:
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM agents WHERE agent_id = ?",
                (agent_id,)
            ).fetchone()
            if not row:
                return None
            return Agent(
                agent_id=row["agent_id"],
                role=row["role"],
                tenant=row["tenant"],
                environment=row["environment"],
                capabilities=json.loads(row["capabilities_json"]),
                identity_subject=row["identity_subject"],
                task_id=row["task_id"],
                workspace_id=row["workspace_id"],
                lifecycle_state=AgentLifecycleState(row["lifecycle_state"]),
                session_id=row["session_id"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                metadata=json.loads(row["metadata_json"]),
            )

    def list_agents(
        self,
        role: Optional[str] = None,
        tenant: Optional[str] = None,
        lifecycle_state: Optional[AgentLifecycleState] = None,
    ) -> List[Agent]:
        query = "SELECT * FROM agents WHERE 1=1"
        params: List[Any] = []
        if role:
            query += " AND role = ?"
            params.append(role)
        if tenant:
            query += " AND tenant = ?"
            params.append(tenant)
        if lifecycle_state:
            query += " AND lifecycle_state = ?"
            params.append(lifecycle_state.value)
        query += " ORDER BY created_at ASC"

        with self._get_connection() as conn:
            rows = conn.execute(query, params).fetchall()
            return [
                Agent(
                    agent_id=r["agent_id"],
                    role=r["role"],
                    tenant=r["tenant"],
                    environment=r["environment"],
                    capabilities=json.loads(r["capabilities_json"]),
                    identity_subject=r["identity_subject"],
                    task_id=r["task_id"],
                    workspace_id=r["workspace_id"],
                    lifecycle_state=AgentLifecycleState(r["lifecycle_state"]),
                    session_id=r["session_id"],
                    created_at=r["created_at"],
                    updated_at=r["updated_at"],
                    metadata=json.loads(r["metadata_json"]),
                )
                for r in rows
            ]

    def delete_agent(self, agent_id: str) -> bool:
        with self._get_connection() as conn:
            cursor = conn.execute("DELETE FROM agents WHERE agent_id = ?", (agent_id,))
            return cursor.rowcount > 0

    def record_revocation(self, jti: str, subject: str, reason: str = "") -> None:
        import datetime
        with self._get_connection() as conn:
            conn.execute("""
                INSERT INTO identity_revocations (jti, subject, revoked_at, reason)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(jti) DO NOTHING
            """, (
                jti,
                subject,
                datetime.datetime.now(datetime.timezone.utc).isoformat(),
                reason,
            ))

    def is_revoked(self, jti: str) -> bool:
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT 1 FROM identity_revocations WHERE jti = ?",
                (jti,)
            ).fetchone()
            return row is not None

    def record_audit_event(self, event: AuditEvent) -> None:
        with self._get_connection() as conn:
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

    def list_audit_events(
        self,
        session_id: Optional[str] = None,
        task_id: Optional[str] = None,
        limit: int = 100,
    ) -> List[AuditEvent]:
        query = "SELECT * FROM audit_events WHERE 1=1"
        params: List[Any] = []
        if session_id:
            query += " AND session_id = ?"
            params.append(session_id)
        if task_id:
            query += " AND task_id = ?"
            params.append(task_id)
        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        with self._get_connection() as conn:
            rows = conn.execute(query, params).fetchall()
            return [
                AuditEvent(
                    event_id=r["event_id"],
                    session_id=r["session_id"],
                    task_id=r["task_id"],
                    from_status=r["from_status"],
                    to_status=r["to_status"],
                    reason=r["reason"],
                    actor=r["actor"],
                    timestamp=r["timestamp"],
                    details=json.loads(r["details_json"]),
                )
                for r in rows
            ]


