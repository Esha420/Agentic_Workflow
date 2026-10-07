"""
services/gateway/authorizer.py — Agent Gateway In-Path Authorizer with Delegation Support
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
import logging
from typing import Any, Dict, List, Optional
import uuid
import jwt

from domain.sessions.models import AuditEvent
from services.identity.manager import IdentityManager
from services.policy.scope_issuer import ScopeIssuer, ScopeIssuerError
from services.delegation.engine import DelegationEngine, DelegationEngineError
from adapters.storage.metadata_store import MetadataStoreInterface, SQLiteMetadataStore

logger = logging.getLogger("agent-lab.services.gateway.authorizer")


@dataclass
class GatewayAuthorizationDecision:
    """Gateway authorization outcome for an in-flight invocation."""
    allowed: bool
    reason: str
    subject: Optional[str] = None
    capability: Optional[str] = None
    action: Optional[str] = None
    resource: Optional[str] = None
    invocations_remaining: Optional[int] = None
    delegation_chain: List[str] = field(default_factory=list)
    parent_scope_id: Optional[str] = None
    audit_id: str = field(default_factory=lambda: f"gtw-{uuid.uuid4().hex[:8]}")
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class AgentGatewayAuthorizer:
    """
    In-path authorizer intercepting agent invocations at the Agent Gateway boundary.
    Enforces dual verification of Workload Identity Token (M3) and Scope Token (M4/M5),
    verifying target agent identity, delegation provenance, and task/workspace binding.
    """

    def __init__(
        self,
        identity_manager: Optional[IdentityManager] = None,
        scope_issuer: Optional[ScopeIssuer] = None,
        delegation_engine: Optional[DelegationEngine] = None,
        metadata_store: Optional[MetadataStoreInterface] = None,
    ):
        self.store = metadata_store or SQLiteMetadataStore()
        self.identity_mgr = identity_manager or IdentityManager(metadata_store=self.store)
        self.scope_issuer = scope_issuer or ScopeIssuer()
        self.delegation_engine = delegation_engine or DelegationEngine(
            identity_manager=self.identity_mgr,
            scope_issuer=self.scope_issuer,
            metadata_store=self.store,
        )

    def authorize_invocation(
        self,
        identity_token: str,
        scope_token: Optional[str] = None,
        action: str = "",
        resource: str = "",
        task_id: str = "",
        workspace_id: str = "",
        session_id: Optional[str] = None,
    ) -> GatewayAuthorizationDecision:
        """
        Executes fail-closed gateway interception verifying both identity and scope tokens.
        Supports both M4/M5 scope tokens and direct dynamic OIDC scopes.
        """
        # 1. Verify Workload Identity Token (M3 - WHO)
        id_val = self.identity_mgr.verify_workload_token(
            token=identity_token,
            expected_task_id=task_id,
            expected_workspace_id=workspace_id,
        )
        if not id_val.valid:
            decision = GatewayAuthorizationDecision(
                allowed=False,
                reason=f"Gateway rejected: Identity invalid ({id_val.error})",
                action=action,
                resource=resource,
            )
            self._record_audit(decision, session_id=session_id, task_id=task_id)
            return decision

        identity_subject = id_val.subject or ""
        claims = id_val.claims or {}
        oidc_scope = claims.get("scope", "")

        # 2. Direct OIDC Authorization if scope_token is omitted
        if not scope_token:
            if oidc_scope:
                from services.identity.external_oidc_adapter import ExternalOIDCProviderAdapter
                if not ExternalOIDCProviderAdapter.is_action_in_scope(action, oidc_scope):
                    decision = GatewayAuthorizationDecision(
                        allowed=False,
                        reason=f"Gateway rejected: Action '{action}' not permitted by dynamic OIDC scope '{oidc_scope}'",
                        subject=identity_subject,
                        action=action,
                        resource=resource,
                    )
                    self._record_audit(decision, session_id=session_id, task_id=task_id)
                    return decision

            decision = GatewayAuthorizationDecision(
                allowed=True,
                reason="Invocation authorized by Agent Gateway via dynamic OIDC scope",
                subject=identity_subject,
                capability=action.split(":")[0] if ":" in action else "oidc_scoped",
                action=action,
                resource=resource,
                invocations_remaining=None,
                delegation_chain=[identity_subject],
            )
            self._record_audit(decision, session_id=session_id, task_id=task_id)
            return decision

        # 3. Inspect Scope Token (Determine if direct M4 or delegated M5)
        try:
            unverified_claims = jwt.decode(
                scope_token,
                options={"verify_signature": False, "verify_exp": False},
            )
        except Exception as e:
            decision = GatewayAuthorizationDecision(
                allowed=False,
                reason=f"Gateway rejected: Malformed scope token ({e})",
                subject=identity_subject,
                action=action,
                resource=resource,
            )
            self._record_audit(decision, session_id=session_id, task_id=task_id)
            return decision

        # 4. Immediate Subject Binding Check (Prevent Scope Token Theft)
        scope_sub_claim = unverified_claims.get("sub") or unverified_claims.get("child_subject")
        if scope_sub_claim and scope_sub_claim != identity_subject:
            decision = GatewayAuthorizationDecision(
                allowed=False,
                reason=f"Gateway rejected: Scope subject '{scope_sub_claim}' does not match identity subject '{identity_subject}'",
                subject=identity_subject,
                action=action,
                resource=resource,
            )
            self._record_audit(decision, session_id=session_id, task_id=task_id)
            return decision

        is_delegated = "parent_scope_id" in unverified_claims or "delegation_chain" in unverified_claims

        # 5. Verify and Consume Scope Token
        if is_delegated:
            try:
                child_scope = self.delegation_engine.validate_and_consume_child_scope(
                    raw_token=scope_token,
                    expected_action=action,
                    expected_resource=resource,
                )
                scope_subject = child_scope.child_subject
                capability = child_scope.capability
                invocations_remaining = child_scope.invocations_remaining
                delegation_chain = child_scope.delegation_chain
                parent_scope_id = child_scope.parent_scope_id
            except DelegationEngineError as e:
                decision = GatewayAuthorizationDecision(
                    allowed=False,
                    reason=f"Gateway rejected: Delegated scope unauthorized ({e})",
                    subject=identity_subject,
                    action=action,
                    resource=resource,
                )
                self._record_audit(decision, session_id=session_id, task_id=task_id)
                return decision
        else:
            try:
                scope = self.scope_issuer.validate_and_consume_scope(
                    raw_scope_token=scope_token,
                    expected_action=action,
                    expected_resource=resource,
                )
                scope_subject = scope.subject
                capability = scope.capability
                invocations_remaining = scope.invocations_remaining
                delegation_chain = [scope.subject]
                parent_scope_id = None
            except ScopeIssuerError as e:
                decision = GatewayAuthorizationDecision(
                    allowed=False,
                    reason=f"Gateway rejected: Scope unauthorized ({e})",
                    subject=identity_subject,
                    action=action,
                    resource=resource,
                )
                self._record_audit(decision, session_id=session_id, task_id=task_id)
                return decision

        # 6. Subject Binding Invariant (Prevent Scope Token Theft)
        if scope_subject != identity_subject:
            decision = GatewayAuthorizationDecision(
                allowed=False,
                reason=f"Gateway rejected: Scope subject '{scope_subject}' does not match identity subject '{identity_subject}'",
                subject=identity_subject,
                action=action,
                resource=resource,
                delegation_chain=delegation_chain,
                parent_scope_id=parent_scope_id,
            )
            self._record_audit(decision, session_id=session_id, task_id=task_id)
            return decision

        # 7. Success: Approved
        decision = GatewayAuthorizationDecision(
            allowed=True,
            reason="Invocation authorized by Agent Gateway",
            subject=identity_subject,
            capability=capability,
            action=action,
            resource=resource,
            invocations_remaining=invocations_remaining,
            delegation_chain=delegation_chain,
            parent_scope_id=parent_scope_id,
        )
        self._record_audit(decision, session_id=session_id, task_id=task_id)
        return decision

    def _record_audit(
        self,
        decision: GatewayAuthorizationDecision,
        session_id: Optional[str],
        task_id: str,
    ) -> None:
        try:
            event = AuditEvent(
                event_id=decision.audit_id,
                session_id=session_id or "system",
                task_id=task_id,
                from_status="GATEWAY_CHECK",
                to_status="ALLOWED" if decision.allowed else "DENIED",
                reason=decision.reason,
                actor="agent-gateway",
                details={
                    "subject": decision.subject,
                    "capability": decision.capability,
                    "action": decision.action,
                    "resource": decision.resource,
                    "allowed": decision.allowed,
                    "delegation_chain": decision.delegation_chain,
                    "parent_scope_id": decision.parent_scope_id,
                },
            )
            self.store.record_audit_event(event)
        except Exception as e:
            logger.warning(f"Could not record gateway audit event: {e}")
