"""
tests/unit/test_identity_lifecycle.py — Unit tests for IdentityManager and end-to-end identity lifecycle
"""
import os
import sys
import tempfile
import unittest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from domain.agents.models import AgentLifecycleState
from adapters.storage.metadata_store import SQLiteMetadataStore
from services.agents.registry import AgentRegistryService
from services.identity.manager import IdentityManager


class TestIdentityLifecycle(unittest.TestCase):
    def setUp(self):
        self.tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp_db.close()
        self.store = SQLiteMetadataStore(db_path=self.tmp_db.name)
        self.registry = AgentRegistryService(self.store)
        self.identity_mgr = IdentityManager(registry=self.registry, metadata_store=self.store)

    def tearDown(self):
        if os.path.exists(self.tmp_db.name):
            os.remove(self.tmp_db.name)

    def test_full_identity_lifecycle(self):
        # 1. Register logical agent
        agent = self.registry.register_agent(
            agent_id="researcher-27",
            role="research-agent",
            tenant="acme",
            environment="staging",
            capabilities=["web_research"],
        )
        self.assertEqual(agent.lifecycle_state, AgentLifecycleState.REGISTERED)

        # 2. Issue task-scoped identity
        agent, token = self.identity_mgr.provision_agent_identity(
            agent_id="researcher-27",
            task_id="T-482",
            workspace_id="WS-security",
        )
        self.assertEqual(agent.lifecycle_state, AgentLifecycleState.ACTIVE)
        self.assertEqual(agent.task_id, "T-482")

        # 3. Verify valid workload token
        val = self.identity_mgr.verify_workload_token(
            token=token.raw_token,
            expected_task_id="T-482",
            expected_workspace_id="WS-security",
        )
        self.assertTrue(val.valid)

        # 4. Inspect status
        status = self.identity_mgr.get_agent_identity_status("researcher-27")
        self.assertTrue(status["identity"]["is_valid"])
        self.assertFalse(status["identity"]["is_revoked"])

        # 5. Transition to SUSPENDED
        self.registry.update_lifecycle("researcher-27", AgentLifecycleState.SUSPENDED)
        agent = self.registry.get_agent("researcher-27")
        self.assertEqual(agent.lifecycle_state, AgentLifecycleState.SUSPENDED)

        # Token is still cryptographically valid while suspended
        val_suspended = self.identity_mgr.verify_workload_token(token.raw_token)
        self.assertTrue(val_suspended.valid)

        # 6. Resume to ACTIVE
        self.registry.update_lifecycle("researcher-27", AgentLifecycleState.ACTIVE)
        agent = self.registry.get_agent("researcher-27")
        self.assertEqual(agent.lifecycle_state, AgentLifecycleState.ACTIVE)

        # 7. Terminate / Revoke Identity
        self.identity_mgr.terminate_agent_identity("researcher-27", reason="Research task completed")
        agent = self.registry.get_agent("researcher-27")
        self.assertEqual(agent.lifecycle_state, AgentLifecycleState.TERMINATED)

        # Token must now be rejected fail-closed
        val_revoked = self.identity_mgr.verify_workload_token(token.raw_token)
        self.assertFalse(val_revoked.valid)
        self.assertIn("revoked", val_revoked.error)


if __name__ == "__main__":
    unittest.main()
