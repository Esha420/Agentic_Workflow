"""
tests/unit/test_identity_provider.py — Unit tests for OIDC-compatible Workload Identity Provider
"""
import os
import sys
import unittest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from domain.agents.models import Agent
from domain.identity.provider import OIDCWorkloadIdentityProvider


class TestOIDCWorkloadIdentityProvider(unittest.TestCase):
    def setUp(self):
        self.provider = OIDCWorkloadIdentityProvider(
            issuer="https://identity.agent-lab.internal",
            audience="agent-gateway",
            secret_key="test-secret-key-identity",
        )
        self.agent = Agent(
            agent_id="researcher-27",
            role="research-agent",
            tenant="acme",
            environment="staging",
            capabilities=["web_research", "doc_analysis"],
        )

    def test_issue_and_validate_token(self):
        token = self.provider.issue_identity(
            agent=self.agent,
            task_id="T-482",
            workspace_id="WS-security",
            ttl_seconds=3600,
        )
        self.assertIsNotNone(token.raw_token)
        self.assertEqual(token.subject, "agent:researcher-27")
        self.assertEqual(token.task_id, "T-482")
        self.assertEqual(token.workspace_id, "WS-security")
        self.assertEqual(token.role, "research-agent")
        self.assertEqual(token.tenant, "acme")

        # Validate valid token
        val = self.provider.validate_identity(
            token=token.raw_token,
            expected_task_id="T-482",
            expected_workspace_id="WS-security",
        )
        self.assertTrue(val.valid)
        self.assertEqual(val.subject, "agent:researcher-27")
        self.assertIn("web_research", val.claims.get("capabilities", []))

    def test_reject_tampered_token(self):
        token = self.provider.issue_identity(self.agent, "T-482", "WS-security")
        tampered_token = token.raw_token[:-4] + "fake"
        val = self.provider.validate_identity(tampered_token)
        self.assertFalse(val.valid)
        self.assertIn("tampered", val.error)

    def test_reject_task_mismatch(self):
        token = self.provider.issue_identity(self.agent, "T-482", "WS-security")
        val = self.provider.validate_identity(token.raw_token, expected_task_id="T-999")
        self.assertFalse(val.valid)
        self.assertIn("Task binding mismatch", val.error)

    def test_reject_workspace_mismatch(self):
        token = self.provider.issue_identity(self.agent, "T-482", "WS-security")
        val = self.provider.validate_identity(token.raw_token, expected_workspace_id="WS-other")
        self.assertFalse(val.valid)
        self.assertIn("Workspace binding mismatch", val.error)

    def test_reject_revoked_token(self):
        token = self.provider.issue_identity(self.agent, "T-482", "WS-security")
        val_before = self.provider.validate_identity(token.raw_token)
        self.assertTrue(val_before.valid)

        self.provider.revoke_identity(token.jti, reason="Key compromised")
        val_after = self.provider.validate_identity(token.raw_token)
        self.assertFalse(val_after.valid)
        self.assertIn("revoked", val_after.error)


if __name__ == "__main__":
    unittest.main()
