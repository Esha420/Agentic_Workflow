"""
domain/delegation/models.py — Domain Models for Multi-Agent Delegation & Child Scope
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
import fnmatch
from typing import Any, Dict, List, Optional
import uuid


class DelegationVerdict(str, Enum):
    ALLOWED = "ALLOWED"
    DENIED = "DENIED"


@dataclass
class DelegationRequest:
    """
    Structured delegation request presented to the Delegation Engine.
    Agent A requests to delegate bounded capability to Agent B.
    """
    caller_identity_token: str
    parent_scope_token: str
    target_agent_id: str
    task_id: str
    workspace_id: str
    requested_capability: str
    requested_action: str = "*"
    requested_resource: str = "/workspace/*"
    requested_ttl_seconds: Optional[int] = None
    requested_max_invocations: Optional[int] = None
    requested_delegation_depth: int = 0
    environment: str = "staging"
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ChildScopeToken:
    """
    Cryptographically signed, short-lived delegated child scope token.
    Explicitly retains end-to-end delegation provenance and remaining depth.
    Invariant: Child Scope ⊆ Parent Scope.
    """
    scope_id: str
    parent_scope_id: str
    delegated_by: str                 # Caller agent subject
    child_subject: str                # Target agent subject
    original_subject: str             # Root initiator subject
    delegation_chain: List[str]       # Ordered provenance: [root, hop_1, ..., hop_n]
    task_id: str
    workspace_id: str
    capability: str
    allowed_actions: List[str]
    resource_pattern: str
    max_invocations: int
    invocations_remaining: int
    issued_at: int
    expires_at: int
    remaining_delegation_depth: int
    raw_token: str
    claims: Dict[str, Any] = field(default_factory=dict)

    def is_expired(self) -> bool:
        return datetime.now(timezone.utc).timestamp() > self.expires_at

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ChildScopeToken:
        return cls(**data)


@dataclass
class DelegationResult:
    """
    Outcome of evaluating a DelegationRequest against parent scope and delegation policies.
    """
    verdict: DelegationVerdict
    reason: str
    child_scope: Optional[ChildScopeToken] = None
    parent_scope_id: Optional[str] = None
    delegation_chain: List[str] = field(default_factory=list)
    audit_id: str = field(default_factory=lambda: f"dlg-{uuid.uuid4().hex[:8]}")
    evaluated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["verdict"] = self.verdict.value
        return d
