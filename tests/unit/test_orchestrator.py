"""
tests/unit/test_orchestrator.py — Unit tests for Orchestrator & Metadata Store
"""
import os
import tempfile
import unittest
from typing import List, Optional, Tuple
from domain.sessions.models import SessionStatus
from domain.tasks.models import Task, TaskPhase
from adapters.ax.ax_adapter import AXAdapterInterface
from adapters.storage.metadata_store import SQLiteMetadataStore
from services.orchestrator.orchestrator import ResearchSessionService


class MockAXAdapter(AXAdapterInterface):
    """In-memory mock AX adapter for deterministic unit tests."""

    def __init__(self):
        self.tasks = {}

    def apply_task(self, task_name: str, session_id: str, target: str, atespace: str = "default") -> Task:
        task = Task(
            id=task_name,
            session_id=session_id,
            atespace=atespace,
            phase=TaskPhase.RUNNING,
            worker_ip="10.244.0.15",
            metadata={"target": target},
        )
        self.tasks[task_name] = task
        return task

    def get_task(self, task_name: str, atespace: str = "default") -> Optional[Task]:
        return self.tasks.get(task_name)

    def list_tasks(self, atespace: str = "default") -> List[Task]:
        return list(self.tasks.values())

    def suspend_task(self, task_name: str, atespace: str = "default") -> bool:
        if task_name in self.tasks:
            self.tasks[task_name].phase = TaskPhase.SUSPENDED
            self.tasks[task_name].worker_ip = None
            return True
        return False

    def resume_task(self, task_name: str, atespace: str = "default") -> bool:
        if task_name in self.tasks:
            self.tasks[task_name].phase = TaskPhase.RUNNING
            self.tasks[task_name].worker_ip = "10.244.0.18"
            return True
        return False

    def delete_task(self, task_name: str, atespace: str = "default") -> bool:
        if task_name in self.tasks:
            del self.tasks[task_name]
            return True
        return False

    def exec_task(self, task_name: str, command: List[str], atespace: str = "default") -> Tuple[int, str, str]:
        return 0, "# Mock Report\nAll proofs verified.", ""


class TestOrchestrator(unittest.TestCase):

    def test_full_orchestrator_lifecycle(self):
        with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
            store = SQLiteMetadataStore(db_path=tmp.name)
            mock_ax = MockAXAdapter()
            service = ResearchSessionService(metadata_store=store, ax_adapter=mock_ax)

            # 1. Create Session
            session = service.create_session(
                objective="Synthesize distributed actor proofs",
                session_id="test-rs-100",
                idempotency_key="key-create-100",
            )
            self.assertEqual(session.id, "test-rs-100")
            self.assertEqual(session.status, SessionStatus.RUNNING)
            self.assertEqual(session.active_task_id, "test-rs-100")

            # Verify idempotency on retry
            retry_session = service.create_session(
                objective="Duplicate call",
                session_id="test-rs-100",
                idempotency_key="key-create-100",
            )
            self.assertEqual(retry_session.id, "test-rs-100")

            # 2. Suspend Session
            suspended = service.suspend_session(
                session_id="test-rs-100",
                reason="Waiting for theorem verification",
                idempotency_key="key-suspend-100",
            )
            self.assertEqual(suspended.status, SessionStatus.SUSPENDED)
            self.assertIsNone(suspended.active_worker_ip)
            checkpoints = store.list_checkpoints("test-rs-100")
            self.assertEqual(len(checkpoints), 1)

            # 3. Resume Session
            resumed = service.resume_session(
                session_id="test-rs-100",
                reason="Theorem verified by external prover",
                idempotency_key="key-resume-100",
            )
            self.assertEqual(resumed.status, SessionStatus.RUNNING)
            self.assertEqual(resumed.active_worker_ip, "10.244.0.18")

            # 4. Read Artifact
            report = service.read_session_artifact("test-rs-100", "report.md")
            self.assertIn("Mock Report", report)

            # 5. Verify Audit Trail
            stored_session = service.get_session("test-rs-100")
            self.assertGreaterEqual(len(stored_session.audit_trail), 4)


if __name__ == "__main__":
    unittest.main()
