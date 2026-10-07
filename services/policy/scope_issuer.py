"""
services/policy/scope_issuer.py — Short-Lived Scope Token Issuer
"""
from __future__ import annotations
import logging
import os
import threading
import time
from typing import Any, Dict, Optional, Set
import uuid
import jwt

from domain.policy.models import (
    AuthorizationRequest,
    EvaluationVerdict,
    PolicyEvaluationResult,
    ScopeToken,
)
from services.policy.engine import PolicyEngine

logger = logging.getLogger("agent-lab.services.policy.scope_issuer")


class ScopeIssuerError(Exception):
    pass


class ScopeIssuer:
    """
    Issues cryptographically signed, short-lived Scope Tokens based on
    PolicyEngine evaluations. Tracks invocation quotas and active expirations.
    """

    def __init__(
        self,
        policy_engine: Optional[PolicyEngine] = None,
        issuer: str = "https://scope.agent-lab.internal",
        secret_key: Optional[str] = None,
    ):
        self.engine = policy_engine or PolicyEngine()
        self.issuer = issuer
        self.secret_key = secret_key or os.environ.get("AGENT_LAB_SCOPE_SECRET", "agent-lab-dev-scope-secret-2026")
        self._active_scopes: Dict[str, ScopeToken] = {}
        self._revoked_scopes: Set[str] = set()
        self._lock = threading.Lock()

    def issue_scope(
        self,
        request: Optional[AuthorizationRequest] = None,
        evaluation: Optional[PolicyEvaluationResult] = None,
        identity_token: Optional[str] = None,
        ttl_seconds: Optional[int] = None,
        max_invocations: Optional[int] = None,
    ) -> ScopeToken:
        """
        Evaluates contextual intersection and mints a short-lived Scope Token if allowed.
        Accepts either an AuthorizationRequest or a pre-evaluated PolicyEvaluationResult.
        """
        if evaluation is None:
            if request is None:
                raise ScopeIssuerError("Either 'request' or 'evaluation' must be provided")
            evaluation = self.engine.evaluate(request)

        if evaluation.verdict != EvaluationVerdict.ALLOWED:
            raise ScopeIssuerError(f"Scope issuance denied: {evaluation.reason}")

        scope_data = evaluation.effective_scope or {}
        now = int(time.time())
        ttl = ttl_seconds if ttl_seconds is not None else scope_data.get("ttl_seconds", 900)
        exp = now + ttl
        scope_id = f"scp-{uuid.uuid4().hex[:10]}"
        invocations = max_invocations if max_invocations is not None else scope_data.get("max_invocations", 10)


        claims: Dict[str, Any] = {
            "iss": self.issuer,
            "sub": scope_data.get("subject"),
            "aud": "agent-gateway",
            "scope_id": scope_id,
            "task_id": scope_data.get("task_id"),
            "workspace_id": scope_data.get("workspace_id"),
            "capability": scope_data.get("capability"),
            "granted_action": scope_data.get("granted_action"),
            "resource_path": scope_data.get("resource_path"),
            "max_invocations": invocations,
            "delegation_depth": scope_data.get("delegation_depth", 0),
            "policy_rule": scope_data.get("policy_rule"),
            "iat": now,
            "exp": exp,
        }

        raw_token = jwt.encode(claims, self.secret_key, algorithm="HS256")

        scope_token = ScopeToken(
            scope_id=scope_id,
            subject=scope_data.get("subject", ""),
            task_id=scope_data.get("task_id", ""),
            workspace_id=scope_data.get("workspace_id", ""),
            capability=scope_data.get("capability", ""),
            allowed_actions=[scope_data.get("granted_action", "")],
            resource_pattern=scope_data.get("resource_path", ""),
            max_invocations=invocations,
            invocations_remaining=invocations,
            issued_at=now,
            expires_at=exp,

            delegation_depth=scope_data.get("delegation_depth", 0),
            raw_token=raw_token,
            claims=claims,
        )

        with self._lock:
            self._active_scopes[scope_id] = scope_token

        logger.info(f"Issued Scope Token '{scope_id}' for '{scope_token.subject}' [cap={scope_token.capability}, ttl={ttl}s]")
        return scope_token

    def validate_and_consume_scope(
        self,
        raw_scope_token: str,
        expected_action: str,
        expected_resource: str,
    ) -> ScopeToken:
        """
        Validates token signature, expiration, quotas, and decrements remaining invocations.
        """
        try:
            claims = jwt.decode(
                raw_scope_token,
                self.secret_key,
                algorithms=["HS256"],
                issuer=self.issuer,
                audience="agent-gateway",
            )
        except jwt.ExpiredSignatureError:
            raise ScopeIssuerError("Scope token has expired")
        except Exception as e:
            raise ScopeIssuerError(f"Scope token cryptographic failure: {e}")

        scope_id = claims.get("scope_id")
        if not scope_id:
            raise ScopeIssuerError("Malformed scope token: missing scope_id")

        with self._lock:
            if scope_id in self._revoked_scopes:
                raise ScopeIssuerError(f"Scope token '{scope_id}' has been explicitly revoked")

            scope_token = self._active_scopes.get(scope_id)
            if not scope_token:
                # Reconstruct from claims if server restarted
                scope_token = ScopeToken(
                    scope_id=scope_id,
                    subject=claims.get("sub", ""),
                    task_id=claims.get("task_id", ""),
                    workspace_id=claims.get("workspace_id", ""),
                    capability=claims.get("capability", ""),
                    allowed_actions=[claims.get("granted_action", "")],
                    resource_pattern=claims.get("resource_path", ""),
                    max_invocations=claims.get("max_invocations", 10),
                    invocations_remaining=claims.get("max_invocations", 10),
                    issued_at=claims.get("iat", 0),
                    expires_at=claims.get("exp", 0),
                    delegation_depth=claims.get("delegation_depth", 0),
                    raw_token=raw_scope_token,
                    claims=claims,
                )
                self._active_scopes[scope_id] = scope_token

            if scope_token.invocations_remaining <= 0:
                raise ScopeIssuerError(f"Scope quota exhausted: {scope_token.max_invocations} calls consumed")

            # Check action and resource bounds
            granted_action = claims.get("granted_action")
            if granted_action != "*" and granted_action != expected_action:
                raise ScopeIssuerError(f"Action '{expected_action}' not granted by scope token (granted: '{granted_action}')")

            # Consume 1 invocation
            scope_token.invocations_remaining -= 1
            return scope_token

    def revoke_scope(self, scope_id: str) -> bool:
        with self._lock:
            self._revoked_scopes.add(scope_id)
            if scope_id in self._active_scopes:
                del self._active_scopes[scope_id]
            logger.info(f"Revoked scope token '{scope_id}'")
            return True
