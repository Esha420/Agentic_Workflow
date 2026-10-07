"""
tests/unit/test_checkpoint_branching.py — Unit tests for Checkpoint Branching and Invariant Enforcement
Enforces: Branch Authorization ⊆ Source Authorization
"""
import os
import shutil
import tempfile
import time
import unittest
import uuid
import jwt

from domain.agents.models import Agent, AgentLifecycleState
from domain.checkpoints.branching import BranchRequest, BranchStatus
from domain.checkpoints.models import Checkpoint
from domain.sessions.models import ResearchSession, SessionStatus
from services.agents.registry import AgentRegistryService
from services.checkpoints.branching import (
    BranchEscalationDenied,
    BranchingError,
    CheckpointBranchingController,
)
from services.identity.manager import IdentityManager
from services.policy.capabilities import CapabilityRegistry
from services.policy.scope_issuer import ScopeIssuer
from adapters.storage.metadata_store import SQLiteMetadataStore


class TestCheckpointBranching(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmp_dir, f"test_branching_{uuid.uuid4().hex[:6]}.db")
        self.workspace_base = os.path.join(self.tmp_dir, "workspaces")
        os.makedirs(self.workspace_base, exist_ok=True)

        self.store = SQLiteMetadataStore(db_path=self.db_path)
        self.registry = AgentRegistryService(self.store)
        self.identity_mgr = IdentityManager(registry=self.registry, metadata_store=self.store)
        self.capabilities = CapabilityRegistry()
        self.scope_issuer = ScopeIssuer()
        self.secret_key = "test-secret-key-m6-2026"
        self.scope_issuer.secret_key = self.secret_key

        self.controller = CheckpointBranchingController(
            metadata_store=self.store,
            agent_registry=self.registry,
            identity_manager=self.identity_mgr,
            capability_registry=self.capabilities,
            scope_issuer=self.scope_issuer,
            secret_key=self.secret_key,
            workspace_base_dir=self.workspace_base,
        )

        # Setup source session, agent, and checkpoint
        self.session_id = f"RS-{uuid.uuid4().hex[:6]}"
        self.session = ResearchSession(
            id=self.session_id,
            objective="Autonomous Architecture Analysis",
            target="State Persistence",
            role="lead-researcher",
            status=SessionStatus.RUNNING,
        )
        self.store.save_session(self.session)

        self.parent_agent = self.registry.register_agent(
            agent_id="researcher-01",
            role="lead-researcher",
            tenant="acme",
            environment="production",
            capabilities=["document_analysis", "web_research"],
            identity_subject="agent:researcher-01",
        )
        self.parent_agent.task_id = "T-source-01"
        self.parent_agent.workspace_id = f"ws-{self.session_id}"
        self.parent_agent.lifecycle_state = AgentLifecycleState.ACTIVE
        self.parent_agent.session_id = self.session_id
        _, self.parent_identity_token = self.identity_mgr.provision_agent_identity(
            agent_id=self.parent_agent.agent_id,
            task_id="T-source-01",
            workspace_id=f"ws-{self.session_id}",
            session_id=self.session_id,
        )

        # Setup parent workspace directory with initial research files
        parent_ws_dir = os.path.join(self.workspace_base, f"ws-{self.session_id}")
        os.makedirs(parent_ws_dir, exist_ok=True)
        with open(os.path.join(parent_ws_dir, "research_notes.md"), "w") as f:
            f.write("# Foundational Research Notes\nInitial findings before branching.")

        # Create parent checkpoint C1
        self.checkpoint_c1 = Checkpoint(
            id="chk-root-c1",
            session_id=self.session_id,
            task_id="T-source-01",
            workspace_version="v1",
            workspace_generation=1,
            snapshot_reference="snapshot-ref://rustfs/root-c1",
            metadata={"phase": "initial_synthesis"},
        )
        self.store.save_checkpoint(self.checkpoint_c1)

        # Mint parent scope token
        now = int(time.time())
        self.parent_scope_claims = {
            "scope_id": "scp-parent-c1",
            "sub": self.parent_agent.identity_subject,
            "task_id": "T-source-01",
            "workspace_id": f"ws-{self.session_id}",
            "capability": "document_analysis",
            "granted_action": "read",
            "allowed_actions": ["read"],
            "resource_path": "/workspace/research/*",
            "resource_pattern": "/workspace/research/*",
            "max_invocations": 10,
            "invocations_remaining": 10,
            "delegation_depth": 2,
            "iat": now,
            "exp": now + 3600,
            "iss": "https://scope.agent-lab.internal",
            "aud": "agent-gateway",
            "role": "lead-researcher",
            "environment": "production",
        }
        self.parent_scope_token = jwt.encode(self.parent_scope_claims, self.secret_key, algorithm="HS256")

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_valid_branch_creation_and_isolation(self):
        """Verifies creating a valid branch inheriting subset authority."""
        req = BranchRequest(
            parent_checkpoint_id=self.checkpoint_c1.id,
            caller_identity_token=self.parent_identity_token.raw_token,
            source_scope_token=self.parent_scope_token,
            hypothesis="Hypothesis A: Empirical analysis",
            branch_name="branch-alpha",
            requested_capabilities=["document_analysis"],
            requested_actions=["read"],
            requested_resources=["/workspace/research/sources/*"],
            max_invocations=5,
        )

        branch = self.controller.create_branch(req)

        self.assertEqual(branch.branch_id, "branch-alpha")
        self.assertEqual(branch.parent_checkpoint_id, self.checkpoint_c1.id)
        self.assertEqual(branch.workspace_generation, 2)
        self.assertEqual(branch.status, BranchStatus.ACTIVE)
        self.assertEqual(branch.hypothesis, "Hypothesis A: Empirical analysis")

        # Verify cloned workspace file exists in branch workspace
        branch_ws_dir = os.path.join(self.workspace_base, branch.workspace_id)
        self.assertTrue(os.path.exists(os.path.join(branch_ws_dir, "research_notes.md")))
        self.assertTrue(os.path.exists(os.path.join(branch_ws_dir, "BRANCH_METADATA.json")))

    def test_branch_capability_escalation_denied(self):
        """Verifies that requesting a capability outside source scope is blocked fail-closed."""
        req = BranchRequest(
            parent_checkpoint_id=self.checkpoint_c1.id,
            caller_identity_token=self.parent_identity_token.raw_token,
            source_scope_token=self.parent_scope_token,
            hypothesis="Adversarial escalation to prod_deploy",
            requested_capabilities=["prod_deploy"],
        )

        with self.assertRaises(BranchEscalationDenied) as ctx:
            self.controller.create_branch(req)
        self.assertIn("Capability escalation denied", str(ctx.exception))

    def test_branch_resource_escape_denied(self):
        """Verifies that requesting a resource path escaping parent boundary is denied fail-closed."""
        req = BranchRequest(
            parent_checkpoint_id=self.checkpoint_c1.id,
            caller_identity_token=self.parent_identity_token.raw_token,
            source_scope_token=self.parent_scope_token,
            hypothesis="Escape boundary to payroll",
            requested_resources=["/workspace/finance/payroll/*"],
        )

        with self.assertRaises(BranchEscalationDenied) as ctx:
            self.controller.create_branch(req)
        self.assertIn("Resource escalation denied", str(ctx.exception))

    def test_branch_quota_escalation_denied(self):
        """Verifies that requesting quota beyond source remaining calls is denied fail-closed."""
        req = BranchRequest(
            parent_checkpoint_id=self.checkpoint_c1.id,
            caller_identity_token=self.parent_identity_token.raw_token,
            source_scope_token=self.parent_scope_token,
            hypothesis="Quota escalation",
            max_invocations=50,  # Parent only has 10
        )

        with self.assertRaises(BranchEscalationDenied) as ctx:
            self.controller.create_branch(req)
        self.assertIn("Quota escalation denied", str(ctx.exception))

    def test_dual_branch_divergence_and_lineage_dag(self):
        """Verifies dual branches diverge independently and construct correct lineage DAG."""
        # Branch A
        req_a = BranchRequest(
            parent_checkpoint_id=self.checkpoint_c1.id,
            caller_identity_token=self.parent_identity_token.raw_token,
            source_scope_token=self.parent_scope_token,
            hypothesis="Hypothesis A: Fast heuristic approach",
            branch_name="branch-A",
            requested_resources=["/workspace/research/a/*"],
        )
        branch_a = self.controller.create_branch(req_a)

        # Branch B
        req_b = BranchRequest(
            parent_checkpoint_id=self.checkpoint_c1.id,
            caller_identity_token=self.parent_identity_token.raw_token,
            source_scope_token=self.parent_scope_token,
            hypothesis="Hypothesis B: Deep semantic verification",
            branch_name="branch-B",
            requested_resources=["/workspace/research/b/*"],
        )
        branch_b = self.controller.create_branch(req_b)

        # Mutate Branch A workspace
        ws_a_file = os.path.join(self.workspace_base, branch_a.workspace_id, "heuristic_result.txt")
        with open(ws_a_file, "w") as f:
            f.write("Heuristic result score: 0.94")

        # Verify mutation does NOT bleed into Branch B
        ws_b_file = os.path.join(self.workspace_base, branch_b.workspace_id, "heuristic_result.txt")
        self.assertFalse(os.path.exists(ws_b_file))

        # Commit checkpoints from each branch
        chk_a = self.controller.commit_branch_checkpoint(branch_a.branch_id, {"id": "chk-branch-a-c2"})
        chk_b = self.controller.commit_branch_checkpoint(branch_b.branch_id, {"id": "chk-branch-b-c2"})

        self.assertEqual(chk_a.parent_checkpoint_id, self.checkpoint_c1.id)
        self.assertEqual(chk_a.workspace_generation, 2)
        self.assertEqual(chk_b.parent_checkpoint_id, self.checkpoint_c1.id)

        # Query lineage
        lineage = self.controller.get_lineage(self.session_id)
        self.assertEqual(lineage.total_checkpoints, 3)
        self.assertEqual(lineage.total_branches, 2)
        self.assertIn("branch-A", lineage.lineage_dag[self.checkpoint_c1.id])
        self.assertIn("branch-B", lineage.lineage_dag[self.checkpoint_c1.id])


if __name__ == "__main__":
    unittest.main()
