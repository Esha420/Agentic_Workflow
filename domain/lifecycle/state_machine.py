"""
domain/lifecycle/state_machine.py — Explicit lifecycle state machine and validation
"""
from __future__ import annotations
from typing import Dict, Set, Tuple
from domain.sessions.models import SessionStatus


class InvalidTransitionError(Exception):
    """Raised when an illegal lifecycle transition is attempted."""
    def __init__(self, from_status: SessionStatus, to_status: SessionStatus, reason: str = ""):
        msg = f"Cannot transition session from '{from_status.value}' to '{to_status.value}'"
        if reason:
            msg += f": {reason}"
        super().__init__(msg)
        self.from_status = from_status
        self.to_status = to_status


class LifecycleStateMachine:
    """
    Validates and enforces deterministic transitions for ResearchSession.
    """

    ALLOWED_TRANSITIONS: Dict[SessionStatus, Set[SessionStatus]] = {
        SessionStatus.CREATED: {
            SessionStatus.STARTING,
            SessionStatus.CANCELLED,
            SessionStatus.FAILED,
        },
        SessionStatus.STARTING: {
            SessionStatus.RUNNING,
            SessionStatus.FAILED,
            SessionStatus.CANCELLED,
        },
        SessionStatus.RUNNING: {
            SessionStatus.WAITING,
            SessionStatus.SUSPENDING,
            SessionStatus.COMPLETED,
            SessionStatus.FAILED,
            SessionStatus.CANCELLED,
        },
        SessionStatus.WAITING: {
            SessionStatus.SUSPENDING,
            SessionStatus.RUNNING,  # Fast wake before suspension
            SessionStatus.FAILED,
            SessionStatus.CANCELLED,
        },
        SessionStatus.SUSPENDING: {
            SessionStatus.SUSPENDED,
            SessionStatus.FAILED,
        },
        SessionStatus.SUSPENDED: {
            SessionStatus.RESUMING,
            SessionStatus.CANCELLED,
        },
        SessionStatus.RESUMING: {
            SessionStatus.RUNNING,
            SessionStatus.FAILED,
        },
        SessionStatus.COMPLETED: set(),  # Terminal
        SessionStatus.FAILED: set(),     # Terminal
        SessionStatus.CANCELLED: set(),  # Terminal
    }

    @classmethod
    def can_transition(cls, from_status: SessionStatus, to_status: SessionStatus) -> bool:
        if from_status == to_status:
            return True  # Idempotent no-op
        return to_status in cls.ALLOWED_TRANSITIONS.get(from_status, set())

    @classmethod
    def validate_transition(
        cls,
        from_status: SessionStatus,
        to_status: SessionStatus,
        reason: str = "",
    ) -> None:
        if not cls.can_transition(from_status, to_status):
            raise InvalidTransitionError(from_status, to_status, reason)
