"""
domain/lifecycle/transitions.py — State transition executors
"""
from __future__ import annotations
from typing import Any, Dict, Optional
from domain.sessions.models import ResearchSession, SessionStatus, AuditEvent
from domain.lifecycle.state_machine import LifecycleStateMachine, InvalidTransitionError


class LifecycleTransitionManager:
    """Coordinates lifecycle transitions on ResearchSession instances."""

    @staticmethod
    def transition(
        session: ResearchSession,
        target_status: SessionStatus,
        reason: str,
        actor: str = "system",
        expected_version: Optional[int] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> AuditEvent:
        """
        Executes a validated, optimistic-concurrency protected state transition.
        """
        if expected_version is not None and session.version != expected_version:
            raise ValueError(
                f"Optimistic lock conflict: session '{session.id}' is at version {session.version}, "
                f"expected {expected_version}"
            )

        # Validate legal transition
        LifecycleStateMachine.validate_transition(session.status, target_status, reason)

        # If idempotent same-state request, return dummy audit event without incrementing version
        if session.status == target_status:
            return AuditEvent(
                session_id=session.id,
                task_id=session.active_task_id,
                from_status=session.status.value,
                to_status=target_status.value,
                reason=f"Idempotent {reason}",
                actor=actor,
                details=details or {},
            )

        # Mutate and record
        return session.record_transition(
            to_status=target_status,
            reason=reason,
            actor=actor,
            details=details,
        )
