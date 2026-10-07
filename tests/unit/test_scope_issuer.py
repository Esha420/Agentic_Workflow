import os
import tempfile
import time
import unittest
from domain.policy.models import AuthorizationRequest, ScopeToken
from services.policy.capabilities import CapabilityRegistry
from services.policy.engine import PolicyEngine
from services.policy.scope_issuer import ScopeIssuer, ScopeIssuerError
from services.identity.manager import IdentityManager
from services.agents.registry import AgentRegistryService
from adapters.storage.metadata_store import SQLiteMetadataStore


class TestScopeIssuer(unittest.TestCase):
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
        self.issuer = ScopeIssuer(policy_engine=self.engine)

        # Register and provision agent
        self.agent = self.agent_registry.register_agent(
            agent_id="researcher-02",
            role="research-agent",
            tenant="default",
            environment="staging",
            capabilities=["web_research"],
        )
        _, self.id_token = self.id_mgr.provision_agent_identity(
            agent_id="researcher-02",
            task_id="task-300",
            workspace_id="ws-300",
        )

    def tearDown(self):
        if os.path.exists(self.tmp_db.name):
            os.remove(self.tmp_db.name)


    def test_issue_scope_success(self):
        """Successfully issue a scope token with proper claims and quota."""
        req = AuthorizationRequest(
            identity_token=self.id_token.raw_token,
            requested_capability="web_research",
            requested_action="search",
            target_resource="/workspace/research/index.html",
            task_id="task-300",
            workspace_id="ws-300",
            environment="staging",
        )
        scope = self.issuer.issue_scope(request=req)
        self.assertIsInstance(scope, ScopeToken)
        self.assertTrue(scope.scope_id.startswith("scp-"))
        self.assertEqual(scope.subject, self.agent.identity_subject)
        self.assertEqual(scope.capability, "web_research")
        self.assertEqual(scope.max_invocations, 10)
        self.assertEqual(scope.invocations_remaining, 10)
        self.assertFalse(scope.is_expired())

    def test_consume_scope_decrements_quota(self):
        """Consuming scope decrements remaining invocations."""
        req = AuthorizationRequest(
            identity_token=self.id_token.raw_token,
            requested_capability="web_research",
            requested_action="search",
            target_resource="/workspace/research/index.html",
            task_id="task-300",
            workspace_id="ws-300",
            environment="staging",
        )
        scope = self.issuer.issue_scope(request=req, max_invocations=3)

        # Consume 1
        s1 = self.issuer.validate_and_consume_scope(
            raw_scope_token=scope.raw_token,
            expected_action="search",
            expected_resource="/workspace/research/index.html",
        )
        self.assertEqual(s1.invocations_remaining, 2)

        # Consume 2
        s2 = self.issuer.validate_and_consume_scope(
            raw_scope_token=scope.raw_token,
            expected_action="search",
            expected_resource="/workspace/research/index.html",
        )
        self.assertEqual(s2.invocations_remaining, 1)

        # Consume 3
        s3 = self.issuer.validate_and_consume_scope(
            raw_scope_token=scope.raw_token,
            expected_action="search",
            expected_resource="/workspace/research/index.html",
        )
        self.assertEqual(s3.invocations_remaining, 0)

        # 4th consume fails due to quota exhaustion
        with self.assertRaises(ScopeIssuerError) as ctx:
            self.issuer.validate_and_consume_scope(
                raw_scope_token=scope.raw_token,
                expected_action="search",
                expected_resource="/workspace/research/index.html",
            )
        self.assertIn("quota exhausted", str(ctx.exception).lower())

    def test_consume_scope_action_mismatch(self):
        """Attempting action other than granted action fails."""
        req = AuthorizationRequest(
            identity_token=self.id_token.raw_token,
            requested_capability="web_research",
            requested_action="search",
            target_resource="/workspace/research/index.html",
            task_id="task-300",
            workspace_id="ws-300",
            environment="staging",
        )
        scope = self.issuer.issue_scope(request=req)

        with self.assertRaises(ScopeIssuerError) as ctx:
            self.issuer.validate_and_consume_scope(
                raw_scope_token=scope.raw_token,
                expected_action="delete",
                expected_resource="/workspace/research/index.html",
            )
        self.assertIn("not granted", str(ctx.exception).lower())

    def test_revoked_scope(self):
        """Revoking scope prevents further consumption."""
        req = AuthorizationRequest(
            identity_token=self.id_token.raw_token,
            requested_capability="web_research",
            requested_action="search",
            target_resource="/workspace/research/index.html",
            task_id="task-300",
            workspace_id="ws-300",
            environment="staging",
        )
        scope = self.issuer.issue_scope(request=req)
        self.issuer.revoke_scope(scope.scope_id)

        with self.assertRaises(ScopeIssuerError) as ctx:
            self.issuer.validate_and_consume_scope(
                raw_scope_token=scope.raw_token,
                expected_action="search",
                expected_resource="/workspace/research/index.html",
            )
        self.assertIn("explicitly revoked", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
