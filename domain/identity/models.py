"""
domain/identity/models.py — Workload Identity Token and Provider Interface
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from domain.agents.models import Agent


@dataclass
class WorkloadIdentityToken:
    """
    Task-scoped OIDC-compatible JWT Workload Identity Token representation.
    """
    raw_token: str
    subject: str
    issuer: str
    audience: str
    task_id: str
    workspace_id: str
    role: str
    tenant: str
    environment: str
    capabilities: List[str]
    issued_at: int
    expires_at: int
    jti: str
    claims: Dict[str, Any] = field(default_factory=dict)
    scope: str = ""
    spiffe_id: Optional[str] = None

    def is_expired(self) -> bool:
        return datetime.now(timezone.utc).timestamp() > self.expires_at

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class TokenValidationResult:
    """Outcome of token cryptographic and contextual claims verification."""
    valid: bool
    subject: Optional[str] = None
    claims: Optional[Dict[str, Any]] = None
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class IdentityProviderInterface(ABC):
    """
    Abstract interface for Identity Providers.
    Decouples Agent Lab and Agent Registry from any specific IdP technology.
    """

    @abstractmethod
    def issue_identity(
        self,
        agent: Agent,
        task_id: str,
        workspace_id: str,
        ttl_seconds: int = 3600,
        scope: Optional[str] = None,
        spiffe_id: Optional[str] = None,
        **kwargs: Any,
    ) -> WorkloadIdentityToken:
        """Issues a cryptographically signed, task-scoped workload identity token."""
        pass

    @abstractmethod
    def validate_identity(
        self,
        token: str,
        expected_task_id: Optional[str] = None,
        expected_workspace_id: Optional[str] = None,
    ) -> TokenValidationResult:
        """Validates token signature, expiration, issuer, audience, and context bindings."""
        pass

    @abstractmethod
    def revoke_identity(self, jti: str, reason: str = "") -> bool:
        """Revokes a specific token by its unique identifier (jti)."""
        pass

    @abstractmethod
    def is_revoked(self, jti: str) -> bool:
        """Checks if a token has been revoked."""
        pass

    @abstractmethod
    def get_subject(self, token: str) -> Optional[str]:
        """Extracts the subject identity from a token string."""
        pass
