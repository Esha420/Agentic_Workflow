"""
api/server.py — Agent Lab REST API Server

Unified Control Plane API conforming to OpenAPI 3.0 specification.
Serves REST endpoints for Research Sessions, Tasks, Checkpoints, Timeline,
Workspace Artifacts, and the interactive Web UI.
"""
from __future__ import annotations

import http.server
import json
import logging
import mimetypes
import os
import re
import sys
import threading
import time
import urllib.parse
from typing import Any, Dict, List, Optional, Tuple

# Ensure project root is in sys.path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from domain.sessions.models import SessionStatus, ResearchSession
from domain.checkpoints.models import Checkpoint
from domain.agents.models import AgentLifecycleState
from domain.policy.models import AuthorizationRequest, EvaluationVerdict
from domain.delegation.models import DelegationRequest, DelegationVerdict
from domain.checkpoints.branching import ExecutionBranch, BranchRequest, BranchStatus
from services.agents.registry import AgentRegistryError
from services.identity.manager import IdentityManagerError
from services.policy.scope_issuer import ScopeIssuerError
from services.checkpoints.branching import BranchingError, BranchEscalationDenied
from domain.speculative.models import ScoringConfig
from services.speculative.promoter import PromotionError
from services.orchestrator.orchestrator import ResearchSessionService, OrchestratorError


logger = logging.getLogger("agent-lab.api")


