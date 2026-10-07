"""
services/delegation/engine.py — Delegation Engine enforcing Child Scope ⊆ Parent Scope
"""
from __future__ import annotations
import fnmatch
import logging
import os
import threading
import time
from typing import Any, Dict, List, Optional, Set
import uuid
import jwt

from domain.delegation.models import (
    DelegationRequest,
    ChildScopeToken,
    DelegationResult,
    DelegationVerdict,
)
from domain.sessions.models import AuditEvent
from services.agents.registry import AgentRegistryService
from services.identity.manager import IdentityManager
from services.policy.capabilities import CapabilityRegistry
from services.policy.scope_issuer import ScopeIssuer
from adapters.storage.metadata_store import MetadataStoreInterface, SQLiteMetadataStore

logger = logging.getLogger("agent-lab.services.delegation.engine")


class DelegationEngineError(Exception):
    pass


class DelegationEngine:
    """
    Evaluates and mints delegated Child Scope Tokens enforcing the core security invariant:
    Child Scope ⊆ Parent Scope.
    Guarantees that no sequence of valid delegations can produce authority
    that was not present in the original authorized parent scope.
    """

    def __init__(
        self,
        agent_registry: Optional[AgentRegistryService] = None,
        identity_manager: Optional[IdentityManager] = None,
        capability_registry: Optional[CapabilityRegistry] = None,
        scope_issuer: Optional[ScopeIssuer] = None,
        metadata_store: Optional[MetadataStoreInterface] = None,
        secret_key: Optional[str] = None,
        issuer: str = "https://delegation.agent-lab.internal",
    ):
        self.store = metadata_store or SQLiteMetadataStore()
        self.agent_registry = agent_registry or AgentRegistryService(self.store)
        self.identity_mgr = identity_manager or IdentityManager(registry=self.agent_registry, metadata_store=self.store)
        self.capabilities = capability_registry or CapabilityRegistry()
        self.scope_issuer = scope_issuer or ScopeIssuer()
        self.issuer = issuer
        self.secret_key = secret_key or os.environ.get("AGENT_LAB_SCOPE_SECRET", "agent-lab-dev-scope-secret-2026")
        self._active_child_scopes: Dict[str, ChildScopeToken] = {}
        self._revoked_child_scopes: Set[str] = set()
        self._lock = threading.Lock()

    def delegate(self, request: DelegationRequest) -> DelegationResult:
        """
        Executes fail-closed delegation evaluation and issues a ChildScopeToken if valid.
        """
        now = int(time.time())

        # ======================================================================
        # 1. Validate Caller Workload Identity Token
        # ======================================================================
        id_val = self.identity_mgr.verify_workload_token(
            token=request.caller_identity_token,
            expected_task_id=request.task_id,
            expected_workspace_id=request.workspace_id,
        )
        if not id_val.valid:
            return self._deny(
                reason=f"Caller identity verification failed: {id_val.error}",
                request=request,
            )

        caller_subject = id_val.subject or ""
        caller_agent = self.agent_registry.get_agent_by_subject(caller_subject)
        caller_tenant = caller_agent.tenant if caller_agent else (id_val.claims or {}).get("tenant", "default")

        # ======================================================================
        # 2. Decode & Cryptographically Validate Parent Scope Token
        # ======================================================================
        try:
            parent_claims = jwt.decode(
                request.parent_scope_token,
                self.secret_key,
                algorithms=["HS256"],
                audience="agent-gateway",
                options={"verify_exp": True},
            )
        except jwt.ExpiredSignatureError:
            return self._deny(
                reason="Parent scope token has expired",
                request=request,
            )
        except Exception as e:
            return self._deny(
                reason=f"Parent scope cryptographic verification failed: {e}",
                request=request,
            )

        parent_scope_id = parent_claims.get("scope_id", "")
        parent_target_sub = parent_claims.get("sub", "")

        # Check if parent scope is revoked
        if parent_scope_id in self.scope_issuer._revoked_scopes or parent_scope_id in self._revoked_child_scopes:
            return self._deny(
                reason=f"Parent scope '{parent_scope_id}' has been revoked",
                request=request,
                parent_scope_id=parent_scope_id,
            )

        # Invariant: Caller must own the parent scope
        if caller_subject != parent_target_sub:
            return self._deny(
                reason=f"Caller subject '{caller_subject}' does not match parent scope subject '{parent_target_sub}'",
                request=request,
                parent_scope_id=parent_scope_id,
            )

        # Invariant: Task & Workspace Context Binding
        parent_task = parent_claims.get("task_id")
        parent_ws = parent_claims.get("workspace_id")
        if request.task_id != parent_task:
            return self._deny(
                reason=f"Task binding mismatch: request task '{request.task_id}' != parent scope task '{parent_task}'",
                request=request,
                parent_scope_id=parent_scope_id,
            )
        if request.workspace_id != parent_ws:
            return self._deny(
                reason=f"Workspace binding mismatch: request workspace '{request.workspace_id}' != parent scope workspace '{parent_ws}'",
                request=request,
                parent_scope_id=parent_scope_id,
            )

        # Core Invariant Check: Capability containment (Child Scope ⊆ Parent Scope)
        parent_cap = parent_claims.get("capability")
        if request.requested_capability != parent_cap:
            return self._deny(
                reason=f"Capability escalation denied: requested '{request.requested_capability}' is not granted by parent scope ('{parent_cap}')",
                request=request,
                parent_scope_id=parent_scope_id,
            )

        # ======================================================================
        # 3. Validate Target Agent & Cross-Tenant Isolation
        # ======================================================================

        target_agent = self.agent_registry.get_agent(request.target_agent_id)
        if not target_agent:
            return self._deny(
                reason=f"Target agent '{request.target_agent_id}' not found in registry",
                request=request,
                parent_scope_id=parent_scope_id,
            )

        # Cross-Tenant isolation invariant
        if target_agent.tenant != caller_tenant:
            return self._deny(
                reason=f"Cross-tenant delegation denied: caller tenant '{caller_tenant}' != target tenant '{target_agent.tenant}'",
                request=request,
                parent_scope_id=parent_scope_id,
            )

        # Target Environment invariant
        if target_agent.environment != request.environment:
            return self._deny(
                reason=f"Environment mismatch: target environment '{target_agent.environment}' != request environment '{request.environment}'",
                request=request,
                parent_scope_id=parent_scope_id,
            )

        # Capability role eligibility for target agent
        cap_def = self.capabilities.get_capability(request.requested_capability)
        if not cap_def:
            return self._deny(
                reason=f"Requested capability '{request.requested_capability}' is not registered",
                request=request,
                parent_scope_id=parent_scope_id,
            )
        if not cap_def.is_role_allowed(target_agent.role):
            return self._deny(
                reason=f"Target agent role '{target_agent.role}' is not eligible for capability '{request.requested_capability}'",
                request=request,
                parent_scope_id=parent_scope_id,
            )

        # ======================================================================
        # 4. Validate Delegation Depth Invariant
        # ======================================================================
        parent_depth = parent_claims.get("remaining_delegation_depth")
        if parent_depth is None:
            # Fallback for root M4 scope tokens
            parent_depth = parent_claims.get("delegation_depth", 0)

        if parent_depth <= 0:
            return self._deny(
                reason=f"Delegation depth exhausted: parent scope remaining delegation depth is {parent_depth}",
                request=request,
                parent_scope_id=parent_scope_id,
            )

        child_remaining_depth = min(request.requested_delegation_depth, parent_depth - 1)

        # ======================================================================
        # 5. Core Invariant Check: Child Scope ⊆ Parent Scope
        # ======================================================================
        parent_cap = parent_claims.get("capability")
        if request.requested_capability != parent_cap:
            return self._deny(
                reason=f"Capability escalation denied: requested '{request.requested_capability}' is not granted by parent scope ('{parent_cap}')",
                request=request,
                parent_scope_id=parent_scope_id,
            )

        # Action subset check
        parent_action = parent_claims.get("granted_action", "*")
        if parent_action != "*" and request.requested_action != parent_action:
            return self._deny(
                reason=f"Action escalation denied: requested '{request.requested_action}' is not permitted by parent scope ('{parent_action}')",
                request=request,
                parent_scope_id=parent_scope_id,
            )
        if not cap_def.is_action_allowed(request.requested_action):
            return self._deny(
                reason=f"Action '{request.requested_action}' is not permitted under capability '{cap_def.name}'",
                request=request,
                parent_scope_id=parent_scope_id,
            )

        # Resource path subset check
        parent_res = parent_claims.get("resource_path", "/workspace/*")
        if not self._is_resource_subpattern(child_pattern=request.requested_resource, parent_pattern=parent_res):
            return self._deny(
                reason=f"Resource escalation denied: requested resource '{request.requested_resource}' escapes parent boundary '{parent_res}'",
                request=request,
                parent_scope_id=parent_scope_id,
            )
        if not cap_def.is_resource_allowed(request.requested_resource.rstrip("*").rstrip("/")):
            # Also verify within capability definition pattern
            if not fnmatch.fnmatch(request.requested_resource, cap_def.resource_path_pattern):
                return self._deny(
                    reason=f"Requested resource '{request.requested_resource}' violates capability boundary '{cap_def.resource_path_pattern}'",
                    request=request,
                    parent_scope_id=parent_scope_id,
                )

        # Quota subset check
        parent_max_calls = parent_claims.get("max_invocations", 10)
        # Check parent remaining invocations from active store if present
        parent_token_obj = self.scope_issuer._active_scopes.get(parent_scope_id) or self._active_child_scopes.get(parent_scope_id)
        parent_remaining_calls = parent_token_obj.invocations_remaining if parent_token_obj else parent_max_calls
        if parent_remaining_calls <= 0:
            return self._deny(
                reason=f"Parent scope quota exhausted ({parent_remaining_calls} remaining)",
                request=request,
                parent_scope_id=parent_scope_id,
            )

        requested_quota = request.requested_max_invocations or 5
        child_quota = min(requested_quota, parent_remaining_calls)

        # TTL subset check
        parent_exp = parent_claims.get("exp", now + 900)
        requested_ttl = request.requested_ttl_seconds or 600
        child_exp = min(now + requested_ttl, parent_exp)

        # ======================================================================
        # 6. Issue Delegated Child Scope Token
        # ======================================================================
        child_scope_id = f"dlg-{uuid.uuid4().hex[:10]}"
        parent_chain: List[str] = parent_claims.get("delegation_chain", [parent_target_sub])
        original_subject: str = parent_claims.get("original_subject", parent_chain[0] if parent_chain else parent_target_sub)
        child_chain = list(parent_chain) + [target_agent.identity_subject]

        child_claims: Dict[str, Any] = {
            "iss": self.issuer,
            "sub": target_agent.identity_subject,
            "aud": "agent-gateway",
            "scope_id": child_scope_id,
            "parent_scope_id": parent_scope_id,
            "delegated_by": caller_subject,
            "child_subject": target_agent.identity_subject,
            "original_subject": original_subject,
            "delegation_chain": child_chain,
            "task_id": request.task_id,
            "workspace_id": request.workspace_id,
            "capability": request.requested_capability,
            "granted_action": request.requested_action,
            "resource_path": request.requested_resource,
            "max_invocations": child_quota,
            "remaining_delegation_depth": child_remaining_depth,
            "iat": now,
            "exp": child_exp,
        }

        raw_token = jwt.encode(child_claims, self.secret_key, algorithm="HS256")

        child_token = ChildScopeToken(
            scope_id=child_scope_id,
            parent_scope_id=parent_scope_id,
            delegated_by=caller_subject,
            child_subject=target_agent.identity_subject,
            original_subject=original_subject,
            delegation_chain=child_chain,
            task_id=request.task_id,
            workspace_id=request.workspace_id,
            capability=request.requested_capability,
            allowed_actions=[request.requested_action],
            resource_pattern=request.requested_resource,
            max_invocations=child_quota,
            invocations_remaining=child_quota,
            issued_at=now,
            expires_at=child_exp,
            remaining_delegation_depth=child_remaining_depth,
            raw_token=raw_token,
            claims=child_claims,
        )

        with self._lock:
            self._active_child_scopes[child_scope_id] = child_token

        result = DelegationResult(
            verdict=DelegationVerdict.ALLOWED,
            reason=f"Delegation approved: Child Scope ⊆ Parent Scope. Depth={child_remaining_depth}",
            child_scope=child_token,
            parent_scope_id=parent_scope_id,
            delegation_chain=child_chain,
        )

        self._record_audit(result, request=request, parent_scope_id=parent_scope_id)
        logger.info(f"Delegated Child Scope '{child_scope_id}' from '{caller_subject}' to '{target_agent.identity_subject}' (chain: {' -> '.join(child_chain)})")
        return result

    def validate_and_consume_child_scope(
        self,
        raw_token: str,
        expected_action: str,
        expected_resource: str,
    ) -> ChildScopeToken:
        """
        Validates child scope token, checks parent validity, decrements quota, and returns token.
        """
        try:
            claims = jwt.decode(
                raw_token,
                self.secret_key,
                algorithms=["HS256"],
                audience="agent-gateway",
                options={"verify_exp": True},
            )
        except jwt.ExpiredSignatureError:
            raise DelegationEngineError("Delegated child scope token has expired")
        except Exception as e:
            raise DelegationEngineError(f"Delegated token cryptographic verification failed: {e}")

        scope_id = claims.get("scope_id", "")
        with self._lock:
            if scope_id in self._revoked_child_scopes:
                raise DelegationEngineError(f"Child scope '{scope_id}' has been revoked")

            # Check if parent scope is revoked
            parent_id = claims.get("parent_scope_id")
            if parent_id and (parent_id in self.scope_issuer._revoked_scopes or parent_id in self._revoked_child_scopes):
                raise DelegationEngineError(f"Delegation invalidated: Parent scope '{parent_id}' is revoked")

            token_obj = self._active_child_scopes.get(scope_id)
            if not token_obj:
                # Reconstruct token from claims if cache was reset
                token_obj = ChildScopeToken(
                    scope_id=scope_id,
                    parent_scope_id=claims.get("parent_scope_id", ""),
                    delegated_by=claims.get("delegated_by", ""),
                    child_subject=claims.get("child_subject", claims.get("sub", "")),
                    original_subject=claims.get("original_subject", ""),
                    delegation_chain=claims.get("delegation_chain", []),
                    task_id=claims.get("task_id", ""),
                    workspace_id=claims.get("workspace_id", ""),
                    capability=claims.get("capability", ""),
                    allowed_actions=[claims.get("granted_action", "*")],
                    resource_pattern=claims.get("resource_path", ""),
                    max_invocations=claims.get("max_invocations", 5),
                    invocations_remaining=claims.get("max_invocations", 5),
                    issued_at=claims.get("iat", 0),
                    expires_at=claims.get("exp", 0),
                    remaining_delegation_depth=claims.get("remaining_delegation_depth", 0),
                    raw_token=raw_token,
                    claims=claims,
                )
                self._active_child_scopes[scope_id] = token_obj

            if token_obj.invocations_remaining <= 0:
                raise DelegationEngineError(f"Delegated scope quota exhausted ({token_obj.max_invocations} calls consumed)")

            # Check action and resource bounds
            granted_action = claims.get("granted_action")
            if granted_action != "*" and granted_action != expected_action:
                raise DelegationEngineError(f"Action '{expected_action}' not granted by child scope (granted: '{granted_action}')")

            res_pattern = claims.get("resource_path", "/workspace/*")
            if not fnmatch.fnmatch(expected_resource, res_pattern):
                raise DelegationEngineError(f"Resource '{expected_resource}' escapes child scope pattern '{res_pattern}'")

            token_obj.invocations_remaining -= 1
            return token_obj

    def revoke_child_scope(self, scope_id: str) -> bool:
        with self._lock:
            self._revoked_child_scopes.add(scope_id)
            if scope_id in self._active_child_scopes:
                del self._active_child_scopes[scope_id]
            logger.info(f"Revoked child scope token '{scope_id}'")
            return True

    def _is_resource_subpattern(self, child_pattern: str, parent_pattern: str) -> bool:
        """
        Ensures child resource pattern is a strict subset or match of parent resource pattern.
        e.g.:
          Parent: /workspace/*
          Child:  /workspace/research/* -> True
          Parent: /workspace/research/*
          Child:  /workspace/research/sources/* -> True
          Child:  /workspace/other/* -> False
          Child:  /etc/shadow -> False
        """
        p_clean = parent_pattern.rstrip("*").rstrip("/")
        c_clean = child_pattern.rstrip("*").rstrip("/")

        if parent_pattern == child_pattern or parent_pattern == "*":
            return True

        if c_clean.startswith(p_clean):
            return True

        return False

    def _deny(
        self,
        reason: str,
        request: DelegationRequest,
        parent_scope_id: Optional[str] = None,
    ) -> DelegationResult:
        result = DelegationResult(
            verdict=DelegationVerdict.DENIED,
            reason=reason,
            parent_scope_id=parent_scope_id,
        )
        self._record_audit(result, request=request, parent_scope_id=parent_scope_id)
        logger.warning(f"Delegation denied: {reason}")
        return result

    def _record_audit(
        self,
        result: DelegationResult,
        request: DelegationRequest,
        parent_scope_id: Optional[str],
    ) -> None:
        try:
            event = AuditEvent(
                event_id=result.audit_id,
                session_id=request.metadata.get("session_id", "system"),
                task_id=request.task_id,
                from_status="DELEGATION_REQUEST",
                to_status=result.verdict.value,
                reason=result.reason,
                actor="delegation-engine",
                details={
                    "target_agent": request.target_agent_id,
                    "requested_capability": request.requested_capability,
                    "requested_action": request.requested_action,
                    "requested_resource": request.requested_resource,
                    "parent_scope_id": parent_scope_id,
                    "child_scope_id": result.child_scope.scope_id if result.child_scope else None,
                    "delegation_chain": result.delegation_chain,
                },
            )
            self.store.record_audit_event(event)
        except Exception as e:
            logger.warning(f"Could not record delegation audit event: {e}")
