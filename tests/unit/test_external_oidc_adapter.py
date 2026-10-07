"""
tests/unit/test_external_oidc_adapter.py — Unit tests for External OIDC Provider Adapter and Dynamic Scope
"""
import unittest
import time
from domain.agents.models import Agent
from services.identity.external_oidc_adapter import ExternalOIDCProviderAdapter


class TestExternalOIDCProviderAdapter(unittest.TestCase):
    def setUp(self):
        self.adapter = ExternalOIDCProviderAdapter(
            provider_name="Auth0-Test",
            issuer="https://auth0.agent-lab.internal/",
            audience="agent-gateway",
            signing_key="unit-test-secret-key-2026",
            algorithm="HS256",
        )
        self.agent = Agent(
            agent_id="test-researcher",
            role="researcher",
            tenant="acme",
            environment="production",
            capabilities=["document_analysis", "web_research"],
            identity_subject="agent:test-researcher",
        )

    def test_issue_and_validate_dynamic_scope_token(self):
        token = self.adapter.issue_identity(
            agent=self.agent,
            task_id="T-100",
            workspace_id="ws-100",
            ttl_seconds=3600,
            scope="document:read web:search",
            spiffe_id="spiffe://cluster.local/ns/default/sa/worker-actor-100",
        )
        self.assertEqual(token.subject, "agent:test-researcher")
        self.assertEqual(token.claims["scope"], "document:read web:search")
        self.assertEqual(token.claims["spiffe_workload_id"], "spiffe://cluster.local/ns/default/sa/worker-actor-100")

        # Validate with correct bindings
        res = self.adapter.validate_identity(
            token=token.raw_token,
            expected_task_id="T-100",
            expected_workspace_id="ws-100",
        )
        self.assertTrue(res.valid)
        self.assertEqual(res.subject, "agent:test-researcher")

    def test_reject_task_and_workspace_mismatch(self):
        token = self.adapter.issue_identity(
            agent=self.agent,
            task_id="T-100",
            workspace_id="ws-100",
        )
        # Task mismatch
        res_task = self.adapter.validate_identity(
            token=token.raw_token,
            expected_task_id="T-DIFFERENT",
            expected_workspace_id="ws-100",
        )
        self.assertFalse(res_task.valid)
        self.assertIn("Task binding mismatch", res_task.error)

        # Workspace mismatch
        res_ws = self.adapter.validate_identity(
            token=token.raw_token,
            expected_task_id="T-100",
            expected_workspace_id="ws-DIFFERENT",
        )
        self.assertFalse(res_ws.valid)
        self.assertIn("Workspace binding mismatch", res_ws.error)

    def test_revocation(self):
        token = self.adapter.issue_identity(
            agent=self.agent,
            task_id="T-100",
            workspace_id="ws-100",
        )
        self.assertFalse(self.adapter.is_revoked(token.jti))

        self.adapter.revoke_identity(token.jti, reason="Testing revocation")
        self.assertTrue(self.adapter.is_revoked(token.jti))

        res = self.adapter.validate_identity(token.raw_token)
        self.assertFalse(res.valid)
        self.assertIn("revoked", res.error.lower())

    def test_is_action_in_scope_helper(self):
        scope_str = "document:read web:search deployment:*"
        self.assertTrue(self.adapter.is_action_in_scope("document:read", scope_str))
        self.assertTrue(self.adapter.is_action_in_scope("web:search", scope_str))
        self.assertTrue(self.adapter.is_action_in_scope("deployment:execute", scope_str))
        self.assertTrue(self.adapter.is_action_in_scope("deployment:read", scope_str))
        self.assertFalse(self.adapter.is_action_in_scope("document:write", scope_str))
        self.assertFalse(self.adapter.is_action_in_scope("finance:transfer", scope_str))


if __name__ == "__main__":
    unittest.main()
