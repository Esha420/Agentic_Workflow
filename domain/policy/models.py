"""
domain/policy/models.py — Domain models for Trust & Scope Plane
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
import fnmatch
from typing import Any, Dict, List, Optional
import uuid


class EvaluationVerdict(str, Enum):
    ALLOWED = "ALLOWED"
    DENIED = "DENIED"


class RuleEffect(str, Enum):
    ALLOW = "ALLOW"
    DENY = "DENY"


@dataclass
class Capability:
    """
    Authoritative definition of a typed capability in Agent Lab.
    Defines permissible actions, eligible roles, resource patterns, and delegation depth.
    """
    name: str
    description: str
    allowed_roles: List[str] = field(default_factory=list)
    allowed_actions: List[str] = field(default_factory=list)
    resource_path_pattern: str = "/workspace/*"
    default_ttl_seconds: int = 900
    max_delegation_depth: int = 1
    metadata: Dict[str, Any] = field(default_factory=dict)

    def is_role_allowed(self, role: str) -> bool:
        return "*" in self.allowed_roles or role in self.allowed_roles

    def is_action_allowed(self, action: str) -> bool:
        return "*" in self.allowed_actions or action in self.allowed_actions

    def is_resource_allowed(self, resource_path: str) -> bool:
        return fnmatch.fnmatch(resource_path, self.resource_path_pattern)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Capability:
        return cls(**data)


@dataclass
class PolicyRule:
    """
    Explicit authorization policy rule evaluated by the Policy Engine.
    """
    rule_id: str
    name: str
    effect: RuleEffect
    target_roles: List[str] = field(default_factory=list)
    target_capabilities: List[str] = field(default_factory=list)
    target_tenants: List[str] = field(default_factory=list)
    target_environments: List[str] = field(default_factory=list)
    conditions: Dict[str, Any] = field(default_factory=dict)

    def matches(
        self,
        role: str,
        capability: str,
        tenant: str,
        environment: str,
    ) -> bool:
        role_match = not self.target_roles or "*" in self.target_roles or role in self.target_roles
        cap_match = not self.target_capabilities or "*" in self.target_capabilities or capability in self.target_capabilities
        tenant_match = not self.target_tenants or "*" in self.target_tenants or tenant in self.target_tenants
        env_match = not self.target_environments or "*" in self.target_environments or environment in self.target_environments
        return role_match and cap_match and tenant_match and env_match

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["effect"] = self.effect.value
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> PolicyRule:
        data = dict(data)
        if "effect" in data and isinstance(data["effect"], str):
            data["effect"] = RuleEffect(data["effect"])
        return cls(**data)


@dataclass
class AuthorizationRequest:
    """
    Invocation context presented to the Policy Engine for evaluation.
    """
    identity_token: str
    requested_capability: str
    requested_action: str
    target_resource: str
    task_id: str
    workspace_id: str
    target_agent: Optional[str] = None
    delegation_depth: int = 0
    environment: str = "staging"
    parameters: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PolicyEvaluationResult:
    """
    Outcome of evaluating the 6-dimension Contextual Intersection model.
    """
    verdict: EvaluationVerdict
    reason: str
    rule_id: Optional[str] = None
    effective_scope: Optional[Dict[str, Any]] = None
    audit_id: str = field(default_factory=lambda: f"aud-{uuid.uuid4().hex[:8]}")
    evaluated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["verdict"] = self.verdict.value
        return d


@dataclass
class ScopeToken:
    """
    Short-lived, cryptographically signed authorization token carrying effective scope.
    """
    scope_id: str
    subject: str
    task_id: str
    workspace_id: str
    capability: str
    allowed_actions: List[str]
    resource_pattern: str
    max_invocations: int
    invocations_remaining: int
    issued_at: int
    expires_at: int
    delegation_depth: int
    raw_token: str
    claims: Dict[str, Any] = field(default_factory=dict)

    def is_expired(self) -> bool:
        return datetime.now(timezone.utc).timestamp() > self.expires_at

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
