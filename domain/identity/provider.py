"""
domain/identity/provider.py — Concrete OIDC-compatible Workload Identity Provider
"""
from __future__ import annotations
from datetime import datetime, timezone
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


class OIDCWorkloadIdentityProvider(IdentityProviderInterface):
    """
    Standard OIDC-compatible workload identity provider using signed JWTs.
    Signs tokens with HS256 by default (with configurable secret or RSA key pair).
    """

    def __init__(
        self,
        issuer: str = "https://identity.agent-lab.internal",
        audience: str = "agent-gateway",
        secret_key: Optional[str] = None,
    ):
        self.issuer = issuer
        self.audience = audience
        self.secret_key = secret_key or os.environ.get("AGENT_LAB_IDENTITY_SECRET", "agent-lab-dev-identity-secret-2026")
        self._revoked_jtis: Set[str] = set()
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
        now = int(time.time())
        exp = now + ttl_seconds
        jti = f"tok-{uuid.uuid4().hex[:12]}"

        subject = agent.identity_subject or f"agent:{agent.agent_id}"
        effective_scope = scope if scope is not None else " ".join(f"{c}:*" for c in agent.capabilities)

        claims: Dict[str, Any] = {
            "iss": self.issuer,
            "sub": subject,
            "aud": self.audience,
            "iat": now,
            "nbf": now,
            "exp": exp,
            "jti": jti,
            # Contextual Task & Workspace Bindings
            "task_id": task_id,
            "workspace_id": workspace_id,
            # Logical Agent Metadata
            "role": agent.role,
            "agent_role": agent.role,
            "tenant": agent.tenant,
            "environment": agent.environment,
            "capabilities": list(agent.capabilities),
        }
        if scope is not None:
            claims["scope"] = scope
        if spiffe_id:
            claims["spiffe_workload_id"] = spiffe_id

        token_str = jwt.encode(claims, self.secret_key, algorithm="HS256")

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
            scope=scope or "",
            spiffe_id=spiffe_id,
        )

    def validate_identity(
        self,
        token: str,
        expected_task_id: Optional[str] = None,
        expected_workspace_id: Optional[str] = None,
    ) -> TokenValidationResult:
        try:
            claims = jwt.decode(
                token,
                self.secret_key,
                algorithms=["HS256"],
                issuer=self.issuer,
                audience=self.audience,
                options={"require": ["exp", "iss", "sub", "aud", "task_id", "workspace_id", "jti"]},
            )
        except jwt.ExpiredSignatureError:
            return TokenValidationResult(valid=False, error="Token signature has expired")
        except jwt.InvalidIssuerError:
            return TokenValidationResult(valid=False, error="Token issuer does not match")
        except jwt.InvalidAudienceError:
            return TokenValidationResult(valid=False, error="Token audience does not match")
        except jwt.InvalidSignatureError:
            return TokenValidationResult(valid=False, error="Token signature is invalid (tampered)")
        except jwt.DecodeError as e:
            return TokenValidationResult(valid=False, error=f"Token decode failure: {e}")
        except Exception as e:
            return TokenValidationResult(valid=False, error=f"Token validation error: {e}")

        # Check revocation
        jti = claims.get("jti")
        if jti and self.is_revoked(jti):
            return TokenValidationResult(
                valid=False,
                subject=claims.get("sub"),
                claims=claims,
                error=f"Token {jti} has been explicitly revoked",
            )

        # Enforce task binding
        if expected_task_id and claims.get("task_id") != expected_task_id:
            return TokenValidationResult(
                valid=False,
                subject=claims.get("sub"),
                claims=claims,
                error=f"Task binding mismatch: expected '{expected_task_id}', token contains '{claims.get('task_id')}'",
            )

        # Enforce workspace binding
        if expected_workspace_id and claims.get("workspace_id") != expected_workspace_id:
            return TokenValidationResult(
                valid=False,
                subject=claims.get("sub"),
                claims=claims,
                error=f"Workspace binding mismatch: expected '{expected_workspace_id}', token contains '{claims.get('workspace_id')}'",
            )

        return TokenValidationResult(
            valid=True,
            subject=claims.get("sub"),
            claims=claims,
        )

    def revoke_identity(self, jti: str, reason: str = "") -> bool:
        with self._lock:
            self._revoked_jtis.add(jti)
            return True

    def is_revoked(self, jti: str) -> bool:
        with self._lock:
            return jti in self._revoked_jtis

    def get_subject(self, token: str) -> Optional[str]:
        try:
            unverified = jwt.decode(token, options={"verify_signature": False})
            return unverified.get("sub")
        except Exception:
            return None
