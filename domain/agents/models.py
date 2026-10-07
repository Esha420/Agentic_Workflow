"""
domain/agents/models.py — Authoritative Agent Lab Agent domain representation
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
import uuid


class AgentLifecycleState(str, Enum):
    REGISTERED = "REGISTERED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    DRAINING = "DRAINING"
    TERMINATED = "TERMINATED"


@dataclass
class Agent:
    """
    Authoritative logical agent representation in Agent Lab.
    Represents the logical agent entity, independent of physical compute workers.
    """
    agent_id: str
    role: str
    tenant: str = "default"
    environment: str = "staging"
    capabilities: List[str] = field(default_factory=list)
    identity_subject: str = ""
    task_id: Optional[str] = None
    workspace_id: Optional[str] = None
    lifecycle_state: AgentLifecycleState = AgentLifecycleState.REGISTERED
    session_id: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.identity_subject:
            self.identity_subject = f"agent:{self.agent_id}"

    def update_lifecycle(self, state: AgentLifecycleState, metadata_updates: Optional[Dict[str, Any]] = None) -> None:
        self.lifecycle_state = state
        self.updated_at = datetime.now(timezone.utc).isoformat()
        if metadata_updates:
            self.metadata.update(metadata_updates)

    def bind_execution(self, task_id: str, workspace_id: str, session_id: Optional[str] = None) -> None:
        self.task_id = task_id
        self.workspace_id = workspace_id
        if session_id:
            self.session_id = session_id
        self.lifecycle_state = AgentLifecycleState.ACTIVE
        self.updated_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["lifecycle_state"] = self.lifecycle_state.value
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Agent:
        data = dict(data)
        if "lifecycle_state" in data and isinstance(data["lifecycle_state"], str):
            data["lifecycle_state"] = AgentLifecycleState(data["lifecycle_state"])
        if "capabilities" not in data or data["capabilities"] is None:
            data["capabilities"] = []
        if "metadata" not in data or data["metadata"] is None:
            data["metadata"] = {}
        return cls(**data)
