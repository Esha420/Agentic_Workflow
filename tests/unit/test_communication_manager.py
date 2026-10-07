"""
tests/unit/test_communication_manager.py — Unit tests for CommunicationManager and Peer Discovery
"""
import os
import tempfile
import unittest

from domain.delegation.models import DelegationRequest, DelegationVerdict
from domain.policy.models import AuthorizationRequest
from services.agents.registry import AgentRegistryService
from services.identity.manager import IdentityManager
from services.policy.capabilities import CapabilityRegistry
from services.policy.engine import PolicyEngine
from services.policy.scope_issuer import ScopeIssuer
from services.delegation.engine import DelegationEngine
from services.communication.manager import CommunicationManager
from adapters.storage.metadata_store import SQLiteMetadataStore


class TestCommunicationManager(unittest.TestCase):
    def setUp(self):
        self.tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp_db.close()
        self.store = SQLiteMetadataStore(db_path=self.tmp_db.name)
        self.registry = AgentRegistryService(self.store)
        self.id_mgr = IdentityManager(registry=self.registry, metadata_store=self.store)
        self.cap_registry = CapabilityRegistry()
        self.policy_engine = PolicyEngine(
            capability_registry=self.cap_registry,
            identity_manager=self.id_mgr,
            metadata_store=self.store,
        )
        self.scope_issuer = ScopeIssuer(policy_engine=self.policy_engine)
        self.delegation_engine = DelegationEngine(
            agent_registry=self.registry,
            identity_manager=self.id_mgr,
            capability_registry=self.cap_registry,
            scope_issuer=self.scope_issuer,
            metadata_store=self.store,
        )
        self.comm_mgr = CommunicationManager(
            delegation_engine=self.delegation_engine,
            agent_registry=self.registry,
            metadata_store=self.store,
        )

        # Register agents in acme tenant
        self.a1 = self.registry.register_agent(
            agent_id="planner-01",
            role="lead-researcher",
            tenant="acme",
            environment="staging",
            capabilities=["web_research", "document_analysis"],
        )
        self.registry.update_lifecycle(self.a1.agent_id, self.a1.lifecycle_state.ACTIVE)

        self.a2 = self.registry.register_agent(
            agent_id="doc-agent-02",
            role="research-agent",
            tenant="acme",
            environment="staging",
            capabilities=["document_analysis"],
        )
        self.registry.update_lifecycle(self.a2.agent_id, self.a2.lifecycle_state.ACTIVE)

        self.a3 = self.registry.register_agent(
            agent_id="coder-03",
            role="coder-agent",
            tenant="acme",
            environment="staging",
            capabilities=["code_generation"],
        )
        self.registry.update_lifecycle(self.a3.agent_id, self.a3.lifecycle_state.ACTIVE)

        # Agent in another tenant
        self.a_other = self.registry.register_agent(
            agent_id="other-doc-04",
            role="research-agent",
            tenant="other-tenant",
            environment="staging",
            capabilities=["document_analysis"],
        )
        self.registry.update_lifecycle(self.a_other.agent_id, self.a_other.lifecycle_state.ACTIVE)

    def tearDown(self):
        if os.path.exists(self.tmp_db.name):
            os.remove(self.tmp_db.name)

    def test_discover_peers_by_capability(self):
        """Peer discovery discovers only active agents in the same tenant with matching capability."""
        peers = self.comm_mgr.discover_peers(
            capability="document_analysis",
            tenant="acme",
            environment="staging",
            exclude_agent_id="planner-01",
        )
        peer_ids = [p.agent_id for p in peers]
        self.assertIn("doc-agent-02", peer_ids)
        self.assertNotIn("planner-01", peer_ids)      # excluded
        self.assertNotIn("coder-03", peer_ids)        # no document_analysis
        self.assertNotIn("other-doc-04", peer_ids)    # different tenant


if __name__ == "__main__":
    unittest.main()
