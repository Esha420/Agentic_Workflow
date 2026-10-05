"""
domain/sessions/models.py — ResearchSession and Audit domain models
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
import uuid


class SessionStatus(str, Enum):
    CREATED = "CREATED"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    WAITING = "WAITING"
    SUSPENDING = "SUSPENDING"
    SUSPENDED = "SUSPENDED"
    RESUMING = "RESUMING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


@dataclass
class AuditEvent:
    event_id: str = field(default_factory=lambda: f"evt-{uuid.uuid4().hex[:8]}")
    session_id: str = ""
    task_id: Optional[str] = None
    from_status: Optional[str] = None
    to_status: str = ""
    reason: str = ""
    actor: str = "system"
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ResearchSession:
    id: str
    objective: str
    target: str = "Autonomous Actor Checkpointing & State Persistence"
    role: str = "research"
    atespace: str = "default"
    workspace_id: str = ""
    active_task_id: Optional[str] = None
    active_worker_ip: Optional[str] = None
    status: SessionStatus = SessionStatus.CREATED
    version: int = 1  # Optimistic concurrency lock
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    metadata: Dict[str, Any] = field(default_factory=dict)
    audit_trail: List[AuditEvent] = field(default_factory=list)

    def record_transition(
        self,
        to_status: SessionStatus,
        reason: str,
        actor: str = "system",
        details: Optional[Dict[str, Any]] = None,
    ) -> AuditEvent:
        event = AuditEvent(
            session_id=self.id,
            task_id=self.active_task_id,
            from_status=self.status.value,
            to_status=to_status.value,
            reason=reason,
            actor=actor,
            details=details or {},
        )
        self.status = to_status
        self.version += 1
        self.updated_at = datetime.now(timezone.utc).isoformat()
        self.audit_trail.append(event)
        return event

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        d["audit_trail"] = [e.to_dict() if isinstance(e, AuditEvent) else e for e in self.audit_trail]
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ResearchSession:
        data = dict(data)
        if "status" in data and isinstance(data["status"], str):
            data["status"] = SessionStatus(data["status"])
        if "audit_trail" in data:
            data["audit_trail"] = [
                AuditEvent(**e) if isinstance(e, dict) else e for e in data["audit_trail"]
            ]
        return cls(**data)
