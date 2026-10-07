"""
tests/unit/test_api_server.py — Unit tests for the Agent Lab REST API Server
"""
import json
import time
import unittest
from api.server import AgentLabServer
from adapters.storage.metadata_store import SQLiteMetadataStore
from domain.sessions.models import ResearchSession, SessionStatus
from services.orchestrator.orchestrator import ResearchSessionService
from adapters.ax.ax_adapter import AXAdapterInterface
from domain.tasks.models import Task, TaskPhase


class MockAXAdapter(AXAdapterInterface):
    def __init__(self):
        self.tasks = {}

    def apply_task(self, task_name, session_id, target, atespace="default", identity_token=None, identity_subject=None, **kwargs):
        t = Task(id=task_name, session_id=session_id, atespace=atespace, phase=TaskPhase.RUNNING, worker_ip="10.244.0.28")
        self.tasks[task_name] = t
        return t

    def get_task(self, task_name, atespace="default"):
        return self.tasks.get(task_name)

    def list_tasks(self, atespace="default"):
        return list(self.tasks.values())

    def suspend_task(self, task_name, atespace="default"):
        if task_name in self.tasks:
            self.tasks[task_name].phase = TaskPhase.SUSPENDED
            self.tasks[task_name].worker_ip = None
        return True

    def resume_task(self, task_name, atespace="default"):
        if task_name in self.tasks:
            self.tasks[task_name].phase = TaskPhase.RUNNING
            self.tasks[task_name].worker_ip = "10.244.0.26"
        return True

    def delete_task(self, task_name, atespace="default"):
        self.tasks.pop(task_name, None)
        return True

    def exec_task(self, task_name, command, atespace="default"):
        return 0, "mock stdout", ""


class TestAgentLabAPIServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import tempfile
        cls.tmp_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        cls.tmp_file.close()
        cls.store = SQLiteMetadataStore(cls.tmp_file.name)
        cls.ax = MockAXAdapter()
        cls.service = ResearchSessionService(metadata_store=cls.store, ax_adapter=cls.ax)
        cls.server = AgentLabServer(host="127.0.0.1", port=8991, service=cls.service)
        cls.server.start(block=False)
        time.sleep(0.2)  # Give server brief moment to bind

    @classmethod
    def tearDownClass(cls):
        cls.server.stop()
        import os
        try:
            os.remove(cls.tmp_file.name)
        except Exception:
            pass

    def setUp(self):
        import urllib.request
        self.base_url = "http://127.0.0.1:8991"

    def _req(self, method, path, data=None, headers=None):
        import urllib.request
        url = f"{self.base_url}{path}"
        req_headers = {"Content-Type": "application/json"}
        if headers:
            req_headers.update(headers)
        body = json.dumps(data).encode("utf-8") if data else None
        req = urllib.request.Request(url, data=body, headers=req_headers, method=method)
        with urllib.request.urlopen(req, timeout=5) as res:
            return res.getcode(), json.loads(res.read().decode("utf-8"))

    def test_healthz(self):
        code, data = self._req("GET", "/api/v1/healthz")
        self.assertEqual(code, 200)
        self.assertEqual(data.get("status"), "HEALTHY")

    def test_create_and_get_session(self):
        payload = {
            "objective": "Verify API Endpoints",
            "id": "rs-api-test-01",
            "target": "Test Target",
        }
        code, session = self._req("POST", "/api/v1/research-sessions", data=payload)
        self.assertEqual(code, 201)
        self.assertEqual(session.get("id"), "rs-api-test-01")
        self.assertEqual(session.get("status"), "RUNNING")

        # Get details
        code, fetched = self._req("GET", "/api/v1/research-sessions/rs-api-test-01")
        self.assertEqual(code, 200)
        self.assertEqual(fetched.get("id"), "rs-api-test-01")

    def test_list_sessions(self):
        code, sessions = self._req("GET", "/api/v1/research-sessions")
        self.assertEqual(code, 200)
        self.assertIsInstance(sessions, list)
        self.assertTrue(len(sessions) >= 1)

    def test_suspend_and_resume(self):
        # Create session
        self._req("POST", "/api/v1/research-sessions", data={"objective": "Suspend Resume Test", "id": "rs-suspend-01"})
        
        # Suspend
        code, suspended = self._req("POST", "/api/v1/research-sessions/rs-suspend-01/suspend", data={"reason": "Testing suspend"})
        self.assertEqual(code, 200)
        self.assertEqual(suspended.get("status"), "SUSPENDED")

        # Resume
        code, resumed = self._req("POST", "/api/v1/research-sessions/rs-suspend-01/resume", data={})
        self.assertEqual(code, 200)
        self.assertEqual(resumed.get("status"), "RUNNING")
        self.assertEqual(resumed.get("active_worker_ip"), "10.244.0.26")

    def test_checkpoint_and_timeline(self):
        self._req("POST", "/api/v1/research-sessions", data={"objective": "Timeline Test", "id": "rs-timeline-01"})
        
        # Create checkpoint
        code, cp = self._req("POST", "/api/v1/research-sessions/rs-timeline-01/checkpoints", data={"reason": "manual-chk"})
        self.assertEqual(code, 201)
        self.assertEqual(cp.get("session_id"), "rs-timeline-01")

        # Timeline
        code, tl = self._req("GET", "/api/v1/research-sessions/rs-timeline-01/timeline")
        self.assertEqual(code, 200)
        self.assertIn("timeline", tl)
        self.assertTrue(len(tl["timeline"]) >= 1)

    def test_policy_scope_evaluation(self):
        payload = {
            "caller_role": "research-agent",
            "requested_capability": "code_review",
            "target_agent": "reviewer-04",
            "environment": "staging",
        }
        code, res = self._req("POST", "/api/v1/scope/evaluate", data=payload)
        self.assertEqual(code, 200)
        self.assertEqual(res.get("verdict"), "ALLOWED")
        self.assertIn("effective_scope", res)

    def test_checkpoint_branching_and_lineage_api(self):
        # 1. Create a session
        code, sess = self._req("POST", "/api/v1/research-sessions", data={
            "objective": "Branching API Integration Test",
            "role": "lead-researcher",
        })
        self.assertEqual(code, 201)
        sess_id = sess["id"]

        # 2. Get initial checkpoint from service
        checkpoints = self.service.store.list_checkpoints(sess_id)
        if not checkpoints:
            from domain.checkpoints.models import Checkpoint
            chk = Checkpoint(session_id=sess_id, task_id="T-init", workspace_version="v1")
            self.service.store.save_checkpoint(chk)
            chk_id = chk.id
        else:
            chk_id = checkpoints[0].id

        # 3. Create agent and identity
        agent = self.service.registry.register_agent(
            agent_id=f"api-tester-{sess_id[:6]}",
            role="lead-researcher",
            tenant="default",
            capabilities=["document_analysis"],
        )
        _, ident = self.service.identity_mgr.provision_agent_identity(
            agent_id=agent.agent_id,
            task_id="T-init",
            workspace_id=f"ws-{sess_id}",
        )

        import jwt, time
        now = int(time.time())
        scope_claims = {
            "scope_id": f"scp-{sess_id[:6]}",
            "sub": agent.identity_subject,
            "task_id": "T-init",
            "workspace_id": f"ws-{sess_id}",
            "capability": "document_analysis",
            "granted_action": "read",
            "allowed_actions": ["read"],
            "resource_path": "/workspace/*",
            "resource_pattern": "/workspace/*",
            "max_invocations": 10,
            "invocations_remaining": 10,
            "iat": now,
            "exp": now + 3600,
            "iss": "https://scope.agent-lab.internal",
            "aud": "agent-gateway",
        }
        scope_jwt = jwt.encode(scope_claims, self.service.branching_controller.secret_key, algorithm="HS256")

        # 4. POST /api/v1/checkpoints/{id}/branch
        branch_payload = {
            "caller_identity_token": ident.raw_token,
            "source_scope_token": scope_jwt,
            "hypothesis": "Hypothesis API Branch",
            "branch_name": f"branch-api-{sess_id[:6]}",
        }
        code, branch_res = self._req("POST", f"/api/v1/checkpoints/{chk_id}/branch", data=branch_payload)
        self.assertEqual(code, 201)
        self.assertEqual(branch_res.get("hypothesis"), "Hypothesis API Branch")
        branch_id = branch_res["branch_id"]

        # 5. GET /api/v1/sessions/{id}/branches
        code, branches_res = self._req("GET", f"/api/v1/sessions/{sess_id}/branches")
        self.assertEqual(code, 200)
        self.assertTrue(len(branches_res) >= 1)

        # 6. GET /api/v1/sessions/{id}/lineage
        code, lineage_res = self._req("GET", f"/api/v1/sessions/{sess_id}/lineage")
        self.assertEqual(code, 200)
        self.assertIn("lineage_dag", lineage_res)
        self.assertIn(chk_id, lineage_res["lineage_dag"])


if __name__ == "__main__":
    unittest.main()