class AgentLabRequestHandler(http.server.BaseHTTPRequestHandler):
    """
    HTTP Request Handler routing requests to ResearchSessionService and static UI files.
    """

    service: ResearchSessionService = None
    ui_dir: str = os.path.join(BASE_DIR, "ui")

    def log_message(self, format: str, *args: Any) -> None:
        logger.info("%s - - [%s] %s", self.client_address[0], self.log_date_time_string(), format % args)

    # --------------------------------------------------------------------------
    # CORS & Response Helpers
    # --------------------------------------------------------------------------

    def _set_headers(self, status_code: int = 200, content_type: str = "application/json") -> None:
        self.send_response(status_code)
        self.send_header("Content-Type", content_type)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS, HEAD")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Idempotency-Key, Authorization, X-Correlation-ID")
        self.end_headers()

    def do_OPTIONS(self) -> None:
        self._set_headers(204)

    def do_HEAD(self) -> None:
        self._set_headers(200, "text/html")

    def _send_json(self, status_code: int, data: Any) -> None:
        self._set_headers(status_code, "application/json")
        body = json.dumps(data, indent=2).encode("utf-8")
        self.wfile.write(body)

    def _send_error(self, status_code: int, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        payload = {"error": message, "status_code": status_code}
        if details:
            payload["details"] = details
        self._send_json(status_code, payload)

    def _read_body_json(self) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            if content_length == 0:
                return {}, None
            raw_body = self.rfile.read(content_length).decode("utf-8")
            return json.loads(raw_body), None
        except Exception as e:
            return None, str(e)

    # --------------------------------------------------------------------------
    # Request Dispatcher (GET, POST, DELETE)
    # --------------------------------------------------------------------------

    def do_GET(self) -> None:
        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path.rstrip("/")
        query = urllib.parse.parse_qs(parsed_url.query)

        # 1. Healthz endpoint
        if path in ("/healthz", "/api/v1/healthz", "/v1/healthz"):
            self._send_json(200, {"status": "HEALTHY", "timestamp": time.time(), "version": "1.0.0"})
            return

        # 2. Static UI routes
        if path == "" or path == "/" or path == "/ui":
            self._serve_static_file("index.html")
            return
        elif path.startswith("/ui/") or path.startswith("/css/") or path.startswith("/js/"):
            relative_path = path.lstrip("/ui/").lstrip("/")
            self._serve_static_file(relative_path)
            return

        # 3. List Research Sessions: GET /api/v1/research-sessions or /v1/research/sessions
        if path in ("/api/v1/research-sessions", "/v1/research/sessions"):
            status_param = query.get("status", [None])[0]
            status_filter = None
            if status_param:
                try:
                    status_filter = SessionStatus(status_param)
                except ValueError:
                    self._send_error(400, f"Invalid status filter: {status_param}")
                    return

            sessions = self.service.list_sessions(status=status_filter)
            self._send_json(200, [s.to_dict() for s in sessions])
            return

        # 4. Session details: GET /api/v1/research-sessions/{id}
        m_session = re.match(r"^/(?:api/v1/research-sessions|v1/research/sessions)/([a-zA-Z0-9_-]+)$", path)
        if m_session:
            session_id = m_session.group(1)
            session = self.service.get_session(session_id, sync=True)
            if not session:
                self._send_error(404, f"Research session '{session_id}' not found")
                return
            self._send_json(200, session.to_dict())
            return

        # 5. Checkpoints: GET /api/v1/research-sessions/{id}/checkpoints
        m_checkpoints = re.match(r"^/(?:api/v1/research-sessions|v1/research/sessions)/([a-zA-Z0-9_-]+)/checkpoints$", path)
        if m_checkpoints:
            session_id = m_checkpoints.group(1)
            session = self.service.get_session(session_id, sync=False)
            if not session:
                self._send_error(404, f"Research session '{session_id}' not found")
                return
            checkpoints = self.service.store.list_checkpoints(session_id)
            self._send_json(200, [cp.to_dict() for cp in checkpoints])
            return

        # 6. Timeline: GET /api/v1/research-sessions/{id}/timeline
        m_timeline = re.match(r"^/(?:api/v1/research-sessions|v1/research/sessions)/([a-zA-Z0-9_-]+)/timeline$", path)
        if m_timeline:
            session_id = m_timeline.group(1)
            session = self.service.get_session(session_id, sync=True)
            if not session:
                self._send_error(404, f"Research session '{session_id}' not found")
                return
            timeline = [evt.to_dict() for evt in session.audit_trail]
            self._send_json(200, {"session_id": session_id, "timeline": timeline})
            return

        # 7. Workspace explorer: GET /api/v1/research-sessions/{id}/workspace
        m_workspace = re.match(r"^/(?:api/v1/research-sessions|v1/research/sessions)/([a-zA-Z0-9_-]+)/workspace$", path)
        if m_workspace:
            session_id = m_workspace.group(1)
            session = self.service.get_session(session_id, sync=False)
            if not session:
                self._send_error(404, f"Research session '{session_id}' not found")
                return
            artifacts = self.service.list_session_artifacts(session_id)
            self._send_json(200, {
                "session_id": session_id,
                "workspace_id": session.workspace_id,
                "root_path": "/workspace",
                "artifacts": artifacts,
            })
            return

        # 8. Artifact content: GET /api/v1/research-sessions/{id}/artifacts/{file_path}
        m_art = re.match(r"^/(?:api/v1/research-sessions|v1/research/sessions)/([a-zA-Z0-9_-]+)/artifacts/(.+)$", path)
        if m_art:
            session_id = m_art.group(1)
            rel_path = m_art.group(2)
            content = self.service.read_session_artifact(session_id, relative_path=rel_path)
            if content is None:
                self._send_error(404, f"Artifact '{rel_path}' not found in session '{session_id}' workspace")
                return
            self._send_json(200, {"session_id": session_id, "path": rel_path, "content": content})
            return

        # 9. List Agents: GET /api/v1/agents
        if path in ("/api/v1/agents", "/v1/agents"):
            role_param = query.get("role", [None])[0]
            tenant_param = query.get("tenant", [None])[0]
            status_param = query.get("status", [None])[0] or query.get("lifecycle_state", [None])[0]
            state_filter = None
            if status_param:
                try:
                    state_filter = AgentLifecycleState(status_param)
                except ValueError:
                    self._send_error(400, f"Invalid agent lifecycle state: {status_param}")
                    return

            agents = self.service.registry.list_agents(
                role=role_param,
                tenant=tenant_param,
                lifecycle_state=state_filter,
            )
            self._send_json(200, [a.to_dict() for a in agents])
            return

        # 10. Agent Identity Status: GET /api/v1/agents/{id}/identity
        m_agent_id = re.match(r"^/(?:api/v1/agents|v1/agents)/([a-zA-Z0-9_-]+)/identity$", path)
        if m_agent_id:
            agent_id = m_agent_id.group(1)
            try:
                status_info = self.service.identity_mgr.get_agent_identity_status(agent_id)
                self._send_json(200, status_info)
            except IdentityManagerError as e:
                self._send_error(404, str(e))
            return

        # 11. Agent details: GET /api/v1/agents/{id}
        m_agent = re.match(r"^/(?:api/v1/agents|v1/agents)/([a-zA-Z0-9_-]+)$", path)
        if m_agent:
            agent_id = m_agent.group(1)
            agent = self.service.registry.get_agent(agent_id)
            if not agent:
                self._send_error(404, f"Agent '{agent_id}' not found in registry")
                return
            self._send_json(200, agent.to_dict())
            return

        # 12. List Capabilities: GET /api/v1/capabilities
        if path in ("/api/v1/capabilities", "/v1/capabilities"):
            caps = self.service.capability_registry.list_capabilities()
            self._send_json(200, [c.to_dict() for c in caps])
            return

        # 13. Capability Detail: GET /api/v1/capabilities/{name}
        m_cap = re.match(r"^/(?:api/v1/capabilities|v1/capabilities)/([a-zA-Z0-9_:-]+)$", path)
        if m_cap:
            cap_name = m_cap.group(1)
            cap = self.service.capability_registry.get_capability(cap_name)
            if not cap:
                self._send_error(404, f"Capability '{cap_name}' not registered")
                return
            self._send_json(200, cap.to_dict())
            return

        # 14. Gateway Audit Trail: GET /api/v1/gateway/audit
        if path in ("/api/v1/gateway/audit", "/v1/gateway/audit"):
            session_filter = query.get("session_id", [None])[0]
            task_filter = query.get("task_id", [None])[0]
            limit_val = int(query.get("limit", ["50"])[0])
            events = self.service.store.list_audit_events(
                session_id=session_filter,
                task_id=task_filter,
                limit=limit_val,
            )
            self._send_json(200, [e.to_dict() for e in events])
            return

        # 15. Inspect Delegated Scope Chain: GET /api/v1/delegation/chain/{scope_id}
        m_dlg = re.match(r"^/(?:api/v1/delegation/chain|v1/delegation/chain)/([a-zA-Z0-9_-]+)$", path)
        if m_dlg:
            scope_id = m_dlg.group(1)
            child_scope = self.service.communication_mgr.get_delegated_scope(scope_id)
            if not child_scope:
                self._send_error(404, f"Delegated child scope '{scope_id}' not found")
                return
            self._send_json(200, child_scope.to_dict())
            return

        # 16. List Branches for Session: GET /api/v1/sessions/{session_id}/branches
        m_branches = re.match(r"^/(?:api/v1/sessions|v1/sessions|api/v1/research-sessions)/([a-zA-Z0-9_-]+)/branches$", path)
        if m_branches:
            session_id = m_branches.group(1)
            branches = self.service.list_branches(session_id=session_id)
            self._send_json(200, [b.to_dict() for b in branches])
            return

        # 17. Checkpoint Lineage DAG: GET /api/v1/sessions/{session_id}/lineage
        m_lineage = re.match(r"^/(?:api/v1/sessions|v1/sessions|api/v1/research-sessions)/([a-zA-Z0-9_-]+)/lineage$", path)
        if m_lineage:
            session_id = m_lineage.group(1)
            lineage = self.service.get_lineage(session_id)
            self._send_json(200, lineage.to_dict())
            return

        # 18. Get Execution Branch by ID: GET /api/v1/branches/{branch_id}
        m_branch = re.match(r"^/(?:api/v1/branches|v1/branches)/([a-zA-Z0-9_-]+)$", path)
        if m_branch:
            branch_id = m_branch.group(1)
            branch = self.service.get_branch(branch_id)
            if not branch:
                self._send_error(404, f"Branch '{branch_id}' not found")
                return
            self._send_json(200, branch.to_dict())
            return

        # 19. Get Session Primary HEAD: GET /api/v1/sessions/{session_id}/speculative/head
        m_head = re.match(r"^/(?:api/v1/sessions|v1/sessions|api/v1/research-sessions)/([a-zA-Z0-9_-]+)/speculative/head$", path)
        if m_head:
            session_id = m_head.group(1)
            head_chk = self.service.get_session_head(session_id)
            self._send_json(200, {"session_id": session_id, "head_checkpoint_id": head_chk})
            return

        # 20. List Speculative Evaluations: GET /api/v1/sessions/{session_id}/speculative/evaluations
        m_evals = re.match(r"^/(?:api/v1/sessions|v1/sessions|api/v1/research-sessions)/([a-zA-Z0-9_-]+)/speculative/evaluations$", path)
        if m_evals:
            session_id = m_evals.group(1)
            evals = self.service.list_evaluations(session_id=session_id)
            self._send_json(200, [e.to_dict() for e in evals])
            return

        # 21. Get Evaluation Matrix by ID: GET /api/v1/evaluations/{matrix_id}
        m_mat = re.match(r"^/(?:api/v1/evaluations|v1/evaluations)/([a-zA-Z0-9_-]+)$", path)
        if m_mat:
            matrix_id = m_mat.group(1)
            mat = self.service.store.get_evaluation(matrix_id)
            if not mat:
                self._send_error(404, f"Evaluation matrix '{matrix_id}' not found")
                return
            self._send_json(200, mat.to_dict())
            return

        self._send_error(404, f"Path not found: {path}")



    def do_POST(self) -> None:
        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path.rstrip("/")
        idempotency_key = self.headers.get("Idempotency-Key")

        body, err = self._read_body_json()
        if err:
            self._send_error(400, f"Malformed JSON request body: {err}")
            return
        body = body or {}

        # 1. Create Research Session: POST /api/v1/research-sessions
        if path in ("/api/v1/research-sessions", "/v1/research/sessions"):
            objective = body.get("objective")
            if not objective:
                self._send_error(400, "Missing required parameter: 'objective'")
                return
            session_id = body.get("id") or body.get("session_id")
            target = body.get("target", "Autonomous Actor Checkpointing & State Persistence")
            atespace = body.get("atespace", "default")
            role = body.get("role", "research")
            metadata = body.get("metadata", {})

            try:
                session = self.service.create_session(
                    objective=objective,
                    session_id=session_id,
                    target=target,
                    role=role,
                    atespace=atespace,
                    idempotency_key=idempotency_key,
                    metadata=metadata,
                )
                self._send_json(201, session.to_dict())
            except OrchestratorError as e:
                self._send_error(409, str(e))
            except Exception as e:
                logger.exception("Unexpected error creating session: %s", e)
                self._send_error(500, f"Internal server error: {e}")
            return

        # 2. Suspend session: POST /api/v1/research-sessions/{id}/suspend
        m_suspend = re.match(r"^/(?:api/v1/research-sessions|v1/research/sessions)/([a-zA-Z0-9_-]+)/suspend$", path)
        if m_suspend:
            session_id = m_suspend.group(1)
            reason = body.get("reason", "Operator manual suspend via API")
            actor = body.get("actor", "api_user")
            try:
                session = self.service.suspend_session(
                    session_id=session_id,
                    reason=reason,
                    actor=actor,
                    idempotency_key=idempotency_key,
                )
                self._send_json(200, session.to_dict())
            except OrchestratorError as e:
                self._send_error(409, str(e))
            except Exception as e:
                self._send_error(500, f"Error suspending session: {e}")
            return

        # 3. Resume session: POST /api/v1/research-sessions/{id}/resume
        m_resume = re.match(r"^/(?:api/v1/research-sessions|v1/research/sessions)/([a-zA-Z0-9_-]+)/resume$", path)
        if m_resume:
            session_id = m_resume.group(1)
            reason = body.get("reason", "Operator manual resume via API")
            actor = body.get("actor", "api_user")
            try:
                session = self.service.resume_session(
                    session_id=session_id,
                    reason=reason,
                    actor=actor,
                    idempotency_key=idempotency_key,
                )
                self._send_json(200, session.to_dict())
            except OrchestratorError as e:
                self._send_error(409, str(e))
            except Exception as e:
                self._send_error(500, f"Error resuming session: {e}")
            return

        # 4. Create explicit checkpoint: POST /api/v1/research-sessions/{id}/checkpoints
        m_cp = re.match(r"^/(?:api/v1/research-sessions|v1/research/sessions)/([a-zA-Z0-9_-]+)/checkpoints$", path)
        if m_cp:
            session_id = m_cp.group(1)
            session = self.service.get_session(session_id, sync=True)
            if not session:
                self._send_error(404, f"Session '{session_id}' not found")
                return
            reason = body.get("reason", "Explicit operator checkpoint request")
            checkpoint = Checkpoint(
                session_id=session.id,
                task_id=session.active_task_id,
                workspace_version=f"v-{int(time.time())}",
                metadata={"reason": reason},
            )
            self.service.store.save_checkpoint(checkpoint)
            self._send_json(201, checkpoint.to_dict())
            return

        # 5. Evaluate policy (Simulator / Scope): POST /api/v1/scope/evaluate
        if path in ("/api/v1/scope/evaluate", "/v1/scope/evaluate"):
            caller_role = body.get("caller_role", "research-agent")
            requested_capability = body.get("requested_capability", "code_review")
            target_agent = body.get("target_agent", "reviewer-04")
            task_id = body.get("task_id", "T-482")
            workspace_id = body.get("workspace_id", "WS-security")
            environment = body.get("environment", "staging")

            # Dynamic evaluation simulation
            allowed = (
                caller_role == "research-agent"
                and requested_capability in ("code_review", "document_analysis", "web_research")
                and environment == "staging"
            )
            if allowed:
                self._send_json(200, {
                    "verdict": "ALLOWED",
                    "reason": "Authorized by policy evaluation intersection",
                    "effective_scope": {
                        "capability": requested_capability,
                        "target": target_agent,
                        "task_id": task_id,
                        "workspace_id": workspace_id,
                        "ttl_seconds": 900,
                        "max_calls": 10,
                        "delegation_depth": 1,
                    },
                    "policy_rule": "rule-research-collab-v1",
                })
            else:
                self._send_json(200, {
                    "verdict": "DENIED",
                    "reason": f"Role '{caller_role}' is not authorized for capability '{requested_capability}' in environment '{environment}'",
                    "policy_rule": "default-deny-rule",
                })
            return

        # 6. Register Logical Agent: POST /api/v1/agents
        if path in ("/api/v1/agents", "/v1/agents"):
            agent_id = body.get("agent_id")
            role = body.get("role")
            if not agent_id or not role:
                self._send_error(400, "Missing required parameters: 'agent_id' and 'role'")
                return
            tenant = body.get("tenant", "default")
            environment = body.get("environment", "staging")
            capabilities = body.get("capabilities", [])
            identity_subject = body.get("identity_subject")
            metadata = body.get("metadata", {})

            try:
                agent = self.service.registry.register_agent(
                    agent_id=agent_id,
                    role=role,
                    tenant=tenant,
                    environment=environment,
                    capabilities=capabilities,
                    identity_subject=identity_subject,
                    metadata=metadata,
                )
                self._send_json(201, agent.to_dict())
            except AgentRegistryError as e:
                self._send_error(409, str(e))
            return

        # 7. Provision Agent Identity: POST /api/v1/agents/{id}/identity/provision
        m_prov = re.match(r"^/(?:api/v1/agents|v1/agents)/([a-zA-Z0-9_-]+)/identity/provision$", path)
        if m_prov:
            agent_id = m_prov.group(1)
            task_id = body.get("task_id")
            workspace_id = body.get("workspace_id")
            if not task_id or not workspace_id:
                self._send_error(400, "Missing required parameters: 'task_id' and 'workspace_id'")
                return
            session_id = body.get("session_id")
            ttl_seconds = int(body.get("ttl_seconds", 3600))

            try:
                agent, token = self.service.identity_mgr.provision_agent_identity(
                    agent_id=agent_id,
                    task_id=task_id,
                    workspace_id=workspace_id,
                    session_id=session_id,
                    ttl_seconds=ttl_seconds,
                )
                self._send_json(201, {
                    "agent": agent.to_dict(),
                    "identity_token": token.to_dict(),
                })
            except (AgentRegistryError, IdentityManagerError) as e:
                self._send_error(400, str(e))
            return

        # 8. Revoke Agent Identity: POST /api/v1/agents/{id}/revoke-identity
        m_rev = re.match(r"^/(?:api/v1/agents|v1/agents)/([a-zA-Z0-9_-]+)/revoke-identity$", path)
        if m_rev:
            agent_id = m_rev.group(1)
            reason = body.get("reason", "Operator revocation")
            success = self.service.identity_mgr.terminate_agent_identity(agent_id, reason=reason)
            if success:
                self._send_json(200, {"status": "REVOKED", "agent_id": agent_id, "reason": reason})
            else:
                self._send_error(404, f"Agent '{agent_id}' not found")
            return

        # 9. Cryptographically Validate Raw Token: POST /api/v1/identity/validate
        if path in ("/api/v1/identity/validate", "/v1/identity/validate"):
            raw_token = body.get("token")
            if not raw_token:
                self._send_error(400, "Missing required parameter: 'token'")
                return
            expected_task_id = body.get("expected_task_id")
            expected_workspace_id = body.get("expected_workspace_id")

            result = self.service.identity_mgr.verify_workload_token(
                token=raw_token,
                expected_task_id=expected_task_id,
                expected_workspace_id=expected_workspace_id,
            )
            self._send_json(200, result.to_dict())
            return

        # 10. Contextual Intersection Policy Evaluation: POST /api/v1/policy/evaluate
        if path in ("/api/v1/policy/evaluate", "/v1/policy/evaluate"):
            identity_token = body.get("identity_token")
            requested_cap = body.get("requested_capability")
            task_id = body.get("task_id")
            workspace_id = body.get("workspace_id")

            if not identity_token or not requested_cap or not task_id or not workspace_id:
                self._send_error(400, "Missing required parameters: 'identity_token', 'requested_capability', 'task_id', 'workspace_id'")
                return

            req = AuthorizationRequest(
                identity_token=identity_token,
                requested_capability=requested_cap,
                requested_action=body.get("requested_action", "*"),
                target_resource=body.get("target_resource", "/workspace/*"),
                task_id=task_id,
                workspace_id=workspace_id,
                target_agent=body.get("target_agent"),
                delegation_depth=int(body.get("delegation_depth", 0)),
                environment=body.get("environment", "staging"),
                parameters=body.get("parameters", {}),
            )
            eval_result = self.service.policy_engine.evaluate(req)
            self._send_json(200, eval_result.to_dict())
            return

        # 11. Issue Cryptographic Scope Token: POST /api/v1/policy/issue-scope
        if path in ("/api/v1/policy/issue-scope", "/v1/policy/issue-scope"):
            identity_token = body.get("identity_token")
            if not identity_token:
                self._send_error(400, "Missing required parameter: 'identity_token'")
                return

            # Check if evaluation result passed in or evaluate on the fly
            eval_data = body.get("evaluation_result")
            if not eval_data:
                requested_cap = body.get("requested_capability")
                task_id = body.get("task_id")
                workspace_id = body.get("workspace_id")
                if not requested_cap or not task_id or not workspace_id:
                    self._send_error(400, "Missing required evaluation parameters: 'requested_capability', 'task_id', 'workspace_id'")
                    return
                req = AuthorizationRequest(
                    identity_token=identity_token,
                    requested_capability=requested_cap,
                    requested_action=body.get("requested_action", "*"),
                    target_resource=body.get("target_resource", "/workspace/*"),
                    task_id=task_id,
                    workspace_id=workspace_id,
                    target_agent=body.get("target_agent"),
                    delegation_depth=int(body.get("delegation_depth", 0)),
                    environment=body.get("environment", "staging"),
                )
                eval_res = self.service.policy_engine.evaluate(req)
            else:
                eval_res = PolicyEvaluationResult(
                    verdict=EvaluationVerdict(eval_data.get("verdict", "DENIED")),
                    reason=eval_data.get("reason", ""),
                    rule_id=eval_data.get("rule_id"),
                    effective_scope=eval_data.get("effective_scope"),
                )

            ttl_seconds = body.get("ttl_seconds")
            invocations = int(body.get("max_invocations", 10))
            try:
                scope_token = self.service.scope_issuer.issue_scope(
                    evaluation=eval_res,
                    identity_token=identity_token,
                    ttl_seconds=int(ttl_seconds) if ttl_seconds else None,
                    max_invocations=invocations,
                )
                self._send_json(201, {
                    "scope_token": scope_token.to_dict(),
                    "raw_token": scope_token.raw_token,
                })
            except ScopeIssuerError as e:
                self._send_error(403, str(e))
            return

        # 12. Agent Gateway In-Path Authorize: POST /api/v1/gateway/authorize
        if path in ("/api/v1/gateway/authorize", "/v1/gateway/authorize"):
            id_token = body.get("identity_token")
            scope_tok = body.get("scope_token")
            action = body.get("action")
            resource = body.get("resource")
            task_id = body.get("task_id")
            workspace_id = body.get("workspace_id")
            session_id = body.get("session_id")

            if not all([id_token, scope_tok, action, resource, task_id, workspace_id]):
                self._send_error(400, "Missing required parameters: 'identity_token', 'scope_token', 'action', 'resource', 'task_id', 'workspace_id'")
                return

            decision = self.service.gateway_authorizer.authorize_invocation(
                identity_token=id_token,
                scope_token=scope_tok,
                action=action,
                resource=resource,
                task_id=task_id,
                workspace_id=workspace_id,
                session_id=session_id,
            )
            self._send_json(200, decision.to_dict())
            return

        # 13. Peer Agent Capability Discovery: POST /api/v1/agents/discover
        if path in ("/api/v1/agents/discover", "/v1/agents/discover"):
            capability = body.get("capability")
            if not capability:
                self._send_error(400, "Missing required parameter: 'capability'")
                return
            tenant = body.get("tenant", "default")
            environment = body.get("environment", "staging")
            exclude_agent = body.get("exclude_agent_id")
            peers = self.service.communication_mgr.discover_peers(
                capability=capability,
                tenant=tenant,
                environment=environment,
                exclude_agent_id=exclude_agent,
            )
            self._send_json(200, [p.to_dict() for p in peers])
            return

        # 14. Inter-Agent Capability Delegation: POST /api/v1/delegation/delegate
        if path in ("/api/v1/delegation/delegate", "/v1/delegation/delegate"):
            caller_token = body.get("caller_identity_token")
            parent_scope = body.get("parent_scope_token")
            target_agent = body.get("target_agent_id")
            task_id = body.get("task_id")
            workspace_id = body.get("workspace_id")
            requested_cap = body.get("requested_capability")

            if not all([caller_token, parent_scope, target_agent, task_id, workspace_id, requested_cap]):
                self._send_error(400, "Missing required parameters: 'caller_identity_token', 'parent_scope_token', 'target_agent_id', 'task_id', 'workspace_id', 'requested_capability'")
                return

            req = DelegationRequest(
                caller_identity_token=caller_token,
                parent_scope_token=parent_scope,
                target_agent_id=target_agent,
                task_id=task_id,
                workspace_id=workspace_id,
                requested_capability=requested_cap,
                requested_action=body.get("requested_action", "*"),
                requested_resource=body.get("requested_resource", "/workspace/*"),
                requested_ttl_seconds=body.get("requested_ttl_seconds"),
                requested_max_invocations=body.get("requested_max_invocations"),
                requested_delegation_depth=int(body.get("requested_delegation_depth", 0)),
                environment=body.get("environment", "staging"),
                metadata=body.get("metadata", {}),
            )
            result = self.service.communication_mgr.delegate(req)
            self._send_json(200, result.to_dict())
            return

        # 16. Fork Checkpoint into Branch: POST /api/v1/checkpoints/{checkpoint_id}/branch
        m_branch = re.match(r"^/(?:api/v1/checkpoints|v1/checkpoints)/([a-zA-Z0-9_-]+)/branch$", path)
        if m_branch:
            checkpoint_id = m_branch.group(1)
            caller_token = body.get("caller_identity_token") or body.get("caller_token")
            source_scope = body.get("source_scope_token") or body.get("parent_scope_token") or body.get("source_scope")
            hypothesis = body.get("hypothesis")
            if not caller_token or not source_scope or not hypothesis:
                self._send_error(400, "Missing required fields: caller_identity_token, source_scope_token, hypothesis")
                return

            try:
                req = BranchRequest(
                    parent_checkpoint_id=checkpoint_id,
                    caller_identity_token=caller_token,
                    source_scope_token=source_scope,
                    hypothesis=hypothesis,
                    branch_name=body.get("branch_name") or body.get("branch_id"),
                    target_agent_id=body.get("target_agent_id"),
                    requested_capabilities=body.get("requested_capabilities"),
                    requested_actions=body.get("requested_actions"),
                    requested_resources=body.get("requested_resources"),
                    requested_ttl=int(body.get("requested_ttl", 3600)),
                    max_invocations=int(body.get("max_invocations", 10)),
                    metadata=body.get("metadata", {}),
                )
                branch = self.service.create_branch(req)
                self._send_json(201, branch.to_dict())
            except BranchEscalationDenied as e:
                self._send_error(403, f"Branch Escalation Denied: {e}")
            except BranchingError as e:
                self._send_error(400, f"Branching Error: {e}")
            return

        # 16. Speculative Execution Run: POST /api/v1/sessions/{session_id}/speculative/run
        m_spec_run = re.match(r"^/(?:api/v1/sessions|v1/sessions|api/v1/research-sessions)/([a-zA-Z0-9_-]+)/speculative/run$", path)
        if m_spec_run:
            session_id = m_spec_run.group(1)
            session = self.service.get_session(session_id)
            if not session:
                self._send_error(404, f"Session '{session_id}' not found")
                return

            checkpoint_id = body.get("checkpoint_id")
            if not checkpoint_id:
                # Fallback to active head or latest session checkpoint
                checkpoint_id = self.service.get_session_head(session_id)
                if not checkpoint_id:
                    chks = self.service.list_checkpoints(session_id)
                    if chks:
                        checkpoint_id = chks[-1].id
            if not checkpoint_id:
                self._send_error(400, "Missing required 'checkpoint_id' and session has no existing checkpoints")
                return

            caller_token = body.get("caller_identity_token") or self.headers.get("Authorization", "").replace("Bearer ", "")
            source_scope = body.get("source_scope_token") or self.headers.get("X-Scope-Token", "")
            if not caller_token or not source_scope:
                self._send_error(400, "Missing required 'caller_identity_token' and/or 'source_scope_token'")
                return

            branch_specs = body.get("branches", [])
            if not branch_specs or not isinstance(branch_specs, list):
                self._send_error(400, "Missing or invalid 'branches' specification list")
                return

            scoring_config_data = body.get("scoring_config")
            scoring_config = None
            if scoring_config_data and isinstance(scoring_config_data, dict):
                scoring_config = ScoringConfig(
                    weights=scoring_config_data.get("weights"),
                    min_compliance_threshold=scoring_config_data.get("min_compliance_threshold", 1.0),
                    strict_compliance_disqualification=scoring_config_data.get("strict_compliance_disqualification", True),
                )

            auto_promote = bool(body.get("auto_promote", True))

            try:
                matrix, promotion = self.service.run_speculative_execution(
                    checkpoint_id=checkpoint_id,
                    caller_identity_token=caller_token,
                    source_scope_token=source_scope,
                    branch_specs=branch_specs,
                    scoring_config=scoring_config,
                    auto_promote=auto_promote,
                )
                self._send_json(200, {
                    "matrix": matrix.to_dict(),
                    "promotion": promotion.to_dict() if promotion else None,
                })
            except BranchEscalationDenied as e:
                self._send_error(403, f"Branch Escalation Denied during speculative execution: {e}")
            except (BranchingError, PromotionError) as e:
                self._send_error(400, f"Speculative Execution Error: {e}")
            except Exception as e:
                self._send_error(500, f"Internal Speculative Execution Error: {e}")
            return

        # 17. Promote Branch to Primary HEAD: POST /api/v1/sessions/{session_id}/speculative/promote
        m_spec_promote = re.match(r"^/(?:api/v1/sessions|v1/sessions|api/v1/research-sessions)/([a-zA-Z0-9_-]+)/speculative/promote$", path)
        if m_spec_promote:
            session_id = m_spec_promote.group(1)
            winning_branch_id = body.get("winning_branch_id")
            winning_checkpoint_id = body.get("winning_checkpoint_id")
            evaluation_id = body.get("evaluation_id")
            operator = body.get("operator", "api-operator")

            if not winning_branch_id or not winning_checkpoint_id:
                self._send_error(400, "Missing required 'winning_branch_id' or 'winning_checkpoint_id'")
                return

            try:
                promo_result = self.service.promote_branch(
                    session_id=session_id,
                    winning_branch_id=winning_branch_id,
                    winning_checkpoint_id=winning_checkpoint_id,
                    evaluation_id=evaluation_id,
                    operator=operator,
                )
                self._send_json(200, promo_result.to_dict())
            except PromotionError as e:
                self._send_error(400, f"Promotion Error: {e}")
            except Exception as e:
                self._send_error(500, f"Internal Promotion Error: {e}")
            return

        self._send_error(404, f"Path not found: {path}")



    def do_DELETE(self) -> None:
        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path.rstrip("/")

        m_del = re.match(r"^/(?:api/v1/research-sessions|v1/research/sessions)/([a-zA-Z0-9_-]+)$", path)
        if m_del:
            session_id = m_del.group(1)
            success = self.service.delete_session(session_id)
            if success:
                self._send_json(200, {"status": "DELETED", "session_id": session_id})
            else:
                self._send_error(404, f"Session '{session_id}' not found")
            return

        self._send_error(404, f"Path not found: {path}")

    # --------------------------------------------------------------------------
    # Static File Serving (Web UI)
    # --------------------------------------------------------------------------

    def _serve_static_file(self, filename: str) -> None:
        safe_path = os.path.normpath(os.path.join(self.ui_dir, filename))
        if not safe_path.startswith(self.ui_dir) or not os.path.isfile(safe_path):
            # Fallback to index.html for SPA client-side routing
            index_path = os.path.join(self.ui_dir, "index.html")
            if os.path.isfile(index_path):
                safe_path = index_path
            else:
                self._send_error(404, f"UI file '{filename}' not found")
                return

        mime_type, _ = mimetypes.guess_type(safe_path)
        mime_type = mime_type or "application/octet-stream"

        try:
            with open(safe_path, "rb") as f:
                content = f.read()
            self._set_headers(200, mime_type)
            self.wfile.write(content)
        except Exception as e:
            self._send_error(500, f"Error reading static file: {e}")


class AgentLabServer:
    """
    Multi-threaded HTTP Server managing the Agent Lab Control Plane API.
    """

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 8000,
        service: Optional[ResearchSessionService] = None,
    ):
        self.host = host
        self.port = port
        self.service = service or ResearchSessionService()
        AgentLabRequestHandler.service = self.service

        self.server = http.server.ThreadingHTTPServer((self.host, self.port), AgentLabRequestHandler)
        self.thread: Optional[threading.Thread] = None

    def start(self, block: bool = False) -> None:
        logger.info(f"Starting Agent Lab API server on http://{self.host}:{self.port}")
        if block:
            try:
                self.server.serve_forever()
            except KeyboardInterrupt:
                logger.info("Shutting down Agent Lab API server")
                self.stop()
        else:
            self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
            self.thread.start()

    def stop(self) -> None:
        if self.server:
            self.server.shutdown()
            self.server.server_close()
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=2.0)
        logger.info("Agent Lab API server stopped")


def run_server():
    import argparse
    parser = argparse.ArgumentParser(description="Agent Lab Control Plane API Server")
    parser.add_argument("--host", default="0.0.0.0", help="Binding host (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8000, help="Binding port (default: 8000)")
    args = parser.parse_args()

    server = AgentLabServer(host=args.host, port=args.port)
    server.start(block=True)


if __name__ == "__main__":
    run_server()
