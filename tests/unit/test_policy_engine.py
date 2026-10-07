"""
tests/unit/test_policy_engine.py — Unit tests for Contextual Intersection Policy Engine
"""
import os
import tempfile
import unittest
from domain.policy.models import (
    Capability,
    PolicyRule,
    RuleEffect,
    EvaluationVerdict,
    AuthorizationRequest,
)
from services.policy.capabilities import CapabilityRegistry
from services.policy.engine import PolicyEngine
from services.identity.manager import IdentityManager
from services.agents.registry import AgentRegistryService
from adapters.storage.metadata_store import SQLiteMetadataStore


class TestPolicyEngine(unittest.TestCase):
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

        # Register agents for tests
        self.researcher = self.agent_registry.register_agent(
            agent_id="researcher-01",
            role="research-agent",
            tenant="default",
            environment="staging",
            capabilities=["web_research", "document_analysis"],
        )
        _, self.res_token = self.id_mgr.provision_agent_identity(
            agent_id="researcher-01",
            task_id="task-100",
            workspace_id="ws-100",
        )

        self.coder = self.agent_registry.register_agent(
            agent_id="coder-01",
            role="coder-agent",
            tenant="default",
            environment="staging",
            capabilities=["code_generation"],
        )
        _, self.coder_token = self.id_mgr.provision_agent_identity(
            agent_id="coder-01",
            task_id="task-200",
            workspace_id="ws-200",
        )

    def tearDown(self):
        if os.path.exists(self.tmp_db.name):
            os.remove(self.tmp_db.name)


    def test_allow_valid_request(self):
        """Valid identity, role, capability, action, and resource should be ALLOWED."""
        req = AuthorizationRequest(
            identity_token=self.res_token.raw_token,
            requested_capability="web_research",
            requested_action="search",
            target_resource="/workspace/research/findings.md",
            task_id="task-100",
            workspace_id="ws-100",
            environment="staging",
        )
        result = self.engine.evaluate(req)
        self.assertEqual(result.verdict, EvaluationVerdict.ALLOWED)
        self.assertIn("Granted", result.reason)
        self.assertIsNotNone(result.effective_scope)
        self.assertEqual(result.effective_scope["capability"], "web_research")
        self.assertIn("search", result.effective_scope["allowed_actions"])

    def test_deny_role_mismatch(self):
        """Coder attempting web_research should be DENIED because role not in allowed_roles."""
        req = AuthorizationRequest(
            identity_token=self.coder_token.raw_token,
            requested_capability="web_research",
            requested_action="search",
            target_resource="/workspace/research/data.json",
            task_id="task-200",
            workspace_id="ws-200",
            environment="staging",
        )
        result = self.engine.evaluate(req)
        self.assertEqual(result.verdict, EvaluationVerdict.DENIED)
        self.assertIn("not authorized for capability", result.reason)

    def test_deny_resource_path_escape(self):
        """Requesting path outside allowed pattern should be DENIED."""
        req = AuthorizationRequest(
            identity_token=self.res_token.raw_token,
            requested_capability="web_research",
            requested_action="search",
            target_resource="/etc/shadow",
            task_id="task-100",
            workspace_id="ws-100",
            environment="staging",
        )
        result = self.engine.evaluate(req)
        self.assertEqual(result.verdict, EvaluationVerdict.DENIED)
        self.assertIn("Resource path", result.reason)

    def test_deny_action_not_permitted(self):
        """Action not permitted by capability should be DENIED."""
        req = AuthorizationRequest(
            identity_token=self.res_token.raw_token,
            requested_capability="web_research",
            requested_action="delete_system_core",
            target_resource="/workspace/research/data.json",
            task_id="task-100",
            workspace_id="ws-100",
            environment="staging",
        )
        result = self.engine.evaluate(req)
        self.assertEqual(result.verdict, EvaluationVerdict.DENIED)
        self.assertIn("not permissible", result.reason)

    def test_deny_invalid_task_context(self):
        """Token task_id mismatching requested task_id should be DENIED."""
        req = AuthorizationRequest(
            identity_token=self.res_token.raw_token,
            requested_capability="web_research",
            requested_action="search",
            target_resource="/workspace/research/data.json",
            task_id="task-WRONG",
            workspace_id="ws-100",
            environment="staging",
        )
        result = self.engine.evaluate(req)
        self.assertEqual(result.verdict, EvaluationVerdict.DENIED)
        self.assertIn("Identity verification failed", result.reason)


    def test_deny_explicit_policy_rule(self):
        """Explicit DENY rule overrides any capability eligibility."""
        # prod_deploy capability is explicitly DENIED for research-agent
        req = AuthorizationRequest(
            identity_token=self.res_token.raw_token,
            requested_capability="prod_deploy",
            requested_action="deploy",
            target_resource="/workspace/deploy/prod.yaml",
            task_id="task-100",
            workspace_id="ws-100",
            environment="staging",
        )
        result = self.engine.evaluate(req)
        self.assertEqual(result.verdict, EvaluationVerdict.DENIED)

    def test_deny_exceeded_delegation_depth(self):
        """Delegation depth exceeding capability maximum should be DENIED."""
        req = AuthorizationRequest(
            identity_token=self.res_token.raw_token,
            requested_capability="web_research",
            requested_action="search",
            target_resource="/workspace/research/notes.txt",
            task_id="task-100",
            workspace_id="ws-100",
            delegation_depth=2,  # max is 1
            environment="staging",
        )
        result = self.engine.evaluate(req)
        self.assertEqual(result.verdict, EvaluationVerdict.DENIED)
        self.assertIn("Delegation depth", result.reason)


if __name__ == "__main__":
    unittest.main()
