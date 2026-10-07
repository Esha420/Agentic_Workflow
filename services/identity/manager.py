"""
services/identity/manager.py — Workload Identity Lifecycle Manager
"""
from __future__ import annotations
import logging
import time
from typing import Any, Dict, Optional, Tuple

from domain.agents.models import Agent, AgentLifecycleState
from domain.identity.models import (
    IdentityProviderInterface,
    WorkloadIdentityToken,
    TokenValidationResult,
)
from domain.identity.provider import OIDCWorkloadIdentityProvider
from services.agents.registry import AgentRegistryService
from adapters.storage.metadata_store import MetadataStoreInterface, SQLiteMetadataStore

logger = logging.getLogger("agent-lab.services.identity")


class IdentityManagerError(Exception):
    pass


class IdentityManager:
    """
    Coordinates workload identity issuance, validation, and lifecycle revocation
    between the Agent Registry and the cryptographic Identity Provider.
    """

    def __init__(
        self,
        registry: Optional[AgentRegistryService] = None,
        identity_provider: Optional[IdentityProviderInterface] = None,
        metadata_store: Optional[MetadataStoreInterface] = None,
    ):
        self.store = metadata_store or SQLiteMetadataStore()
        self.registry = registry or AgentRegistryService(self.store)
        self.provider = identity_provider or OIDCWorkloadIdentityProvider()

    def provision_agent_identity(
        self,
        agent_id: str,
        task_id: str,
        workspace_id: str,
        session_id: Optional[str] = None,
        ttl_seconds: int = 3600,
        scope: Optional[str] = None,
        spiffe_id: Optional[str] = None,
    ) -> Tuple[Agent, WorkloadIdentityToken]:
        """
        Issues a task-scoped cryptographic workload identity token for an agent,
        binding its execution context.
        """
        agent = self.registry.get_agent(agent_id)
        if not agent:
            raise IdentityManagerError(f"Cannot provision identity: agent '{agent_id}' does not exist in registry")

        # Delegate cryptographic token issuance to the Identity Provider
        token = self.provider.issue_identity(
            agent=agent,
            task_id=task_id,
            workspace_id=workspace_id,
            ttl_seconds=ttl_seconds,
            scope=scope,
            spiffe_id=spiffe_id,
        )

        # Update logical agent directory record with execution binding and token metadata
        token_metadata = {
            "last_issued_jti": token.jti,
            "last_issued_at": token.issued_at,
            "expires_at": token.expires_at,
            "issuer": token.issuer,
            "audience": token.audience,
            "token_preview": f"{token.raw_token[:16]}...{token.raw_token[-12:]}",
        }
        agent = self.registry.bind_execution(
            agent_id=agent_id,
            task_id=task_id,
            workspace_id=workspace_id,
            session_id=session_id,
        )
        self.registry.update_lifecycle(agent_id, AgentLifecycleState.ACTIVE, metadata_updates={"identity": token_metadata})

        logger.info(f"Provisioned workload identity for '{agent_id}' bound to task '{task_id}', jti={token.jti}")
        return agent, token

    def verify_workload_token(
        self,
        token: str,
        expected_task_id: Optional[str] = None,
        expected_workspace_id: Optional[str] = None,
    ) -> TokenValidationResult:
        """
        Cryptographically verifies an incoming workload token and checks its
        task and workspace context bounds.
        """
        result = self.provider.validate_identity(
            token=token,
            expected_task_id=expected_task_id,
            expected_workspace_id=expected_workspace_id,
        )
        # Also check persistent revocation store if jti is present
        if result.claims and "jti" in result.claims:
            jti = result.claims["jti"]
            if self.store.is_revoked(jti):
                return TokenValidationResult(
                    valid=False,
                    subject=result.subject,
                    claims=result.claims,
                    error=f"Token {jti} is recorded as revoked in persistent store",
                )
        return result

    def revoke_token(self, jti: str, subject: str = "", reason: str = "") -> bool:
        """Explicitly revokes a workload identity token."""
        self.provider.revoke_identity(jti, reason=reason)
        self.store.record_revocation(jti, subject=subject, reason=reason)
        logger.info(f"Revoked token {jti} for subject '{subject}': {reason}")
        return True

    def terminate_agent_identity(self, agent_id: str, reason: str = "Lifecycle completed") -> bool:
        """
        Terminates the logical agent's active execution and revokes any active tokens.
        """
        agent = self.registry.get_agent(agent_id)
        if not agent:
            return False

        id_meta = agent.metadata.get("identity", {})
        jti = id_meta.get("last_issued_jti")
        if jti:
            self.revoke_token(jti, subject=agent.identity_subject, reason=reason)

        self.registry.update_lifecycle(agent_id, AgentLifecycleState.TERMINATED, metadata_updates={"termination_reason": reason})
        return True

    def get_agent_identity_status(self, agent_id: str) -> Dict[str, Any]:
        """Inspects the current cryptographic identity status of an agent."""
        agent = self.registry.get_agent(agent_id)
        if not agent:
            raise IdentityManagerError(f"Agent '{agent_id}' not found")

        id_meta = agent.metadata.get("identity", {})
        jti = id_meta.get("last_issued_jti")
        now = time.time()
        expires_at = id_meta.get("expires_at", 0)

        is_revoked = self.store.is_revoked(jti) if jti else False
        is_expired = now > expires_at if expires_at else True
        is_valid = bool(jti and not is_revoked and not is_expired and agent.lifecycle_state != AgentLifecycleState.TERMINATED)

        return {
            "agent_id": agent.agent_id,
            "subject": agent.identity_subject,
            "role": agent.role,
            "tenant": agent.tenant,
            "environment": agent.environment,
            "task_id": agent.task_id,
            "workspace_id": agent.workspace_id,
            "lifecycle_state": agent.lifecycle_state.value,
            "identity": {
                "jti": jti,
                "issuer": id_meta.get("issuer"),
                "audience": id_meta.get("audience"),
                "token_preview": id_meta.get("token_preview"),
                "issued_at": id_meta.get("last_issued_at"),
                "expires_at": expires_at,
                "is_expired": is_expired,
                "is_revoked": is_revoked,
                "is_valid": is_valid,
            },
        }
