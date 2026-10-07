"""
tests/unit/test_agent_registry.py — Unit tests for Agent Registry Service
"""
import os
import sys
import tempfile
import unittest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from domain.agents.models import Agent, AgentLifecycleState
from adapters.storage.metadata_store import SQLiteMetadataStore
from services.agents.registry import AgentRegistryService, AgentRegistryError


class TestAgentRegistryService(unittest.TestCase):
    def setUp(self):
        self.tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp_db.close()
        self.store = SQLiteMetadataStore(db_path=self.tmp_db.name)
        self.registry = AgentRegistryService(self.store)

    def tearDown(self):
        if os.path.exists(self.tmp_db.name):
            os.remove(self.tmp_db.name)

    def test_register_and_get_agent(self):
        agent = self.registry.register_agent(
            agent_id="researcher-01",
            role="research-agent",
            tenant="acme",
            environment="staging",
            capabilities=["web_research", "doc_analysis"],
        )
        self.assertEqual(agent.agent_id, "researcher-01")
        self.assertEqual(agent.identity_subject, "agent:researcher-01")
        self.assertEqual(agent.lifecycle_state, AgentLifecycleState.REGISTERED)

        retrieved = self.registry.get_agent("researcher-01")
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.agent_id, "researcher-01")
        self.assertEqual(retrieved.tenant, "acme")
        self.assertEqual(retrieved.capabilities, ["web_research", "doc_analysis"])

    def test_duplicate_registration_raises(self):
        self.registry.register_agent(agent_id="agent-dup", role="research")
        with self.assertRaises(AgentRegistryError):
            self.registry.register_agent(agent_id="agent-dup", role="research")

    def test_list_and_filter_agents(self):
        self.registry.register_agent(agent_id="agent-a", role="research", tenant="t1")
        self.registry.register_agent(agent_id="agent-b", role="review", tenant="t1")
        self.registry.register_agent(agent_id="agent-c", role="research", tenant="t2")

        all_agents = self.registry.list_agents()
        self.assertEqual(len(all_agents), 3)

        t1_agents = self.registry.list_agents(tenant="t1")
        self.assertEqual(len(t1_agents), 2)

        research_agents = self.registry.list_agents(role="research")
        self.assertEqual(len(research_agents), 2)

    def test_lifecycle_and_execution_binding(self):
        agent = self.registry.register_agent(agent_id="agent-exec", role="research")
        self.assertEqual(agent.lifecycle_state, AgentLifecycleState.REGISTERED)

        bound = self.registry.bind_execution(
            agent_id="agent-exec",
            task_id="T-100",
            workspace_id="WS-100",
            session_id="S-100",
        )
        self.assertEqual(bound.lifecycle_state, AgentLifecycleState.ACTIVE)
        self.assertEqual(bound.task_id, "T-100")
        self.assertEqual(bound.workspace_id, "WS-100")
        self.assertEqual(bound.session_id, "S-100")

        suspended = self.registry.update_lifecycle("agent-exec", AgentLifecycleState.SUSPENDED)
        self.assertEqual(suspended.lifecycle_state, AgentLifecycleState.SUSPENDED)


if __name__ == "__main__":
    unittest.main()
