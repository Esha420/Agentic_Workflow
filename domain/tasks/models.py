"""
domain/tasks/models.py — Task domain model
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional


class TaskPhase(str, Enum):
    PENDING = "Pending"
    RUNNING = "Running"
    SUSPENDED = "Suspended"
    COMPLETED = "Completed"
    FAILED = "Failed"
    UNKNOWN = "Unknown"


@dataclass
class Task:
    id: str
    session_id: str
    atespace: str = "default"
    phase: TaskPhase = TaskPhase.PENDING
    actor_id: Optional[str] = None
    worker_ip: Optional[str] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    checkpoint_state_key: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["phase"] = self.phase.value
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Task:
        data = dict(data)
        if "phase" in data and isinstance(data["phase"], str):
            try:
                data["phase"] = TaskPhase(data["phase"])
            except ValueError:
                data["phase"] = TaskPhase.UNKNOWN
        return cls(**data)
