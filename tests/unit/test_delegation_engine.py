"""
tests/unit/test_delegation_engine.py — Unit tests for Delegation Engine and Child Scope ⊆ Parent Scope
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
from adapters.storage.metadata_store import SQLiteMetadataStore


class TestDelegationEngine(unittest.TestCase):
    def setUp(self):
        self.tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp_db.close()
        self.store = SQLiteMetadataStore(db_path=self.tmp_db.name)
        self.registry = AgentRegistryService(self.store)
        self.id_mgr = IdentityManager(registry=self.registry, metadata_store=self.store)
        self.cap_registry = CapabilityRegistry()
        doc_cap = self.cap_registry.get_capability("document_analysis")
        if doc_cap:
            doc_cap.max_delegation_depth = 2

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

        # Agent A (Parent): Researcher
        self.agent_a = self.registry.register_agent(
            agent_id="researcher-27",
            role="research-agent",
            tenant="acme",
            environment="staging",
            capabilities=["web_research", "document_analysis"],
        )
        _, self.token_a = self.id_mgr.provision_agent_identity(
            agent_id="researcher-27",
            task_id="T-482",
            workspace_id="WS-security",
        )

        # Agent B (Child): Document Analyzer
        self.agent_b = self.registry.register_agent(
            agent_id="researcher-42",
            role="research-agent",
            tenant="acme",
            environment="staging",
            capabilities=["document_analysis"],
        )
        _, self.token_b = self.id_mgr.provision_agent_identity(
            agent_id="researcher-42",
            task_id="T-482",
            workspace_id="WS-security",
        )

        # Agent C (External Tenant)
        self.agent_c = self.registry.register_agent(
            agent_id="external-99",
            role="research-agent",
            tenant="rival-corp",
            environment="staging",
            capabilities=["document_analysis"],
        )

        # Mint parent scope for Agent A with delegation_depth=2
        auth_req = AuthorizationRequest(
            identity_token=self.token_a.raw_token,
            requested_capability="document_analysis",
            requested_action="read",
            target_resource="/workspace/research/*",
            task_id="T-482",
            workspace_id="WS-security",
            delegation_depth=2,
            environment="staging",
        )
        self.parent_scope = self.scope_issuer.issue_scope(request=auth_req, max_invocations=10)

    def tearDown(self):
        if os.path.exists(self.tmp_db.name):
            os.remove(self.tmp_db.name)

    def test_valid_delegation_child_subset_of_parent(self):
        """Child requests strict subset of parent capability, action, resource, and quota."""
        del_req = DelegationRequest(
            caller_identity_token=self.token_a.raw_token,
            parent_scope_token=self.parent_scope.raw_token,
            target_agent_id="researcher-42",
            task_id="T-482",
            workspace_id="WS-security",
            requested_capability="document_analysis",
            requested_action="read",
            requested_resource="/workspace/research/sources/*",
            requested_max_invocations=3,
            requested_delegation_depth=1,
            environment="staging",
        )
        result = self.delegation_engine.delegate(del_req)
        self.assertEqual(result.verdict, DelegationVerdict.ALLOWED)
        self.assertIsNotNone(result.child_scope)
        cs = result.child_scope
        self.assertEqual(cs.capability, "document_analysis")
        self.assertEqual(cs.allowed_actions, ["read"])
        self.assertEqual(cs.resource_pattern, "/workspace/research/sources/*")
        self.assertEqual(cs.max_invocations, 3)
        self.assertEqual(cs.remaining_delegation_depth, 1)
        self.assertEqual(cs.child_subject, self.agent_b.identity_subject)
        self.assertEqual(cs.delegated_by, self.agent_a.identity_subject)
        self.assertEqual(result.delegation_chain, [self.agent_a.identity_subject, self.agent_b.identity_subject])

    def test_deny_capability_escalation(self):
        """Child attempts to request capability not present in parent scope."""
        del_req = DelegationRequest(
            caller_identity_token=self.token_a.raw_token,
            parent_scope_token=self.parent_scope.raw_token,
            target_agent_id="researcher-42",
            task_id="T-482",
            workspace_id="WS-security",
            requested_capability="prod_deploy",  # ESCALATION!
            requested_action="deploy",
            requested_resource="/workspace/research/*",
        )
        result = self.delegation_engine.delegate(del_req)
        self.assertEqual(result.verdict, DelegationVerdict.DENIED)
        self.assertIn("Capability escalation denied", result.reason)

    def test_deny_resource_path_escalation(self):
        """Child attempts to request path outside parent pattern."""
        del_req = DelegationRequest(
            caller_identity_token=self.token_a.raw_token,
            parent_scope_token=self.parent_scope.raw_token,
            target_agent_id="researcher-42",
            task_id="T-482",
            workspace_id="WS-security",
            requested_capability="document_analysis",
            requested_action="read",
            requested_resource="/workspace/other_project/*",  # ESCALATION!
        )
        result = self.delegation_engine.delegate(del_req)
        self.assertEqual(result.verdict, DelegationVerdict.DENIED)
        self.assertIn("Resource escalation denied", result.reason)

    def test_deny_cross_tenant_delegation(self):
        """Delegating to agent in another tenant must be denied."""
        del_req = DelegationRequest(
            caller_identity_token=self.token_a.raw_token,
            parent_scope_token=self.parent_scope.raw_token,
            target_agent_id="external-99",  # rival-corp tenant!
            task_id="T-482",
            workspace_id="WS-security",
            requested_capability="document_analysis",
            requested_action="read",
            requested_resource="/workspace/research/sources/*",
        )
        result = self.delegation_engine.delegate(del_req)
        self.assertEqual(result.verdict, DelegationVerdict.DENIED)
        self.assertIn("Cross-tenant delegation denied", result.reason)

    def test_deny_delegation_depth_zero(self):
        """When parent delegation depth reaches zero, further delegation must be denied."""
        # 1. First delegation with remaining depth = 0
        del_req_1 = DelegationRequest(
            caller_identity_token=self.token_a.raw_token,
            parent_scope_token=self.parent_scope.raw_token,
            target_agent_id="researcher-42",
            task_id="T-482",
            workspace_id="WS-security",
            requested_capability="document_analysis",
            requested_action="read",
            requested_resource="/workspace/research/sources/*",
            requested_delegation_depth=0,
        )
        res_1 = self.delegation_engine.delegate(del_req_1)
        self.assertEqual(res_1.verdict, DelegationVerdict.ALLOWED)
        child_scope_1 = res_1.child_scope
        self.assertEqual(child_scope_1.remaining_delegation_depth, 0)

        # 2. Agent B tries to delegate to Agent D using child_scope_1
        agent_d = self.registry.register_agent(
            agent_id="researcher-99",
            role="research-agent",
            tenant="acme",
            environment="staging",
            capabilities=["document_analysis"],
        )
        del_req_2 = DelegationRequest(
            caller_identity_token=self.token_b.raw_token,
            parent_scope_token=child_scope_1.raw_token,
            target_agent_id="researcher-99",
            task_id="T-482",
            workspace_id="WS-security",
            requested_capability="document_analysis",
            requested_action="read",
            requested_resource="/workspace/research/sources/*",
        )
        res_2 = self.delegation_engine.delegate(del_req_2)
        self.assertEqual(res_2.verdict, DelegationVerdict.DENIED)
        self.assertIn("Delegation depth exhausted", res_2.reason)


if __name__ == "__main__":
    unittest.main()
