"""
services/identity/external_oidc_adapter.py — Production-Grade External OIDC Provider Adapter
Implements IdentityProviderInterface for external identity providers (Auth0, ZITADEL, Ory).

Key Architectural Roles:
1. Decouples logical agent identity from compute workers.
2. Mints RFC 7519 / RFC 9068 compliant OIDC JWT access tokens with dynamic scopes.
3. Carries contextual bindings (task_id, workspace_id, spiffe_workload_id) without bloating the token with policy ASTs.
4. Preserves underlying AX/Substrate SPIFFE workload identity.
"""
from __future__ import annotations
import logging
import os
import threading
import time
from typing import Any, Dict, List, Optional, Set
import uuid
import jwt

from domain.agents.models import Agent
from domain.identity.models import (
    IdentityProviderInterface,
    WorkloadIdentityToken,
    TokenValidationResult,
)

logger = logging.getLogger("agent-lab.services.identity.external_oidc")


class ExternalOIDCProviderAdapter(IdentityProviderInterface):
    """
    Adapter integrating Agent Lab with external OIDC providers (Auth0, ZITADEL, Ory).
    Mints task-scoped, dynamic-authority JWTs while bridging to AX SPIFFE workload identity.
    """

    def __init__(
        self,
        provider_name: str = "Auth0",
        issuer: str = "https://auth0.agent-lab.internal/",
        audience: str = "agent-gateway",
        signing_key: Optional[str] = None,
        algorithm: str = "HS256",
        jwks_uri: Optional[str] = None,
    ):
        self.provider_name = provider_name
        self.issuer = issuer.rstrip("/") + "/"
        self.audience = audience
        self.signing_key = signing_key or os.environ.get("EXTERNAL_OIDC_SECRET", "auth0-agent-lab-enterprise-secret-2026")
        self.algorithm = algorithm
        self.jwks_uri = jwks_uri or f"{self.issuer}.well-known/jwks.json"
        self._revocation_store: Set[str] = set()
        self._lock = threading.Lock()

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
        """
        Dynamically provisions an OIDC identity token for an autonomous agent.
        The token carries signed logical identity and dynamic authorization scope,
        along with task/workspace and SPIFFE workload context.
        """
        now = int(time.time())
        exp = now + ttl_seconds
        jti = f"oidc-{uuid.uuid4().hex[:12]}"

        subject = agent.identity_subject or f"agent:{agent.agent_id}"

        # Dynamic scope formatting (space-delimited OAuth2/OIDC standard)
        if scope is not None:
            effective_scope = scope
        else:
            # Fallback to agent declared capabilities
            effective_scope = " ".join(f"{c}:*" for c in agent.capabilities)

        claims: Dict[str, Any] = {
            "iss": self.issuer,
            "sub": subject,
            "aud": self.audience,
            "iat": now,
            "nbf": now,
            "exp": exp,
            "jti": jti,
            # Standard OAuth 2.0 Dynamic Scope
            "scope": effective_scope,
            # Contextual Task & Workspace Bindings
            "task_id": task_id,
            "workspace_id": workspace_id,
            # Logical Agent Metadata
            "agent_role": agent.role,
            "tenant": agent.tenant,
            "environment": agent.environment,
            "provider": self.provider_name,
        }

        # Underlying Substrate / AX SPIFFE Workload Binding
        if spiffe_id:
            claims["spiffe_workload_id"] = spiffe_id
        else:
            claims["spiffe_workload_id"] = f"spiffe://cluster.local/ns/default/sa/worker-actor-{task_id}"

        # Sign token using configured algorithm
        token_str = jwt.encode(claims, self.signing_key, algorithm=self.algorithm)

        logger.info(
            f"[{self.provider_name}] Issued dynamic OIDC token for '{subject}' "
            f"(scope='{effective_scope}', task='{task_id}', spiffe='{claims['spiffe_workload_id']}')"
        )

        return WorkloadIdentityToken(
            raw_token=token_str,
            subject=subject,
            issuer=self.issuer,
            audience=self.audience,
            task_id=task_id,
            workspace_id=workspace_id,
            role=agent.role,
            tenant=agent.tenant,
            environment=agent.environment,
            capabilities=list(agent.capabilities),
            issued_at=now,
            expires_at=exp,
            jti=jti,
            claims=claims,
            scope=effective_scope,
            spiffe_id=claims.get("spiffe_workload_id"),
        )

    def validate_identity(
        self,
        token: str,
        expected_task_id: Optional[str] = None,
        expected_workspace_id: Optional[str] = None,
    ) -> TokenValidationResult:
        """
        Validates token signature, expiration, issuer, audience, and context bindings.
        """
        try:
            claims = jwt.decode(
                token,
                self.signing_key,
                algorithms=[self.algorithm],
                issuer=self.issuer,
                audience=self.audience,
                options={"verify_exp": True, "verify_iss": True, "verify_aud": True},
            )
        except jwt.ExpiredSignatureError:
            return TokenValidationResult(valid=False, error="Token expired")
        except jwt.InvalidIssuerError:
            return TokenValidationResult(valid=False, error=f"Invalid issuer: expected '{self.issuer}'")
        except jwt.InvalidAudienceError:
            return TokenValidationResult(valid=False, error=f"Invalid audience: expected '{self.audience}'")
        except Exception as e:
            return TokenValidationResult(valid=False, error=f"Cryptographic verification failed: {e}")

        jti = claims.get("jti", "")
        if self.is_revoked(jti):
            return TokenValidationResult(valid=False, error="Token has been revoked by IdP")

        # Validate task binding if expected
        if expected_task_id and claims.get("task_id") != expected_task_id:
            return TokenValidationResult(
                valid=False,
                error=f"Task binding mismatch: token bound to '{claims.get('task_id')}', expected '{expected_task_id}'",
            )

        # Validate workspace binding if expected
        if expected_workspace_id and claims.get("workspace_id") != expected_workspace_id:
            return TokenValidationResult(
                valid=False,
                error=f"Workspace binding mismatch: token bound to '{claims.get('workspace_id')}', expected '{expected_workspace_id}'",
            )

        return TokenValidationResult(
            valid=True,
            subject=claims.get("sub"),
            claims=claims,
        )

    def revoke_identity(self, jti: str, reason: str = "") -> bool:
        """Revokes a specific token by jti."""
        with self._lock:
            self._revocation_store.add(jti)
        logger.warning(f"[{self.provider_name}] Token '{jti}' revoked. Reason: {reason or 'unspecified'}")
        return True

    def is_revoked(self, jti: str) -> bool:
        with self._lock:
            return jti in self._revocation_store

    def get_subject(self, token: str) -> Optional[str]:
        try:
            unverified = jwt.decode(token, options={"verify_signature": False, "verify_exp": False})
            return unverified.get("sub")
        except Exception:
            return None

    @staticmethod
    def is_action_in_scope(action: str, scope_str: str) -> bool:
        """
        Determines whether a requested action (e.g. 'document:read') is permitted
        by a space-delimited OAuth2 scope string (e.g. 'document:read web:search').
        Supports wildcard matching (e.g. 'document:*' permits 'document:read').
        """
        if not scope_str:
            return False
        granted_scopes = scope_str.strip().split()
        if "*" in granted_scopes or "admin:*" in granted_scopes:
            return True

        if action in granted_scopes:
            return True

        # Check prefix matching, e.g. 'document:*' matches 'document:read' or 'read' matches 'read'
        if ":" in action:
            domain, act = action.split(":", 1)
            if f"{domain}:*" in granted_scopes:
                return True

        return False
