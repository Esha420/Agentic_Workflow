"""
services/orchestrator/orchestrator.py — ResearchSession & Lifecycle Orchestrator
"""
from __future__ import annotations
import logging
import time
import uuid
from typing import Any, Dict, List, Optional
from domain.sessions.models import ResearchSession, SessionStatus
from domain.tasks.models import Task, TaskPhase
from domain.checkpoints.models import Checkpoint
from domain.lifecycle.transitions import LifecycleTransitionManager
from domain.lifecycle.policies import SuspensionPolicy
from adapters.ax.ax_adapter import AXAdapterInterface, ClusterAXAdapter
from adapters.storage.metadata_store import MetadataStoreInterface, SQLiteMetadataStore

logger = logging.getLogger("agent-lab.orchestrator")


class OrchestratorError(Exception):
    pass


class ResearchSessionService:
    """
    Coordinates the end-to-end lifecycle of research sessions across the control plane
    and the AX execution plane.
    """

    def __init__(
        self,
        metadata_store: Optional[MetadataStoreInterface] = None,
        ax_adapter: Optional[AXAdapterInterface] = None,
        suspension_policy: Optional[SuspensionPolicy] = None,
    ):
        self.store = metadata_store or SQLiteMetadataStore()
        self.ax = ax_adapter or ClusterAXAdapter()
        self.policy = suspension_policy or SuspensionPolicy()

    def create_session(
        self,
        objective: str,
        session_id: Optional[str] = None,
        target: str = "Autonomous Actor Checkpointing & State Persistence",
        role: str = "research",
        atespace: str = "default",
        idempotency_key: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ResearchSession:
        """Creates a research session and launches its execution task."""
        if idempotency_key:
            cached = self.store.check_idempotency(idempotency_key)
            if cached:
                logger.info(f"Returning cached session for idempotency key '{idempotency_key}'")
                return ResearchSession.from_dict(cached)

        session_id = session_id or f"rs-{uuid.uuid4().hex[:8]}"
        existing = self.store.get_session(session_id)
        if existing:
            raise OrchestratorError(f"Research session with id '{session_id}' already exists")

        session = ResearchSession(
            id=session_id,
            objective=objective,
            target=target,
            role=role,
            atespace=atespace,
            workspace_id=f"ws-{session_id}",
            metadata=metadata or {},
        )

        # Transition: CREATED -> STARTING
        LifecycleTransitionManager.transition(
            session=session,
            target_status=SessionStatus.STARTING,
            reason="Session initialization",
            actor="orchestrator",
        )
        self.store.save_session(session)

        # Apply AX Task
        task_name = f"task-{session_id}"
        try:
            task = self.ax.apply_task(
                task_name=task_name,
                session_id=session_id,
                target=target,
                atespace=atespace,
            )
            session.active_task_id = task.id
            self.store.save_task(task)

            # Transition: STARTING -> RUNNING
            LifecycleTransitionManager.transition(
                session=session,
                target_status=SessionStatus.RUNNING,
                reason="Task scheduled on AX execution plane",
                actor="orchestrator",
                details={"task_name": task.id},
            )
            self.store.save_session(session)

        except Exception as e:
            LifecycleTransitionManager.transition(
                session=session,
                target_status=SessionStatus.FAILED,
                reason=f"Failed to schedule AX task: {e}",
                actor="orchestrator",
            )
            self.store.save_session(session)
            raise OrchestratorError(f"Failed to create session task: {e}") from e

        if idempotency_key:
            self.store.record_idempotency(idempotency_key, session.to_dict())

        return session

    def get_session(self, session_id: str, sync: bool = True) -> Optional[ResearchSession]:
        session = self.store.get_session(session_id)
        if not session:
            return None

        if sync and session.active_task_id:
            self.sync_session_state(session)

        return session

    def list_sessions(self, status: Optional[SessionStatus] = None) -> List[ResearchSession]:
        return self.store.list_sessions(status)

    def sync_session_state(self, session: ResearchSession) -> ResearchSession:
        """Polls AX execution state and reconciles session status."""
        if not session.active_task_id:
            return session

        try:
            ax_task = self.ax.get_task(session.active_task_id, atespace=session.atespace)
            if not ax_task:
                return session

            session.active_worker_ip = ax_task.worker_ip
            self.store.save_task(ax_task)

            # Reconcile status transitions
            if ax_task.phase == TaskPhase.SUSPENDED and session.status not in (
                SessionStatus.SUSPENDED,
                SessionStatus.SUSPENDING,
            ):
                LifecycleTransitionManager.transition(
                    session=session,
                    target_status=SessionStatus.SUSPENDED,
                    reason="AX reported Task suspended; worker compute reclaimed",
                    actor="ax_sync",
                )
                self.store.save_session(session)

            elif ax_task.phase == TaskPhase.RUNNING and session.status in (
                SessionStatus.SUSPENDED,
                SessionStatus.RESUMING,
                SessionStatus.STARTING,
            ):
                LifecycleTransitionManager.transition(
                    session=session,
                    target_status=SessionStatus.RUNNING,
                    reason="AX reported Task running on worker",
                    actor="ax_sync",
                    details={"worker_ip": ax_task.worker_ip},
                )
                self.store.save_session(session)

            elif ax_task.phase == TaskPhase.COMPLETED and session.status != SessionStatus.COMPLETED:
                LifecycleTransitionManager.transition(
                    session=session,
                    target_status=SessionStatus.COMPLETED,
                    reason="AX reported Task completed successfully",
                    actor="ax_sync",
                )
                self.store.save_session(session)

            elif ax_task.phase == TaskPhase.FAILED and session.status != SessionStatus.FAILED:
                LifecycleTransitionManager.transition(
                    session=session,
                    target_status=SessionStatus.FAILED,
                    reason="AX reported Task execution failure",
                    actor="ax_sync",
                )
                self.store.save_session(session)

        except Exception as e:
            logger.warning(f"Error syncing task state for session '{session.id}': {e}")

        return session

    def suspend_session(
        self,
        session_id: str,
        reason: str = "Operator requested suspend",
        actor: str = "operator",
        idempotency_key: Optional[str] = None,
    ) -> ResearchSession:
        """Suspends active session task and confirms worker reclamation."""
        if idempotency_key:
            cached = self.store.check_idempotency(idempotency_key)
            if cached:
                return ResearchSession.from_dict(cached)

        session = self.get_session(session_id, sync=True)
        if not session:
            raise OrchestratorError(f"Session '{session_id}' not found")

        if session.status == SessionStatus.SUSPENDED:
            logger.info(f"Session '{session_id}' is already suspended")
            return session

        if not session.active_task_id:
            raise OrchestratorError(f"Session '{session_id}' has no active task to suspend")

        # Transition: RUNNING/WAITING -> SUSPENDING
        LifecycleTransitionManager.transition(
            session=session,
            target_status=SessionStatus.SUSPENDING,
            reason=reason,
            actor=actor,
        )
        self.store.save_session(session)

        # Execute AX suspend
        try:
            self.ax.suspend_task(session.active_task_id, atespace=session.atespace)
        except Exception as e:
            LifecycleTransitionManager.transition(
                session=session,
                target_status=SessionStatus.FAILED,
                reason=f"Failed to suspend AX task: {e}",
                actor=actor,
            )
            self.store.save_session(session)
            raise OrchestratorError(f"AX suspend failed: {e}") from e

        # Wait briefly for AX status update
        time.sleep(1)

        # Capture checkpoint record
        checkpoint = Checkpoint(
            session_id=session.id,
            task_id=session.active_task_id,
            workspace_version=f"v-{int(time.time())}",
            metadata={"reason": reason, "suspended_at_version": session.version},
        )
        self.store.save_checkpoint(checkpoint)

        # Transition: SUSPENDING -> SUSPENDED
        LifecycleTransitionManager.transition(
            session=session,
            target_status=SessionStatus.SUSPENDED,
            reason="Worker released; checkpoint saved to RustFS",
            actor=actor,
            details={"checkpoint_id": checkpoint.id},
        )
        session.active_worker_ip = None
        self.store.save_session(session)

        if idempotency_key:
            self.store.record_idempotency(idempotency_key, session.to_dict())

        return session

    def resume_session(
        self,
        session_id: str,
        reason: str = "Operator requested resume",
        actor: str = "operator",
        idempotency_key: Optional[str] = None,
    ) -> ResearchSession:
        """Resumes a suspended session onto an available worker."""
        if idempotency_key:
            cached = self.store.check_idempotency(idempotency_key)
            if cached:
                return ResearchSession.from_dict(cached)

        session = self.get_session(session_id, sync=True)
        if not session:
            raise OrchestratorError(f"Session '{session_id}' not found")

        if session.status == SessionStatus.RUNNING:
            logger.info(f"Session '{session_id}' is already running")
            return session

        if not session.active_task_id:
            raise OrchestratorError(f"Session '{session_id}' has no active task to resume")

        # Transition: SUSPENDED -> RESUMING
        LifecycleTransitionManager.transition(
            session=session,
            target_status=SessionStatus.RESUMING,
            reason=reason,
            actor=actor,
        )
        self.store.save_session(session)

        # Execute AX resume
        try:
            self.ax.resume_task(session.active_task_id, atespace=session.atespace)
        except Exception as e:
            LifecycleTransitionManager.transition(
                session=session,
                target_status=SessionStatus.FAILED,
                reason=f"Failed to resume AX task: {e}",
                actor=actor,
            )
            self.store.save_session(session)
            raise OrchestratorError(f"AX resume failed: {e}") from e

        # Wait briefly for AX status update
        time.sleep(1)

        # Transition: RESUMING -> RUNNING
        LifecycleTransitionManager.transition(
            session=session,
            target_status=SessionStatus.RUNNING,
            reason="Actor restored from snapshot onto available worker",
            actor=actor,
        )
        self.sync_session_state(session)
        self.store.save_session(session)

        if idempotency_key:
            self.store.record_idempotency(idempotency_key, session.to_dict())

        return session

    def delete_session(self, session_id: str) -> bool:
        session = self.get_session(session_id, sync=False)
        if not session:
            return False

        if session.active_task_id:
            try:
                self.ax.delete_task(session.active_task_id, atespace=session.atespace)
            except Exception as e:
                logger.warning(f"Error deleting AX task for session '{session_id}': {e}")

        return self.store.delete_session(session_id)

    def read_session_artifact(self, session_id: str, relative_path: str = "report.md") -> Optional[str]:
        session = self.get_session(session_id, sync=True)
        if not session or not session.active_task_id:
            return None

        # Execute ssh cat inside task container
        file_path = f"/workspace/{relative_path}"
        code, stdout, stderr = self.ax.exec_task(
            session.active_task_id,
            ["cat", file_path],
            atespace=session.atespace,
        )
        if code == 0:
            return stdout
        return None
