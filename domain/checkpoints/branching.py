"""
domain/checkpoints/branching.py — Checkpoint Branching and Lineage domain models
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
import uuid


class BranchStatus(str, Enum):
    CREATED = "CREATED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    ABANDONED = "ABANDONED"


@dataclass
class ExecutionBranch:
    branch_id: str = field(default_factory=lambda: f"br-{uuid.uuid4().hex[:8]}")
    parent_checkpoint_id: str = ""
    session_id: str = ""
    agent_id: str = ""
    task_id: str = ""
    workspace_id: str = ""
    identity_subject: str = ""
    scope_id: str = ""
    delegation_chain: List[str] = field(default_factory=list)
    workspace_generation: int = 1
    snapshot_reference: str = ""
    hypothesis: str = ""
    status: BranchStatus = BranchStatus.CREATED
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value if isinstance(self.status, BranchStatus) else self.status
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ExecutionBranch:
        data = dict(data)
        if "status" in data and isinstance(data["status"], str):
            data["status"] = BranchStatus(data["status"])
        return cls(**data)


@dataclass
class BranchRequest:
    parent_checkpoint_id: str
    caller_identity_token: str
    source_scope_token: str
    hypothesis: str
    branch_name: Optional[str] = None
    target_agent_id: Optional[str] = None
    requested_capabilities: Optional[List[str]] = None
    requested_actions: Optional[List[str]] = None
    requested_resources: Optional[List[str]] = None
    requested_ttl: int = 3600
    max_invocations: int = 10
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class BranchLineageNode:
    checkpoint_id: str
    parent_checkpoint_id: Optional[str]
    session_id: str
    branch_id: Optional[str]
    workspace_generation: int
    created_at: str
    branches: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class BranchLineage:
    session_id: str
    root_checkpoint_id: Optional[str]
    total_checkpoints: int
    total_branches: int
    lineage_dag: Dict[str, List[str]]
    checkpoints: List[Dict[str, Any]]
    branches: List[Dict[str, Any]]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
