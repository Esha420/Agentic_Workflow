import os
import tempfile
import unittest
from domain.policy.models import AuthorizationRequest
from services.policy.capabilities import CapabilityRegistry
from services.policy.engine import PolicyEngine
from services.policy.scope_issuer import ScopeIssuer
from services.gateway.authorizer import AgentGatewayAuthorizer
from services.identity.manager import IdentityManager
from services.agents.registry import AgentRegistryService
from adapters.storage.metadata_store import SQLiteMetadataStore


class TestGatewayAuthorizer(unittest.TestCase):
    def setUp(self):
        self.tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp_db.close()
        self.store = SQLiteMetadataStore(db_path=self.tmp_db.name)
        self.agent_registry = AgentRegistryService(self.store)
        self.id_mgr = IdentityManager(registry=self.agent_registry, metadata_store=self.store)
        self.cap_registry = CapabilityRegistry()
        self.engine = PolicyEngine(
            capability_registry=self.cap_registry,
            identity_manager=self.id_mgr,
            metadata_store=self.store,
        )
        self.scope_issuer = ScopeIssuer(policy_engine=self.engine)
        self.authorizer = AgentGatewayAuthorizer(
            identity_manager=self.id_mgr,
            scope_issuer=self.scope_issuer,
            metadata_store=self.store,
        )

        # Register Agent 1
        self.agent1 = self.agent_registry.register_agent(
            agent_id="agent-alpha",
            role="research-agent",
            tenant="default",
            environment="staging",
            capabilities=["web_research"],
        )
        _, self.token1 = self.id_mgr.provision_agent_identity(
            agent_id="agent-alpha",
            task_id="task-alpha",
            workspace_id="ws-alpha",
        )

        # Register Agent 2
        self.agent2 = self.agent_registry.register_agent(
            agent_id="agent-beta",
            role="reviewer-agent",
            tenant="default",
            environment="staging",
            capabilities=["code_review"],
        )
        _, self.token2 = self.id_mgr.provision_agent_identity(
            agent_id="agent-beta",
            task_id="task-beta",
            workspace_id="ws-beta",
        )

    def tearDown(self):
        if os.path.exists(self.tmp_db.name):
            os.remove(self.tmp_db.name)


    def test_authorize_invocation_success(self):
        """Valid identity and scope tokens authorize invocation and log audit event."""
        req = AuthorizationRequest(
            identity_token=self.token1.raw_token,
            requested_capability="web_research",
            requested_action="search",
            target_resource="/workspace/research/summary.md",
            task_id="task-alpha",
            workspace_id="ws-alpha",
            environment="staging",
        )
        scope = self.scope_issuer.issue_scope(request=req)

        decision = self.authorizer.authorize_invocation(
            identity_token=self.token1.raw_token,
            scope_token=scope.raw_token,
            action="search",
            resource="/workspace/research/summary.md",
            task_id="task-alpha",
            workspace_id="ws-alpha",
            session_id="session-alpha",
        )
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.subject, self.agent1.identity_subject)
        self.assertEqual(decision.capability, "web_research")
        self.assertEqual(decision.invocations_remaining, 9)

        # Verify audit event in store
        events = self.store.list_audit_events(session_id="session-alpha")
        self.assertGreaterEqual(len(events), 1)
        self.assertEqual(events[0].to_status, "ALLOWED")

    def test_reject_scope_theft_subject_mismatch(self):
        """Agent Beta attempting to use Agent Alpha's scope token is rejected."""
        # Alpha gets a scope token
        req = AuthorizationRequest(
            identity_token=self.token1.raw_token,
            requested_capability="web_research",
            requested_action="search",
            target_resource="/workspace/research/summary.md",
            task_id="task-alpha",
            workspace_id="ws-alpha",
            environment="staging",
        )
        alpha_scope = self.scope_issuer.issue_scope(request=req)

        # Beta tries to use alpha's scope token with beta's identity token
        decision = self.authorizer.authorize_invocation(
            identity_token=self.token2.raw_token,
            scope_token=alpha_scope.raw_token,
            action="search",
            resource="/workspace/research/summary.md",
            task_id="task-beta",
            workspace_id="ws-beta",
            session_id="session-beta",
        )
        self.assertFalse(decision.allowed)
        self.assertIn("does not match identity subject", decision.reason)

        # Audit event logged as DENIED
        events = self.store.list_audit_events(session_id="session-beta")
        self.assertGreaterEqual(len(events), 1)
        self.assertEqual(events[0].to_status, "DENIED")

    def test_reject_revoked_identity(self):
        """Revoked workload identity token is rejected at gateway."""
        req = AuthorizationRequest(
            identity_token=self.token1.raw_token,
            requested_capability="web_research",
            requested_action="search",
            target_resource="/workspace/research/summary.md",
            task_id="task-alpha",
            workspace_id="ws-alpha",
            environment="staging",
        )
        scope = self.scope_issuer.issue_scope(request=req)

        # Revoke alpha identity
        self.id_mgr.terminate_agent_identity("agent-alpha", reason="Security containment")

        decision = self.authorizer.authorize_invocation(
            identity_token=self.token1.raw_token,
            scope_token=scope.raw_token,
            action="search",
            resource="/workspace/research/summary.md",
            task_id="task-alpha",
            workspace_id="ws-alpha",
        )
        self.assertFalse(decision.allowed)
        self.assertIn("Identity invalid", decision.reason)


if __name__ == "__main__":
    unittest.main()
