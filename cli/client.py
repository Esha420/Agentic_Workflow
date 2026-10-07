"""
cli/client.py — Agent Lab HTTP API Client

Provides typed client operations for CLI and external scripts to interact
with the unified Agent Lab Control Plane REST API.
"""
from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

logger = logging.getLogger("agent-lab.client")


class APIClientError(Exception):
    """Raised when an API request fails."""
    def __init__(self, message: str, status_code: Optional[int] = None, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.status_code = status_code
        self.details = details or {}


class AgentLabClient:
    """
    HTTP Client communicating with the Agent Lab API Server.
    """

    def __init__(self, base_url: Optional[str] = None):
        self.base_url = (base_url or os.getenv("AGENT_LAB_API_URL", "http://127.0.0.1:8000")).rstrip("/")

    def _request(
        self,
        method: str,
        path: str,
        body: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        timeout: float = 30.0,
    ) -> Any:
        url = f"{self.base_url}{path}"
        if params:
            query_string = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
            if query_string:
                url = f"{url}?{query_string}"

        req_headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "agent-lab-cli/1.0",
        }
        if headers:
            req_headers.update(headers)

        data_bytes = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(url, data=data_bytes, headers=req_headers, method=method)

        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                status_code = response.getcode()
                raw_data = response.read().decode("utf-8")
                if not raw_data:
                    return None
                return json.loads(raw_data)
        except urllib.error.HTTPError as e:
            raw_err = e.read().decode("utf-8")
            err_msg = f"HTTP {e.code}: {e.reason}"
            err_details = {}
            try:
                parsed = json.loads(raw_err)
                if isinstance(parsed, dict):
                    err_msg = parsed.get("error", err_msg)
                    err_details = parsed
            except Exception:
                pass
            raise APIClientError(err_msg, status_code=e.code, details=err_details) from e
        except urllib.error.URLError as e:
            raise APIClientError(f"Failed to connect to Agent Lab API at '{self.base_url}': {e.reason}") from e
        except Exception as e:
            raise APIClientError(f"Unexpected client request error: {e}") from e

    def healthz(self) -> Dict[str, Any]:
        return self._request("GET", "/api/v1/healthz")

    def create_session(
        self,
        objective: str,
        session_id: Optional[str] = None,
        target: str = "Autonomous Actor Checkpointing & State Persistence",
        atespace: str = "default",
        role: str = "research",
        idempotency_key: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        headers = {"Idempotency-Key": idempotency_key} if idempotency_key else None
        payload = {
            "objective": objective,
            "id": session_id,
            "target": target,
            "atespace": atespace,
            "role": role,
            "metadata": metadata or {},
        }
        return self._request("POST", "/api/v1/research-sessions", body=payload, headers=headers)

    def list_sessions(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        params = {"status": status} if status else None
        res = self._request("GET", "/api/v1/research-sessions", params=params)
        return res if isinstance(res, list) else []

    def get_session(self, session_id: str) -> Dict[str, Any]:
        return self._request("GET", f"/api/v1/research-sessions/{session_id}")

    def suspend_session(
        self,
        session_id: str,
        reason: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        headers = {"Idempotency-Key": idempotency_key} if idempotency_key else None
        payload = {"reason": reason or "Operator manual suspend via CLI"}
        return self._request("POST", f"/api/v1/research-sessions/{session_id}/suspend", body=payload, headers=headers)

    def resume_session(
        self,
        session_id: str,
        idempotency_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        headers = {"Idempotency-Key": idempotency_key} if idempotency_key else None
        payload = {"reason": "Operator manual resume via CLI"}
        return self._request("POST", f"/api/v1/research-sessions/{session_id}/resume", body=payload, headers=headers)

    def create_checkpoint(self, session_id: str, reason: Optional[str] = None) -> Dict[str, Any]:
        payload = {"reason": reason or "Explicit operator checkpoint request"}
        return self._request("POST", f"/api/v1/research-sessions/{session_id}/checkpoints", body=payload)

    def list_checkpoints(self, session_id: str) -> List[Dict[str, Any]]:
        res = self._request("GET", f"/api/v1/research-sessions/{session_id}/checkpoints")
        return res if isinstance(res, list) else []

    def get_timeline(self, session_id: str) -> Dict[str, Any]:
        return self._request("GET", f"/api/v1/research-sessions/{session_id}/timeline")

    def get_workspace(self, session_id: str) -> Dict[str, Any]:
        return self._request("GET", f"/api/v1/research-sessions/{session_id}/workspace")

    def read_artifact(self, session_id: str, relative_path: str = "report.md") -> Dict[str, Any]:
        return self._request("GET", f"/api/v1/research-sessions/{session_id}/artifacts/{relative_path}")

    def delete_session(self, session_id: str) -> Dict[str, Any]:
        return self._request("DELETE", f"/api/v1/research-sessions/{session_id}")

    def evaluate_scope(
        self,
        caller_role: str,
        requested_capability: str,
        target_agent: str,
        task_id: str,
        workspace_id: str,
        environment: str = "staging",
    ) -> Dict[str, Any]:
        payload = {
            "caller_role": caller_role,
            "requested_capability": requested_capability,
            "target_agent": target_agent,
            "task_id": task_id,
            "workspace_id": workspace_id,
            "environment": environment,
        }
        return self._request("POST", "/api/v1/scope/evaluate", body=payload)

    def list_agents(
        self,
        role: Optional[str] = None,
        tenant: Optional[str] = None,
        status: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        params = {"role": role, "tenant": tenant, "status": status}
        res = self._request("GET", "/api/v1/agents", params=params)
        return res if isinstance(res, list) else []

    def get_agent(self, agent_id: str) -> Dict[str, Any]:
        return self._request("GET", f"/api/v1/agents/{agent_id}")

    def register_agent(
        self,
        agent_id: str,
        role: str,
        tenant: str = "default",
        environment: str = "staging",
        capabilities: Optional[List[str]] = None,
        identity_subject: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        payload = {
            "agent_id": agent_id,
            "role": role,
            "tenant": tenant,
            "environment": environment,
            "capabilities": capabilities or [],
            "identity_subject": identity_subject,
            "metadata": metadata or {},
        }
        return self._request("POST", "/api/v1/agents", body=payload)

    def get_agent_identity(self, agent_id: str) -> Dict[str, Any]:
        return self._request("GET", f"/api/v1/agents/{agent_id}/identity")

    def provision_agent_identity(
        self,
        agent_id: str,
        task_id: str,
        workspace_id: str,
        session_id: Optional[str] = None,
        ttl_seconds: int = 3600,
    ) -> Dict[str, Any]:
        payload = {
            "task_id": task_id,
            "workspace_id": workspace_id,
            "session_id": session_id,
            "ttl_seconds": ttl_seconds,
        }
        return self._request("POST", f"/api/v1/agents/{agent_id}/identity/provision", body=payload)

    def revoke_agent_identity(self, agent_id: str, reason: str = "Operator revocation") -> Dict[str, Any]:
        payload = {"reason": reason}
        return self._request("POST", f"/api/v1/agents/{agent_id}/revoke-identity", body=payload)

    def validate_identity_token(
        self,
        token: str,
        expected_task_id: Optional[str] = None,
        expected_workspace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        payload = {
            "token": token,
            "expected_task_id": expected_task_id,
            "expected_workspace_id": expected_workspace_id,
        }
        return self._request("POST", "/api/v1/identity/validate", body=payload)

    # --------------------------------------------------------------------------
    # Trust & Scope Plane (M4)
    # --------------------------------------------------------------------------

    def list_capabilities(self) -> List[Dict[str, Any]]:
        res = self._request("GET", "/api/v1/capabilities")
        return res if isinstance(res, list) else []

    def get_capability(self, name: str) -> Dict[str, Any]:
        return self._request("GET", f"/api/v1/capabilities/{name}")

    def evaluate_policy(
        self,
        identity_token: str,
        requested_capability: str,
        task_id: str,
        workspace_id: str,
        requested_action: str = "*",
        target_resource: str = "/workspace/*",
        target_agent: Optional[str] = None,
        delegation_depth: int = 0,
        environment: str = "staging",
    ) -> Dict[str, Any]:
        payload = {
            "identity_token": identity_token,
            "requested_capability": requested_capability,
            "requested_action": requested_action,
            "target_resource": target_resource,
            "task_id": task_id,
            "workspace_id": workspace_id,
            "target_agent": target_agent,
            "delegation_depth": delegation_depth,
            "environment": environment,
        }
        return self._request("POST", "/api/v1/policy/evaluate", body=payload)

    def issue_scope(
        self,
        identity_token: str,
        requested_capability: str,
        task_id: str,
        workspace_id: str,
        requested_action: str = "*",
        target_resource: str = "/workspace/*",
        max_invocations: int = 10,
        ttl_seconds: Optional[int] = None,
    ) -> Dict[str, Any]:
        payload = {
            "identity_token": identity_token,
            "requested_capability": requested_capability,
            "requested_action": requested_action,
            "target_resource": target_resource,
            "task_id": task_id,
            "workspace_id": workspace_id,
            "max_invocations": max_invocations,
            "ttl_seconds": ttl_seconds,
        }
        return self._request("POST", "/api/v1/policy/issue-scope", body=payload)

    def gateway_authorize(
        self,
        identity_token: str,
        scope_token: str,
        action: str,
        resource: str,
        task_id: str,
        workspace_id: str,
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        payload = {
            "identity_token": identity_token,
            "scope_token": scope_token,
            "action": action,
            "resource": resource,
            "task_id": task_id,
            "workspace_id": workspace_id,
            "session_id": session_id,
        }
        return self._request("POST", "/api/v1/gateway/authorize", body=payload)

    def get_gateway_audit(
        self,
        session_id: Optional[str] = None,
        task_id: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        params = {"session_id": session_id, "task_id": task_id, "limit": limit}
        res = self._request("GET", "/api/v1/gateway/audit", params=params)
        return res if isinstance(res, list) else []

    # --------------------------------------------------------------------------
    # Multi-Agent Communication & Delegation (M5)
    # --------------------------------------------------------------------------

    def discover_peers(
        self,
        capability: str,
        tenant: str = "default",
        environment: str = "staging",
        exclude_agent_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        payload = {
            "capability": capability,
            "tenant": tenant,
            "environment": environment,
            "exclude_agent_id": exclude_agent_id,
        }
        res = self._request("POST", "/api/v1/agents/discover", body=payload)
        return res if isinstance(res, list) else []

    def delegate_capability(
        self,
        caller_identity_token: str,
        parent_scope_token: str,
        target_agent_id: str,
        task_id: str,
        workspace_id: str,
        requested_capability: str,
        requested_action: str = "*",
        requested_resource: str = "/workspace/*",
        requested_ttl_seconds: Optional[int] = None,
        requested_max_invocations: Optional[int] = None,
        requested_delegation_depth: int = 0,
        environment: str = "staging",
    ) -> Dict[str, Any]:
        payload = {
            "caller_identity_token": caller_identity_token,
            "parent_scope_token": parent_scope_token,
            "target_agent_id": target_agent_id,
            "task_id": task_id,
            "workspace_id": workspace_id,
            "requested_capability": requested_capability,
            "requested_action": requested_action,
            "requested_resource": requested_resource,
            "requested_ttl_seconds": requested_ttl_seconds,
            "requested_max_invocations": requested_max_invocations,
            "requested_delegation_depth": requested_delegation_depth,
            "environment": environment,
        }
        return self._request("POST", "/api/v1/delegation/delegate", body=payload)

    def get_delegation_chain(self, scope_id: str) -> Dict[str, Any]:
        return self._request("GET", f"/api/v1/delegation/chain/{scope_id}")

    def create_branch(
        self,
        checkpoint_id: str,
        caller_identity_token: str,
        source_scope_token: str,
        hypothesis: str,
        branch_name: Optional[str] = None,
        target_agent_id: Optional[str] = None,
        requested_capabilities: Optional[List[str]] = None,
        requested_actions: Optional[List[str]] = None,
        requested_resources: Optional[List[str]] = None,
        requested_ttl: int = 3600,
        max_invocations: int = 10,
    ) -> Dict[str, Any]:
        payload = {
            "caller_identity_token": caller_identity_token,
            "source_scope_token": source_scope_token,
            "hypothesis": hypothesis,
            "branch_name": branch_name,
            "target_agent_id": target_agent_id,
            "requested_capabilities": requested_capabilities,
            "requested_actions": requested_actions,
            "requested_resources": requested_resources,
            "requested_ttl": requested_ttl,
            "max_invocations": max_invocations,
        }
        return self._request("POST", f"/api/v1/checkpoints/{checkpoint_id}/branch", body=payload)

    def list_branches(self, session_id: str) -> List[Dict[str, Any]]:
        res = self._request("GET", f"/api/v1/sessions/{session_id}/branches")
        return res if isinstance(res, list) else []

    def get_branch(self, branch_id: str) -> Dict[str, Any]:
        return self._request("GET", f"/api/v1/branches/{branch_id}")

    def get_lineage(self, session_id: str) -> Dict[str, Any]:
        return self._request("GET", f"/api/v1/sessions/{session_id}/lineage")

    def run_speculative(
        self,
        session_id: str,
        checkpoint_id: str,
        caller_identity_token: str,
        source_scope_token: str,
        branches: List[Dict[str, Any]],
        scoring_config: Optional[Dict[str, Any]] = None,
        auto_promote: bool = True,
    ) -> Dict[str, Any]:
        payload = {
            "checkpoint_id": checkpoint_id,
            "caller_identity_token": caller_identity_token,
            "source_scope_token": source_scope_token,
            "branches": branches,
            "scoring_config": scoring_config,
            "auto_promote": auto_promote,
        }
        return self._request("POST", f"/api/v1/sessions/{session_id}/speculative/run", body=payload)

    def promote_branch(
        self,
        session_id: str,
        winning_branch_id: str,
        winning_checkpoint_id: str,
        evaluation_id: Optional[str] = None,
        operator: str = "cli-operator",
    ) -> Dict[str, Any]:
        payload = {
            "winning_branch_id": winning_branch_id,
            "winning_checkpoint_id": winning_checkpoint_id,
            "evaluation_id": evaluation_id,
            "operator": operator,
        }
        return self._request("POST", f"/api/v1/sessions/{session_id}/speculative/promote", body=payload)

    def get_session_head(self, session_id: str) -> Dict[str, Any]:
        return self._request("GET", f"/api/v1/sessions/{session_id}/speculative/head")

    def list_evaluations(self, session_id: str) -> List[Dict[str, Any]]:
        res = self._request("GET", f"/api/v1/sessions/{session_id}/speculative/evaluations")
        return res if isinstance(res, list) else []




