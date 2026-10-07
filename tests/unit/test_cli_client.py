"""
tests/unit/test_cli_client.py — Unit tests for the Agent Lab CLI HTTP Client
"""
import time
import unittest
from api.server import AgentLabServer
from adapters.storage.metadata_store import SQLiteMetadataStore
from services.orchestrator.orchestrator import ResearchSessionService
from adapters.ax.ax_adapter import AXAdapterInterface
from domain.tasks.models import Task, TaskPhase
from cli.client import AgentLabClient, APIClientError


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


class TestAgentLabCLIClient(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import tempfile
        cls.tmp_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        cls.tmp_file.close()
        cls.store = SQLiteMetadataStore(cls.tmp_file.name)
        cls.ax = MockAXAdapter()
        cls.service = ResearchSessionService(metadata_store=cls.store, ax_adapter=cls.ax)
        cls.server = AgentLabServer(host="127.0.0.1", port=8992, service=cls.service)
        cls.server.start(block=False)
        time.sleep(0.2)
        cls.client = AgentLabClient(base_url="http://127.0.0.1:8992")

    @classmethod
    def tearDownClass(cls):
        cls.server.stop()
        import os
        try:
            os.remove(cls.tmp_file.name)
        except Exception:
            pass

    def test_client_healthz(self):
        res = self.client.healthz()
        self.assertEqual(res.get("status"), "HEALTHY")

    def test_client_session_lifecycle(self):
        # 1. Create
        s = self.client.create_session(objective="CLI Client Lifecycle Test", session_id="rs-cli-01")
        self.assertEqual(s.get("id"), "rs-cli-01")
        self.assertEqual(s.get("status"), "RUNNING")

        # 2. Get
        fetched = self.client.get_session("rs-cli-01")
        self.assertEqual(fetched.get("id"), "rs-cli-01")

        # 3. List
        all_sessions = self.client.list_sessions()
        self.assertTrue(any(item.get("id") == "rs-cli-01" for item in all_sessions))

        # 4. Suspend
        susp = self.client.suspend_session("rs-cli-01", reason="CLI suspend")
        self.assertEqual(susp.get("status"), "SUSPENDED")

        # 5. Resume
        resumed = self.client.resume_session("rs-cli-01")
        self.assertEqual(resumed.get("status"), "RUNNING")
        self.assertEqual(resumed.get("active_worker_ip"), "10.244.0.26")

        # 6. Checkpoint
        cp = self.client.create_checkpoint("rs-cli-01", reason="CLI checkpoint")
        self.assertEqual(cp.get("session_id"), "rs-cli-01")

        # 7. Timeline
        tl = self.client.get_timeline("rs-cli-01")
        self.assertTrue(len(tl.get("timeline", [])) >= 3)

        # 8. Scope evaluation
        eval_res = self.client.evaluate_scope(
            caller_role="research-agent",
            requested_capability="code_review",
            target_agent="reviewer-04",
            task_id="rs-cli-01",
            workspace_id="ws-rs-cli-01",
            environment="staging",
        )
        self.assertEqual(eval_res.get("verdict"), "ALLOWED")


if __name__ == "__main__":
    unittest.main()
